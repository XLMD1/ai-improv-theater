# 阶段 1 规则与兼容评测结果

日期：2026-10-10；指标版本：task-success-1。
口径：[基础评测规范](task-success-baseline.md)。
故事样本：draft-1，尚未获用户语义审定。

## 已执行结果

| 套件 | 成功/固定总数 | 失败 | 错误 | 跳过 | 成功率 | 总耗时 |
|---|---|---|---|---|---|---|
| rules | 29/29 | 0 | 0 | 0 | 100% | 16.781 秒 |
| legacy | 9/9 | 0 | 0 | 0 | 100% | 10.844 秒 |

耗时包含 pytest 子进程启动及断言，两个套件并行运行；不是玩家回合或模型时延。纯规则与旧存档兼容分开报告，不把上述数字称为真实 AI 任务成功率。

## 可追溯输入与环境

- 源码提交：48c70e3bff33aa3b3dc3217047980c6e22a008fb；两次运行 git_dirty=false。
- Python 3.12、PostgreSQL 18；pytest 9.1.1、Pydantic 2.14.0、SQLAlchemy 2.1.4、Alembic 1.20.0、psycopg 3.3.6、FastAPI 0.143.0。
- 调查引擎 investigation-1，故事 draft-1；兼容引擎 legacy-1，原 Demo 1.0.0。
- 无模型与 prompt；未调用供应商，实际外部模型 token 与费用均为 0。
- manifest 原文件 SHA-256：3a413484cf6f4ed491702ca4cf392b725d2c75df6193961512fadacebea3b7fb。
- fixture LF 规范化 SHA-256：404b60fc9639adb23f327b12131bdd3611cd09531f3dc022e5236f351045dad5。
- fixture 本次原字节 SHA-256：aea817271f5f6f71d1d1f014d26ed1cff095f8e9bcd4bd96f5fce2a05ad01610。
- 规范化故事定义 SHA-256（版本存储使用）：8f54507a5b96f70c7b4c8629c962d4d24607ac782fc192b45c991e91ded1f599。

## 原始结果定位

- rules run ID：ebccbd5135c44a609cd5b3927ef257a5；本地 runtime/evals/ebccbd5135c44a609cd5b3927ef257a5/report.json。
- legacy run ID：39e5960cc3384cfb9845ece7e209cc6f；本地 runtime/evals/39e5960cc3384cfb9845ece7e209cc6f/report.json。

原始 JSON 和逐案安全计数保留在 Git 忽略目录，不保存原始 pytest 异常、node ID、stdout 或 stderr。报告引用实际运行结果，没有重写失败记录。

## 覆盖与边界

完整状态搜索 70 个唯一状态，覆盖五地点、十二证据、三结局，各结局有 21 次有效行动见证。负例涵盖严格类型、额外字段、未知版本/实体、非法效果、信任越界、重复/错误地点、父及兄弟分支隔离、事件闭包、线索互锁、结局不可达、搜索超限和公开信息过滤。

兼容套件验证旧 Demo 三结局、幂等与授权、已保存节点不调用生成器，以及从 0003 增量升级后旧节点/事件/渲染原文一致、旧关联仍为 NULL。版本定义与身份/hash不能更新或删除；存在调查记录时降级拒绝。

额外故障验证：缺测试库运行按固定 9 项全部 error、成功率 0 并非零退出；评测子进程超时按 error 计入分母；继承的 pytest 筛选不能漏跑 13 个状态子检查；失败诊断及 stdout 中的模拟令牌不进入保存产物。Windows 换行只影响原字节 hash，不影响 LF 规范化 fixture 身份。

人工剧情评审人数为 0；一次独立 Agent 代码审查发现的评测筛选及敏感产物问题已用失败复现和回归修复。外部工具注册、供应商重试/超时、完整 Trace 和真实模型评测属于阶段 2，未在本报告验收。

后续记录：本文保留用户批准前的实际状态与测量值。用户随后批准并冻结 1.0.0，见[批准后的验收记录](2026-10-10-stage-1-approved-results.md)。
