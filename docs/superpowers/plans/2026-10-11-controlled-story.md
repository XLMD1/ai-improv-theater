# Controlled Story Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans 在当前会话逐任务实施。用户此前已选顺序执行，不重新选择执行方式；用户已于 2026-10-11 确认本计划，按实测记录实施进度。步骤使用复选框，验收未通过不得勾选完成。

**Goal:** 通过受控调查骨架与严格内容协议交付阶段 2 自定义故事，并完成原三背景创建、九结局路径与人工核查。

**Architecture:** 模型只填写内容；纯组装函数把内容与独立版本化骨架合成现有 Story。创建任务在检查点固定协议、骨架 hash 和 prompt 版本，新操作经统一执行边界记账后再组装、规则校验与语义检查。旧无标记的任务继续完整 Story v2 兼容路径，已保存节点不改。

**Tech Stack:** Python 3.12、Pydantic 2、FastAPI、SQLAlchemy、PostgreSQL、pytest、现有执行注册表和可达性工作进程；无新增依赖。

**Spec:** [已批准方案 A](../../design/stage-2-controlled-story-proposal.md)，用户于 2026-10-11 选择“采用 A，认可草案（推荐）”；基础[阶段 2 设计](../../design/stage-2-custom-stories.md)与[可靠性要求](../../design/runtime-reliability.md)继续适用。

## Global Constraints

- 三角色（主角与两位 NPC）、五地点、三个不同后果结局；15–25 行动仍为体验目标，记录实际路径。
- 每局独立实体 ID，不使用 Demo 固定 ID。模型不能输出/覆盖条件、效果、出口、固定知识引用或状态。
- 完整 Story 校验、有界可达性、语义及公开信息检查全部保留，至多一次内容修复；不替换或放宽失败故事来提高成功率。
- 新生成/内容修复操作独立版本、严格 Pydantic 协议，通过既有执行入口；调用先持久化 usage/Trace，再解析内容和组装，失败用量不能因事务回滚丢失。
- 生成/修复单次 120 秒、创建总限时 300 秒；其他文字单次 20 秒、行动总限时 60 秒；重试、修复共享截止时间和预算。
- 已保存节点/渲染/批准故事版本保持原样，回放零 provider 调用。恢复使用原检查点版本；未知版本拒绝，不猜测或自动升级。
- 80 CNY 警告、100 CNY 停止、未知费用阻断及现有人工核账保持。实际与估算分列，密钥仅进程内存。
- 同一 stage2_real_test 继续真实评测，原 12 项真实清单及 10 项模拟清单不改。模拟/规则/真实/人工分别记录。
- 当前工作树 `C:/Users/Lenovo/.codex/worktrees/stage2-custom-stories/ai-improv-theater`，分支 `codex/stage2-custom-stories`。不改原目录四份草稿，不合并/推送。
- 不改前端、图片、包装、OpenAI、多 Agent、云数据库；Demo 与旧存档保留。不据设计批准或代码存在宣称阶段完成。

## Review Focus

- 未知检查点协议/骨架 hash：新 provider 调用前拒绝，保留输入与历史记录（Task 3）。
- 内容缺失/额外/重复槽位，伪装规则字段，身份版本不符：严格拒绝，不能删掉问题字段后接受（Task 1、2、3）。
- 中断在 usage 保存之后、检查点保存之前：原费用保留，恢复不盲重发；使用原协议与原修复次数（Task 3）。
- 合法文本却提前剧透、证据不支持真相、结局叙述不支持状态：语义否决仍有效，批准前不提交节点（Task 3、4）。
- 调查模板 ID 泄漏到新局、跨故事/兄弟分支上下文或旧存档回放：完整兼容与隔离检查，旧节点 hash 不变（Task 2、4）。

## 文件与接口

