# How we work in this repo (usage limits matter)

## Sessions
- At the start, read `handoffs/INDEX.md` and the last 10 lines of `DECISIONS.md` (there is no session hook to do it for you). A session usually starts from one handoff file.
- One workstream per session, and one writer per workstream. For parallel work use a separate git worktree and branch.
- Log non-obvious decisions with `$decide <decision> -- <why>`. When a task is finished or the topic changes, run `$handoff`, then start a new session.
- `$recap` gives a verified summary of the session. `$checkpoint` prepares a checkpoint (after `$handoff`, at a meaningful boundary and before usage runs out) so another account or tool can continue.

## Keep output small
- Read only the parts of files you need. Don't re-read a file you just edited.
- Filter test and build output to failures and the summary line. For logs use grep or tail, never print a whole log. If `rtk` is installed, prefix commands with it; if not, plain commands work.
- Long-running jobs (over about 2 minutes): give the user the command to run instead of waiting.

## Safety
- Never run `git push`, the AWS CLI, or gh write commands (pr merge, repo delete, release create or delete). Give the user the exact command to run.
- No paid or live calls (paid model APIs, production endpoints) without the user's explicit OK in this session.
- When resuming work, never discard, stash, commit or overwrite changes you did not make. Check `git status` first.

## Usage and checkpoints
- `usagectl usage fetch --account <codex-alias>` reads the current Codex CLI login's limits. `usagectl config capture-claude --account <claude-alias>` enables terminal status-line capture. Aliases must match the user's actual login; they do not select credentials.
- `usagectl advise --refresh ...` refreshes Codex then runs routing. Claude Fable limits stay manual; unknown or stale readings must not be treated as full. Manual records/imports remain supported.
- `usagectl usage status`, `usagectl pace show` and `usagectl route recommend ...` give guidance, never a provider limit.
- `usagectl handoff prepare|verify|resume|claim` manage `handoffs/<slug>.checkpoint.md`. Run `usagectl --help` for options.

## Escalation
- If a step has failed twice, stop and say "Worth escalating", with a 5-line summary of the problem and what was tried.
