# 阶段 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户已确认本计划，选用推荐的当前会话顺序实施，最后一次独立审查。实际验证及未完成门槛见[实施日志](../development-log/2026-10-10-stage-2.md)及[验收报告](../evaluation/2026-10-10-stage-2-results.md)；以下步骤保留原始验收要求，不能只凭代码存在勾选全部。

**Goal:** 交付可创建并确认自定义故事的普通调查流水线，通过严格执行、恢复、费用与 Trace 约束及三类背景真实验收。

**Architecture:** 复用阶段 1 的故事 schema、纯裁决及不可变存储。先实现独立持久化和统一执行边界，再将创建与行动接入；模型只返回提案，任务服务提交服务器裁决结果。

**Tech Stack:** Python 3.11+、Pydantic 2、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、asyncio、pytest；不增加队列或编排框架。

**Spec:** [已确认的阶段 2 设计](stage-2-custom-stories.md)，用户于 2026-10-10 明确回复“我已确认”并确认实施计划及推荐执行方式。相关约束：[运行可靠性](runtime-reliability.md)、[评测](../evaluation/task-success-baseline.md)。后端任务 1–7 已实施；任务 8 原动态叙事验收失败记录保留，后续已批准方案 A/R1/v2 完成固定真实 12/12 及一位用户五项剧情核查，阶段 2 已验收，见[最新结果](../evaluation/2026-10-11-stage-2-approved-feedback-results.md)。下面原步骤保留其历史要求，不将旧动态叙事勾选为真实通过。

## Global Constraints

- 三角色、五地点、三结局；沿用 investigation-story-1、investigation-1 和 schema_version=2，不改变阶段 1 冻结样本/hash。
- 用户确认首次真实评测补充后：完整设定生成/修复 v2 单次 120 秒，其余文字 v1 单次 20 秒、行动整体 60 秒、创建执行区间 300 秒；BFS 50,000 状态上限。取消和超时后禁止提交。
- 安全传输重试最多三次（首次加两次），退避 0.5/1 秒加 0–0.25 秒抖动；遵守 Retry-After。内容修复全故事至多一次，恢复不重置计数。
- 输出预算：故事生成/修复 12,000 token、行动理解 300、叙事 900、语义检查 2,000；接入前核实受控模型支持，价格需版本化。
- 全局费用 80 CNY 提醒、100 CNY 停止；每次调用/重试/修复重新检查。失败和未知 usage 不按免费处理；共享图片原子预留在阶段 3。
- 旧 Demo、DeepSeek 兼容路径及 API 保留；不开放 OpenAI、自定义故事前端、图片或多 Agent。
- 本地 .env、用户库、凭据和四份预存草稿均不纳入。使用独立工作树及 *_test 数据库，测试环境显式设置 DATABASE_URL/MIGRATION_DATABASE_URL，不读取原目录 .env。
- 每个任务完成红灯 → 最小实现 → 绿灯 → 验证 → 开发日志 → 相关提交；提交标题 English: 中文。只提交任务相关文件，不推送远端。

## Review Focus

1. 远端成功、本地账本失败：后续调用与剧情提交必须停止，记录审计/费用不确定状态；任务 1、2、6 验证。
2. 恢复请求和旧 worker 同时结束：任务认领、恢复来源和状态比较防止二次提交；任务 4、6 验证。
3. 模型 schema 失败但已有 usage：费用先持久化，候选至多修复一次；任务 2、3、4 验证。
4. 合法 ID 或玩家文本携带隐藏信息：公开选项使用不透明 ID，Trace 脱敏且语义检查否决泄漏；任务 1、5、6 验证。
5. Windows 子进程及失败报告：BFS 进程真退出、结果受限投影、不保存原始敏感诊断；任务 3、7 验证。

## 进入实施前的环境核对

