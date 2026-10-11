# 阶段 2 已审核反馈呈现评测

状态：R1 代码、独立审查必要修复及机器检查通过；本轮原固定真实清单 11/12，古代自由文本最后一步未通过。真人核查未执行，阶段 2 未验收。人工审阅人数 0。本报告不改写原受控模式的 3/12 失败结果。

## 机器检查

独立审查发现的材料覆盖与正文/按钮标签缺失已用 RED→GREEN 修复；导出回归 15/15（13.26 秒），修复后完整后端 285/285（69.22 秒，13 条依赖警告），alembic check 无新操作。原规则/兼容/模拟结果保留如下，没有重复运行这些评测。

执行环境：既有 55438 独立 PostgreSQL 集群，新 stage2_presentation_test；同库检查顺序运行。完整后端 283/283，62.39 秒，13 条依赖弃用警告；alembic check 无新迁移操作。

| 评测 | 成功/固定分母 | 报告 run |
|---|---|---|
| 确定性规则 | 30/30 | ac5419b981a54742903b54ace4add7d5 |
| 旧存档兼容 | 9/9 | 509716b80f8740a38ca4da4a780aa2e9 |
| 固定模拟故障 | 10/10 | 8c52de8ebdbe41018c5f8a38b5c61f4f |

规则耗时 17.078 秒，旧兼容 11.609 秒，固定模拟 46.203 秒、112 项断言检查。原清单与骨架 SHA256 保持：清单 ac927d293c87f5407692d7aa11aa22307191a936175c1b8c017335f5315fef5a；骨架 516f8804af3bf97df0b964a875a1d818c6ff084fd68ec552e092de016c438c9e。原目录四份既有草稿 hash 未变。

## 来源与验收边界

新故事固定 controlled-content-2/approved-feedback-1，创建提示仍 investigation-single-6，内容 schema 与规则骨架不变。按钮路径是服务器裁决/呈现，自由输入才调用 action.interpret；真实报告 measurement 为 real_model_with_approved_feedback，按实际 attempt 与关联 LLMCall 分操作报告用量，不能称为实时叙事模型成功率。

导出只读本地已批准故事和终点父链，检查完整固定 12 项、清单/故事/冻结路径 hash、故事归属和终点。测试覆盖部分报告、错根、跨会话、断链、循环、兄弟分支正文泄漏、缺终点和哈希不符。模拟供应商下完整导出测试不是实际人工审阅。

本轮真实调用复用原 stage2_real_test，保留旧失败和账本；调用前已复核累计估算 2.770514 CNY、旧 34 节点/5 版本及 9 历史报告并迁移新增表，不回填旧版本。

## R1 原固定清单真实结果

运行 821e5821b3814ac4a931075da2642dd9，提交 b318b8b29f38cbddf78e255f8ca6b78acd99aeb6，210.891 秒。measurement=real_model_with_approved_feedback，模型 deepseek-flash，创建提示 investigation-single-6，controlled-content-2/approved-feedback-1，原骨架和清单 hash 不变。原报告留在 Git 忽略目录 runtime/evals/821e5821b3814ac4a931075da2642dd9/report.json，SHA256=65b84a4db6d561d303670ce77251635a47722e4b0ba04256a2c3a090eb34d6cd。

| 类别 | 成功/固定分母 | 结果 |
|---|---|---|
| ancient / modern / future 创建 | 3/3 | 全部生成、校验、显式批准；其中一次内容修复 |
| 三年代纯按钮结局路径 | 6/6 | 每条 21 行动，终点符合冻结见证 |
| 三年代完整自由文本路径 | 2/3 | modern、future 通过；ancient 最后一步错误 |
| 合计 | 11/12 | 1 error，0 failed，0 skipped，退出 1 |

古代路径第 21 步的输入为公开结局标签“共同保护与核查”。action.interpret.v1 返回了旧 talk/verify_together 话题，未选择当前公开 decide/guard_together 候选，裁决为 invalid/unknown_action。runner 报 text_or_button_not_accepted。该已保存拒绝反馈节点的完整 state_snapshot 与所选父节点相同，没有解锁结局或授予证据；局部公开输入诊断保存在同 run 的 failure-diagnosis.json。没有换故事重采样、额外自动修复或改写失败为通过。

| 实际操作 | 调用 | 输入 token | 输出 token | 保守估算 CNY |
|---|---:|---:|---:|---:|
| story.content_generate | 3 | 42819 | 15557 | 0.236356 |
| story.content_repair | 1 | 20868 | 6494 | 0.105399 |
| story.semantic_check | 3 | 40502 | 27 | 0.091372 |
| action.interpret | 63 | 163995 | 3101 | 0.396898 |
| 合计 | 70 | 268184 | 25179 | 0.830025 |

70 attempts 均有对应账本记录，未知/未确认费用均为 0；scene.render/scene.semantic_check 无调用。按既有峰值 USD×7.5 价格版本计价，0.830025 CNY 是保守预算估算，供应商实际账单尚未取得。累计预算估算 3.600539 CNY，预算检查通过。

评测后数据库实测 226 节点、8 故事版本、3 固定呈现记录。原 34 节点/5 版本完整行 hash、9 历史报告 hash 及旧 model-scene-1 模式全部不变。未达到 12/12，未导出 human-review.md，人工人数仍为 0；Task 3 验收步骤保持未完成。
