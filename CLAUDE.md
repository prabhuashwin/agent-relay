# How we work in this repo (usage limits matter)

## Sessions
- One workstream per session. Ongoing work is listed in `handoffs/INDEX.md`; a session usually starts from one of those files.
- When a task is finished or I change topic, remind me to run /handoff, then /clear.
- If you get a "[Context check]" note, follow it.

## Who does what
- This main session is the **planner**. For anything bigger than a small change (more than one file or ~30 lines), use `/crew`: plan, get my approval, hand steps to `worker` subagents (Sonnet), then one `reviewer` pass (Opus).
- Small changes: just do them here, no crew.
- Searching across many files: use the `scout` subagent instead of reading files here.
- Never run more than 2 subagents at once.

## Keep context small
- Read only the parts of files you need. Don't re-read a file you just edited.
- Run tests and builds with output filtered to failures and the summary line. For logs, grep or tail; never print a whole log.
- Long-running jobs (over ~2 minutes): give me the command to run myself instead of waiting on it here, unless I ask you to run it.

## Safety
- `git push` and the AWS CLI are blocked by this repo's permission settings. If a step needs one, give me the exact command to run myself.
- Never make other paid or live calls (paid model APIs, production endpoints) without my explicit OK in this session.
- Don't start loops, monitors, or scheduled wake-ups unless I ask. If one is still running when we finish, tell me.

## Escalation
- If a step has failed twice, or you and the reviewer disagree on something important, stop and say "Worth escalating", with a 5-line summary of the problem and what was tried. I decide whether to take it to a stronger model.

## Replies
- Keep replies short. Don't recap work I can already see.