| 文件 | 职责 |
|---|---|
| `backend/app/data/controlled_investigation_v1.json` | 单独冻结骨架和中性槽位指导文本；记录来源与版本，不是默认可游玩故事 |
| `backend/app/story_content.py` | 内容协议、骨架加载/ID 映射、纯组装，禁止数据库和 provider 导入 |
| `backend/app/operation_schemas.py` | 新内容生成/修复入参，与旧完整 Story 协议并存 |
| `backend/app/story_operations.py` | 注册新操作、内容提示和动态槽位 schema；旧操作策略保留 |
| `backend/app/story_creation.py` | 检查点固定协议，分派内容生成/修复，复用校验和批准路径 |
| `backend/tests/test_controlled_story.py` | 内容与组装的纯协议/规则断言 |
| `backend/tests/test_custom_story_creation.py` | 原完整 Story v2 兼容回归，标明版本；共享假 provider 兼容新内容协议 |
| `backend/tests/test_stage2_evaluation.py` | 新默认创建/修复/恢复与真实 runner 模拟路径，仍被原固定模拟清单覆盖 |
| `evals/run_stage2.py` | 报告实际协议/骨架版本和 hash；原清单/分母不变 |
| `docs/development-log/2026-10-11-stage-2-controlled-story.md`、`docs/evaluation/2026-10-11-stage-2-controlled-story-results.md` | 实际验证、失败、审查与人工记录 |

### 协议的确定选择

`ControlledStoryContent(StrictModel)` 必含 `schema_version='investigation-content-1'`、`blueprint_version='controlled-investigation-1'`、请求的 `story_id/story_version/setting/era`、`title/public_intro`。其余全部是以模板实体 ID 为键的字典，键集必须与该组骨架完全相等：

| 字段 | 值模型/允许内容 | 固定关系 |
|---|---|---|
| characters | `CharacterContent(name, goal, taboos, appearance)` | 3 个槽位；位置、知识、秘密引用由模板固定 |
| locations | `NamedContent(name, description)` | 5 个槽位；出口固定 |
| objects | `NamedContent` | 12 个槽位；所在地点固定 |
| evidence | `EvidenceContent(description)` | 12 个槽位；fact_ids 固定 |
| truth | 现有 `Truth(text, facts)`，facts 的 6 个键固定 | 六类事实内容生成，证据与角色知识关系固定 |
| disclosures | Text | 4 个槽位；角色、fact_ids 固定 |
| commitments | Text | 1 个槽位；角色固定 |
| action_feedback | Text | 16 个槽位；行动、条件、效果、once 固定 |
| event_feedback | Text | 1 个槽位；条件和效果固定 |
| endings | `EndingContent(title, consequence)` | 3 个槽位；条件固定 |

所有内容模型 `extra='forbid', strict=True, frozen=True`。字典不采用 list，JSON 中重复键必须在解析时拒绝，不能让最后一个值静默覆盖前一个。`ControlledStoryContent.model_validate_json` 在调用父类之前用同一 hook 检查原始字符串；`parse_story_content` 调用该方法。这样真实 provider 在现有执行边界内就会被检查，不能先经 Pydantic 再序列化而丢失重复键。现有执行入口已把 ValueError/ValidationError 归为 output_validation 并保存脱敏原稿，usage 先于该检查保存；不修改通用执行器。恢复也走同一入口。模板关系语义随输入提供，不把原样本原文当成新故事生成结果。

生产模板由已批准样本的关系拓扑派生，文本全部替换为中性槽位说明；不是直接读取测试 fixture。`i_<story UUID hex>_<slot>` 生成该局独立 ID，映射全部实体、事实键和 talk 的 topic_id，长度不超过 64；不得替换生成文本中的任意子串。模板不包含动态插件或模型代码。

## Task 1：冻结骨架与严格内容协议

**Files:** Create `backend/app/data/controlled_investigation_v1.json`, `backend/app/story_content.py`, `backend/tests/test_controlled_story.py`；先更新 `docs/01-requirements.md`、`docs/02-technical-design.md`、`docs/design/stage-2-custom-stories.md` 的已确认生成方式，再改产品代码，日志记录实际检查。

**Interfaces:** Consumes 现有 `Story`, `StrictModel`, `canonical_hash`, `check_reachability`。Produces `BLUEPRINT_VERSION`, `BLUEPRINT_SHA256`, `ControlledStoryContent`, `load_blueprint_template(story_id: str, story_version: str, setting: str, era: str) -> Story`, `parse_story_content(raw: str) -> ControlledStoryContent`。

- [x] Step 1：写 RED 测试，两个不同 UUID 模板 ID 完全分离，3/5/3、所有引用合法，证明 passed、三个见证均 21 步；缺额外字段及重复 JSON 键拒绝。

