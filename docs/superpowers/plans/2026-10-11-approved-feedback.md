# Approved Feedback Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 当前会话顺序实施已由用户选择；不重新选择执行方式。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将用户批准的 R1 接入后续新故事，以已审核反馈完成调查回合，同时保持旧故事、真实账本、自由输入与不可变存档。

**Architecture:** 新建只增不改的 story_presentations 表，把 approved-feedback-1 绑定到新故事版本；无记录的旧版本走 model-scene-1。新创建检查点 controlled-content-2 固定呈现协议，完整内容生成/校验保持。回合服务直接保存已有裁决反馈，不再调用回合生成/审核；状态提交与回放沿现有路径。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL、pytest；不新增依赖或前端改动。

**Spec:** [已批准 R1](../../design/stage-2-controlled-scenes-proposal.md)，并读取 `docs/01-requirements.md`、`docs/02-technical-design.md`、`docs/03-development-plan.md`、`docs/design/stage-2-custom-stories.md`、`docs/design/runtime-reliability.md`。

## Global Constraints

- 三角色、五主要地点、三结局；固定原清单 12 个真实任务与 10 个模拟任务。阶段 2 未验收，人工人数不得预填。
- 新创建 controlled-content-2；新呈现 approved-feedback-1；旧无记录版本 model-scene-1。未知或不一致协议拒绝，不按实体 ID/Node prompt 推断。
- 内容 schema investigation-content-1、骨架 controlled-investigation-1、SHA256 516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e、创建提示 investigation-single-6 保持；不是通过改提示版本阻止旧任务恢复。
- 创建/修复仍 120 秒单次、300 秒总限时、至多一次修复；行动 60 秒总限时，action.interpret.v1 20 秒单次。80/100 CNY 与未知费用保护保留。
- R1 accepted 回合 narration 等于 Adjudication.feedback、dialogue=[]；反馈已含本轮事件与结局，不重复拼接、不截断、不另写自由叙事。非法/重复行动仍保持原状态。
- R1 按钮无模型调用、不要求密钥；自由文本仍需要内存密钥与预算校验。旧模式仍保持原密钥、生成与语义否决路径；不从旧失败任务回退到 R1。
- R1 回合 Node.prompt_version=approved-feedback-1、model_id=server:approved-feedback-1；开场仍记录创建来源。Trace 和报告区分服务器呈现与真实模型操作，不伪造用量。
- 使用当前已附加工作树 `C:/Users/Lenovo/.codex/worktrees/stage2-custom-stories/ai-improv-theater`；原目录四份既有草稿不改、不暂存。提交标题 `English: 中文`，不合并/推送。
- 独立 55438 测试集群现已停止；恢复原 pgdata 后模拟用新 stage2_presentation_test，真实只用原 stage2_real_test，不能换库绕开费用。所有同库检查顺序运行。

## Review Focus

1. 新版降级到 0005/0004 时不能先删除呈现/审计记录再拒绝；有记录时在 0006 即拒绝，旧保护错误仍有测试。
2. 旧 controlled-content-1 已通过检查点恢复后仍为原模式，重复确认不升级；包含跨故事候选与协议冲突负例。
3. 反馈与事件/结局文本可能超过 scene.render 的 1200 字上限；R1 不经过该供应商输出 schema，不截断或重复文本。
4. 没有密钥或有未知费用时，R1 按钮仍零外部调用；自由输入仍阻断，不能把纯呈现当作免费 provider 调用。
5. 长分支/兄弟分支的人工材料必须由保存的终点沿父链导出，不混入其他分支、Trace、候选或凭据；不完整报告拒绝导出为验收材料。

## Task 1：不可变呈现协议与增量迁移

**Files:** Create `backend/migrations/versions/0006_story_presentations.py`, `backend/tests/test_story_presentations.py`; Modify `backend/app/models.py`, `backend/app/story_versions.py`。

**Interfaces:** Consumes 现有 Story/canonical_hash、Session、StoryVersion；Produces `StoryPresentation`、`load_narration_protocol(db: Session, version_id: str) -> str` 和 `save_story_version(db, story, *, narration_protocol='model-scene-1') -> StoryVersion`。`load_story_version` 的定义解析/hash 行为不变。

- [x] Step 1：在新测试文件写 RED，现有 sample_data 创建独立 UUID 故事，覆盖新记录保存、同内容不同协议冲突、未知协议、旧无记录兼容，以及数据库 UPDATE/DELETE 拒绝。示例：

