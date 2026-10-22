# Stage 5 Portfolio Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Execute in this session; one independent final review.

**Goal:** 交付真实、可复现的普通流水线基线及求职展示，取消已移出范围的 OpenAI 和多 Agent 义务。

**Architecture:** 复用现有执行器与阶段二真实 runner，不改变游戏规则和供应商。新增只读证据采集及离线统计入口，原始模型数据与录制检查点存入 runtime；仅公开无凭据 Demo 视频、封面和安全聚合报告。

**Tech Stack:** Python、pytest、SQLAlchemy/PostgreSQL、Next.js 静态导出、Playwright 录屏、Markdown/Mermaid。

**Spec:** [阶段五设计](../specs/2026-10-22-stage5-portfolio-design.md)

## Global Constraints

- 不接入 OpenAI/多 Agent，不修改用户数据库，不改写已保存节点或历史报告。
- 保留四份预先存在的未跟踪草稿，不将生成故事、密钥、数据库、日志提交 Git。
- 只读采集使用 PostgreSQL `_test`；新集成测试使用单独的测试数据库。
- 历史重算、模拟故障、新模型运行与人工评价分别报告。

## Review Focus

- 篡改/不完整来源不能变成 100% 成功；失败、缺失和跳过保留原固定分母。
- 只读采集不能启动应用生命周期、重发模型或读取兄弟分支/其他会话账单。
- 输出结构正确不能被描述为事实正确；没有匹配人工证据就保留未知。
- 零调用回合不能伪造 token；费用未知不能按零收费。
- 历史 prompt 6 的结果不能冒称当前 prompt 7 的新质量验收。

### Task 1: 范围与架构

**Files:** 修改 AGENTS.md、三主文档、docs/design/implementation-plan.md；新增 docs/design/stage-5-portfolio.md。

**Interfaces:** 消费当前 R1 实现与最新取消 OpenAI 提交；产出当前范围、架构图及展示说明。

- [x] 同步取消阶段六，保留原编号与历史计划。
- [x] 写实际模块、信任边界、创建/回合/回放流程与作品描述。
- [x] 核对本地链接及历史保留；`git diff --check` 通过。

### Task 2: 评测入口

**Files:** 新增 evals/run_stage5.py、backend/tests/test_stage5_evaluation.py；复用 evals/run_stage2.py 与 stage2.json。

**Interfaces:** `collect_baseline(source_report, database_url, human_review=None)` 只读采集；`summarize_baseline(bundle)` 纯统计；CLI 支持 recorded/replay/real_model/runtime_simulated。

- [x] 先写边界测试并观察失败：来源/哈希/固定分母、结构/语义区分、延迟分组、账本归属、只读与零调用。
- [x] 实现最小采集、离线复算和现有 runner 调用；失败退出非零。
- [x] 运行相关 pytest；实际提取匹配的历史真实/人工记录并离线复算一致。

### Task 3: 演示与收尾

**Files:** 新增 scripts/record-demo.mjs、docs/evaluation/2026-10-22-stage-5-results.md、docs/development-log/2026-10-22-stage-5.md；修改 README.md 与阶段状态。

**Interfaces:** 消费 Task 1 的产品说明和 Task 2 的版本化基线；产出实际录屏、复现指引及安全聚合报告。

- [x] 在独立测试库迁移并运行 Demo；生产前端构建后实际录屏调查、分支、回放和刷新恢复。
- [x] 检查视频与截图、确认无 API Key/会话令牌、记录 Demo 非 AI 质量证据。
- [x] 运行相关后端测试、前端测试/typecheck/build，检查文档链接、diff 及四份草稿未变。
- [x] 一次独立最终审查，修复必要问题并验证；记录实际结果后提交相关文件，不自动推送或合并。