```python
def test_blueprint_has_frozen_reachable_structure():
    from app.story_content import load_blueprint_template
    from app.story_validation import check_reachability
    story = load_blueprint_template('00000000-0000-0000-0000-000000000001','draft-1','古代河运','ancient')
    proof = check_reachability(story)
    assert proof.status == 'passed'
    assert sorted(map(len,proof.ending_paths.values())) == [21,21,21]
    assert proof.states_checked == 70
```

- [x] Step 2：在 `backend/` 运行 `python -m pytest tests/test_controlled_story.py -q`，Expected：新模块/协议缺失而失败。不得用别的导入异常代替真实 RED。
- [x] Step 3：冻结模板，中性说明准确描述指令、偏转、主动破坏、救援、隐瞒和受保护者六类事实。生成 32 hex UUID 前缀，递归仅映射模板 ID 字段/事实键/话题引用，保留原关系；校验资源 SHA256，不匹配或未知版本报 `blueprint_version_mismatch`。实现上述严格内容模型，重复 JSON 键检查用下列入口，受控内容 schema 版本不能改旧 Story。

```python
def reject_duplicate_keys(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate_content_key')
        result[key] = value
    return result
```

JSON 在该 hook 检查后，Pydantic 仍用父类 `model_validate_json` 保持 UUID/严格 JSON 类型语义；错误详情通过现有脱敏审计路径。资源严格 envelope 只含 `blueprint_version`、`source_story_hash`、`template`，template 按现有 Story 校验；模块校验冻结文件原始 bytes 的 SHA256。模板 SHA256 在生成资源后实际计算并写入模块/断言，不填写猜测值；资源来自固定批准 hash `dbdb37eb57b2eaf90eddfb42246189920147fa94adfeef85cf43598bcbd3ce79`，原 fixture 不修改。提供器返回重复 JSON 键的集成负例还须断言 output_validation、原稿可修复、已产生 usage 保留，不能只测纯解析函数。
- [x] Step 4：增加未知资源版本/hash、错误/重复/超长 ID、额外 action_rules/conditions 字段的具体负例；重跑同一套件 Expected：全部通过，无 provider 调用。记录实际模板 hash/状态数。
- [x] Step 5：仅暂存上述资源/模块/测试/文档，提交 `feat: 冻结受控调查骨架与内容协议`。

## Task 2：纯组装与内容操作注册

**Files:** Modify `backend/app/story_content.py`, `backend/app/operation_schemas.py`, `backend/app/story_operations.py`, `backend/tests/test_controlled_story.py`, `backend/tests/test_story_prompt_identity.py`。

**Interfaces:** Consumes Task 1 协议和模板；Produces `assemble_story_content(template: Story, content: ControlledStoryContent) -> Story`, `ControlledGenerateInput`, `ControlledRepairInput`，操作 `story.content_generate.v1` / `story.content_repair.v1`。

- [x] Step 1：写 RED 断言：逐组缺失或未知键、身份/年代/版本/背景错配拒绝，原模板不变，组装前后结构投影相同。合法修改只作用于文本；带状态/条件的内容在协议层即拒绝。

```python
def test_compilation_never_changes_exits_or_effects(controlled_template, controlled_content):
    from app.story_content import assemble_story_content
    from app.story_schema import canonical_hash
    before = canonical_hash(controlled_template)
    story = assemble_story_content(controlled_template,controlled_content)
    assert [l.exits for l in story.locations] == [l.exits for l in controlled_template.locations]
    assert [(r.action,r.conditions,r.effects,r.once) for r in story.action_rules] == [
        (r.action,r.conditions,r.effects,r.once) for r in controlled_template.action_rules]
    assert canonical_hash(controlled_template) == before
```

`controlled_template` 与 `controlled_content` fixtures 在该测试文件定义：模板调用 Task 1，内容取模板全部允许文本字段形成严格字典，身份字段使用同一请求；不导入数据库。
- [x] Step 2：运行 `python -m pytest tests/test_controlled_story.py tests/test_story_prompt_identity.py -q`，Expected：组装/新注册项尚缺失，失败。
- [x] Step 3：纯函数先比较身份与每组实际/预期键集，分别报告组名、missing/extra ID；复制模板、逐字段填文本，最后 `Story.model_validate`。不通过删除未知键或合并内容修复候选。

