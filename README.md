# claude-setup

A small, installable kit that makes [Claude Code](https://claude.com/claude-code) cheaper and safer to use day to day. It exists because usage limits matter: long sessions, oversized context, and expensive models doing cheap work burn through quota fast. The kit encodes one way of working and installs it into every project with a single script.

## What you get

**A division of labour by model.** The main session (Opus) plans and decides. Sonnet `worker` subagents implement single steps. An Opus `reviewer` checks the result with fresh eyes. A Haiku `scout` does cross-file searches. Fable is wrapped in an `oracle` subagent that answers one hard question and never runs as the session model.

**Slash commands that keep sessions short.**

| Command | Job |
|---|---|
| `/crew <task>` | Plan, get approval, hand steps to workers, run one review |
| `/handoff` | Save the workstream to `handoffs/<topic>.md` so a fresh session can continue it |
| `/recap` | Verified summary of what the session did |
| `/decide <what> -- <why>` | Append one row to the project's `DECISIONS.md` |

**Hooks that enforce the rules.**

- **Context check** warns at 100k tokens and blocks prompts at 150k until you hand off or compact.
- **Bash guard** blocks `git push`, the AWS CLI, and destructive `gh` commands, even through wrappers. You run those yourself in a terminal.
- **Session brief** prints the open workstreams and the last ten decisions into context at session start, for a few hundred tokens.
- **Status line** shows the current context size.

**Project scaffolding.** A `CLAUDE.md` block with the working rules, a permissions block in `.claude/settings.json`, a `handoffs/` folder, and an append-only `DECISIONS.md`.

## Quick start

Needs bash (Git Bash on Windows) and Python 3.

```bash
git clone <this-repo> claude-setup
bash claude-setup/install.sh /path/to/your/project   # or . from inside the project
```

Then open a new Claude Code session in that project. The installer is safe to re-run, backs up anything it overwrites to `~/.claude/backups/claude-setup/`, and migrates older per-project installs.

Agents, skills, scripts and hooks go to `~/.claude/` once and are shared by all projects. The CLAUDE.md block, permissions, `handoffs/` and `DECISIONS.md` go into each project you run it on.

## Repo layout

```
install.sh                  the installer (user level + project level)
GUIDE.md                    full manual: daily loop, every installed piece, when to use Fable
CLAUDE.md                   working rules for this repo (same block the installer adds to projects)
DECISIONS.md                this repo's own decision log
handoffs/                   this repo's own workstream notes
claude-files/               everything the installer copies
  agents/                   worker, reviewer, scout, oracle
  skills/                   crew, handoff, recap, decide
  scripts/                  hook and status line scripts (.sh and .ps1 pairs)
  project-settings.json     permissions block merged into each project's .claude/settings.json
  DECISIONS.md              template for new projects
  test-transcript*.jsonl    fixtures for testing the context-check hook
```

## Changing the kit

Edit under `claude-files/` or `CLAUDE.md`, then re-run the installer against any project to refresh the user-level pieces, or against each project to refresh its CLAUDE.md and permissions. Commit the change here. Non-obvious choices are logged in `DECISIONS.md`, with the reasoning in the linked handoff file.

## Read next

`GUIDE.md` covers the daily loop, the full list of installed pieces, and where Fable fits. `DECISIONS.md` explains why things are the way they are.
