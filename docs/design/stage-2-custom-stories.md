# 阶段 2：自定义故事与普通流水线设计

日期：2026-10-10；设计版本：1。
状态：用户于 2026-10-10 确认设计及[实施计划](stage-2-implementation-plan.md)，选择当前会话顺序实施和一次最终独立审查。后端实现及模拟验证已开展；真实三类背景路径和人工剧情核查未通过，阶段 2 尚未验收。实际结果见[实施日志](../development-log/2026-10-10-stage-2.md)。
依据：[阶段计划](../03-development-plan.md)、[故事规则](stage-1-story-rules.md)、[运行可靠性](runtime-reliability.md)、[评测口径](../evaluation/task-success-baseline.md)。

## 1. 目标、范围与实施顺序

把阶段 1 已验收的 investigation-1 规则底座接入 DeepSeek 自定义故事创建和普通行动流水线。首版仍为三角色、五地点、三结局，保留无密钥 Demo、旧 DeepSeek 会话、原样回放和旧 API。古代、近现代、未来三类背景须实际创建并完成后端完整路径。

本阶段交付后端接口、可执行评测及验收记录；完整新前端、配图和跨浏览器恢复在阶段 3，便携包、OpenAI、多 Agent 按后续阶段实施。新故事入口暂不在旧前端开放。后台批准并建立根节点是阶段 2 的后端可运行状态，不代表图片准备或最终游玩体验已验收。

选择先建立执行器/Trace，再接创建任务，最后接调查回合：每个真实调用从首次接入即受超时、费用和审计约束。直接先接故事生成虽然更快看到结果，却需要后来改写调用及失败路径；同时改造前端则超出本阶段范围。沿用现有 FastAPI、SQLAlchemy、PostgreSQL、Pydantic 和 asyncio，不增加编排框架或后台队列服务。

## 2. 现有模块与新增职责

已实现的 story_schema.py、investigation.py、story_validation.py、state.py 和 story_versions.py 继续负责故事协议、裁决、公开投影、可达性及不可变存储。生成器只能返回提案，数据库状态仍由任务服务通过统一更新路径提交。

新增模块按职责划分：

| 模块 | 职责 |
|---|---|
| execution.py | ToolSpec、注册表、严格执行、错误分类、有限退避、截止时间 |
| execution_traces.py | 独立事务写入脱敏轨迹和 attempt 用量、只读本地检查 |
| story_creation.py | 创建任务、检查/一次修复、玩家确认、显式恢复 |
| investigation_generation.py | 文本行动理解、公开上下文、叙事及语义检查 |
| investigation_jobs.py | 调查任务生命周期、统一裁决、事务提交 |
| story_api.py | 新创建/公开世界接口；挂载到现有 app |

models.py 和增量迁移承载新增记录；jobs.py/main.py 只在必要位置按引擎分派，保留旧协议。provider_clients.py 保持唯一供应商 HTTP 边界，增加可分类的结果及失败元数据。四份既有未跟踪草稿不纳入。

## 3. 创建会话、任务及接口

创建身份先于模型调用。新增 POST /story-sessions，严格请求为 provider=deepseek、可选受控 model_id；返回一次 token、session_id、固定 provider/model_id 和 engine_version=investigation-1、mode=single。这里只建立空会话，不创建 Demo 根节点、不调用模型。旧 POST /sessions 的请求、默认值和返回不变。

下列接口均使用现有 Bearer 会话认证，并验证 task/session/story 归属；不存在及他人对象均返回 404。创建和恢复使用 1–80 字符 Idempotency-Key，同键同规范化输入复用结果，同键异输入为 409。空会话可以重新尝试失败的创建，但批准后不得换故事。

| 接口 | 请求和响应职责 |
|---|---|
| POST /story-tasks | setting：去首尾空白后 1–500 字；era：ancient/modern/future。202 返回 task_id、status |
| GET /story-tasks/{id} | 返回 task_id、status、stage、error_code、可恢复状态；只有 awaiting_confirmation/approved 返回已检查简介、候选版本和 hash |
| GET /story-tasks/{id}/events?after=N | 按持久化序号补发进度、简介待确认、批准或失败；不发送候选正文或内部校验详情 |
| POST /story-tasks/{id}/confirm | 严格请求 candidate_version_id、content_hash；核对当前候选与检查记录，原子批准并建立根节点。返回保存的根节点，重复相同确认复用，旧候选/hash 返回 409 |
| POST /story-tasks/{id}/resume | 仅 failed/interrupted 可恢复；202 返回新 task_id、恢复来源。awaiting_confirmation 只等待确认，approved 复用已有结果，不重复调用 |
| GET /session/world?node_id=... | 只读取本会话已保存节点，返回公开世界、当前可知证据/披露/承诺；不接受玩家伪造快照 |