- [x] 使用 using-git-worktrees 创建或复用本任务合适工作树，从含设计及本计划的提交开始，分支使用 codex/ 前缀。记录四份原目录草稿 hash，不复制用户 .env。
- [x] 定位现有 Python 3.12 和项目 .venv 的可执行文件；定位 PostgreSQL 工具，不创建猜测路径。使用 runtime/stage2-test 中独立本地端口、数据目录和数据库，禁止连用户故事库。若需要后台进程，在 Windows 隐藏窗口启动并记录自己启动的 PID。
- [x] 在独立 *_test 数据库 upgrade head、alembic check 后运行完整 `python -m pytest -q`（cwd=backend）。记录实际通过/失败/跳过；规则 `python evals/run_stage1.py --suite rules` 和兼容 `--suite legacy --database-url-env MIGRATION_DATABASE_URL` 均须非零失败策略生效。

## Task 1：创建任务、Trace 和失败用量持久化

**Files:** 修改 backend/app/models.py；新增 backend/app/execution_traces.py、backend/migrations/versions/0005_execution_records.py、backend/tests/test_execution_records.py。保留 0001–0004 原文。

**Interfaces:** execution_traces.py 定义冻结 dataclass `TaskRef(kind: Literal['action','creation'], task_id: str, session_id: str)`、`AttemptRef(trace_id: str, span_id: str, attempt_id: str, number: int)`；`TraceRecorder(factory)` 使用独立 Session 工厂，提供 `start(task: TaskRef) -> str`、`event(task: TaskRef,event_type: str,payload: dict) -> None`、`begin_attempt(task: TaskRef,operation: str,version: str,number: int,payload: dict) -> AttemptRef`、`finish_attempt(ref: AttemptRef,provider_outcome: dict,error_code: str | None) -> None`。内部 dict 仅供普通存储函数使用，注册操作仍使用专用严格 schema。

- [ ] 红灯：test_trace_survives_story_rollback（回滚剧情后独立轨迹/费用仍存在）、test_attempt_finalization_is_idempotent（同 attempt 只一笔费用）、test_unknown_usage_is_not_zero（token 为 NULL，费用状态 uncertain）、test_foreign_task_rejected（越权不写）、test_redacts_known_credentials_and_headers（输入/输出/异常无模拟 key、token、连接凭据）。命名条件各为独立测试，断言数据库保存结果。
- [x] 运行 `python -m pytest tests/test_execution_records.py -q`，确认缺失模型/接口导致失败。
- [ ] 实现 StoryTask/StoryTaskEvent、ExecutionTrace、Run trace 关联、Node 可空 investigation_options，以及 LLMCall 可空 token/run 与创建关联。LLMCall 恰好一种任务归属，attempt 唯一；旧值保留。锁任务分配序号，不能使用无锁 max+1。StoryTask 保存 story_id、候选检查点、repair_count、候选版本及恢复关联。
- [ ] 实现凭据脱敏和开始/收尾独立事务；重复收尾必须核对相同内容，不覆盖旧结果。存储错误用 `TraceStorageFailure` 中止调用者。增加真实并发序号测试及存在新记录时拒绝降级的迁移测试。
- [x] 执行本文件测试、旧 test_story_versions.py、隔离库 upgrade/check；核对旧记录升级前后原文和 NULL 关联。全部通过后提交 `feat: 增加创建任务与独立执行记录`。

## Task 2：统一执行器、供应商分类与预算

**Files:** 新增 backend/app/execution.py、backend/tests/test_execution.py；修改 backend/app/provider_clients.py、backend/app/costs.py；新增 backend/tests/test_provider_execution.py。

**Interfaces:** execution.py 定义 `ToolSpec(name,version,input_schema,output_schema,handler,timeout_seconds,max_attempts,retry_codes,side_effect_policy,estimate_cost)`、`ToolRegistry.register(spec)/get(name,version)`、`ExecutionContext(task: TaskRef,deadline: float,provider: str,model_id: str,recorder: TraceRecorder)`、严格 ToolSuccess/ToolFailure 联合 `ToolResult`；`async execute(registry: ToolRegistry,name: str,version: str,raw_input: object,context: ExecutionContext) -> ToolResult`。内部 handler 接收验证模型及 context，返回 provider_clients.py 定义的 `ProviderOutcome(text: str | None,input_tokens: int | None,output_tokens: int | None,error_code: str | None,request_sent: bool,retry_after: float | None)`。provider_clients 新增 `async call_operation_provider(provider,model_id,api_key,prompt,max_tokens,timeout_seconds) -> ProviderOutcome`，旧 call_provider 签名与兼容行为不变。

