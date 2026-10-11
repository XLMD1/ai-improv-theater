# 阶段 2 受控故事实施记录

用户于 2026-10-11 确认[方案 A](../design/stage-2-controlled-story-proposal.md)及[详细计划](../superpowers/plans/2026-10-11-controlled-story.md)，沿用顺序实施。阶段整体仍未验收，真实/人工结果不得由模拟替代。

任务 1：RED 15 项因模块缺失失败，GREEN 15 passed；生产骨架 SHA256=516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e，穷举 70 状态、三个最短结局路径各 21 行动。完整后端 195 passed、7 warnings、40.84 秒。提交 499634b；原批准样本未改。

Ruling: 对唯一冻结 JSON 资源固定 LF — Windows core.autocrlf 会改变字节 hash — 代价为增加一条资源专属 Git 属性，不影响其他文件。

任务 2：RED 28 failed/20 passed，纯组装/注册 GREEN 48 passed、1.18 秒；初次 Pydantic schema 读取把 patternProperties 误当 additionalProperties，相关测试发现并修正，无真实调用。完整后端第一次 222 passed/1 failed，旧注册表集合断言未包含新增两项操作；保留旧四项全部检查并增加新项后，223 passed、7 warnings、39.36 秒。纯组装不改引用/规则/效果/出口，输入与提示槽位绑定独立故事 ID，旧生成操作仍注册。

Ruling: 补充现有注册表断言的两项内容操作 — 旧集合与批准扩展不符 — 所有旧操作检查保留，没有放宽校验。

本轮仅独立 stage2_prompt_test 用于数据库测试，未新调用模型、未重跑真实清单。当前 prompt=investigation-single-6；真实内容质量未验证。