GET /session 为调查会话增加 lifecycle、root_node_id 和当前创建任务 ID，旧会话维持旧响应。GET /world 继续仅提供旧 Demo 数据。未批准会话的 /turns 返回 story_not_ready，/tree 返回空列表；其他节点和任务接口维持授权检查。

创建任务状态：queued → running → awaiting_confirmation → approved；执行失败为 failed，进程重启或总截止时间耗尽为 interrupted。stage 是有限枚举 generate/validate/semantic_check/repair/awaiting_confirmation/approved，不携带隐藏内容。批准和根节点提交前完成内部 Trace 写入，事务失败不留下批准状态或半个根节点。

## 4. 生成、检查、一次修复与确认

服务器在任务创建时生成 story_id 并固定 provider/model/mode、请求 hash、prompt 版本和价格版本。模型生成 Story 协议的候选，故事身份由服务器约束，不接受其他 story_id 或未知协议。候选版本依次 draft-1/draft-2；模型不能自行选择已批准状态。

流程为故事生成 → 严格 Story 校验与实体引用 → 有界可达性检查 → 语义检查 → 无剧透公开材料检查 → awaiting_confirmation。使用阶段 1 的 50,000 状态上限；将 BFS 放入有界工作进程，墙钟超时后停止进程并拒绝候选，不能让同步搜索阻塞事件循环或继续后台写状态。

语义检查为独立注册操作，输入完整内部候选、规则检查结果及见证路径；严格输出 passed、issues。issues 最多 20 项，每项含枚举 code（evidence_support/contradiction/public_leak/ending_consequence）、entity_ids 和内部说明。引用须属于候选；passed=true 时 issues 必须为空。检查证据是否充分支撑固定真相、角色知识矛盾、结局后果是否不同，以及所有公开字段和规则反馈是否提前透露未获知内容。不能仅以模型自报 passed 代替结构和规则检查。

完整检查不通过时至多一次设定修复，输入原候选及内部诊断，修复后重跑全部检查。非法 JSON/schema 可使用受限原始候选作为修复输入；凭据、授权信息和隐藏思考不进入候选或诊断。供应商错误、预算、存储故障及截止时间不足不触发内容修复。修复计数持久化，恢复不能重置或通过新 attempt 越过一次上限。

各执行步骤将候选与检查结果作为内部检查点持久化，以便恢复只续未完成步骤；这些检查点不是批准的 StoryVersion。只有全部通过才保存不可变 draft 版本。保存 Story 的内容不再改写；玩家看到 title/setting/era/public_intro，以及主角和初始地点公开介绍，不看到 truth、规则、秘密、结局路径或内部诊断。

确认锁定会话和创建任务，核对版本/hash/检查通过及未绑定其他故事，然后使用现有 draft → approved 转移，绑定 session.story_version_id；创建初始快照、公开开场及服务器选项。根节点开场使用已检查简介和初始地点描述，不额外调用模型。冻结版本仍使用 draft-1/draft-2 的不可变身份，批准状态与内容版本分开；不为改版本号原地修改定义。

## 5. 调查回合协议和生成上下文

沿用 POST /turns 的外部 Action(type=option|text,value<=500)，调查会话分派到新任务服务。按钮 ID 必须属于选中父节点保存的服务器选项；每个节点内部保存 option_id → 规范化行动的映射，玩家仅看到不透明 option_id 和公开 label。按钮直接取服务器行动，不调用行动理解；自由输入通过注册操作理解为调查、交流、出示、移动或抉择。无法映射时返回 uninterpretable 的明确反馈，不凭空创造规则。

行动理解只得到公开世界、当前公开选项对应的可执行行动及同序公开标签（action_labels）和最近三个祖先回合，不得到真相、未知证据、规则条件或内部 Trace。标签使模型可以将公开地点名和交流序号对应到服务器行动，不依赖猜测内部 ID。严格输出为判别联合：recognized（一个阶段 1 Action）或 unrecognized；识别出的行动还须确定性校验实体、地点和条件。玩家文本按数据编码，不拼接为系统指令。

