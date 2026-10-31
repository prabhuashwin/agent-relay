---
name: recap
description: Complete, verified recap of what this session did. Use on /recap, "what have we done", "summarize this session", or before reviewing someone's work.
---

# Recap

Check claims against the repo, not memory alone: run `git log --oneline -n 20` (or since the date the user gives you), `git status` and `git diff --stat` in each repo this session touched.

Report:
1. **Goal**: what was asked, and whether it changed along the way
2. **Done**: each change with file paths and commit ids
3. **Not done or partly done**, and why
4. **Decisions** and the reason for each
5. **Paid, live or irreversible actions** taken (cloud resources, paid APIs, pushes, deletes); say "none" if none
6. **Risks**: failing tests, open questions, anything you're unsure about
7. **Next step**: one concrete action

Mark anything you couldn't verify as **unverified**. Keep it under 40 lines.
Finish by asking whether to save it with /handoff.
