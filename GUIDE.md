# Working with Claude (setup kit)

## Install
Needs Git Bash (Windows) or bash, plus Python 3 on PATH. Give it a project folder (`.` is allowed):
    bash <path-to>/claude-setup/install.sh /path/to/project
    bash <path-to>/claude-setup/install.sh .        # from inside a project
What it does:
- **User level** (shared by all projects, refreshed on every run): agents, skills and hook scripts in `~/.claude/agents/`, `skills/`, `scripts/`; status line and hooks in `~/.claude/settings.json`.
- **Project level**: the CLAUDE.md block, a `permissions` block in `.claude/settings.json`, a `handoffs/` folder, and a `DECISIONS.md` decision log (created only if missing).
- Backups go to `~/.claude/backups/claude-setup/`; the 10 newest are kept. Running the installer on the kit folder itself skips the CLAUDE.md step. Safe to re-run.
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
| `oracle` agent | Fable | Second opinion on a risky plan or diff, or a diagnosis after two failures; does not edit, only with your OK |
| `/crew` | - | Plan -> your approval -> workers -> review -> report |
| `/handoff` | - | Saves the workstream to `handoffs/<topic>.md` + INDEX |
| `/recap` | - | Verified summary of what a session did |
| `/decide` | - | `/decide <decision> -- <why>` appends one row to `DECISIONS.md` |
| Context check | - | User-level hook in `~/.claude/scripts/`; warns at 100k; at 150k blocks prompts (slash commands still work) until /handoff then /clear, or /compact. Log: `~/.claude/scripts/context-check.log`, last 500 lines |
| Bash guard | - | User-level PreToolUse hook: blocks git push, aws, and gh pr merge / repo delete / release, even through wrappers like rtk proxy or sh -c |
| Status line | - | User-level, `~/.claude/scripts/`; context size at the bottom (terminal `claude` only) |
| Permissions | - | Project `.claude/settings.json`: deny `git push`, `aws` and gh pr merge / repo delete / release create+delete (second layer behind the guard); allow common read-only commands. Run pushes yourself in a terminal |
| Session brief | - | SessionStart hook (matchers `startup`, `resume`, `clear`): prints `handoffs/INDEX.md` and the last 10 lines of `DECISIONS.md` into context, a few hundred tokens |
| Post-compact note | - | SessionStart hook (matcher `compact`): after `/compact`, reminds Claude to offer `/handoff` if progress is unsaved |

## Daily loop
1. **Start**: in sessions started after the install, the session brief already shows `handoffs/INDEX.md` and recent decisions, so just start with a workstream's "Resume with" line
   (e.g. `Search indexing: continue from handoffs/search-indexing.md`). New work: just describe it.
2. **Work**: small fix -> ask directly. Anything bigger -> `/crew <task>`, read the plan, say go.
3. **Long jobs** (tests over ~2 min, deploys): run them yourself in a terminal, paste only failures. When something non-obvious is settled mid-session, log it with `/decide`.
4. **Context warning** at 100k -> `/compact` with a focus note; at 150k prompts are blocked, so /handoff then /clear (step 5).
5. **Finish or switch topic**: `/handoff`, then `/clear`. Pushes are blocked, so push from your own terminal if needed.
6. **Weekly**: check the usage panel. Targets: ">150k context" under 30%, "8+ hour sessions" under 20%.

## Changing the kit
Edit files under `claude-files/` (or `CLAUDE.md`), re-run the installer (see Install for which runs are needed), then commit the kit (it is a git repo).

## Where Fable fits
Fable is the escalation tier, not part of the daily loop. Opus handles almost everything here, and the main session should stay on Opus (check `/model`): a long session on Fable pays the top rate on every turn.
The kit wraps Fable in the `oracle` subagent (does not edit, fresh context, one question, at most 40 lines back). Each call is cheap relative to a Fable session because it sees only what it is handed. It runs only when you say so; `/crew` offers it at three points:
- **before approval**, when the plan is paid, hard to undo, or touches security, concurrency or a data migration;
- **"Worth escalating"**, when a step has failed twice (it gets the 5-line summary and the files);
- **after review**, when planner and reviewer disagree on something risky.
You can also ask for it directly: "Ask oracle: read handoffs/<topic>.md and <file:lines>. <question>." Take the answer and keep implementing with Opus.
Never use Fable as a worker, as the routine reviewer, or as the main session's model.

## Decision log and notes
- `DECISIONS.md` (project root) is an append-only table: `| Date | Decision | Why | Handoff |`, one row per decision, newest last. The Handoff column names the file with the detail.
- Rows come from `/decide`, from `/handoff` (it adds the session's new decisions), or from you by hand. Never rewrite history: if a decision is reversed, add a new row saying so.
- It is a repo file, not Notion/Obsidian storage, because it is tracked in git, the scout agent can grep it, and the session brief reads it at start for a few hundred tokens. Notion would need a live call.
- **Obsidian as a viewer**: open the parent folder of your projects as a vault, or make a vault holding symlinks to each project's `handoffs/` folder and `DECISIONS.md`. Search, backlinks and graph view come free; nothing to sync.
- Optional: keep a `kit-conventions.md` in that vault, by hand, for decisions that apply to every project.
- **Notion**: only as a one-way mirror if you want it on your phone; never the source of truth.
- **Guard workaround**: the Bash guard blocks any command whose text contains "git push", including heredocs that write docs. Ask Claude to use the Write tool for those files.

## Optional, later
- **Context Mode** (MCP): keeps big command outputs out of the conversation. Worth a trial given the size of your test and CI logs. Read its README and permissions first.