```python
def require_slots(group, actual, expected):
    if set(actual) != set(expected):
        raise ValueError(f'content_slots:{group}:missing={sorted(set(expected)-set(actual))}:extra={sorted(set(actual)-set(expected))}')
```

- [x] Step 4：`ControlledGenerateInput` 继承现有生成身份入参，增加严格 `blueprint_version`、64 位 `blueprint_sha256`、`template: Story`，入参校验模板身份与顶层相同。修复入参再加 `raw_candidate`（256,000 字符上限）与 `issues`（最多 20）。注册两项新操作，输出为严格 `ControlledStoryContent`，timeout=120/max attempts=3/安全瞬态分类和外部非幂等策略保持；预算仍 12,000。旧 `story.generate.v2`/`story.repair.v2` 与其他 v1 都保留。
- [x] Step 5：内容提示 schema 固定四个身份字段与骨架版本；把各组 dict 的 properties/required 明确为模板 ID，additionalProperties=false，truth.facts 同理。传入模板仅作为内容关系指导，提示不能输出规则。`PROMPT_VERSION` 使用新的实际版本 `investigation-single-6`；旧完整生成兼容操作保留原完整 Story 说明，元数据区分旧操作而非抹除旧 Trace。使用统一 adapter，不在组装函数或 UI 调 provider。
- [x] Step 6：捕获假 provider 请求，断言请求中各组 ID/结构和输出 schema 的身份/槽位约束；同一注册项连用两份模板无 schema 污染。运行 Step 2 同一命令 Expected：全部通过。提交 `feat: 组装受控故事并注册内容操作`。

## Task 3：创建检查点与一次内容修复

**Files:** Modify `backend/app/story_creation.py`, `backend/tests/test_custom_story_creation.py`, `backend/tests/test_stage2_evaluation.py`；必要共享测试 helper 放在 `backend/tests/`，不新增生产兼容开关。

**Interfaces:** Consumes Task 2 注册操作/解析/纯组装；Produces 新任务默认 `creation_protocol='controlled-content-1'`，内部 checkpoint 保存 `blueprint_version`, `blueprint_sha256`, `prompt_version`, `content_raw` 和已有 `raw/proof/semantic_passed/repair_*`。无新 HTTP 字段或数据库迁移。

- [x] Step 1：写新默认 API RED 测试：实际设置 fixture key，严格假 provider 产生内容；创建 awaiting_confirmation 前无节点，确认幂等只得一个根。假 provider 在内容生成输出含 action_rules/缺槽位时一次修复，第二次仍错则失败无节点；语义 veto 也只能修复一次。
- [x] Step 2：保留原完整 Story v2 故障回归。在旧测试模块用明确兼容 fixture，patch `story_api.create_creation_task`：原函数创建 queued 任务后，在路由 dispatch 之前把该测试任务 checkpoint 清空，再返回；模拟旧持久化任务。不能给生产新增开关。共享 `successful_provider` 识别新入参 template 返回内容，旧入参仍返回 Story；新的默认/API/runner 测试放在 `test_stage2_evaluation.py`，使原固定模拟清单确实执行到新边界。
- [x] Step 3：在 `backend/` 运行 `python -m pytest tests/test_custom_story_creation.py tests/test_stage2_evaluation.py -q`，Expected：新默认/检查点/修复分派断言失败，旧兼容回归仍覆盖原含义。
- [x] Step 4：新任务创建时固定协议与 hash。process 在已持有原 300 秒 deadline 的 while 内分派：旧无标记 checkpoint 走原完整 Story v2；新协议调用内容操作、先由执行入口保存 attempt/usage，再持久化脱敏原始内容、parse/assemble，进入现有 Story/身份/有界 proof/语义检查。未知协议/hash 在外部调用前拒绝。恢复原标记，不升级或重建已通过内容。
- [x] Step 5：修复使用目标 draft-2 新模板、原 `content_raw` 和有界脱敏 issues，输出仍为内容；每次 checkpoint 更新保留协议/provenance，清除旧 raw/proof/semantic_passed 后重新组装与全检查。repair_count/repair_started/repair_done 均沿用原至多一次和恢复限制。确认根节点使用任务固定 prompt，不改变已经保存的根。
- [x] Step 6：补充取消/重启、未知协议/骨架、已知费用失败/未知费用阻断、usage 已存而检查点未写、错误修复版本、公开任务不暴露 raw/proof/secret 的负例；断言 provider 次数、无新增失败节点和父状态不变。确认重复回放/恢复已通过检查点不重新生成内容；既有 approved 结果原样返回。
- [x] Step 7：重跑 Step 3 同一命令 Expected：全部通过；`python -m pytest -q` Expected：完整后端全部通过，记录实际数字和警告。提交 `feat: 接入受控内容创建与检查点恢复`。