```python
def test_presentation_is_fixed_with_version(db):
    story = Story.model_validate({**sample_data(), 'story_id': str(uuid4())})
    row = save_story_version(db, story, narration_protocol='approved-feedback-1')
    db.commit()
    assert load_narration_protocol(db, row.id) == 'approved-feedback-1'
    assert load_story_version(db, row.id) == story
    with pytest.raises(ValueError, match='version_identity_conflict'):
        save_story_version(db, story)
```

`db` fixture 使用 SessionLocal，所有相关集成测试仅在 DATABASE_URL 为 PostgreSQL 且数据库名以 `_test` 结尾时运行；纯未知协议单元负例不依赖真实模型。

- [x] Step 2：启动已有独立集群；仅创建新的 stage2_presentation_test 并迁移至当前 head 0005。命令从工作树 root：

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D '.\runtime\stage2-test\pgdata' -l '.\runtime\stage2-test\postgres.log' -o '-p 55438 -h 127.0.0.1' start -w
& 'C:\Program Files\PostgreSQL\18\bin\createdb.exe' -h 127.0.0.1 -p 55438 -U stage2_test_owner stage2_presentation_test
$env:DATABASE_URL='postgresql+psycopg://stage2_test_owner@127.0.0.1:55438/stage2_presentation_test'
$env:MIGRATION_DATABASE_URL=$env:DATABASE_URL
Set-Location backend
& 'E:\vs code\code\ai-improv-theater\.venv\Scripts\python.exe' -m alembic upgrade head
& 'E:\vs code\code\ai-improv-theater\.venv\Scripts\python.exe' -m pytest tests/test_story_presentations.py -q
```

Expected：新模型/参数/加载函数缺失而失败；不因连不上数据库跳过并称通过。若集群已运行，只核对该 pgdata/端口后复用；数据库已存在则检查迁移状态，不重置。

- [x] Step 3：新增表，revision=0006_story_presentations，down_revision=0005_execution_records。模型形状：

```python
class StoryPresentation(Base):
    __tablename__ = 'story_presentations'
    __table_args__ = (CheckConstraint("narration_protocol = 'approved-feedback-1'",
                                     name='ck_narration_protocol'),)
    story_version_id: Mapped[str] = mapped_column(ForeignKey('story_versions.id'), primary_key=True)
    narration_protocol: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
```

迁移建立 BEFORE UPDATE OR DELETE trigger，一律抛 23514；不新增 StoryVersion 列或写任何旧行。0006 downgrade 首先使用 0005 现有审计存在查询，若存在则 `RuntimeError('cannot downgrade execution records')`；其次若呈现记录存在则 `RuntimeError('cannot downgrade presentation records')`，然后才允许删除空表/trigger/function。这样原审计保护测试不在半降级库继续运行。

- [x] Step 4：扩展 save_story_version，只接受两个已知协议。新版本正常保存定义/hash 后，R1 在同一事务新增 StoryPresentation；旧模式不创建记录。已有版本需比较内容和已保存呈现协议，任何不同报 version_identity_conflict，不能追加记录升级旧版本。加载 helper 无记录返回 model-scene-1，非法已保存值报 presentation_protocol_mismatch；从 db.get 的确切版本记录读取，不扫描 StoryTask。关键检查：

```python
if narration_protocol not in ('model-scene-1', 'approved-feedback-1'):
    raise ValueError('presentation_protocol_mismatch')
# In the existing-version branch after the existing content-integrity check:
if load_narration_protocol(db, row.id) != narration_protocol:
    raise ValueError('version_identity_conflict')
