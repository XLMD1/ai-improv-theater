# Repository instructions

## Project scope and source of truth

- Read the relevant files in `docs/` before changing product behavior. `01-requirements.md`, `02-technical-design.md`, and `03-development-plan.md` define the accepted scope and verification gates.
- If an implementation decision changes those documents, update the relevant design documentation before changing code.
- This is a local, single-user interactive narrative app. Treat planned features as incomplete until their documented acceptance checks pass. In particular, OpenAI support is pending verification; multi-agent orchestration, pgvector, Redis, and cloud deployment are not part of the accepted implementation scope unless the user changes it.

## Architecture invariants

- The server and the versioned story data are authoritative for scene transitions and world state. Model output is a proposal and must pass schema and deterministic state validation before it can be committed.
- Apply state changes through the existing state-update path; do not let generators or review code write database state directly.
- Saved nodes and approved rendered scenes are immutable. Replaying a node must return its saved content without calling a generator.
- A new branch uses only its selected parent and that parent's ancestors. Do not include sibling-branch events in generation context.
- Do not stream unvalidated candidate story text to the browser.

## Local configuration and secrets

- Put the local database URL in `backend/.env`. That file is Git-ignored. Never stage, commit, print, or log its contents or any API key.
- Alembic connection precedence is `MIGRATION_DATABASE_URL`, then `DATABASE_URL`, then the settings loaded from `backend/.env`.
- Keep provider API keys in the backend's in-memory settings flow. Do not add key persistence to the database or browser storage unless the requirements are explicitly revised.
- Use a separate test database for migrations and tests. Never point destructive test or reset commands at the user's local story database.

## Development and verification

- From the repository root on Windows, start the local app with `pwsh -NoProfile -File .\scripts\start-local.ps1`. See `README.md` for dependency setup and PowerShell 5.1 instructions.
- For backend changes, run the relevant pytest suite from `backend/`; for frontend changes, run the relevant frontend tests and `npm run typecheck`. Run the production build when frontend behavior or bundling changes.
- Report only checks that were actually run. Do not describe a plan, draft, or unverified feature as complete.
- Preserve unrelated working-tree changes. The untracked `backend/app/generators.py`, `backend/app/llm.py`, `backend/app/memory.py`, and `docker-compose.yml` are pre-existing drafts; do not stage or rewrite them unless they are explicitly brought into scope and validated.

## Git workflow

- Use commit titles in `English: 中文` format, for example `fix: 修复本地启动配置`.
- Stage only files relevant to the requested, verified change. Never commit `.env` files, credentials, local database files, or unrelated drafts.
