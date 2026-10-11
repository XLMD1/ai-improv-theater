# 阶段 2 受控故事实施记录

用户于 2026-10-11 确认[方案 A](../design/stage-2-controlled-story-proposal.md)及[详细计划](../superpowers/plans/2026-10-11-controlled-story.md)，沿用顺序实施。阶段整体仍未验收，真实/人工结果不得由模拟替代。

任务 1：RED 15 项因模块缺失失败，GREEN 15 passed；生产骨架 SHA256=516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e，穷举 70 状态、三个最短结局路径各 21 行动。完整后端 195 passed、7 warnings、40.84 秒。提交 499634b；原批准样本未改。

Ruling: 对唯一冻结 JSON 资源固定 LF — Windows core.autocrlf 会改变字节 hash — 代价为增加一条资源专属 Git 属性，不影响其他文件。

任务 2：RED 28 failed/20 passed，纯组装/注册 GREEN 48 passed、1.18 秒；初次 Pydantic schema 读取把 patternProperties 误当 additionalProperties，相关测试发现并修正，无真实调用。完整后端第一次 222 passed/1 failed，旧注册表集合断言未包含新增两项操作；保留旧四项全部检查并增加新项后，223 passed、7 warnings、39.36 秒。纯组装不改引用/规则/效果/出口，输入与提示槽位绑定独立故事 ID，旧生成操作仍注册。

Ruling: 补充现有注册表断言的两项内容操作 — 旧集合与批准扩展不符 — 所有旧操作检查保留，没有放宽校验。

本轮仅独立 stage2_prompt_test 用于数据库测试，未新调用模型、未重跑真实清单。当前 prompt=investigation-single-6；真实内容质量未验证。

任务 3：干净 RED 13 failed/20 passed；创建/兼容/恢复相关 GREEN 34 passed、19.96 秒，加入取消检查后完整后端 239 passed、7 warnings、56.55 秒。首次绿色运行仅一个测试因未按 Trace seq 排序而失败，明确排序后修正；无产品逻辑放宽。新任务固定 controlled-content-1、骨架版本/hash 与 prompt，旧无标记任务保持完整 Story v2。失效版本与骨架调用前拒绝，语义连续否决或修复仍非法均不提交版本/根，重复确认不调用 provider。

Ruling: 模拟库切换到 stage2_controlled_test — 一项 RED 假供应商配置产生模拟 uncertain 行，修正假供应商并保留 stage2_prompt_test 的原记录 — 代价是增加独立模拟库；真实库 stage2_real_test 不变。

Ruling: 输出失败标记与脱敏内容一起保存 — JSON 脱敏会规范化重复键，不能因此接受原无效输出 — 增加一个内部标记，仍至多一次修复。生成意图先保存；若成功用量已记录而内容检查点写失败，恢复报 creation_checkpoint_incomplete，不盲重发。保留玩家输入、Trace 与用量，该极少见存储失败窗口不提供自动重新生成。

旧任务未记录创建 prompt 时，新批准根明确标为 investigation-single-legacy，不能猜测当年的 prompt；已有批准根原样返回。取消测试记录 uncertain 并检查无节点，随后仅清理该测试自行建立的模拟会话记录；不删除真实用量。

任务 4 评测来源：RED 2 failed/21 passed；新增字段后 GREEN 23 passed、13.47 秒。完整后端 240 passed、7 warnings、44.19 秒，Alembic check 无新增操作。报告/冻结文件注明 creation_protocol、blueprint_version/hash 与实际创建 prompt；原清单 hash、取样与分母保持，人工人数仍 0。

真实调用前只读快照原库 4 节点/2 故事版本，预算 1.248071 CNY、未知费用与未完成审计均无阻断。快照为忽略目录 runtime/stage2-test/controlled-before-real.json；新调用后须逐项核对原 hash。

2026-10-11 核对[官方 Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)与[官方英文价格](https://api-docs.deepseek.com/quick_start/pricing/)：deepseek-flash 对应 DeepSeek-V4.1-Flash，支持非思考与 json_object，输出上限支持 12,000 token。价格页网页工具超时后直接只读获取官方页面，峰时缓存未命中输入 USD 0.30/百万、输出 USD 1.20/百万，与既有保守估算表一致；沿用价格版本及固定 7.5 换算，不当作实际账单或周末实际价格。未调用模型。

提交 a8f83d8 后规则 30/30、17.344 秒，兼容 9/9、12.188 秒，模拟 10/10、48.328 秒；具体报告 ID 见[结果](../evaluation/2026-10-11-stage-2-controlled-story-results.md)。八份相关文档 58 个本地链接无断链，git diff --check 通过，原四份草稿与清单 hash 未变。已发起一次仅覆盖本受控变更的独立只读审查，真实/人工仍待进行。

独立最终审查范围 368d0fc..a8f83d8：Critical 0、Important 1、Minor 0。Important 为供应商成功且已保存已知用量后，执行入口因截止时间返回 task_timeout，但创建检查点清除了生成意图；恢复可能再次付费生成。保持 Important 分级，单次修复保留该超时窗口的 content_started；不改通用执行入口或自动取出 Trace 候选。新增 test_deadline_after_known_usage_cannot_blindly_regenerate_on_resume：RED 在 content_started=False 处失败；相关套件 GREEN 24 passed、1 warning、14.74 秒，验证已知用量一条、无节点、恢复零新增调用。

Ruling: 审查未判断三故事及九路径的自然语言质量 — 留给原固定真实清单与至少一位真实人工评审，自动测试不足以判断 — 代价是阶段 2 仍待验收，不能提前标为完成。

Ruling: 审查未重审早期阶段 2 的所有未改行为 — 本次只审受控改动及集成依赖，完整回归、原规则与旧存档套件负责兼容证据 — 代价是未改变部分仍依赖已有范围的回归，不能声称整项目重新审计。没有延期 Minor，没有发起第二次审查。

验证安排失误：完整 pytest 与固定模拟 runner 同时使用 stage2_controlled_test，应用启动恢复逻辑互相中断运行任务。完整检查 231 passed/10 failed、42.79 秒，模拟报告 159559df08d14bab9acd8795fe9420f5 为 8/10、34.265 秒；失败以 process_restarted 为主要证据。保留该失败报告与用量，不修改产品启动逻辑掩盖测试干扰；两个进程结束后顺序重跑。真实数据库未参与。

顺序重跑完成：完整后端 241 passed、7 warnings、45.76 秒；固定模拟 10/10、52.765 秒，报告 92b32c10d85c4eebb7773aaa314c6c9a，111 项实际断言检查。没有再改产品逻辑，证实同库竞争为上述验证失败来源。原规则/兼容结果不重复计数，真实/人工仍未执行。
