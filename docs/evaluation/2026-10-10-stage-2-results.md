# 阶段 2 实测与验收状态

日期：2026-10-10。阶段 2 后端实现已完成自动验证，整体**尚未验收**；真实三类背景路径和人工剧情核查仍未通过。

## 范围与隔离

分支 codex/stage2-custom-stories，从 efd835c 开始。已接入空调查会话、创建任务/检查点、一次设定修复、显式恢复、原子确认、调查回合、公开过滤、严格操作注册与受控执行、独立失败用量/Trace、固定评测及本地只读复盘。0001–0004 未改，0005 增量迁移保留旧记录。

独立 PostgreSQL 18 集群为本工作树 runtime/stage2-test，127.0.0.1:55438。最终库 stage2_acceptance_test；未读取/复制用户 .env，未连接用户故事库。此前测试库保留失败审计，未清空以掩盖记账故障。前端、图片、便携包、OpenAI 和多 Agent 未实现或验证。

## 已运行检查

| 检查 | 实际结果 |
|---|---|
| 完整后端 pytest | 154 passed、7 warnings，29.73 秒（审查修复后）；审查前 151 passed |
| Alembic upgrade head | 0001→0005 成功，专用测试库 |
| Alembic check | No new upgrade operations detected |
| 规则基线 | 30/30，17.110 秒，报告 1da0356c47874180bc525a50a793a952 |
| 旧存档兼容 | 9/9，10.906 秒，报告 b2105f3984cd472eadb254e1e88ac63f |
| runtime_simulated | 10/10，32.047 秒，报告 7b38b53be0214b8b9dfe7b9c2915800a（审查修复后） |
| real_model（首次无密钥） | 0/12，12 error：key_not_configured，报告 18a8989e3adc425eb570d9eb8ce1cf8c；未发出真实请求 |
| real_model（本地输入密钥后） | 0/12，12 error，20.828 秒，报告 4ac6f08bfd764d9c8807e3380ed1ab06；1 个真实 attempt 超时且费用未知，后续调用被阻断 |
| 人工剧情核查 | 0 人，门槛未通过 |
| 前端测试/typecheck/build | 本阶段未修改前端，未运行 |

必需案例的 skip/error/timeout 均保留分母，返回非零。模拟故障不是 AI 任务成功率；模拟账本统计只覆盖保留行，主动清理的故障 fixture 不计入，不称供应商实际费用。首次无密钥运行没有真实 attempt。最新运行有 1 个真实 attempt，其 token 与费用均未知；报告汇总的 0 只是已知数值之和，不能解释为实际零费用。没有成功候选，不能推断截断率、语义质量或恢复成功率。

自动检查覆盖 strict schema、未知操作、有限安全重试、Retry-After、未知结果、单次墙钟超时、截止时间、取消、账本故障阻断、并发序号、越权、一次修复、确认幂等、创建恢复、五类行动、三结局规则路径、同地点重复不改状态、错误发言角色、语义否决、事务回滚、旧 worker、兄弟祖先隔离与保存回放。自然语言检查仍有漏报风险，不能用模拟 passed 代替真实人工核查。

## 官方参数与价格核对

