# Stage 3 Completion Implementation Plan

> Implement inline with superpowers:executing-plans, following the already confirmed roadmap and UI direction. Preserve main and unrelated drafts in the attached worktree.

**Goal:** Connect approved custom stories, fixed CogView-4 assets, atomic shared costs and persistent responsive play.

**Architecture:** Extend the existing operation executor/audit boundary and incremental PostgreSQL schema. Separate image preparation from immutable story state. Add a versioned browser library and fixed exported routes that adapt the existing cinematic stage to authenticated public worlds.

**Tech Stack:** Existing FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Next.js, Zustand; Pillow for image validation.

**Spec:** [Stage 3 completion](../../design/stage-3-completion.md).

## Global constraints

- `cogview-4`, `standard`, five 1344x768 backgrounds, three 768x1344 portraits, 0.06 CNY/request, price version `cogview4-2026-10-14-cny`.
- Global 80 CNY warning / 100 CNY stop includes text, image, retries, repairs and uncertain outcomes.
- Keys only in backend memory; no player secrets in public APIs; static export; no modifications to previous approved nodes.
- Dedicated test database only; preserve main's four draft files; do not publish or claim real acceptance from simulation.

## Review focus

- Two concurrent reservations cannot bypass the remaining budget; account locking and transaction rollback leave no partial reservation.
- Image generation succeeded but download failed: reuse stored URL; never regenerate a ready file or an uncertain request implicitly.
- Browser/network restart before a create/confirm/turn response: reuse saved request/key and respect the selected story's token.
- R1 empty dialogue and many long options remain readable; projections must exclude hidden story facts.
- Legacy sessions continue without mandatory newly introduced images; new sessions cannot bypass preparation through direct API calls.

## Tasks

1. [x] **Atomic ledger and migration.** Create `budget.py`, new budget/reservation/image task/asset models and migration; add failing concurrency, unknown outcome and legacy accounting tests; implement shared reserve/settle at the trace boundary; run relevant existing execution tests.
2. [x] **Registered image operations.** Create `image_operations.py` with strict generation/download schemas, official pricing and policies; extend provider outcomes for image usage; test malformed output, missing keys, timeout, host restrictions, size/format validation and chargeable failed calls.
3. [x] **Image task lifecycle and authenticated API.** Create `image_tasks.py` / `image_api.py`; implement fixed eight slots, idempotent start/resume, progress, checkpoint download, interruption, read-only asset serving and server preparation gate. Test cross-session, concurrency, restart, partial recovery and legacy compatibility.
4. [x] **Persistent frontend library.** Create `lib/library.ts` and tests; migrate old browser session storage; save per-story tokens, current nodes, drafts and pending keys. Extend types/API/store to support public custom worlds and restore pending work. Tests pin sibling/story isolation and unknown request recovery.
5. [x] **Complete pages and settings.** Add fixed library/create/play routes, actual create/confirm/prepare states and CogView settings. Adapt the existing stage/people/clues/actions to public entity IDs and authenticated image blobs. Preserve cinematic responsive UI; tests/typecheck/build.
6. [ ] **Acceptance and records.** Migrate separate test DB, full backend/frontend suites and schema check. Browser-check Demo, fixed approved investigation sample, multiple stories, pending recovery and responsive forms. Then perform real three-era creation/eight-image/three-ending checks when keys are provided; record measured results, exact limitations and commit.

No API/model calls precede budget protection. Each task starts with a failing behavioral test and finishes with verified commands. A real acceptance gap keeps stage 3 unchecked.

2026-10-14 自动验证：后端332，前端21，typecheck/build、alembic check通过。一次独立审查并修复费用/检查点/重连及测试库身份问题。任务6仍待三年代真实创建、生图及完整路径；Demo本地操作及响应式结果见 design-qa.md。

真实首轮3/15、恢复7/15，v1图片质量失败；v2提示回归通过但实图未验证，任务6继续未完成。见 docs/evaluation/2026-10-14-stage-3-results.md。


2026-10-16 继续任务 6：删除记录已复核并推送 82cd3f9；失败定位为缺 action_feedback 后修复语义未过。新内容/图片提示与 v6 检查点兼容修正已实现，完整回归及真实重测按当日开发日志记录。Ruling：执行一次新版三年代固定清单，保留既有样本/旧图/原失败分母，不自动循环建局；真实门槛未通过前不勾选任务 6。


2026-10-16 任务6真实执行：源码2ac878e，首次11/15，复用批准故事/固定图补下载并运行剩余路径后15/15；三创建、24图、九路径共189行动通过。新增估算2.195450 CNY。图片全部逐张核查仍有年龄、背景人物、文字和构图缺口，实机可访问性待验；任务6保持未完成，不自动循环创建更多样本。见 docs/evaluation/2026-10-16-stage-3-results.md。