通过 apply_state_changes(parent_state,story=story,action=action) 得到完整裁决，包括事件闭包及后继快照。invalid/repeat/precondition_failed 或 uninterpretable 使用确定性反馈节点，不调用叙事模型，父状态完全不变。accepted 才调用叙事生成；模型出参只有 narration（1–1200 字）、dialogue（0–2 条，每条 character_id、1–280 字 text 和固定情绪枚举），禁止 state_changes、scene_id、选项或规则字段。

叙事输入为服务器裁决公开反馈、后继公开投影、当前在场角色公开资料、玩家行动和最近三个祖先已提交回合。秘密知识不交给叙事模型；新增证据、披露、承诺和事件由服务端公开反馈携带。只允许当前地点的非主角 NPC 发言；无人时对白为空。服务器生成地点、选项、进度和结局元数据。

叙事后执行结构与引用检查，再用注册的语义检查审查候选是否违背裁决、增造事实或泄露未知内容；该检查可以消费内部真相作否决，输出仅为内部检查结果，不能作为生成上下文或剧情内容。普通叙事校验失败默认任务失败，不修复或静默降级。所有调用共享行动 60 秒截止时间。

自然语言语义检查存在漏报风险，自动通过不能证明绝无事实冲突。验收必须包含秘密哨兵、诱导泄漏和错误事实负例，并对真实完整路径做人工核查；报告分别记录结构/规则、语义及人工结果。

服务器选项从当前候选行动经纯裁决筛选 accepted 得到，不执行数据库写入。标签使用已检查的公开对象名、角色名、已发现证据描述、出口地点名或已可抉择结局标题；交流话题用服务器序号标识，不输出 topic_id 或规则反馈作为未行动前的标签。不同节点使用各自保存映射，旧按钮不能移用于新父节点。

## 6. 提交、玩家投影和回放

任务加载父节点后保存身份、版本与快照；提交时锁定 run/session 并重新核对任务状态、截止时间和父节点归属。按同一规范化行动重新计算裁决，必须与先前结果一致。一个事务提交不可变 Node、TurnEvent、run 终态及批准后 SSE；任何失败无新节点或部分状态。

Node.scene_id 使用服务器 location_id，story_version_id 绑定该局版本，canon_version 保存故事版本；新 prompt_version 使用 investigation-single-1。TurnEvent 分别记录玩家输入、行动理解、确定性裁决、披露/承诺/主动事件和批准场景；内部快照保留阶段 1 完整协议。

调查节点的玩家 state_snapshot 只包含版本身份、当前地点、action_turn、已发现证据/披露/承诺 ID、trust 和 ending_id，不输出 applied_once_rules、fired_events、规则条件或隐藏定义。调查事件和世界接口使用各自字段白名单；内部 option 映射不进入 public_node。旧节点响应保持原协议。

GET /nodes、节点事件、/tree、run 查询/SSE 均核对会话归属。scene_chunk/options/done 只随已提交内容补发；进度可提前发送。回放只读取原文、快照与已批准映射，不调用生成器、语义检查或裁决器。

## 7. 执行器、费用和内部 Trace

ToolSpec 与 ToolResult 遵循运行可靠性设计，每项独立严格入参/出参。生成与修复使用第 11 节已确认的 story.generate.v2、story.repair.v2；action.interpret.v1、scene.render.v1、story.semantic_check.v1、scene.semantic_check.v1 保持短操作策略，旧 v1 Trace 不改写。语义操作因入参不同分开注册。未分类普通异常为 internal_error，取消继续传播。普通规则函数保持内部函数，不包装为模型工具。

完整故事生成/修复 v2 attempt 最多 120 秒；其余文字 attempt 最多 20 秒，均不得超过剩余任务时间。行动全部阶段 60 秒，创建执行区间 300 秒。候选输出解析、规则工作进程及语义检查均受区间墙钟上限约束；等待玩家确认不计入外部执行区间。允许安全重试总共最多三次、0.5/1 秒基准加 0–0.25 秒抖动，并遵守 Retry-After 和剩余时间。401/403、非法输出、未知结果的读超时/5xx 不自动重试。

