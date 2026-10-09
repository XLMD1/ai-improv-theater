# Repository instructions

## Project scope and source of truth

- Read the relevant files in `docs/` before changing product behavior. `01-requirements.md`, `02-technical-design.md`, and `03-development-plan.md` define the accepted scope and verification gates; `docs/design/implementation-plan.md` records the confirmed expansion plan.
- If an implementation decision changes those documents, update the relevant design documentation before changing code.
- This is a local, single-user investigation narrative app. The accepted roadmap is playable experience, portfolio delivery, then a validated multi-agent default. The first custom-story release targets three characters, five main locations, and three endings; keep the built-in Demo available without API keys.
- Treat planned features as incomplete until their documented acceptance checks pass. Custom stories, CogView-4 images, investigation rules, portable packaging, OpenAI text support, and multi-agent orchestration are planned, not currently verified. OpenAI remains disabled until its independent acceptance check passes; multi-agent becomes the default for new stories only after the final phase passes. pgvector, Redis, and cloud deployment remain out of scope.
- Use the current phase 0–6 numbering in `docs/03-development-plan.md`. Earlier phase numbers and test counts belong to the preserved historical baseline and do not prove completion of the new phases. Do not restore week-based deadlines.

## Architecture invariants

- The server and the versioned story data are authoritative for scene transitions and world state. Model output is a proposal and must pass schema and deterministic state validation before it can be committed.
- Approved story definitions, including the truth and evidence rules, are fixed for that game. Use only server-supported declarative rules; never execute model-generated rule code. Filter hidden truth, secrets, and undiscovered clues from every player-facing response.
- Apply state changes through the existing state-update path; do not let generators or review code write database state directly.
- Investigation turns and location changes are separate. Invalid or repeated actions must not automatically move the player or grant clues. Record important disclosures, commitments, and triggered events as structured state.
- Saved nodes and approved rendered scenes are immutable. Replaying a node must return its saved content without calling a generator.
- A new branch uses only its selected parent and that parent's ancestors. Do not include sibling-branch events in generation context.
- Add explicit story, state, and engine versions through incremental migrations. Keep old nodes and rendered scenes intact and replay legacy stories through their compatibility path. New stories use story-provided character and location IDs instead of the Demo's hardcoded IDs.
- Do not stream unvalidated candidate story text to the browser.

## Local configuration and secrets

- Put the local database URL in `backend/.env`. That file is Git-ignored. Never stage, commit, print, or log its contents or any API key.
- Alembic connection precedence is `MIGRATION_DATABASE_URL`, then `DATABASE_URL`, then the settings loaded from `backend/.env`.
- Keep provider API keys in the backend's in-memory settings flow. Do not add key persistence to the database or browser storage unless the requirements are explicitly revised.
- Text and image calls share the 80 CNY warning and 100 CNY stop threshold. The planned shared ledger must reserve cost before calls and account for actual usage, repairs, and chargeable failed calls. Verify and version CogView-4 pricing before enabling image calls; do not invent a price.
- Generated stories, user images, databases, credentials, and local logs belong in Git-ignored runtime directories. Freeze completed image assets and reuse them on replay; recovery retries only missing assets.
- Use a separate test database for migrations and tests. Never point destructive test or reset commands at the user's local story database.

## Development and verification

- From the repository root on Windows, start the local app with `pwsh -NoProfile -File .\scripts\start-local.ps1`. See `README.md` for dependency setup and PowerShell 5.1 instructions.
- For backend changes, run the relevant pytest suite from `backend/`; for frontend changes, run the relevant frontend tests and `npm run typecheck`. Run the production build when frontend behavior or bundling changes.
- For documentation-only baseline changes, check local links, scope and phase consistency, preservation of historical acceptance records, and `git diff --check`; do not claim runtime tests were rerun.
- Keep Next.js static export. Planned story pages use fixed routes and query parameters, with a per-story library that restores session credentials, the current node, and pending tasks across browser restarts; API keys never enter that storage.
- Each phase follows specification updates, implementation, tests, local acceptance, a record in `docs/development-log/`, and a relevant commit. Record measured latency, usage, cost, and reviewer count rather than unsupported portfolio claims.
- Report only checks that were actually run. Do not describe a plan, draft, or unverified feature as complete.
- Preserve unrelated working-tree changes. The untracked `backend/app/generators.py`, `backend/app/llm.py`, `backend/app/memory.py`, and `docker-compose.yml` are pre-existing drafts; do not stage or rewrite them unless they are explicitly brought into scope and validated.

## Git workflow

- Use commit titles in `English: 中文` format, for example `fix: 修复本地启动配置`.
- Stage only files relevant to the requested, verified change. Never commit `.env` files, credentials, local database files, or unrelated drafts.