- [ ] 红灯：未知操作、重复注册、错误严格类型分别断言 handler 未执行；401 一次，安全 429 后成功为两次，耗尽为三次；读超时/5xx 一次且 outcome_unknown；非法输出不网络重试但 usage 已保存。test_deadline_includes_retry_after 断言大于剩余时间的 Retry-After 不重发；test_cancellation_propagates 断言取消传播且无后续调用。
- [x] 运行 `python -m pytest tests/test_execution.py tests/test_provider_execution.py -q`，确认失败后实现统一执行顺序。测试注入时钟/等待/抖动依赖，生产路径用 monotonic 和覆盖 attempt 的墙钟 timeout；不真实等待故障退避。
- [ ] 适配器分别处理未发出连接失败、安全明确 429、永久配置错误和未知结果，提取 usage 先于业务 JSON/schema。输入校验、授权、预算及开始记录任一失败均无 HTTP；Trace/账本收尾失败后停止。不吞取消，不重发无幂等保障的超时请求。
- [ ] 增加精确预算边界断言 80/100、失败用量入账、未知费用阻止下一次调用和账本失败中止；Trace 不保存原始 HTTP 头或异常响应。运行相关测试及旧 test_stage2_settings.py/test_stage2_generation.py，保留 legacy fallback 语义。
- [x] 验证后提交 `feat: 实现受控文字执行与故障分类`。

## Task 3：注册故事操作、语义协议与有界规则检查

**Files:** 新增 backend/app/operation_schemas.py、backend/app/story_operations.py、backend/app/reachability_worker.py、backend/app/investigation_generation.py（先交付纯选项函数）、backend/tests/test_story_operations.py、backend/tests/test_reachability_worker.py、backend/tests/test_investigation_options.py。

**Interfaces:** operation_schemas.py 定义 StoryGenerateInput(story_id,story_version,setting,era)、StoryRepairInput(同身份和背景,raw_candidate,issues)、StorySemanticInput(story,reachability)、SceneSemanticInput(story,public_world,adjudication_feedback,candidate)、SemanticReport(passed,issues)、SemanticIssue(code,entity_ids,description)；另定义任务 5 所用 ActionInterpretInput/Interpretation 和 SceneRenderInput/SceneTextDraft。story_operations.py 提供 `register_story_operations(registry: ToolRegistry) -> None`；reachability_worker.py 提供 `async validate_reachability(story: Story,deadline: float) -> ReachabilityReport`。investigation_generation.py 先提供纯函数 `build_public_options(story: Story,state: dict) -> tuple[list[dict],dict]`，返回公开 id/label 与内部 id/action 映射，供任务 4 建立根节点。

- [ ] 红灯：schema 额外字段/非法身份拒绝、语义 unknown entity/passed 与 issues 矛盾拒绝、生成/修复预算 12,000、检查预算 2,000。验证注册表含四项 story.generate/repair/semantic_check 和 scene.semantic_check，生成/修复执行策略现为 v2、检查为 v1（首次实施均为 v1），独立入参/出参。
- [ ] 运行上述两文件测试，失败后实现模型请求模板和 JSON 解析；业务非法候选的脱敏内部 artifact 引用进入 ToolFailure，以便一次修复，不能把未校验内容当成功返回。模型不能指定工具、版本或批准状态。
- [ ] 使用 Windows 可用的 spawn 工作进程运行既有 check_reachability，同一 50,000 上限；到截止时间必须 terminate/join 并拒绝，结果不得继续写库。test_worker_timeout_exits_process 断言进程退出，test_worker_matches_frozen_paths 断言与已有结果一致；异常只返回受限诊断。
- [ ] 先写选项负例再实现纯函数：只输出 accepted 动作、UUID 不含 topic_id、present 只已知证据、talk 标签仅角色名/序号、decide 只当前可选结局，内部映射不进入公开字段。运行操作/工作进程/选项及 test_investigation_schema.py/test_investigation_rules.py，核对 Story 和固定 fixture hash 不变。真实参数和价格核对在任务 8 的调用前完成，不据模拟输出宣称供应商支持。
- [x] 验证后提交 `feat: 注册故事生成与有界语义检查`。

