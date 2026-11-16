# Handoff: Relay handoff proof - documentation and local demo verified

## Goal
Make Relay's Git-checked handoff advantage clear and reproducible without claiming
unmeasured superiority over Herdr.

## Done so far
- Updated README positioning around checkpoints and recorded test evidence.
- Added docs/demo/verified-handoff.md: temporary repository, fictional accounts,
  real CLI checks, stale evidence, rejected claim, refresh and successful transfer.
- Linked the demo from docs/setup-and-reference.md; existing quota example retained.
- Executed the exact PowerShell block in a child process: all four expected
  observations verified, including destination owner and generated resume prompt.
- Validation: 15 continuity tests passed; 29 local links/anchors and code fences
  checked; git diff whitespace check passed.
- Prepared on docs/relay-handoff-proof, based on b371434; user explicitly authorized
  committing and pushing this update to prabhuashwin/agent-relay on 2026-11-16.

## Decisions and why
- Lead with Git-checked handoffs and executable evidence; this is a concrete,
  demonstrable benefit rather than an unmeasured competitor ranking.
- Keep the fixture offline and isolated; no provider calls or real ownership changes.

## Open issues / gotchas
- No live Claude-to-Codex benchmark or Herdr integration was performed.
- Demo deliberately retains its temporary directory for inspection.
- Git fingerprint and cooperative ownership limitations are explicit in the docs.

## Next steps
1. Verify relay/main contains the documentation commit before reporting publication.
2. Origin synchronization is separate; this request targets agent-relay only.

## Read first
- README.md
- docs/demo/verified-handoff.md
- docs/superpowers/plans/2026-11-16-relay-handoff-proof.md
