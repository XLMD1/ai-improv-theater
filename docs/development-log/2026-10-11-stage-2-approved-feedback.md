# 阶段 2 已审核反馈呈现实施记录

用户批准 R1，并确认三任务实施计划，沿用当前会话顺序实施。阶段 2 尚未验收；真实模型与人工核查尚未运行。

## Task 1：固定呈现协议

新增独立 story_presentations 表及 0006 增量迁移。新版本同事务固定呈现协议，旧无记录版本保持 model-scene-1，同一版本不能切换协议。数据库拒绝 UPDATE/DELETE、重复、未知协议和缺失外键；有呈现或审计记录时降级先拒绝，不删除数据。

先运行新测试，因 StoryPresentation 尚未实现出现 ImportError；实现后相关 36 项通过（3.25 秒，12 条 Alembic 配置弃用警告）。独立 UUID 测试库验证旧故事/节点/事件完整行不变，以及空表降级、已有记录降级保护。

完整后端首次 252 通过、1 失败（43.71 秒）：既有 test_generation_http_and_wall_timeout_share_policy_and_remaining_deadline 的两次实际计时相差 0.016 秒，超出其 0.01 秒断言。未修改时限代码或断言，单项 2/2 通过，再完整重跑 253/253（45.83 秒，13 条既有依赖弃用警告）；alembic check 无新增迁移操作。测试只使用 stage2_presentation_test 和自身临时测试库，未改真实库。
