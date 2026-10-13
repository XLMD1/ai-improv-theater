# Movie-stage UI Implementation Plan

> Execute inline with superpowers:executing-plans; asset generation alone is delegated. User approved the UI document on 2026-10-13.

**Goal:** A responsive movie-stage page using actual existing story actions and immutable replay.

**Architecture:** Keep the existing Next.js static export, Zustand store, legacy API and backend. Split the presentation into stage, reader and accessible panels; strengthen pending-action handling at the existing store boundary.

**Tech Stack:** Next.js 15, React 19, TypeScript, Zustand, existing Lucide icons.

**Spec:** [Approved UI design](../../design/stage-3-ui-design.md).

## Constraints

- Server content and options remain authoritative. No invented investigation targets, evidence or dialogue.
- Current single-session Demo/DeepSeek only; full custom creation, image pipeline and persistent library remain later stage 3 work.
- No API keys in browser storage. Preserve four unrelated draft files.
- Work in the current checkout with existing documentation changes; no merge or publish.
- Only a dedicated new *_test database may be migrated for browser acceptance.

## Tasks

1. [x] Add failing behavioral tests for ancestor-only history, complete narration reading, draft retention and unresolved-task duplicate prevention. Implement the smallest helpers/store changes and run frontend tests.
2. [x] Replace the old stage with generated location assets, cinematic responsive layout, sentence reading and all backend options; add current-story, people, clues, history and branch dialogs. Keep model settings.
3. [x] Run tests, typecheck and static production build. Start with the documented local startup script using the isolated test database.
4. [x] Browser-check three Demo endings and branches, refresh recovery, keyboard/dialogs, mobile layouts and failures. Compare source and rendered screenshots, fix material differences, save design-qa.md and development log. Native browser zoom and physical mobile keyboard remain unverified; a 720px reflow equivalent was checked.

## Review focus

- Failed or unconfirmed submission must retain input and cannot submit with a second key.
- Ancestor history must exclude sibling nodes; replay must not create a turn.
- R1-style empty dialogue, long text and more than three options must remain readable.
- Small width, low landscape height and large text cannot hide send/close controls.
- Image/loading/network failures must leave clear recovery controls and never claim successful state changes.
