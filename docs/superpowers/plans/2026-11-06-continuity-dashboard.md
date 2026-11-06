# Continuity dashboard v1

**Goal:** Ship a local dashboard for checkpoint-backed workstreams, explicit ownership release/claim, evidence freshness, and explained routing.

**Architecture:** Reuse existing checkpoint and routing functions. Store release tickets and executed verification records in SQLite under the coordinator home, keyed by repository path. Serve a buildless UI on loopback using Python's standard library. Existing Markdown checkpoints remain authoritative for goals and owners. No provider calls or automatic agent launches.

**Design accepted:** The user requested implementation of the four-part first version proposed in chat. Ownership is cooperative: release requires explicit confirmation the source writer stopped. This cannot enforce exclusion against independent IDE sessions or legacy CLI commands. Claim checks both checkpoint identity and repository state again. Manually supplied checkpoint checks are labelled reported, never automatically verified.

**Tech stack:** Python 3.9+, SQLite, standard-library HTTP server, HTML/CSS/JavaScript.

- [x] Add regression tests for release/claim, stale tickets, changed verification inputs, and unknown quota.
- [x] Implement `continuity.py`: board aggregation, release tickets, claim, command verification records and resume prompts.
- [x] Add `usagectl board status|serve|release|claim|check` commands. Checks execute only explicitly supplied CLI argument arrays, never through HTTP.
- [x] Implement loopback HTTP endpoints with same-origin checks and per-process action token; static files come only from the packaged dashboard directory.
- [x] Implement responsive workstream, capacity, evidence, recommendation and handoff panels, with visible errors and empty state.
- [x] Run focused tests (15 continuity + 37 checkpoint), JavaScript syntax check and HTTP smoke test. Earlier full coordinator run passed 177 tests (2 skipped).
- [ ] Complete browser smoke test (browser host unavailable) and optional full post-lock suite rerun (interrupted at long-job boundary).
- [x] Document setup, cooperative ownership limitation, evidence semantics and recovery; write decision and handoff notes.

Acceptance: a stale checkpoint cannot transfer ownership; a consumed ticket cannot be reused; failed/changed-tree checks cannot appear freshly passed; missing/stale usage cannot become available; the UI displays real checkpoint data without HTML injection; no live provider calls occur on refresh.