```

- [x] Step 5：独立迁移测试 fixture 仿照 test_story_versions 的 dedicated UUID `_test` 库方式，先升级 0005，直接插入旧 StoryVersion/节点/事件并保存完整旧列 JSON/hash，再升级 head，确认原行/定义/hash 未变、旧版无呈现记录、加载为 model-scene-1；新增 R1 记录后降级拒绝且记录仍在。空库升级/降级可行；测试结束只清理自身新建的临时测试库，不触及 stage2_real_test。
- [x] Step 6：迁移 stage2_presentation_test 至新 head，运行同一 RED 套件以及 `tests/test_story_versions.py tests/test_execution_records.py`、完整 `pytest -q`、`alembic check`。Expected：全部通过，无新增未生成迁移操作。记录实际数字及警告；仅提交该任务文件，`feat: 固定故事呈现协议并保护增量迁移`。

## Task 2：新创建协议与 R1 回合提交

**Files:** Modify `backend/app/story_creation.py`, `backend/app/investigation_jobs.py`, `backend/tests/test_stage2_evaluation.py`; Create `backend/tests/test_approved_feedback.py`。保留旧 investigation_api/custom_story_creation 测试含义，必要的测试 helper 改动单独说明，不改旧模式假供应商成功门槛。

**Interfaces:** Consumes Task 1 呈现存储 helper；Produces 新任务 controlled-content-2 检查点与 `approved-feedback-1` 回合 Node、内部 `presentation_selected` Trace；对外 Action/Node 场景结构不变。

- [x] Step 1：写 API RED，使用 test_custom_story_creation 的 client/create_session/prepare/successful_provider 建立新默认故事并确认；确认后清除密钥，供应商 patch 捕获任何额外请求。按钮应 completed，narration 与保存 adjudication.feedback 逐字相同、dialogue=[]、fallback=false，LLMCall 为零；重复提交同键、节点回放、SSE 补发仍零调用。示例：

```python
def test_r1_button_without_key_commits_only_authorized_feedback():
    with client() as c, patch('app.story_operations.call_operation_provider',
                             side_effect=successful_provider) as provider:
        headers, _ = create_session(c)
        task = prepare(c, headers)
        body = {'candidate_version_id': task['candidate_version_id'], 'content_hash': task['content_hash']}
        root = c.post('/story-tasks/'+task['id']+'/confirm', headers=headers, json=body).json()['root']
        c.delete('/local-settings/keys/deepseek')
        before = provider.call_count
        key = uuid4().hex
        action = {'type':'option', 'value':root['rendered_scene']['options'][0]['id']}
        run = turn(c, headers, root['id'], action, key)
        assert run['status'] == 'completed'
        node = c.get('/nodes/'+run['node_id'], headers=headers).json()
        with SessionLocal() as db:
            feedback = db.scalar(select(TurnEvent.payload).where(
                TurnEvent.node_id == run['node_id'], TurnEvent.event_type == 'adjudication'))['feedback']
            calls = db.scalars(select(LLMCall).where(LLMCall.run_id == run['id'])).all()
        assert node['rendered_scene']['narration'] == feedback
        assert node['rendered_scene']['dialogue'] == [] and not calls
        assert node['prompt_version'] == 'approved-feedback-1'
        assert node['model_id'] == 'server:approved-feedback-1'
        assert turn(c, headers, root['id'], action, key)['node_id'] == run['node_id']
        assert c.get('/nodes/'+run['node_id'], headers=headers).json() == node
        assert provider.call_count == before
```

实际测试把下列步骤放在上述同一 client context 内，复用 test_investigation_api.turn(c,headers,parent,action,key=None) 等待任务，不直接调用裁决来代替 HTTP：清除 key；patch provider 为已知成功假响应并记录次数（避免错误假响应产生模拟未知费用）；取 root 第一个按钮；调用 turn；用 SessionLocal 查询 TurnEvent.adjudication 与该 run 的 LLMCall，断言来源/状态/次数；重放原 key 与 GET 节点。尚未实现时 Expected：缺密钥按钮被拒绝或多出叙事调用。

- [x] Step 2：补充 RED：新协议元数据不符调用前拒绝；controlled-content-1 恢复、无标记兼容、已经 approved 重复确认不升级；长反馈 >1200 字保存完整；事件仅出现一次；自由文本新密钥只调用 action.interpret 一次；401/未知费用/超时无部分节点；无密钥自由文本仍 key_not_configured。测试中 unknown_call/cleanup_records 仅清理该测试新建模拟会话，不删除真实账本。运行 `pytest tests/test_approved_feedback.py tests/test_stage2_evaluation.py -q`，读取失败原因。
- [x] Step 3：创建 checkpoint 默认 controlled-content-2，并固定 narration_protocol=approved-feedback-1；process 将 controlled-content-1/2 都派往现有内容操作，新协议检查附加呈现字段，旧协议附加新呈现字段视为不符。PROMPT_VERSION 不变，完整 proof/semantic/一次修复和已知费用后超时保护保持。保存候选版本时，按协议调用 Task 1 save_story_version 的 narration_protocol 参数；确认检查固定记录与 checkpoint 相符，approved 重放返回旧根。

```python
controlled = protocol in ('controlled-content-1', 'controlled-content-2')
narration_protocol = ('approved-feedback-1' if protocol == 'controlled-content-2' else 'model-scene-1')
# New protocol requires checkpoint['narration_protocol'] == narration_protocol;
# old protocols must not carry the new field. Existing identity/hash/prompt checks remain.
row = save_story_version(db, story, narration_protocol=narration_protocol)
```

- [x] Step 4：create_investigation_run 从绑定版本加载呈现协议，只有 R1+option 跳过 configured(provider) 检查；text 及旧模式仍原检查。process 从所选父节点的绑定版本读取协议并记录 presentation_selected，不读取兄弟分支。保留原 try/deadline、裁决、事务内二次裁决、Trace、状态和事件提交。只改 accepted 叙事分派：

```python
if decision.status == 'accepted' and narration_protocol == 'model-scene-1':
    # existing writing progress and render_investigation_scene call stay here
    draft = await render_investigation_scene(story, decision.state, normalized,
                                             decision.feedback, recent, registry, context)
