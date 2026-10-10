# 阶段 2 补充实测

记录日：2026-10-11（Asia/Shanghai 用户日期）。阶段 2 仍未验收。方案与范围见[已确认补充](../design/stage-2-custom-stories.md#11-首次真实评测后的补充方案已确认)，保留[首轮失败报告](2026-10-10-stage-2-results.md)。

| 检查 | 实际结果 |
|---|---|
| 审查竞态回归 | RED：1 failed；GREEN：核账与预算 26 passed |
| 完整后端 | 171 passed、7 warnings，35.20 秒 |
| 校验反馈修复后完整后端 | 173 passed、7 warnings，35.76 秒 |
| Alembic check | No new upgrade operations detected，无新迁移 |
| runtime_simulated（审查修复前） | 10/10，34.922 秒，6c9d84077b694c7e825bf0f8cd8ab2f2 |
| runtime_simulated（审查修复后） | 10/10，39.578 秒，add66ff4ab8948649e6ac66861f53503 |
| 原真实请求人工核账 | 1 次、0.02 CNY、input 5,088/output 4,510/total 9,598；来源：用户核对控制台 |
| 原始调用及失败报告 | outcome_unknown/uncertain 与 NULL 原 usage 保留；SHA256 不变，0/12 不改 |
| v2 真实固定清单 | 0/12、12 error，102.812 秒；报告 64ecf68a4a1245a1958aecf5901e3a94 |
| 人工故事核查 | 0 人，尚无新候选 |

核账只追加内部事件，原 stage2_real_test 有效预算为 0.02 CNY、ok、未核账调用 0，节点/故事版本仍为 0，Trace 10→11。没有换库绕过费用保护。核账证据不是供应商原始响应，不能从已计费推断丢失故事通过校验。

生成/修复操作 v2 最大 120 秒，其他 v1 最大 20 秒；HTTP 与墙钟均限制到剩余截止时间，行动 60 秒与创建 300 秒。prompt、12,000 输出预算与固定清单未改。长限时效果须由本轮真实调用验证；未知结果仍不自动重试。

2026-10-11 重新检查 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：峰时未缓存输入 USD 0.30/百万 token、输出 USD 1.20/百万，非峰减半。沿用保守 7.5 换算和版本 2026-10-10-flash-peak-usd-cny7.5；该估算与用户报告的真实 0.02 元分列，不能据此编造精确账单。

## v2 真实失败诊断

在提交 97a3d46 上运行，固定清单 hash 不变。6 个供应商 attempt 均拿到 usage，input 45,159/output 24,144；保守估算 0.318904 CNY（非供应商精确账单）。全库有效预算含旧请求核账为 0.338904 CNY、ok，新增未知费用 0。三项创建均 story_repair_exhausted，九条路径 creation_dependency_failed，人工核查 0，无候选或根节点提交。

生成/修复逐次 attempt 用时：古代 18.188/12.187 秒、近现代 22.297/14.734 秒、未来 14.610/10.406 秒。近现代第一次超过旧 20 秒限时但在 v2 内完成，说明放宽限时允许这次响应完成；不能据 6 次请求推断整体 p95 或稳态成功率。

本地只读诊断：古代初稿和修复稿均缺失可达 ending_cover/ending_truth；近现代两稿均 invalid reference: character_id=detective_lin，未来两稿均 invalid reference: character_id=lin_che，均涉及主角被用于 NPC 限制的字段。原修复反馈分别只传 unreachable/reachability_failed 或 story_validation_failed，丢失了具体缺失 ID 和 schema 错误；后续修复该反馈路径及 prompt 规则说明。原错误候选仅留在忽略目录和内部数据库，不进入 Git 或玩家接口，原 0/12 保留。

具体诊断与规则说明修复后，完整后端 173 项通过，prompt=investigation-single-2。下一轮在同一真实库和清单上另建执行记录；旧失败案例不替换、不减分母。新轮真实结果待实际执行，不据合成模型测试宣称成功。

本轮未改前端，未运行前端测试或构建。图片、便携包、OpenAI 与多 Agent 仍按原后续范围。
