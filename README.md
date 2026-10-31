# claude-setup

A small, installable kit that makes [Claude Code](https://claude.com/claude-code) and [Codex](https://developers.openai.com/codex) cheaper and safer to use day to day. It exists because usage limits matter: long sessions, oversized context, and expensive models doing cheap work burn through quota fast. The kit encodes one way of working and installs it into every project with a single script. Use it with Claude Code, Codex, or both subscriptions; the Claude-only install is the default.

## What you get

**A division of labour by model (Claude).** The main session (Opus) plans and decides. Sonnet `worker` subagents implement single steps. An Opus `reviewer` checks the result with fresh eyes. A Haiku `scout` does cross-file searches. Fable is wrapped in an `oracle` subagent that answers one hard question and never runs as the session model.

**Skills that keep sessions short.** Claude uses `/name`, Codex uses `$name`. They come from one shared template, so both tools get the same workflow.

| Command | Claude | Codex | Job |
|---|---|---|---|
| `/crew <task>` | yes | no | Plan, get approval, hand steps to workers, run one review |
| `handoff` | `/handoff` | `$handoff` | Save the workstream to `handoffs/<topic>.md` so a fresh session can continue it |
| `recap` | `/recap` | `$recap` | Verified summary of what the session did |
| `decide <what> -- <why>` | `/decide` | `$decide` | Append one row to the project's `DECISIONS.md` |
| `checkpoint` | `/checkpoint` | `$checkpoint` | Write a machine-checkable handoff so the other tool can take over (only with `--tool codex` or `both`) |

**Hooks that enforce the rules (Claude only).**

- **Context check** warns at 100k tokens and blocks prompts at 150k until you hand off or compact.
- **Bash guard** blocks `git push`, the AWS CLI, and destructive `gh` commands, even through wrappers. You run those yourself in a terminal.
- **Session brief** prints the open workstreams and the last ten decisions into context at session start, for a few hundred tokens.
- **Status line** shows the current context size.

**Rules for Codex.** A rules file (`claude-setup.rules`) forbids the same commands by prefix match. Codex has no installed hooks; the project `AGENTS.md` block tells it to read `handoffs/INDEX.md` and the last ten lines of `DECISIONS.md` at the start.

**A usage coordinator (`usagectl`, Codex and both modes).** Local planning guidance for people with a Claude and a Codex subscription: record what your usage panels say, see pace per account, get a routing recommendation, and hand a workstream from one tool to the other with a git-checked checkpoint. It never calls a provider and never launches a tool.

**Project scaffolding.** A `CLAUDE.md` block (Claude) and an `AGENTS.md` block (Codex) with the working rules, a permissions block in `.claude/settings.json` (Claude), a `handoffs/` folder, and an append-only `DECISIONS.md`. The last two are shared by both tools.

## Quick start

Needs bash (Git Bash on Windows) and Python 3 (3.9 or newer). Codex is optional: without it on PATH, the Codex self-test is skipped, not failed.

```bash
git clone <this-repo> claude-setup
bash claude-setup/install.sh /path/to/your/project                  # Claude only (the original behaviour)
bash claude-setup/install.sh --tool codex /path/to/your/project     # Codex only
bash claude-setup/install.sh --tool both  /path/to/your/project     # both
bash claude-setup/install.sh --tool both --dry-run .                 # print what would happen, change nothing
```

Options may come before or after the folder. `--skip-self-test` skips the post-install checks. A bad `--tool` value or unknown option exits 2 and changes nothing. Everything is validated before anything is written (Python, folder, settings JSON, CLAUDE.md/AGENTS.md markers); a failed check exits 1 and changes nothing.

Then open a new Claude Code or Codex session in that project. The installer is safe to re-run, backs up anything it overwrites to `~/.claude/backups/claude-setup/` (even in Codex mode), and migrates older per-project installs.

| Mode | Goes to `~/` (once, shared) | Goes into each project |
|---|---|---|
| `claude` | `~/.claude/` agents, skills, scripts, hooks, status line | `CLAUDE.md` block, `.claude/settings.json` permissions, `handoffs/`, `DECISIONS.md` |
| `codex` | `~/.agents/skills/` (handoff, decide, recap, checkpoint), `${CODEX_HOME:-~/.codex}/rules/claude-setup.rules`, `~/.claude-setup/` (coordinator and `bin/`) | `AGENTS.md` block, `handoffs/`, `DECISIONS.md` |
| `both` | all of the above | all of the above |

**PATH.** For `usagectl` as a bare command, add `~/.claude-setup/bin` to your PATH. The installer prints the exact path and never edits your shell profile. Without it, run `python <kit>/coordinator/usagectl.py` or the full path to `bin/usagectl` (`bin/usagectl.cmd` on Windows cmd).

**RTK** (a token-saving command wrapper) is optional. The installer prints where it found it, or `RTK: not found; plain commands work, filter output with grep/tail`. Nothing depends on it.

## Using both subscriptions

No windows are preset: plans differ, and some have no 5-hour or weekly limit at all. You describe yours once.

```bash
usagectl init
usagectl account add --account claude-main --provider claude --plan max --capability edit --default-model opus
usagectl account add --account codex-main  --provider codex  --plan plus --capability edit
usagectl window add --account claude-main --id five_hour --kind session --units percent --reserve 10
usagectl window add --account claude-main --id seven_day --kind weekly  --units percent --reserve 10
usagectl window add --account codex-main  --id weekly    --kind weekly  --units percent --reserve 10
```

Each morning, read your panels (Claude `/usage`; Codex `/status` or chatgpt.com/codex/settings/usage) and record them, then ask for the plan:

```bash
usagectl usage record --account claude-main --window five_hour --remaining 80 --resets-in 3h20m
usagectl usage status && usagectl pace show
usagectl route recommend --type refactor --scope medium --risk medium --need edit --workstream search-index
```

`GUIDE.md` has the full workflow: task records, checkpoints and resuming in the other tool, importing snapshots, exit codes, recovery and uninstall.

**Not implemented (deferred):** Codex hooks, automatic reading of Codex usage (no documented interface), Claude status line wiring for usage (the status line does not run in the VS Code extension; only a parser ships), launching one tool from the other, and background polling. Estimates are local planning guidance, not quota enforcement.

## Repo layout

```
install.sh                  the installer (user level + project level), --tool claude|codex|both
GUIDE.md                    full manual: daily loop, dual-account workflow, every installed piece
CLAUDE.md                   working rules for this repo (same block the installer adds to projects)
AGENTS.md                   source of the Codex project block (same role as CLAUDE.md)
DECISIONS.md                this repo's own decision log
handoffs/                   this repo's own workstream notes
claude-files/               Claude pieces the installer copies
  agents/                   worker, reviewer, scout, oracle
  skills/                   crew (handoff, decide, recap are rendered from shared/)
  scripts/                  hook and status line scripts (.sh and .ps1 pairs)
  project-settings.json     permissions block merged into each project's .claude/settings.json
  DECISIONS.md              template for new projects
  test-transcript*.jsonl    fixtures for testing the context-check hook
codex-files/
  rules/claude-setup.rules  Codex forbidden-command rules (prefix rules)
shared/
  skills/*.tmpl.md          handoff, decide, recap, checkpoint templates with {{tokens}}
  tool-vars.json            token values per tool (/handoff vs $handoff and so on)
  render_skills.py          renders the templates for one tool
coordinator/
  usagectl.py               entry point of the usage coordinator
  usagekit/                 config, usage, pacing, routing, history, handoff, selftest
tests/                      unittest suite; tests/golden/ holds fixtures
```

## Changing the kit

Edit under `claude-files/`, `codex-files/`, `shared/`, `coordinator/`, `CLAUDE.md` or `AGENTS.md`, then re-run the installer against any project to refresh the user-level pieces, or against each project to refresh its CLAUDE.md/AGENTS.md block and permissions. Commit the change here. Non-obvious choices are logged in `DECISIONS.md`, with the reasoning in the linked handoff file.

Run the tests from the repo root (they exercise the installer, so allow a few minutes):

```bash
python -m unittest discover -s tests -t .
```

## Read next

`GUIDE.md` covers the daily loop, the dual-account workflow, the full list of installed pieces, recovery and uninstall, and where Fable fits. `DECISIONS.md` explains why things are the way they are.
