# 阶段 2 受控故事验证结果

记录日：2026-10-11。设计与计划已确认，阶段整体尚未验收。真实/人工结果不得以模拟替代；[旧真实失败与费用记录](2026-10-11-stage-2-supplement-results.md)保留。

## 自动检查

- 骨架与严格内容：15 passed，穷举 70 状态，三个最短见证各 21 行动。生产 JSON SHA256=516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e。
- 纯组装/槽位 schema：48 passed，缺失/额外键、错误身份、伪装规则、模板原样及跨故事 ID 受控。
- 创建/旧协议/故障：35 passed、20.82 秒；取消与存储失败不提交节点，原调用费用保留，恢复不重置版本/修复次数。
- 来源报告集成：RED 2 failed/21 passed，GREEN 23 passed、13.47 秒。
- 最新完整后端：审查修复后 241 passed、7 warnings、45.76 秒；此前 240 passed、7 warnings、44.19 秒及 Alembic check 无新增操作。模拟库 stage2_controlled_test；前端未改，未运行前端检查。

## 真实与人工状态

受控协议 prompt investigation-single-6 真实固定清单已完成，未通过，manual_reviewers=0。run 64cc16647c7446ca9a05b977c3a11234，commit aa11c2a：创建 3/3 成功，九结局路径 0/9，总计 succeeded=3/error=9/total=12，task_success_rate=0.25，281.203 秒，退出码 1。所有路径 error_code=scene_semantic_rejected，不将安全拒绝当作任务完成。

90 次 provider attempts/90 条用量记录，input=570577/output=26516，估算 1.522443 CNY，uncertain/unconfirmed=0；没有本轮实际账单，不称实际消费。累计原真实库 stage2_real_test 账本口径从 1.248071 增至 2.770514 CNY，保留历史用户核账 0.02 与其他估算。

运行后原 4 节点/2 故事版本完整行 hash 全部不变；总库 34 节点/5 故事版本，新增为三个根及成功中间回合，九失败 run 的 node_id 均为空。原始 report.json SHA256=622273d972200ad1d84936ea4f63e3bff5466e078de18cdcf05d20a39888c029。冻结故事、全部失败 Trace 及 local-diagnostics.json 在 runtime/evals/64cc16647c7446ca9a05b977c3a11234/，Git 忽略，不包含密钥或会话凭据；未改原报告。

已完成路径为 0，不能准备并宣称完整路径人工验收。诊断显示实际新增事实、与真相冲突，同时有疑似误判，详见[回合呈现补充设计](../design/stage-2-controlled-scenes-proposal.md)。用户随后已批准 R1，[新实施计划](../superpowers/plans/2026-10-11-approved-feedback.md)待审阅、尚未实施；本轮原 3/12 结果不变，不据新设计宣称阶段完成。

## 失败窗口与限制

生成意图已保存且 usage/Trace 已落盘、内容检查点却写失败或执行入口在输出校验后超过截止时间时，恢复报 creation_checkpoint_incomplete，不能自动重发生成。输入与审计保留。JSON 脱敏会规范化重复键，因此独立保存输出失败标记，原无效输出必须进入一次修复，不能因规范化而批准。

一次独立审查发现上述截止时间窗口为 Important；无 Critical 或 Minor。回归先复现 content_started 被错误清除，再修复为保留；相关测试 24 passed、1 warning、14.74 秒，恢复零新增 provider 调用。自然语言质量留待真实/人工评审；未改早期行为仍以已有回归覆盖，不声称全项目重新审计。

重跑时曾错误地并行运行两个同库检查：完整 pytest 231 passed/10 failed、42.79 秒，模拟 8/10、34.265 秒，报告 159559df08d14bab9acd8795fe9420f5 保留。启动恢复逻辑互相标记 process_restarted；停止竞争进程后，仅调整检查顺序、不改产品逻辑，完整 pytest 241 passed。

首次 RED 的假供应商未明确返回值，产生模拟 uncertain 记录；stage2_prompt_test 原记录保留，修正测试后建立 stage2_controlled_test，不改变真实账本。固定真实/模拟清单仍为原 12/10 案例，不挑选成功稿、增加修复或降低门槛。

## 固定套件（提交 a8f83d8）

- 规则：30/30，17.344 秒，7bb2efa1d915498c9a33eb1aac857b8f。
- 旧存档兼容：9/9，12.188 秒，05612b0d892f4ccf8456acb396cb80f4。
- 模拟故障：10/10，48.328 秒，a6712aa8a157481b88d96729d8c96075；其中 runner 及新默认创建故障确实执行受控内容协议，旧创建模块明确保留完整 Story v2 回归。
- 清单 hash ac927d293c87f5407692d7aa11aa22307191a936175c1b8c017335f5315fef5a 未变。上述结果分别为确定性规则、旧存档兼容、模拟故障，不称真实模型任务成功率。

审查修复后顺序重跑固定模拟：10/10、52.765 秒，报告 92b32c10d85c4eebb7773aaa314c6c9a，111 项实际检查；修复前述截止时间回归增加一项，原清单分母与通过门槛不变。规则和旧存档沿用上述实测，不伪称重跑。
