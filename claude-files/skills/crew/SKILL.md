---
name: crew
description: Plan-build-review workflow for any change bigger than a small edit. The main session plans, Sonnet workers implement, an Opus reviewer checks. Use on /crew, or when a task touches several files.
---

# Crew: plan, build, review

## 1. Plan (you, the main session)
- Understand the task. Use the `scout` subagent for searching; read only what you need.
- Write a plan with numbered steps. Each step: goal, exact files, the change, how to verify it. Keep steps small; mark which steps touch different files and can run in parallel.
- List risks and anything paid, live, or hard to undo.
- If the plan is risky (paid, hard to undo, security, concurrency, data migration) or you are unsure of the approach, offer a Fable pass: with the user's OK, send the plan and the one open question to the `oracle` subagent and fold its answer into the plan. Don't do this for routine work.
- **Stop and wait for the user's approval.** Don't start building until they say go.

## 2. Build (`worker` subagents)
- Give each step to a `worker` with everything it needs (it can't see this conversation): files, line ranges, the change, the check.
- At most 2 workers at once, and only for steps touching different files. Otherwise go one at a time.
- If a worker reports a problem, fix the plan rather than pushing on. If the same step fails twice, stop and say "Worth escalating", with a 5-line summary; offer to send that summary and the relevant files to the `oracle` subagent (Fable) for a diagnosis.
- Don't commit until the review passes, unless the user asked otherwise.

## 3. Review (`reviewer` subagent, once)
- Give the `reviewer` the approved plan and the list of changed files.
- Send blocking issues back to a `worker`, then re-run only the affected checks. Don't run a second full review unless the fixes were large.
- If the reviewer flags something risky (data loss, security, cost) and you disagree, don't argue it out: offer the user an `oracle` pass with the diff and the one disputed point.

## 4. Report and wrap up
- Tell the user in under 10 lines: what changed, the review verdict, test results, anything not verified.
- Suggest /handoff and then /clear.