## Task 4：故事创建、一次修复、确认和显式恢复

**Files:** 新增 backend/app/story_creation.py、backend/app/story_api.py、backend/tests/test_custom_story_creation.py；修改 backend/app/main.py、backend/app/story_versions.py（仅新增确认辅助，不改变存储协议）。

**Interfaces:** story_creation.py 定义严格 CreationRequest(setting,era)、ConfirmationRequest(candidate_version_id,content_hash)；`create_custom_session(provider: str,model_id: str) -> tuple[str,StorySession]`、`create_creation_task(session_id: str,request: CreationRequest,key: str) -> tuple[StoryTask,bool]`、`async process_creation_task(task_id: str) -> None`、`confirm_creation(session_id: str,task_id: str,request: ConfirmationRequest) -> Node`、`resume_creation(session_id: str,task_id: str,key: str) -> tuple[StoryTask,bool]`、`interrupt_creation_tasks() -> None`。StoryTask 检查点消费任务 3 schema 和执行结果。story_api 定义 APIRouter；认证依赖以挂载时依赖注入避免 main 循环导入。

- [ ] 红灯：创建空会话无根、去空白 setting 长度 1–500、三年代枚举、未经批准 turns 为 story_not_ready。模拟完整生成后 assert awaiting_confirmation、一个 draft、零节点；两次相同确认 assert 同一 root、approved、一个节点；错误 hash 或他人 task 为拒绝。
- [x] 运行 `python -m pytest tests/test_custom_story_creation.py -q`，失败后实现设计第 3 节全部端点及 SSE。新 API 不开放其他模型，旧 /sessions 响应不变。任务认领行锁/条件状态更新；阶段/序号只输出公开事件。
- [ ] 写负例：结构/规则/语义任一失败只一次 repair；repair 失败无根且非恢复可追加；过程重启/恢复保留 candidate、repair_count，批准重放无 HTTP。旧 worker 与 resume 同时到达、同键真并发、同键不同输入分别断言单一有效任务/根节点和 409。
- [ ] 实现检查点和创建 300 秒区间；确认在一个事务里核对检查通过/hash、绑定 immutable story、根快照/开场和 task 终态。公开开场使用已检查简介，根选项使用任务 3 的 build_public_options，不调用开场生成模型。
- [ ] 运行创建测试、旧会话/API 测试及失败 rollback/Trace 存活测试；仅全部通过提交 `feat: 接入自定义故事创建确认与恢复`。

## Task 5：公开行动选项、自由输入与叙事生成

**Files:** 修改 backend/app/investigation_generation.py；新增 backend/tests/test_investigation_generation.py；补齐任务 3 operation_schemas.py/story_operations.py 的行动与叙事注册。

**Interfaces:** 消费任务 3 的 build_public_options；新增 `register_investigation_operations(registry: ToolRegistry) -> None`、`async interpret_action(story: Story,parent_state: dict,action: app.schemas.Action,options: dict,recent_turns: list[dict],context: ExecutionContext) -> dict | None`、`async render_investigation_scene(story: Story,decision: Adjudication,action: dict,recent_turns: list[dict],context: ExecutionContext) -> dict`。Interpretation 为 recognized(action)/unrecognized 联合；SceneTextDraft 仅 narration、dialogue，字数/情绪/在场 NPC 约束与设计一致。服务器组装 scene_id/options/fallback 等已批准元数据。

