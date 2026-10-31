# Review findings: dual tool (fix all blocking; each needs a regression test)

## Blocking
1. Cooldown skipped when `--checkpoint` is given without `--workstream` (cli.py:259, routing.py:200, history.py:127). Fix: use `args.workstream or checkpoint`.
2. Preflight only checks settings are JSON objects. `{"hooks":[]}` in user settings or `{"permissions":[]}` in project settings passes, then crashes after files are written (install.sh:122-144, 320, 370); dry-run exits 0. Fix: validate types of `hooks`, its event lists, `permissions` and its deny/allow lists.
3. A file at `handoffs` or `$CODEX_HOME/rules` passes preflight, then mkdir aborts part-way (install.sh:408, 451). Fix: preflight every destination that must be a directory.
4. Reset cycle matched by exact `resets_at`, but `--resets-in` differs each call: over-pace never fires and task deltas become `reset-cycle-changed` (pacing.py:44, history.py:64, cli.py:133). Fix: same cycle if resets are within a tolerance (15 minutes), shared helper, test both.
5. Verify can falsely pass: untracked nested repo hashes as a constant (handoff.py:119-124, 137-149). Fix: hash nested repo HEAD and status, or report it as a mismatch; handle submodules likewise.
6. `strip_credentials` only handles scheme URLs; scp-style `alice@host:team/repo.git` and local paths land verbatim in the checkpoint (handoff.py:38-42). Fix: drop the user part of scp-style URLs; reduce local paths to a basename.
7. Windows piped stdout: non-ASCII text gives UnicodeEncodeError and no resume prompt (cli.py:50, 389). Fix: reconfigure stdout and stderr to UTF-8 in `main`.

## Non-blocking, fix if small
- verify and claim must check the JSON `workstream` matches the file name (cli.py:324-328).
- `--tool both` silently replaces a user's own `~/.claude/skills/checkpoint/` (install.sh:268-271): apply the same foreign-skill skip and marker as Codex, without changing crew/handoff/decide/recap behaviour.
- No way to cancel a task, so an abandoned task marks later ones uncertain (history.py:84-85): add `usagectl task cancel --id ID`.
- Committing a checkpoint always fails verify with `head ahead`: if the only commits since head_commit touch `handoffs/*.checkpoint.md`, treat as a match.
- GUIDE.md:215 should say `<project>-<timestamp>`; GUIDE.md:148 "no account names" should say only the alias is stored.
- Dry-run plan omits stale-file removal (install.sh:380-385) and backup pruning (231-235).
- `min_history_samples: 0` crashes (history.py:113): config validation requires >=1.
- `shared/tool-vars.json` hardcodes `~/.claude-setup/bin/usagectl`: note the CLAUDE_SETUP_HOME exception in the checkpoint skill text. Claude golden files must stay byte-identical.

## Not verified by review
macOS/Linux, Python 3.9, `bin/usagectl.cmd` and sh launcher, real Codex forbidden-command check.
