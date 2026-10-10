# 阶段 2 核账与限时补充

记录日：2026-10-11（用户时区）。继续同一已确认实施；阶段整体未验收。

一次针对新增边界的独立审查发现 1 项 Important、0 Critical/Minor：预算阈值和解除阻断分别读取核账，两次读取间提交会漏计金额。确定性回归先失败，再改为共享一份核账快照；相关 26 项通过，完整后端 171 passed、7 warnings，35.20 秒。迁移检查无新增操作。审查前模拟清单 10/10，34.922 秒（6c9d84077b694c7e825bf0f8cd8ab2f2），修复后结果另记。

审查未判断项裁定：未变阶段 2 及旧 Minor 按历史验收和记录，不扩入补充；真实/人工故事质量等实际结果，不据代码测试宣称通过；账单来源仅为用户陈述，不宣称供应商自动核验或远端取消成功；完整测试、迁移、hash 由实现者实际验证，无需审查重复跑；PostgreSQL 4 路核账并发测试不称压力或性能测量；本地操作者直接改库属于信任边界外，图片/预留/UI/OpenAI/多 Agent 保持后续范围；审查修复由 RED→GREEN 和完整回归验证，不发起重复整套审查。

通过本地 CLI 在原 stage2_real_test 追加唯一 usage_reconciled 事件。只读确认原调用仍为 outcome_unknown/uncertain，原 token/估算均 NULL；有效预算 0.02 CNY、status=ok、unconfirmed_calls=0，核账输入 5,088/输出 4,510、合计 9,598。nodes=0、story_versions=0，Trace 10→11；原失败 report.json SHA256 未变，原结果仍 0/12。只读核验保存在忽略目录 runtime/stage2-test/reconciliation-check.json。

按用户时区本日重新核对 DeepSeek 官方价格，峰时未缓存输入 USD 0.30/百万、输出 USD 1.20/百万，与既有执行价格版本一致；不改历史价格或把估算冒充实际账单。[最新结果](../evaluation/2026-10-11-stage-2-supplement-results.md)分开保留实际核账与模型返回 usage。

审查修复后固定模拟清单 10/10、39.578 秒，报告 add66ff4ab8948649e6ac66861f53503。清单 hash 保持 ac927d293c87f5407692d7aa11aa22307191a936175c1b8c017335f5315fef5a。两份模拟报告检查的是本补充尚未提交的工作树，HEAD 字段仍为基点 4f6274c；正式真实评测在提交后运行。8 份相关文档本地链接无断链，git diff --check 通过，原目录四份草稿 hash 均与基线一致。本轮未重跑规则/旧存档独立评测；完整后端已覆盖其回归，不将历史独立报告称为新结果。

提交 97a3d46 后在原 stage2_real_test 隐藏输入密钥，真实报告 64ecf68a4a1245a1958aecf5901e3a94 为 0/12、12 error、102.812 秒。6 个 attempt 都返回 usage，input 45,159/output 24,144，保守估算 0.318904 CNY；全库有效预算 0.338904（含旧核账），新增未知费用 0。三创建 story_repair_exhausted，九路径因创建依赖失败，人工核查 0。没有提交候选或根节点；限时放宽不能等同生成质量通过。

只读诊断显示古代两稿均有两结局不可达，另两背景两稿均误将主角用于 NPC 限制字段。发现修复只有泛化错误码，丢失具体 Pydantic 消息与 BFS 已有 missing_endings。同步设计后补充 bounded 内部错误详情和 JSON Schema 外的现有规则说明，prompt 版本升为 investigation-single-2；不修改 schema、裁决、修复次数或公开投影。两项合成 fixture 回归先确认缺失详情失败，测试提供器断言最初放置错误导致模拟 uncertain 行，保留在 stage2_acceptance_test，后续 TDD 使用新 stage2_prompt_test；真实库始终未切换。限时测试另发现浮点舍入 0.0500000000029，断言加 1e-9 容差，执行限时不变。

诊断反馈修复后完整后端 173 passed、7 warnings，35.76 秒。只有 schema path/type/message 和 BFS 状态/缺失 ID 进入有界内部修复输入，不含 Pydantic 原 input/context，随后脱敏；公开任务接口不暴露这些字段。prompt 版本从 1 升至 2，报告读取实际 PROMPT_VERSION，不继续硬编码旧版本。