- [ ] 红灯：option 不调用理解；free text recognized 仍受纯裁决；不可映射为 None；输入无 truth/secret/未知证据/内部 Trace。test_option_ids_do_not_reveal_rule_targets 断言 UUID 不含 topic_id、映射不进入玩家输出；test_foreign_parent_option_is_rejected 断言其他父节点 ID 无法解析。
- [x] 运行 `python -m pytest tests/test_investigation_generation.py -q`，失败后实现按钮归属解析和自由文本解释，消费任务 3 的服务器选项，不改写任务 4 已提交根节点。
- [ ] 注册 action.interpret.v1（300 token）、scene.render.v1（900 token）；构建只含公开资料和三个祖先回合的 prompt。不得传角色私有事实；结构化裁决公开反馈允许刚发生事件披露。
- [ ] 写并运行叙事错误角色、额外 state_changes、伪造场景、未知秘密、恶意玩家指令负例；结构失败或 scene.semantic_check 否决均抛稳定失败，无内容修复。语义检查可见内部事实只用于否决，检查结果不得进入后续生成上下文。
- [ ] 联调并运行任务 3–5 的测试；通过后提交 `feat: 实现受裁决约束的行动理解与叙事`。

## Task 6：调查任务提交、公开 API 和回放

**Files:** 新增 backend/app/investigation_jobs.py、backend/tests/test_investigation_api.py；修改 backend/app/jobs.py、backend/app/main.py、backend/app/story_api.py，仅增加版本分派和公开过滤。

**Interfaces:** investigation_jobs.py 提供 `create_investigation_run(session_id: str,parent_node_id: str,action: app.schemas.Action,key: str) -> tuple[Run,bool]`、`async process_investigation_run(run_id: str) -> None`、`recent_investigation_turns(db,parent_node_id: str) -> list[dict]`、`public_investigation_node(node: Node) -> dict`、`public_investigation_events(db,node: Node) -> list[dict]`。沿用 task 1 TraceRecorder、task 2 context、task 5 生成接口；不让生成模块写 Node。

- [ ] 红灯：五类行动、同地点多轮、无效/重复不加回合、披露/承诺/事件一次性；兄弟秘密哨兵不进入 recent_turns；纯反馈回合无叙事 HTTP。assert 选中 parent 原样，节点内部完整快照与玩家公开状态分别正确。
- [x] 运行 `python -m pytest tests/test_investigation_api.py -q`，失败后实现 run 认领、60 秒截止时间和版本分派。旧 engine 空值仍走现有 jobs 逻辑，未知 engine 明确拒绝。
- [ ] 提交锁 run/session、重算裁决及确认一致；原子写 Node、结构化 TurnEvent、run、批准后 SSE。test_timeout_and_cancel_never_commit、test_commit_failure_keeps_usage_and_trace、test_old_worker_cannot_commit_resumed_task 分别检查无半节点和独立审计保留。
- [ ] 实现 GET /session/world、公开 node/event/tree、run/SSE 白名单；跨会话均拒绝，隐藏字段/映射/秘密不出现在 JSON 或 SSE。test_replay_calls_no_generation_or_rules 用拒绝执行的生成器/裁决入口验证仍返回保存原文，不重新过滤修改已批准文本。
- [ ] 真实并发同键一个 run/node、SSE after 不重不漏、重启 interrupted 和新键行动恢复通过；跑任务 4–6 与旧 tests/test_stage1.py/test_stage2_generation.py/test_stage3_context.py。通过后提交 `feat: 接入调查回合与不可变公开回放`。

## Task 7：固定故障评测和只读 Trace 检查

**Files:** 新增 evals/run_stage2.py、evals/cases/stage2.json、backend/tests/test_stage2_evaluation.py、scripts/inspect-execution-trace.py；复用 evals/pytest_status.py 的安全计数和阶段 1 报告工具，必要共享提取仅限避免两套安全计数实现。