2026-10-10 检查 [DeepSeek 官方模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)和 [Chat Completions 协议](https://api-docs.deepseek.com/api/create-chat-completion/)：deepseek-flash 当前服务 DeepSeek-V4.1-Flash；支持 thinking.type=disabled 和 JSON 输出，max_tokens 上限 393216，因此设计的 12000/2000/900/300 均在协议范围内。实际输出能否在 20 秒内完整生成尚待真实调用验证。

按峰时未缓存输入 USD 0.30/百万 token、输出 USD 1.20/百万 token 做保守估算；非峰官方费率减半。CNY 使用既有保守换算系数 7.5，此系数不是当日实际汇率，也不是供应商精确账单。新执行账本标识 2026-10-10-flash-peak-usd-cny7.5；旧 2026-10-08 价格版本和历史记录不改写。

## 可复跑入口

从仓库根目录使用项目 Python，显式将 MIGRATION_DATABASE_URL 与 DATABASE_URL 配置为同一专用 PostgreSQL *_test 库并先执行 backend 的 alembic upgrade head。入口拒绝缺少或非测试数据库，不读取用户故事库来补齐配置。

```powershell
python evals/run_stage2.py --suite runtime_simulated --database-url-env MIGRATION_DATABASE_URL
python evals/run_stage2.py --suite real_model --database-url-env MIGRATION_DATABASE_URL --prompt-key
```

--prompt-key 只在本地隐藏输入后写入后端内存，退出即清除；勿把密钥放在命令参数、聊天、数据库或浏览器存储。真实清单预先固定 3 项创建和 9 条结局路径；生成故事与 witness 在行动前冻结于 runtime/evals 并记录 hash，每局一条完整分支使用自由文本，其余用公开按钮。创建失败也保留背景和后续路径分母，不能挑成功故事替换。

本地只读复盘：python scripts/inspect-execution-trace.py --session-id <本地会话ID> --trace-id <本地TraceID>。输出可能含内部剧情事实，仅作本地调试；不会重新调用模型/工具或写剧情。没有玩家 Trace HTTP 接口。

## 剩余门槛

先核对最新未知请求的供应商用量/费用，再完成三类背景生成、九条结局路径和恢复验证，记录各操作真实 attempt、token、费用、时延及至少一位人工剧情核查结果。全部门槛通过前，开发计划中阶段 2 保持未验收，新故事前端入口仍不开放。

## 首次真实请求失败记录

用户确认密钥准备完成后，在本地独立交互终端用 getpass 隐藏输入，仅进入评测进程内存；退出时清除。新建独立 stage2_real_test，迁移 0001→0005 成功，未读取用户 .env 或连接用户故事库。固定清单 hash 为 ac927d293c87f5407692d7aa11aa22307191a936175c1b8c017335f5315fef5a，执行代码为 71c5f0e9ed7403c6781d551781b07053f8643cae，没有更换案例或挑选成功故事。

北京时间 18:57:33–18:57:53，story.generate 的第一次 attempt 用时 20,016 ms，触发当前设计的 20 秒墙钟上限。任务返回 outcome_unknown，账本 call_status=outcome_unknown、usage_status=uncertain，input_tokens/output_tokens/estimated_cost_cny 都是 NULL。没有拿到完整响应，无法确定供应商是否完成推理或计费，也不能据此断言密钥认证成功或失败。

古代创建为 outcome_unknown；近现代与未来创建均为 cost_unconfirmed，没有新增供应商 attempt；九条路径均为 creation_dependency_failed。共 12 error，人工核查 0，无候选故事可供阅读。一次请求结束后没有重试，也未换库绕过未确认费用阻断。

确定的失败边界是本地单次调用限时；供应商排队、生成速度或网络延迟的具体原因尚未区分。[DeepSeek 官方保活说明](https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit/)说明非流式请求可能先持续返回空行等待推理，不能据 20 秒超时判断服务端已经停止。下一步先核对供应商账单；如调整生成限时，需先同步设计及操作策略并验证，不能悄悄放宽所有操作或盲目重发。

一次独立审查发现两项 Important（原始 JSON/裸 token 脱敏、领取后初始化故障不收尾），均以数据库断言 RED→GREEN 修复；完整 154 项通过，不再进行重复全量审查。Minor 待补：approved 的 /resume 使用新键仍返回 409，已保存根节点可经 GET task 与确认重放取得。

实施判断：为理解器添加与合法行动同序的公开标签；若标签配对错误会影响自由文本匹配，因此加入 runner 的完整文本路径模拟断言。真实效果没有证据时保留未验收，误作通过会高估能力；后续阶段功能不扩入本轮，误判范围会延后相关交付。

四份原目录草稿 SHA256 与基线一致；本轮未修改/提交其内容。7 份相关文档本地链接检查无断链；git diff --check 通过。最终故障清单 10/10，模拟保留账本 326 attempts、input 30585/output 30569 token、估算 0.343937 CNY，仅为模拟数据。独立测试 PostgreSQL PID 22392 已停止，pg_ctl 确认 no server running；保留忽略目录中的测试库和报告以供复盘。实现保留在本地工作树分支，未合并或推送。
