---
name: crew
description: Plan-build-review workflow for any change bigger than a small edit. The main session plans, Sonnet workers implement, an Opus reviewer checks. Use on /crew, or when a task touches several files.
---

# Crew: plan, build, review

## 1. Plan (you, the main session)
- Understand the task. Use the `scout` subagent for searching; read only what you need.
- Write a plan with numbered steps. Each step: goal, exact files, the change, how to verify it. Keep steps small; mark which steps touch different files and can run in parallel.
- List risks and anything paid, live, or hard to undo.
- **Stop and wait for the user's approval.** Don't start building until they say go.

## 2. Build (`worker` subagents)
- Give each step to a `worker` with everything it needs (it can't see this conversation): files, line ranges, the change, the check.
- At most 2 workers at once, and only for steps touching different files. Otherwise go one at a time.
- If a worker reports a problem, fix the plan rather than pushing on. If the same step fails twice, stop and say "Worth escalating".
- Don't commit until the review passes, unless the user asked otherwise.

## 3. Review (`reviewer` subagent, once)
- Give the `reviewer` the approved plan and the list of changed files.
- Send blocking issues back to a `worker`, then re-run only the affected checks. Don't run a second full review unless the fixes were large.

## 4. Report and wrap up
- Tell the user in under 10 lines: what changed, the review verdict, test results, anything not verified.
- Suggest /handoff and then /clear.
