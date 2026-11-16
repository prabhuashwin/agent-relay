# Relay handoff proof implementation plan

**Goal:** Make Relay's Git-checked handoff benefit clear and reproducible.

**Approved design:** Update README positioning and add a local walkthrough showing
executed evidence becoming stale, checkpoint refresh, and explicit release/claim.
The user approved this scope on 2026-11-16. Do not claim comparative performance.

**Architecture:** Documentation only. Exercise the existing CLI in a temporary Git
repository with separate Relay state and fictional accounts; no provider calls.

**Tech stack:** Markdown, PowerShell, Python and Git.

## Inline execution

- [x] Update `README.md` headline, evidence explanation and walkthrough link.
- [x] Add `docs/demo/verified-handoff.md` with copyable PowerShell commands,
  expected observations, and fingerprint/ownership limits. Link from the existing
  example in `docs/setup-and-reference.md`.
- [x] Execute the documented block in a child PowerShell process. Confirm passing
  evidence, stale evidence after an edit, rejection of a changed-tree claim,
  refreshed passing evidence, destination ownership and a resume prompt.
- [x] Run `python -m unittest tests.test_continuity -q`, check local links and
  `git diff --check`. No new product code or live agent benchmark is needed.
- [x] Record the positioning decision and save `handoffs/relay-handoff-proof.md`;
  update `handoffs/INDEX.md`. Leave changes local for review.