适配器按操作传入输出预算，旧路径保留 900 token；新故事生成/修复设计预算为 12,000 token，行动理解为 300、叙事为 900、语义检查为 2,000。接入时须核对所选受控模型支持这些参数，并验证完整样本不被截断；不支持时先修订设计，不能静默降到旧 900 token。玩家不能传入预算或任意模型 ID。

调用前先持久化 attempt 开始并检查全局文字预算；每次返回或失败先在独立事务记账/Trace，再解析业务候选及提交故事。已有价格表作为历史版本保留，实际接入前核实文字价格并保存新价格版本，不把旧估算冒充最新报价。阶段 2 检查每次文字调用及修复/重试预算；阶段 3 才交付文字/图片共享原子预留。

已知 usage 按实际值保存，非法候选也收费。已发送但无 usage 的调用保留 nullable token、outcome_unknown 和保守费用估算；无法形成可信费用上界时阻止后续外部调用并提示核对费用，不按零收费处理。Trace/账本失败立即停止后续调用和节点提交，已发出请求标记审计不完整；恢复不得抹去不确定状态。

Trace 含 task/session/node、span/parent_span、attempt、版本、序号、脱敏输入输出、校验、耗时、usage/error 和终态，不保存凭据或隐藏思考。序号由任务记录锁分配，不用无锁 max+1。检查产物及候选只保存在本地内部记录；无玩家 Trace HTTP 接口，本地只读检查命令不重新调用工具。用户输入/模型输出也须做凭据脱敏，而非仅移除字段名。

旧会话仍保持 legacy-1 生成及 fallback 语义；共享 HTTP 适配器改动须回归旧协议，不能把新流水线默认失败方式反向应用于旧节点。

## 8. 持久化与增量迁移

新增 story_tasks：session_id、恢复来源任务、幂等键/请求 hash、请求、status/stage、候选版本关联、repair_count、检查结果关联、trace_id、截止时间、error_code 及时间戳；唯一 (session_id,idempotency_key)。story_task_events 保存公开进度，唯一 (task_id,seq)。新任务没有 parent_node，不复用现有 Run 的非空 parent_node_id。

新增 execution_traces 事件表遵循运行可靠性设计，并通过明确 action run 或 creation task 关联确认归属；task_type/task_id 之外添加受外键保护的关联约束，不能保存无人认领的任意 task_id。run/story_task 增加 trace_id/trace_seq，创建恢复保存父 trace 关联。Node 增加可空内部 investigation_options 字段，旧节点为 NULL。

llm_calls.run_id 改可空，增加 creation_task_id、trace/span/attempt 关联、调用及 usage 状态；约束恰好一种任务关联。token 字段为可空，保留旧历史值；attempt 唯一防止剧情提交重试重复记账。价格与费用状态版本化，失败调用不随故事回滚丢失。

按职责拆成可顺序执行的增量迁移，不能修改 0001–0004 已执行历史。旧会话新增字段为空，不回填为调查引擎，不改写旧故事、节点和渲染。新任务/Trace/账本或调查关联存在时，破坏性降级在删除字段前拒绝。仅在独立 *_test PostgreSQL 库验证升级、降级保护和 alembic check。

## 9. 幂等、恢复与重启

创建/恢复/确认锁会话和任务；Run 继续使用现有 (session_id,key) 唯一约束和真实并发提交检查。任务启动用 queued → running 的条件更新或行锁，不允许两个 worker 都获得同一任务。run/story_task SSE 序号同样在对应任务锁内分配。

重启只标记未完成执行中任务 interrupted，不自动调模型；awaiting_confirmation 和 approved 保持原状。显式创建恢复以新幂等键建立新执行区间，保留 story_id、候选、检查结果及 repair_count，只续未完成步骤，不重复生成已检查通过的设定。单次修复失败后只能新建故事任务重新创作，不能恢复并追加第二次修复。

行动恢复仍从原父节点以新幂等键提交，旧失败 run/attempt 不改写。结果未知的请求先完成费用状态处理才允许新调用。已完成任务、同键重放、确认重放和旧节点读取均不产生新增供应商调用。

## 10. 验收与后续实施计划

实施计划在本设计审阅后编写，按执行基础设施、创建任务、调查回合、评测验收分为可独立验证的任务。阶段整体仅在全部门槛通过后标记完成。

