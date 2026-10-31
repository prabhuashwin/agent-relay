# Handoff: Dual Claude and Codex support - Done, uncommitted

**Goal**
Add `install.sh --tool claude|codex|both`, shared workflows, Codex files and a stdlib usage coordinator (`usagectl`), with tests and docs. Do not commit or push. Claude-only behaviour must stay the same.

**Done so far**
- Design: `handoffs/dual-tool-design.md`. Review findings: `handoffs/dual-tool-review.md`, all 7 blockers and the non-blocking list fixed, with regression tests in `tests/test_review_fixes.py`.
- Full suite after independent validation fixes: 256 tests OK, 2 skipped (IANA, no tzdata). Two existing unclosed-file ResourceWarnings remain in test_review_fixes.py.
- Fixed weighted daily allocation (including reset days), session blockers without converting percentages, partial-estimate uncertainty, and wait times across all blocking windows. Added 14 regression tests in tests/test_budget_regressions.py; focused suite: 87 tests OK, 2 skipped.
- Old vs new Claude-only install at the same paths: identical outside backups and the self-test log.
- Both launchers run in a temp install on Windows.

**Decisions and why**
See the 2026-10-31 rows in `DECISIONS.md`.

**Next steps**
1. User reviews the diff, then commits and pushes. Nothing is committed.
2. Not verified: macOS, Linux, Python 3.9, Codex loading the installed skills and rules in a live session.

**Read first**
- `handoffs/dual-tool-design.md`
- `install.sh`
- `coordinator/usagekit/cli.py`
