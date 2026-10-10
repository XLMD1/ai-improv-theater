# 阶段 1 批准版本评测结果

日期：2026-10-10；指标版本：task-success-1；清单版本：stage1-2。
口径：[基础评测规范](task-success-baseline.md)。
用户已批准完整雾港样本，故事 1.0.0，人工剧情评审人数 1。
[原 draft-1 报告](2026-10-10-stage-1-results.md)保留原提交与测量值。

## 实际结果

| 套件 | 成功/固定总数 | 失败 | 错误 | 跳过 | 成功率 | 总耗时 |
|---|---|---|---|---|---|---|
| rules | 30/30 | 0 | 0 | 0 | 100% | 18.187 秒 |
| legacy | 9/9 | 0 | 0 | 0 | 100% | 11.516 秒 |

两个套件并行运行，耗时包含 pytest 子进程启动及断言，属于确定性规则及旧存档兼容验证。新增一项批准稿冻结校验：批准身份/hash 一致，且将版本号还原为 draft-1 后定义 hash 与审定原稿一致。原有失败、错误、跳过及超时仍计入固定分母。这些结果不代表真实模型任务成功率或玩家回合时延。

完整后端 pytest：88 passed，6 条既有上游兼容警告，9.32 秒；alembic check：No new upgrade operations detected。均使用本轮独立 PostgreSQL 18 测试集群，不连接用户故事库。

## 版本与可追溯结果

- 实测源码提交：848195effe66fb4df988a1c332e97268fdba2340；两个套件 git_dirty=false。
- 调查故事 1.0.0 / investigation-1；旧 Demo 1.0.0 / legacy-1。
- manifest 原字节 SHA-256：720fd38e835c6583d979aa730f844012e3570d12aefb4678b47ed2baf50e7700。
- 样本 LF 规范化文件 SHA-256：8935c8fc113fcd6b03be1e49bb41a4c7b67917ec38fb44ab9d50dc33cbf940ff。
- 样本本次原字节 SHA-256：8935c8fc113fcd6b03be1e49bb41a4c7b67917ec38fb44ab9d50dc33cbf940ff。
- 规范化故事定义 SHA-256：dbdb37eb57b2eaf90eddfb42246189920147fa94adfeef85cf43598bcbd3ce79。
- 审定原稿 draft-1 规范化定义 SHA-256：8f54507a5b96f70c7b4c8629c962d4d24607ac782fc192b45c991e91ded1f599。
- rules run ID：39116dacbf8b40cd8c04c7af698cfac6；本地 runtime/evals/39116dacbf8b40cd8c04c7af698cfac6/report.json。
- legacy run ID：c6e9563c8a06426a99d2c4e6033b3373；本地 runtime/evals/c6e9563c8a06426a99d2c4e6033b3373/report.json。

审批来源及原话保存在[固定批准记录](../../backend/tests/fixtures/mist_harbor_approval.json)，该记录及固定见证路径也纳入清单的文件 hash 校验。JSON 原始结果保留于 Git 忽略 runtime，保存安全计数和稳定错误代码，不保存原始诊断或敏感输出。

## 覆盖与边界

搜索仍为 70 个唯一状态、5 个地点、12 项证据、3 个结局，各结局 21 次有效行动，证明此次冻结仅改变版本身份。新旧版本隔离、不可变定义、分支隔离、无效/重复行动、信息过滤、事件闭包、死锁、不可达、搜索超限与迁移/旧回放验证通过。

供应商调用 0；无模型或 prompt，外部模型 token 与费用 0。人工剧情评审 1 人；此前独立 Agent 代码审查 1 次，本次未重复全量审查。前端未改，未运行前端测试或真实试玩；不报告游玩分钟。阶段 2 的工具注册、外部调用重试与超时、完整 Trace 和真实模型评测尚未验收。
