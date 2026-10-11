# 阶段 2 受控故事验证结果

记录日：2026-10-11。设计与计划已确认，阶段整体尚未验收。真实/人工结果不得以模拟替代；[旧真实失败与费用记录](2026-10-11-stage-2-supplement-results.md)保留。

## 自动检查

- 骨架与严格内容：15 passed，穷举 70 状态，三个最短见证各 21 行动。生产 JSON SHA256=516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e。
- 纯组装/槽位 schema：48 passed，缺失/额外键、错误身份、伪装规则、模板原样及跨故事 ID 受控。
- 创建/旧协议/故障：35 passed、20.82 秒；取消与存储失败不提交节点，原调用费用保留，恢复不重置版本/修复次数。
- 来源报告集成：RED 2 failed/21 passed，GREEN 23 passed、13.47 秒。
- 最新完整后端：240 passed、7 warnings、44.19 秒；Alembic check 无新增操作。模拟库 stage2_controlled_test；前端未改，未运行前端检查。

## 真实与人工状态

受控协议 prompt investigation-single-6 尚未发真实请求，原 12 案例及人工门槛尚未通过；manual_reviewers=0。原真实库 stage2_real_test 4 个节点/2 个故事版本已只读冻结哈希快照，预算 1.248071 CNY，无未核费用阻断；历史失败与批准内容保留。费用为保守估算与用户核账的混合，不能称为全部实际账单。

## 失败窗口与限制

生成意图已保存且 usage/Trace 已落盘、内容检查点却写失败时，恢复报 creation_checkpoint_incomplete，不能自动重发生成。输入与审计保留。JSON 脱敏会规范化重复键，因此独立保存输出失败标记，原无效输出必须进入一次修复，不能因规范化而批准。

首次 RED 的假供应商未明确返回值，产生模拟 uncertain 记录；stage2_prompt_test 原记录保留，修正测试后建立 stage2_controlled_test，不改变真实账本。固定真实/模拟清单仍为原 12/10 案例，不挑选成功稿、增加修复或降低门槛。
