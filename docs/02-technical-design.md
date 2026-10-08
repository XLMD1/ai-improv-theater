# AI 即兴剧场：技术设计

版本：v0.1（开发基线）
对应需求：[01-requirements.md](01-requirements.md)

## 1. 架构与边界

```text
浏览器 Next.js 静态页面
  ├─ POST /sessions、/turns；GET /nodes、/tree、/runs
  └─ GET /runs/{id}/events（带认证头的 fetch SSE）
          ↓
FastAPI 单进程任务调度
  ├─ 导演 → 编剧 → 出场角色并行 → 审核
  ├─ JSON/Pydantic + 确定性状态校验
  └─ PostgreSQL：节点、事件、任务、记忆、调用用量
          ↓
Qwen 兼容接口：聊天模型 + text-embedding-v4
```

上图是目标架构。阶段 1 只运行确定性 Demo，不调用模型、不写向量记忆；前端使用 Next.js 静态导出，浏览器直连 FastAPI。Fly、Neon、模型与 pgvector 留待后续阶段。Redis 首版不用，UI 必须标明 Demo 性质。

## 2. 世界与生成协议

`canon.json` 固定场景、合法转移、角色卡和允许的 flag。节点快照固定为 `schema_version`、`scene_id`、`turn`、`flags`、`relations`、`ending_id`；关系值范围 -3..3，flag 仅可由允许列表设置为 0/1。

阶段 1 的 `backend/app/schemas.py` 只包含玩家行动、状态变更与任务状态。阶段 3 再加入 Agent 协议：所有 Agent 接收只读包 `canon_version`、`parent_node_id`、`world_state`、`recent_turns`、`retrieved_memories`、`user_action`；导演输出场景、目标、冲突及 1–2 位角色；编剧输出叙述、1–4 个对白槽、2–3 个选项、最多 4 个状态变更和 2 条记忆候选；每个出场角色只填自己的槽；审核输出 `pass|repair|block` 与问题列表。届时以严格 Pydantic 类型为执行契约。

处理顺序：解析结构 → 检查场景转移、选项/槽位/状态键 → 组装正文 → 检查硬禁忌 → 审核。审核修复最多一次；二次失败或 `block` 时改用场景预写过渡幕，不改状态、不写记忆。服务端事实优先级是：规则与固定设定 → 父节点快照 → 祖先已提交事件 → 审核意见 → 检索记忆。未知 `fact_key` 的事实冲突指控不生效。

`SingleGenerator` 一次调用生成完整候选幕，仅用于基线与可能的低成本默认模式；`MultiAgentGenerator` 按上述角色协作。两者共享校验、提交和输出格式。调用输入上限目标 4,000 token、输出上限 900 token；上下文超额时依次删低相似度记忆、较早回合、非出场角色细节、非关键说明，不能裁剪当前状态与用户行动。接入真实模型时必须用供应商实际 usage 记录成本；本地字符数守卫只作预防，不能当作精确 token 统计。

## 3. 数据、分支与记忆

- `sessions`：匿名会话与令牌哈希。
- `nodes`：父节点、深度、完整状态快照、批准后的渲染内容、设定/prompt/模型版本。
- `turn_events`：玩家输入、导演决定、批准剧情、实际状态变更；只记录已提交节点。
- `runs` 与 `run_events`：生成状态、幂等键、可补发的 SSE 事件序号。
- `memories`：来源节点、`fact_key`、类型、文本、重要度、创建回合、过期回合、1024 维向量与模型版本。
- `llm_calls`：每次模型调用的角色、模型、输入/输出 token 与估算费用。

阶段 1 的初始迁移只创建 `sessions`、`nodes`、`turn_events`、`runs`、`run_events` 五张表；记忆与调用用量表在对应功能阶段迁移。节点与事件不可变，回放直接读取 `rendered_scene`，不重新生成。阶段 1 创建子节点时，在单一事务中写入节点、事件并结束 run。阶段 3 再把已批准记忆纳入同一事务：只看父节点祖先链，剔除过期项，同 `fact_key` 取最近祖先版本，再按余弦相似度 ≥0.72 取前 3 条。该阈值需用评测数据校准。每日摘要不做；最近 3 回合直接进上下文。

## 4. API、SSE 与恢复

| 接口 | 核心行为 |
|---|---|
| `POST /sessions` | 创建匿名会话及初始节点，令牌仅返回一次 |
| `POST /turns` | 提交父节点、选项或自由行动，`Idempotency-Key` 唯一；返回 run ID |
| `GET /runs/{id}` | 查询任务状态与已提交节点 |
| `GET /runs/{id}/events?after=N` | 只补发序号大于 N 的阶段/批准内容事件 |
| `GET /nodes/{id}` | 回放完整已批准节点 |
| `GET /tree` | 返回当前会话分支树，包含用于区分兄弟分支的 `action_label` |

SSE 阶段事件可实时发送；`scene_chunk`、`options`、`done` 仅在审核与事务提交后发送。连接断开只影响读取，后端任务继续；客户端刷新后用保存在 `sessionStorage` 的 run ID 和最后序号继续读取。新幂等键从同一父节点重新生成，形成明确的新分支。服务重启将未提交任务标记 `interrupted`，不自动重调第三方模型。第三方请求已经发出时无法保证绝对只计费一次。

## 5. 部署与验证门槛

Vercel 仅托管静态前端；浏览器直连 Fly API。CORS 只列实际前端域名与本地开发域名；匿名令牌通过 `Authorization` 发送，避免依赖跨站 Cookie。Fly 保留一台运行机器、一个 Uvicorn worker；运行连接使用 Neon pooled URL，Alembic 用 direct URL；数据库连接池 3+2。生产密钥放 Fly secrets，前端只暴露 API 公共地址。

完成每阶段后验证：结构/状态规则、分支隔离、原样回放、幂等与断线恢复；上线前从生产域名走完五幕并断开一次 SSE。定量结论只能来自 40 个固定输入 × 3 次的配对盲评：主指标为硬校验通过且两名评审均未发现设定冲突的比例；同时记录角色一致率、可玩性、p95 时间与费用。若多 Agent 提升不足 10 个百分点或成本/延迟超过既定界限，在线 Demo 默认使用单次方案。
