# Handoff: Relay resume workflow - four follow-ups implemented and piloted locally

## Goal
Improve resume context and recovery, compare a plain note with Relay using live
receiving agents, and validate a Herdr companion workflow.

## Done so far
- Resume review (2026-11-16): no blocking findings; 62 targeted Python tests,
  both Node UI suites and `git diff --check` passed.
- Changes included in the commit containing this handoff on feat/relay-resume-workflow,
  based on 16417ca; publication remains pending.
- CLI resume and board claim include checkpoint context, latest executed evidence,
  separate reported checks, and recheck guidance. Schema/ownership rules preserved.
- Shared evidence lookup validates malformed records and degrades to unavailable;
  post-transfer evidence errors do not make a completed claim appear failed.
- Transfer conflicts include non-destructive recovery steps; docs/handoff-recovery.md.
- docs/demo/compare_handoffs.py prepares isolated fixtures and opt-in bounded live
  trials. Cleanup covers monitor failures, Windows process trees and POSIX groups;
  immutable acceptance and distinct first-edit/first-passing metrics are tested.
- User explicitly authorized live Claude Code/Codex benchmark allowance consumption.
  Six invocations recorded, including CLI incompatibility, timeout and state-access
  failure. Results and caveats: docs/demo/handoff-comparison-results.md.
- Herdr 0.9.5 portable named session created two panes in a temporary fixture;
  Relay resume output verified. Session stopped; docs/herdr-companion.md.
- Python regression suite: 63 tests ran successfully, 1 skipped; five benchmark
  tests passed separately. Both Node UI suites passed; 24 local links/anchors checked.
- Independent review found and prompted fixes for malformed evidence, process
  cleanup, first-edit scoring and Windows CRLF handling; regressions added.

## Decisions and why
- Keep executed evidence advisory and distinct from reported checks; evidence
  reads must not invalidate a completed cooperative ownership transfer.
- Publish all pilot outcomes without a speed claim: plain notes were faster in
  these tiny, noisy trials; Relay's benefit demonstrated here is evidence clarity.
- Use temporary tool installations and state access; do not change global CLIs or
  weaken the receiver's sandbox to make a benchmark pass.

## Open issues / gotchas
- Not a powered study, source-agent handoff benchmark, Herdr speed comparison,
  or full live Claude-to-Codex transition inside Herdr. Limits explicit in docs.
- First-edit scoring in the last pilot had a CRLF bug; fixed now, excluded from
  reported results. First-passing edit and final acceptance measurements unaffected.
- Raw local traces: %TEMP%/relay-comparison-{9bmn8sgx,27y0_gv4,ve9q04ca,pva72066,0cjpxi9s,iauon1ns}.
  They include local context; do not publish without redaction/review.
- Portable tools remain at %TEMP%/relay-herdr-0.9.5 and %TEMP%/relay-codex-trial.
- No runtime restart or GitHub publication performed for this workstream.

## Next steps
1. Publish from the user terminal when ready; local review and commit are complete.
2. If making performance claims later, run counterbalanced repeated trials across
   several tasks with pinned CLI/model/settings; do not reuse the tiny pilot as proof.

## Read first
- docs/superpowers/plans/2026-11-16-relay-resume-workflow.md
- docs/demo/handoff-comparison-results.md
- docs/herdr-companion.md
- coordinator/usagekit/handoff.py
- coordinator/usagekit/continuity.py
