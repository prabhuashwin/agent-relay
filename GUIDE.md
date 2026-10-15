# Working with Claude (setup kit)

## Install
Needs Git Bash (Windows) or bash, plus Python 3 on PATH. Give it a project folder (`.` is allowed):
    bash <path-to>/claude-setup/install.sh /path/to/project
    bash <path-to>/claude-setup/install.sh .        # from inside a project
What it does:
- **User level** (shared by all projects, refreshed on every run): agents, skills and hook scripts in `~/.claude/agents/`, `skills/`, `scripts/`; status line and hooks in `~/.claude/settings.json`.
- **Project level**: the CLAUDE.md block, a `permissions` block in `.claude/settings.json`, and a `handoffs/` folder.
- Backups go to `~/.claude/backups/claude-setup/`. Safe to re-run.
- Old per-project installs are migrated automatically (the old copies are removed).
After changing agents/skills/scripts: run it once against any project. After changing CLAUDE.md or `project-settings.json`: run it on each project.
Then start a NEW session in that folder (old sessions don't pick up changes).

## New project checklist
1. Run the installer with the project folder.
2. In the first session (Sonnet is fine), ask: "Fill in the Project notes section of CLAUDE.md:
   how to build and run tests (with output filtered to failures), the folder layout,
   and anything off-limits. Keep it under 25 lines."
3. Work as usual; /handoff creates handoffs/ entries as you go.

## What's installed
| Piece | Model | Job |
|---|---|---|
| Main session | Opus (pick it in the app) | Planner: understands, plans, decides |
| `worker` agent | Sonnet | Implements one plan step and verifies it |
| `reviewer` agent | Opus | Fresh-eyes review at the end; never edits |
| `scout` agent | Haiku | Finds things across many files |
| `/crew` | - | Plan -> your approval -> workers -> review -> report |
| `/handoff` | - | Saves the workstream to `handoffs/<topic>.md` + INDEX |
| `/recap` | - | Verified summary of what a session did |
| Context check | - | User-level hook in `~/.claude/scripts/`; warns in Claude's reply at 100k and 150k tokens. Log: `~/.claude/scripts/context-check.log` (confirms the hook fires) |
| Status line | - | User-level, `~/.claude/scripts/`; context size at the bottom (terminal `claude` only) |
| Permissions | - | Project `.claude/settings.json`: deny `git push` and `aws`; allow common read-only commands. Run pushes yourself in a terminal |
| Post-compact note | - | SessionStart hook (matcher `compact`): after `/compact`, reminds Claude to offer `/handoff` if progress is unsaved |

## Daily loop
1. **Start**: open `handoffs/INDEX.md`, pick a workstream, start a new session with its "Resume with" line
   (e.g. `Search indexing: continue from handoffs/search-indexing.md`). New work: just describe it.
2. **Work**: small fix -> ask directly. Anything bigger -> `/crew <task>`, read the plan, say go.
3. **Long jobs** (tests over ~2 min, deploys): run them yourself in a terminal, paste only failures.
4. **Context warning** at 100k -> `/compact` with a focus note; at 150k -> step 5.
5. **Finish or switch topic**: `/handoff`, then `/clear`. Pushes are blocked, so push from your own terminal if needed.
6. **Weekly**: check the usage panel. Targets: ">150k context" under 30%, "8+ hour sessions" under 20%.

## Changing the kit
Edit files under `claude-files/` (or `CLAUDE.md`), re-run the installer (see Install for which runs are needed), then commit the kit (it is a git repo).

## Where Fable fits
Fable is the escalation tier, not part of the daily loop. Opus handles almost everything here.
Use it only when:
- Claude says **"Worth escalating"** (a step failed twice, or planner and reviewer disagree), or
- a plan is **expensive or hard to undo** (paid eval run, data migration, production deploy) and you want a second opinion first, or
- a bug has resisted two honest attempts (race conditions, flaky concurrency).

How to use it cheaply:
1. Run `/handoff` in the current session.
2. Start a fresh session, switch the model to Fable.
3. Ask one focused question: "Read handoffs/<topic>.md and <file:lines>. <specific question>."
4. Take the answer back to an Opus session to implement. Don't keep working in Fable.

A fresh, small session spends a fraction of what the same question costs inside a 150k-token session.
Never use Fable as a worker, a reviewer of routine changes, or the default model.

## Optional, later
- **Context Mode** (MCP): keeps big command outputs out of the conversation. Worth a trial given the size of your test and CI logs. Read its README and permissions first.