## Task 4：固定评测、审查与真实人工验收

**Files:** Modify `evals/run_stage2.py`, `backend/tests/test_stage2_evaluation.py`, `docs/03-development-plan.md`；更新 Task 1 已同步的需求/设计中的实际状态，Create 前述开发日志和实测报告。只有正式通过时才更改阶段验收状态。

**Interfaces:** Consumes Task 3 默认创建，保存 Story/proof、registry/provenance；Produces 含 `creation_protocol`, `blueprint_version`, `blueprint_sha256` 的新真实报告/冻结文件及明确人工记录。历史报告/节点/usage 不改。

- [x] Step 1：写 runner RED 测试，受控默认能确认并用公共按钮/文字走冻结三结局，冻结文件/报告包含骨架来源；provider 不因加载 trace/回放再次调用。命令 `python -m pytest tests/test_stage2_evaluation.py -q`，Expected：新增 provenance 断言失败。
- [x] Step 2：只加来源元数据，不能改清单、取样、分母或语义门槛。继续按保存 proof，无重复 BFS；保留逐项进度、失败 error_code 与人工人数初始 0。模拟无法证明自然语言质量，拒绝把假 provider passed 当人工评审。
- [ ] Step 3：启动本任务自己的 55438 集群；模拟/迁移只用 stage2_prompt_test，真实继续 stage2_real_test。运行完整后端、`python -m alembic check`、根目录 `python evals/run_stage1.py --suite rules` / `--suite legacy` / `python evals/run_stage2.py --suite runtime_simulated`。Expected：各套件全部通过、迁移无新操作；失败则明确诊断修复，不补写结果。
- [ ] Step 4：只对本计划的已验证变更做一次独立最终审查，提供设计/计划/起止 commit/实测。按严重性完成一次必要修复，RED→GREEN 与受影响套件；不重审原完整阶段或重复发实现者审查。
- [ ] Step 5：真实调用前核对官方模型/输出模式/参数与价格版本。打开本地隐藏输入终端，经原 runner `--suite real_model --prompt-key`；不能从聊天/.env/旧进程读取密钥。原 12 案例全部执行，同一真实数据库保留历史消费，报告实际节点/路径/usage/时延/恢复，未知费用先核账再新调用。
- [ ] Step 6：全部三个创建和九路径成功才准备本地忽略目录人工材料，包含三故事真相、证据关系、结局与保存的完整场景；任何内容是已批准结果，未验证稿不进入玩家响应。请至少一位真实评审逐项核查剧情、事实与泄漏，记录其回答与问题，不由助手冒充人工人数。
- [ ] Step 7：只有真实/人工门槛全过，才更新阶段 2 和计划复选框。若仍失败，保留失败报告和准确信息，不宣称完成。核对文档链接、历史批准/hash、`git diff --check`、原目录四份草稿 hash；仅停本次测试集群，保留数据。提交 `docs: 记录受控故事实测与阶段验收`，不合并/推送。

## 计划自检与待审阅状态

规格覆盖：Task 1 骨架/严格内容，Task 2 纯组装/独立操作，Task 3 创建/修复/恢复/失败审计，Task 4 固定评测/来源/审查/真实与人工。Review Focus 五项均在对应任务有负例或回放断言。没有新增依赖、产品开关、规则执行语言、测试外真库重置或重复 benchmark 入口。

原样本只读检查是现有能力的验证，不能作为新骨架已完成。生产骨架 hash、完整测试计数、模型质量/时延与人工人数都要实施后实际记录；不预填结果。用户已确认该计划，保留此前顺序执行方式；完成项仅指其记录的实现/检查，不代替阶段验收。