- 规则/旧存档：复跑固定 rules 与 legacy，完整后端测试及迁移保护通过；冻结样本/hash 不变。
- 模拟执行：未知操作/非法参数、永久错误不重试、安全 429 成功/耗尽、Retry-After、结果未知、单次/总超时、取消、格式及语义错误、一次修复上限、预算/Trace/账本失败。
- 创建/授权：双会话隔离、真并发同键/异输入、旧候选确认拒绝、重复确认一个根节点、创建失败无根、重启/SSE 补发、显式恢复保持候选及修复计数。
- 调查：五类行动、同地点多轮、重复/非法不变状态、事件/披露/承诺记录、兄弟分支隔离、错误角色、候选正文不提前发送、提交回滚后 usage/Trace 留存、回放零调用。
- 泄漏：创建简介和全部玩家接口不输出隐藏字段/秘密哨兵，恶意自由输入及叙事新增秘密被阻止；内部日志不得出现模拟 API Key、会话 token 或数据库连接凭据。
- 真实路径：古代、近现代、未来分别实际生成并确认，在各故事保存的三结局见证路径上从根节点分支走完；至少一条包含自由文本的完整路径。仅用规范化规则行动或脚本映射按钮不算自由文本理解通过。记录模型/prompt/价格/故事版本、各调用及任务耗时、usage/费用和人工语义核查人数。
- 评测入口使用 evals/run_stage2.py 和固定清单，明确 runtime_simulated/real_model 的分母、输入及预期。模型生成后的故事及见证路径在游玩评测开始前冻结；生成失败也计入该背景创建任务分母，不能只挑成功故事。无密钥、未实现、跳过和失败均不能算成功；不把确定性规则通过率当 AI 任务成功率。
- 开发日志记录实际结果、失败明细及相关提交；未完成真实路径则保留阶段 2 未验收状态。前端本阶段不改，不据后端验收宣称配图、最终体验或新入口可用。

## 11. 首次真实评测后的补充方案（已确认）

状态：用户已回复“按补充方案继续”，实施中，尚未验收；第 7 节同步新策略。首次真实生成 20,016 ms 超时；用户核对控制台后报告该请求消费 0.02 CNY、输入 5,088、输出 4,510、总 token 9,598。目标是保留失败审计、正确计入消费并解除已核账请求的阻断，再用原固定清单评测。

1. 通过仅本地操作者可用的核账入口，在现有独立 Trace 事务中追加 versioned usage_reconciled 事件，严格输入为调用 ID、明确来源 user_reported_provider_console、总 token 和实际 CNY 金额；可同时提供非负输入/输出 token，二者必须成对且合计等于总量。不改原 LLMCall 的 outcome_unknown、NULL token/估算、价格版本或原 attempt 结果；不补写剧情。按所属任务锁保证同一调用核账幂等，相同值重复无新增费用，冲突拒绝。只允许核对已经收尾且 uncertain 的调用；无关/已知调用、非法金额或缺来源拒绝。原始失败 report.json 不改写。
2. 预算读取包含核账金额；只有该调用存在有效核账事件时解除其 cost_unconfirmed，其他未知调用和审计缺失继续阻断。核账来源是用户陈述，不冒充供应商 API 验证；报表分开显示已知输入/输出、已核账总 token/实际金额和仍未知的调用。80/100 CNY 门槛不变。不新增玩家 HTTP 接口，不启用原子预留或图片。
3. story.generate/story.repair 新执行策略版本 v2 单次最多 120 秒，HTTP 和墙钟上限均使用同一操作策略且不得超过任务剩余时间；创建执行区间仍为 300 秒。生成/修复输出预算仍为 12,000，prompt 不改。行动理解、叙事和语义检查保留 v1、单次 20 秒，行动总限时仍为 60 秒。未知结果不自动重试，单次内容修复上限保持一次。更长限时可能降低过早取消，但不保证可玩质量或供应商完成时间。

先用失败测试覆盖核账前阻断、后续预算计费、并发/重复不重计、冲突/非法输入拒绝、其他未知调用继续阻断、原账本与节点不变；执行策略测试覆盖生成与短操作区分、适配器限时一致及剩余截止时间截断。通过相关和完整后端测试后，在同一 stage2_real_test 上核对原调用，显式运行新一轮固定 12 项评测；保留首轮 0/12，不换库规避未知费用。同步运行可靠性设计及实测日志，再记录新轮真实结果。
