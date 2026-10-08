# AI 即兴剧场：技术设计

版本：v0.3（本地 DeepSeek 优先开发基线）
对应需求：[01-requirements.md](01-requirements.md)

## 1. 架构与边界

```text
浏览器 Next.js 本地页面
  ├─ POST /sessions、/turns；GET /nodes、/tree、/runs
  └─ GET /runs/{id}/events（带认证头的 fetch SSE）
          ↓
FastAPI 单进程任务调度（仅监听 127.0.0.1）
  ├─ 确定性 Demo / 单次真实生成；多 Agent 仅作为后续实验模式
  ├─ JSON/Pydantic + 确定性状态校验
  ├─ 进程内 API Key（不持久化、不回传明文）
  └─ 本地 PostgreSQL：节点、事件、任务、调用用量
          ↓
DeepSeek JSON Output（deepseek-flash）；OpenAI Responses API 待开发验证
```

上图是目标架构。阶段 1 只运行确定性 Demo，不调用模型。保留当前浏览器直连 FastAPI 的 SSE 通路；不部署 Fly、Neon、Vercel，不接 pgvector 或 Redis。设置页只借鉴供应商、密钥和模型控件，不实现账号或截图中的 AES 持久化声明。密钥仅通过本地设置接口送入后端内存；后端重启后状态变为未配置。前端不把密钥写入浏览器存储，后端不把密钥写入数据库、日志或响应。只允许本地前端 origin，并明确以 127.0.0.1 启动 API。

## 2. 世界与生成协议

`canon.json` 固定场景、合法转移、角色卡和允许的 flag。节点快照固定为 `schema_version`、`scene_id`、`turn`、`flags`、`relations`、`ending_id`；关系值范围 -3..3，flag 仅可由允许列表设置为 0/1。

阶段 2 的单次生成输出只含 `narration`、1–2 位出场角色的 `dialogue` 和最多 4 个 `state_changes`；`scene_id` 与选项 ID 由现有确定性状态机决定，模型不得改变合法转移。输出用禁止额外字段的 Pydantic 类型验证，随后调用唯一的 `apply_state_changes()`。当前只开放 DeepSeek JSON Output；OpenAI 结构化输出和密钥入口须另行实测后开放。阶段 3 若进入多 Agent 实验，再加入导演、编剧、角色、审核协议，并让全部调用跟随会话选择的供应商和模型。

阶段 2 处理顺序：确定性选出下一场景和固定选项 → 模型生成候选 → 解析与结构校验 → 状态键、出场角色及机器可判定的场景/状态约束校验 → 单事务提交。候选格式或状态提案不合法时使用目标场景预写的 `fallback=true` 过渡幕，状态变更为空；密钥、网络或额度错误则令 run 失败且不创建节点。阶段 2 不自动理解叙述与对白的语义，不能保证它们不违背角色禁忌或结局事实；这部分留给后续人工评测及条件性的审核流程，不能写成已解决的一致性能力。阶段 3 的审核修复最多一次；服务端事实优先级始终是：规则与固定设定 → 父节点快照 → 祖先已提交事件 → 审核意见 → 提示材料。

`SingleGenerator` 是阶段 2 默认生成器；后续 `MultiAgentGenerator` 必须共享校验、提交和输出格式。调用输入上限目标 4,000 token、输出上限 900 token；先裁剪较早的最近回合和非出场角色细节，绝不裁剪当前状态或用户行动。实际 usage 记录成本；本地字符数守卫不能当作精确 token 统计。预估累计费用达到 80 元发出警告，达到 100 元阻止新模型调用；换算和供应商标价须版本化，阈值是估算保护而非账单保证。

## 3. 数据、分支与记忆

- `sessions`：匿名会话、令牌哈希、固定的 `provider` 与 `model_id`；旧记录迁移后为 `demo`。
- `nodes`：父节点、深度、完整状态快照、批准后的渲染内容、设定/prompt/模型版本。
- `turn_events`：玩家输入、导演决定、批准剧情、实际状态变更；只记录已提交节点。
- `runs` 与 `run_events`：生成状态、幂等键、可补发的 SSE 事件序号。
- `llm_calls`：每次模型调用的供应商、模型、输入/输出 token 与估算费用。

阶段 1 的初始迁移只创建 `sessions`、`nodes`、`turn_events`、`runs`、`run_events` 五张表。阶段 2 增加会话供应商字段与调用用量表。节点与事件不可变，回放直接读取 `rendered_scene`，不重新生成。阶段 3 的提示词版本为 `single-2`：仅使用最近 3 个祖先节点的已提交玩家行动与剧情作为上下文，按时间正序排列；旧行动最多 120 字、每幕叙述最多 240 字、每句旧对白最多 100 字，当前行动不裁剪。兄弟分支信息不得进入提示材料。不建向量表、不做每日摘要。

## 4. API、SSE 与恢复

| 接口 | 核心行为 |
|---|---|
| `POST /sessions` | 创建匿名会话及初始节点，令牌仅返回一次 |
| `GET /local-settings` | 返回供应商、固定模型列表和密钥配置布尔值，不返回密钥 |
| `PUT/DELETE /local-settings/keys/{provider}` | 设置、替换或清除进程内密钥；当前仅开放 deepseek，openai 返回待验证错误 |
| `POST /turns` | 提交父节点、选项或自由行动，`Idempotency-Key` 唯一；返回 run ID |
| `GET /runs/{id}` | 查询任务状态与已提交节点 |
| `GET /runs/{id}/events?after=N` | 只补发序号大于 N 的阶段/批准内容事件 |
| `GET /nodes/{id}` | 回放完整已批准节点 |
| `GET /tree` | 返回当前会话分支树，包含用于区分兄弟分支的 `action_label` |

`POST /sessions` 请求体可选 `{provider, model_id}`，缺省为 `demo`。供应商与模型在会话创建时固定；设置弹窗的改变只影响下一段新故事。SSE 阶段事件可实时发送；`scene_chunk`、`options`、`done` 仅在校验与事务提交后发送。连接断开只影响读取，后端任务继续；客户端刷新后用保存在 `sessionStorage` 的 run ID 和最后序号继续读取。新幂等键从同一父节点重新生成，形成明确的新分支。服务重启将未提交任务标记 `interrupted`，不自动重调第三方模型。第三方请求已经发出时无法保证绝对只计费一次。

## 5. 本地验证门槛

完成每阶段后验证：结构/状态规则、三个结局、分支隔离、原样回放、幂等与断线恢复。当前真实模型验收先用 DeepSeek 有效密钥走完一局；OpenAI 显示“待开发验证”，接口拒绝配置密钥与新建 OpenAI 故事，不能写成双模型可用。自动评测记录合法率、硬冲突、p95 时间、实际 token 与估算费用；人工评分只按实际获得的评审人手报告，不宣称无法兑现的双人盲评。多 Agent 未达到可用门槛时不作为默认模式，也不以完成态写进简历。