**Interfaces:** stage2 入口 `--suite runtime_simulated|real_model --database-url-env MIGRATION_DATABASE_URL`；`run_suite(suite: str,database_url_env: str) -> tuple[dict,Path]`、`summarize(results: list[dict]) -> dict`。每个 case 固定 ID、故障种子/时钟、初始状态、断言入口和预期；real_model 请求清单先固定，生成后故事/路径另存 hash。检查命令只读 trace_id，不提供玩家 HTTP 接口。

- [ ] 红灯：empty suite 拒绝；skip/error/timeout/未实现保留分母且非零；继承 pytest 筛选被清除，发现 deselected 为失败；未知测试库在连接前拒绝；原始诊断中的模拟密钥不落保存产物。
- [x] 运行 `python -m pytest tests/test_stage2_evaluation.py -q`，失败后实现 safe status 计数、Git/prompt/故事/清单/价格版本、attempt 数、使用/费用状态及失败明细。真实创建失败保留原 case，不删除或换故事刷成功。
- [ ] 只读检查命令拒绝越权/未知 trace 并使用脱敏输出，测试里 handler/HTTP/状态提交均设为禁止执行，仍可复盘保存记录。
- [ ] 运行完整后端 pytest、rules/legacy 与 stage2 runtime_simulated；任何必需 skipped 都不宣称全验收。独立库 upgrade/check 和旧数据原样核对后记录计数、失败和耗时。
- [x] 验证后提交 `test: 固定阶段二故障评测与轨迹复盘`。

## Task 8：真实路径、最终审查与阶段记录

**Files:** 新增 docs/evaluation/2026-10-10-stage-2-results.md（实际执行若跨日期使用执行日）、docs/development-log/2026-10-10-stage-2.md；修改 docs/02-technical-design.md、docs/03-development-plan.md、docs/design/runtime-reliability.md，只有实际通过才更新状态。真实结果和候选正文在 runtime，不能入 Git。

- [ ] 在任何真实调用前查供应商官方文档，核实受控模型、输出预算、响应参数和价格；记录来源/核对日/价格版本。若现有 model_id 或 12,000 budget 不支持，先更新设计并明确该差异，不悄悄换模型。真实密钥只经后端内存设置流配置，不读 .env 或输出密钥；缺少密钥则完成其他工作并如实标记真实验收未执行。
- [ ] 固定 ancient/modern/future 三项创建任务及预期；逐项执行生成、检查和显式确认。运行真实路径前冻结每局故事/hash 和三个结局 witness；每局至少一条完整分支包含自由文本，其余可按服务器按钮行动，不直接注入内部 Action 冒充端到端。
- [ ] 分别统计创建、行动理解、叙事、语义、三个结局及恢复结果；记录实际 attempt、usage/未确认费用、时延和人工剧情核查人数。只通过 schema 不替代人工语义评审；无人工核查不宣称该门槛已通过。
- [ ] 最终运行完整后端 pytest、alembic check、rules/legacy/runtime_simulated 和 real_model；更新实际报告，分开规则、模拟及真实结果。未改前端则明确未运行前端测试/构建，不声称图片或最终体验验收。
- [ ] 一次独立最终审查，重点依据 Review Focus 核对状态权限、失败记账、任务竞争、过滤和取消；修复发现的问题时先写失败复现，再运行受影响检查。不为无新证据重复全量审查。
- [ ] 核对文档链接、历史验收保留、git diff --check、四份草稿 hash 及暂存清单；停止本轮独立测试集群。全部阶段门槛通过才勾选阶段 2，否则记录准确剩余项。提交 `docs: 记录阶段二实测与验收状态`。

## Plan Self-Review

设计 1–2 节对应任务边界和环境核对；3–4 节对应任务 1/3/4；5 节对应任务 3/5/6；6 节对应任务 6；7–8 节对应任务 1/2/7；9 节对应任务 4/6；10 节对应任务 7/8。任务 3 先交付纯选项接口，任务 4 可独立创建完整根节点，任务 5 再补行动和叙事，避免循环依赖和占位输出。五项 Review Focus 均有对应负例，关键参数与已确认设计一致；所有实施步骤保持未勾选。
