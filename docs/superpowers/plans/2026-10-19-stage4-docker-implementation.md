# Stage 4 Docker Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans in the current linked worktree. The user confirmed the design and direct inline execution; do not stop for another plan approval.

**Goal:** A clean source checkout can build and run the local app with Docker Compose, keeping the direct source-install path.
**Architecture:** Nginx static export and same-origin /api proxy, single-worker FastAPI with migration-first startup, PostgreSQL 18 and separate persistent volumes.
**Tech Stack:** Python 3.12, Node 22 build stage, Nginx stable, PostgreSQL 18, Compose v2; existing application dependencies.
**Spec:** [Approved Docker design](../specs/2026-10-19-stage4-docker-design.md).

## Global Constraints

- Only web publishes `127.0.0.1:${APP_PORT:-8080}:80`; api and db have no host ports. Preserve source localhost startup.
- Keep static export; build `NEXT_PUBLIC_API_URL=/api`. Do not modify game behavior, provider defaults, key persistence or the shared ledger.
- Keys are UI/backend-memory only; no personal DB/images/logs/env or four old drafts in build context. The old untracked docker-compose.yml stays untouched; use compose.yaml.
- DB and runtime use named volumes; PostgreSQL 18 mount `/var/lib/postgresql`. Normal down/start never delete volumes.
- Tests use an independent *_test DB and disposable Docker project, never existing story DB or preview ports. Missing Docker is an unverified gate, not a pass.

## Review Focus

- Password URL punctuation must survive migration and API connection; missing/empty password must stop before either launches.
- Migration failure must prevent the API process; signals must reach one worker rather than a shell wrapper.
- Proxy must preserve auth/idempotency/query strings and deliver SSE without buffering or retrying paid writes.
- Clean source contexts must include canon/static images/migrations and exclude secrets, ignored runtime and unrelated drafts.
- Stop/recreate must retain DB/runtime and browser session state; an empty checkout must offer Demo without hidden local fixtures.

### Task 1: Migration-first API image

**Files:** deploy/docker/api_entrypoint.py, deploy/docker/api.Dockerfile, backend/tests/test_docker_entrypoint.py.
**Interfaces:** consumes POSTGRES_HOST/PORT/DB/USER/PASSWORD; produces DATABASE_URL and MIGRATION_DATABASE_URL in the child process environment and executes one uvicorn worker after successful migration.

- [x] Write behavioral tests for missing/empty password, reserved-character URL roundtrip, migration failure with no server launch, and successful migration followed by exec. Run pytest and observe failures before code.
- [x] Implement the smallest entrypoint; it logs no connection values, returns a stable configuration/migration error, and never retries/reset DB. Copy only needed backend sources and migrations into a non-root Python image with writable runtime volume.
- [x] Run new tests, then full backend pytest on the separate regression DB. Verify migration and model schema there. Commit scoped implementation.

### Task 2: Static web proxy and Compose

**Files:** deploy/docker/web.Dockerfile, deploy/docker/nginx.conf, compose.yaml, .dockerignore, .env.example.
**Interfaces:** consumes Task 1 API image; web serves fixed exported paths and proxies /api to api:8000; Compose waits db healthy then api healthy then web.

- [x] Run engine-free Compose config and semantic checks for required password, punctuation, port binding, dependencies and PG18 volume. No source-string mirror tests.
- [ ] Run actual image builds and Nginx configuration execution; deferred by user instruction not to start Docker.
- [x] Build frontend with npm ci and `/api`; provide complete static files and preserve query strings. Configure SSE buffering/retries off and 1300s read timeout. Only web maps a loopback port.
- [x] Configure DB/runtime volumes, required password and local example settings, health dependencies and context exclusions. Use verified versioned official base tags, no pgvector/latest, no read of backend/.env.
- [x] Run frontend tests/typecheck and isolated `/api` production build; commit scoped files.
- [ ] Run clean image builds and health/startup checks when the user chooses to start Docker; retain pending status.

### Task 3: Container acceptance and source instructions

**Files:** scripts/test-docker.py, README.md, docs/evaluation/2026-10-19-stage-4-docker-results.md, docs/development-log/2026-10-19-stage-4-docker.md.
**Interfaces:** consumes running same-origin web base URL, explicit Docker test project and its own volumes; records no tokens/API keys.

- [x] Reuse existing Demo expected paths to run HTTP-only three endings, authenticated replay, idempotency and SSE checks without paid calls; the runner refuses non-loopback base URLs and never resets data.
- [ ] Run Compose with a fresh archive/checkout and a named test project/port, inspect host port exposure, sentinel DB/runtime persistence across stop/recreate and missing/invalid config behavior. Test the actual artifacts, not just YAML text. Keep existing preview isolated.
- [x] Document clone/download, Docker prerequisites, example config, build/access, updates, normal stop/start/down and troubleshooting. Keep source install instructions, clarify Demo-only clean checkout and origin-bound browser saves.
- [x] Record executed checks, failures and unverified engine/device gates; do not close stage 4 until actual container gates pass. Check links/diff and commit.

### Task 4: Whole-change review and completion

- [ ] Request one fresh read-only final review against base db1198a, this plan and spec, with the Review Focus above and ledger rulings. No per-task implementer delegation.
- [ ] Re-grade findings; fix critical/important issues once with failing behavioral reproductions, then rerun relevant suites. Record deferred minor findings and all review limitations.
- [ ] Verify status and documented scope, commit only relevant files. Do not push, merge, install Docker/WSL or delete user data without the corresponding authorization.