else:
    draft = {'narration': decision.feedback, 'dialogue': []}
```

不为两行直接呈现另建单用抽象。R1 Node 用 approved-feedback-1/server:approved-feedback-1 标明来源；旧节点新回合依旧 PROMPT_VERSION/provider:model。所有模式保留 scene_validated/node_committed、fallback=false 和批准后 SSE；没有绕过 Trace 存储失败处理。
- [x] Step 5：用批准的 sample_data 加 SECRET_SENTINEL 建立 R1 独立版本；移动回合不得包含未发现证据/秘密，发现对应证据才披露。选包含事件的见证路径，assert narration==adjudication.feedback 且事件文本出现一次。长反馈使用原 Story Text 协议合法文本，不能删除尾部来通过 SceneTextDraft 的旧限制。保存父/兄弟原始 JSON，两个分支行动后逐项相等，回放 patch provider 与 apply_state_changes 确认零调用。
- [x] Step 6：stage2_evaluation 旧 controlled-content-1 检查改为明确建立旧协议任务的回归；新默认断言为 controlled-content-2。保留全部旧操作/否决测试，不把它们改为新无模型路径后假称原故障通过。必要 helper 按任务 checkpoint 明确设置旧协议，不能依靠 ID 前缀或加生产测试开关。重跑相关与完整后端，记录实际数据；提交 `feat: 接入已审核反馈回合与旧模式兼容`。

## Task 3：可追溯评测、人工材料与验收

**Files:** Modify `evals/run_stage2.py`, `backend/tests/test_stage2_evaluation.py`, `docs/03-development-plan.md`; Create `evals/export_stage2_review.py`, `backend/tests/test_stage2_review_export.py`, `docs/development-log/2026-10-11-stage-2-approved-feedback.md`, `docs/evaluation/2026-10-11-stage-2-approved-feedback-results.md`。按实际进度更新本计划及已批准设计，不改历史结果文件。

**Interfaces:** Consumes Task 2 checkpoint/StoryPresentation/Node/Trace；Produces 含实际 narration_protocol、terminal_node_id、operations 用量分类的新冻结报告，和只读本地人工材料；导出不调用 provider，不增加新 HTTP 接口。

- [x] Step 1：runner RED：正常新默认报告来源为 controlled-content-2/approved-feedback-1，measurement=real_model_with_approved_feedback；按钮不出现 scene.render/scene.semantic_check 用量，文本路径记录 action.interpret；原固定分母/hash 不变。每条成功路径记录 terminal_node_id、root_node_id 和实际 actions/free_text。新报告 ops 计数从本轮 attempt_started.operation 与关联 LLMCall 聚合，不能用路径数推算调用数；旧报告不改。
- [x] Step 2：实施 runner provenance：创建案例读取 checkpoint 与已绑定呈现记录核对；冻结文件和逐案结果保存实际值。报告顶层记录当前默认值与明示 measurement，失败与未知费用仍原样记账，不因全是纯按钮改变成功定义。原输出/进度保留。分别列真实创建、自由输入理解与服务器路径检查，不声称实时叙事模型成功率。
- [x] Step 3：写人工材料导出 RED，纯 helper `saved_path(db, terminal_node_id, root_node_id, session_id) -> list[Node]` 只沿父链直到确切根，返回根至终点顺序；错会话、错根、断链或循环报 review_path_invalid，不搜索兄弟节点。集成测试建两个兄弟分支及秘密哨兵，导出某终点不得带另一个分支正文。另测 3/12/缺终点/冻结 hash 不符报告拒绝，不生成“验收完成”文件。

```python
def test_partial_report_cannot_be_exported_as_review_material(tmp_path, monkeypatch):
    from evals import export_stage2_review as review_export
    monkeypatch.setattr(review_export, 'ROOT', tmp_path)
    monkeypatch.setenv('REVIEW_TEST_DATABASE', os.environ['DATABASE_URL'])
    report = tmp_path/'runtime/evals/review-test/report.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'suite':'real_model', 'summary':{'total':12,'succeeded':3}}), encoding='utf-8')
    with pytest.raises(ValueError, match='review_report_incomplete'):
        review_export.export_review(report, 'REVIEW_TEST_DATABASE')
```

`export_review(report_path: Path, database_url_env: str) -> Path` 在导出脚本定义；测试设置 REVIEW_TEST_DATABASE 为隔离 `_test` 库，不能含真实 key。
- [x] Step 4：实现 CLI `python evals/export_stage2_review.py --report <本轮report.json> --database-url-env MIGRATION_DATABASE_URL`。复用 validate_database_url；读取报告固定12项全部 succeeded、清单 hash、冻结故事 content_hash 和 terminal/root 归属，再读取已批准保存节点，不运行裁决/工具。仅写 report 所在 `runtime/evals/<run>/human-review.md`；拒绝 runtime/evals 之外报告路径，测试 monkeypatch ROOT 到 tmp_path 建相同结构。材料明确是本地有剧透评审文件：三故事简介、真相/证据关系、三结局、九路径完整已保存正文/对白、实际玩家输入、已发现证据/披露/承诺摘要和核查表；不包含 session token/hash、API key、Trace、失败候选或 connection URL。不会把该文件通过玩家 API/生成上下文提供。
- [x] Step 5：新模拟库顺序运行完整 `pytest -q`、`alembic check`、根目录 `evals/run_stage1.py --suite rules`、`--suite legacy`、`evals/run_stage2.py --suite runtime_simulated`，记录实际数量/时延/警告；检查文档本地链接及 `git diff --check`，核对原四草稿/骨架/清单 hash。提交代码与机器结果 `feat: 区分呈现评测来源并导出已保存人工材料`。
- [x] Step 6：对本补充已验证范围做一次独立最终只读审查，提供起止 commit、规格/计划及实际结果。按严重性完成一次必要修复，以每项 RED→GREEN 和完整受影响套件证明；不重复审查上一轮全部改动，不发每任务审查。记录所有裁定与延期 Minor。未通过修复前不发真实请求。
- [x] Step 7：真实前只读快照原库目前所有 34 节点/5 故事版本及旧报告 hash、账本 2.770514 CNY（启动时复核实际值）；增量 upgrade head，只新增表且不回填旧行，旧版本呈现仍 model-scene-1。核对官方供应商模型、参数、价格版本；本地隐藏输入内存密钥，经原 runner `--suite real_model --prompt-key` 执行同一12项，不读取聊天/.env/旧进程。新的结果同时标注新呈现模式，原3/12及所有历史消费保留；未知费用先核账，不能为通过继续换库/采样。
- [ ] Step 8：只有12项全部成功才运行导出；再次检查原全部节点/版本完整行 hash 和旧报告不变。请至少一位实际人工逐项核对三故事与九路径的证据支持、触发时可知性、无事实冲突、年代合理性、结局差异；真实用户答案与问题写入开发日志/新结果报告，不能把助手诊断算人工。若仍失败则保存明细并定位，保持阶段未验收。
- [ ] Step 9：全部门槛通过才完成阶段2/本计划及旧受控计划的未完成验收步骤；未通过不勾选。仅停本任务55438集群，保留全部数据。仅暂存相关文档并提交 `docs: 记录反馈呈现真实验收与人工结论`，不合并/推送。新模式不证明前端/图片/包装/OpenAI/多Agent完成。

## 计划自检与审阅状态

规格覆盖：Task1 固定协议/旧完整行保护，Task2 创建/恢复/确认/零调用呈现/自由输入与原子提交，Task3 口径/路径导出/旧失败保留/真人门槛。五项 Review Focus 分别有迁移降级、旧协议恢复、长文本事件、无钥匙费用边界、兄弟分支导出负例。

未增加供应商、框架、规则语言、自由生成重试、公共调试入口或故事内容重新采样开关。R1 的质量边界明确：避免回合新增扩写，不能代替创建内容人工检查。数据库结构是新增独立表，原 Story schema/hash 不变；Task2/3 都消费 Task1 精确 helper 名称与版本值。

本计划已自检，用户于 2026-10-11 确认“计划符合要求，继续实施”；执行方式继续沿用已选择的当前会话顺序实施。所有 Expected 都是预期，实际结果另记开发日志。
