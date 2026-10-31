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

**A usage coordinator (`usagectl`, Codex and both modes).** Fetch Codex usage, capture Claude terminal status-line limits, or record your panels manually. See pace per account, get a routing recommendation, and hand a workstream to the other tool with a git-checked checkpoint. Fetching starts a temporary Codex app-server for a read-only quota request; it never starts a model task.

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

Each morning, read your panels (Claude `/usage`; Codex `/status` or chatgpt.com/codex/settings/usage) and record **every configured window**, then ask for the plan. These values are illustrative; replace the remaining percentages and reset times with your own:

```bash
usagectl usage record --account claude-main --window five_hour --remaining 80 --resets-in 3h20m
usagectl usage record --account claude-main --window seven_day --remaining 60 --resets-in 4d
usagectl usage record --account codex-main --window weekly --remaining 70 --resets-in 3d
usagectl usage status && usagectl pace show
usagectl route recommend --type refactor --scope medium --risk medium --need edit --workstream search-index
```

`GUIDE.md` has the full workflow: task records, checkpoints and resuming in the other tool, importing snapshots, exit codes, recovery and uninstall.

### Automatic usage

Install or update with `--tool both` for the coordinator and Claude status scripts, then enable capture for your configured account:

```bash
usagectl config capture-claude --account claude-main
usagectl usage fetch --account codex-main
usagectl advise --refresh --codex-account codex-main --type feature --scope small --risk medium --need edit
```

Codex reads the account currently signed into its CLI; aliases are labels, not logins. Claude captures shared session and weekly limits when its terminal status line receives them after a response. `advise --refresh` fetches Codex before evaluating both accounts using the existing engine. It does not force a Claude response. Missing or stale Claude data still needs refreshing.

Observations go to local `state/usage.jsonl`; an editable manual `usage.json` snapshot is not rewritten. Your configured timezone controls displayed timestamps. Claude's separate **Fable allowance stays manual**. Disable capture with `usagectl config capture-claude --disable`.

**Deferred:** Codex hooks, Claude IDE usage capture, automatic Fable readings, launching model tasks in the other tool, and background polling. Estimates remain planning guidance, not quota enforcement. See [collector details](GUIDE.md#automatic-usage-collection).

## Example: continue a Claude task in Codex

You're adding search to an app. Claude has drafted the indexer, but its session allowance is nearing your reserve. You want Codex to finish the tests without repeating the investigation.

This walkthrough assumes you installed `--tool both`, added `usagectl` to PATH, and completed the account/window setup above. Run terminal commands from your app's Git repository. The sample accounts have two Claude windows and one Codex window; configure and record any additional windows your own plans show. Account aliases are local labels, not logins.

**1. Save the current work in Claude before allowance runs out.** Send these messages in Claude Code, one at a time:

```text
/handoff
```

```text
/checkpoint
```

Tell Claude to use `search-index` as the workstream and `claude-main` as the owner. Ask it to include the actual files changed, decisions, verification results, and next action. For this example, the next action is to finish and run the indexer's tests. Don't label tests as passed unless they ran successfully.

This saves a readable handoff and `handoffs/search-index.checkpoint.md`, which records the Git state. Stop editing this workstream in Claude after the checkpoint.

**2. Refresh both accounts' usage in your terminal.** Here Claude has 8% session allowance remaining, below the configured 10% reserve. Codex still has capacity. Replace all example values with fresh readings:

```bash
usagectl usage record --account claude-main --window five_hour --remaining 8 --resets-in 2h
usagectl usage record --account claude-main --window seven_day --remaining 60 --resets-in 4d
usagectl usage record --account codex-main --window weekly --remaining 70 --resets-in 3d
usagectl usage status
usagectl pace show
```

When updating a window, use its actual remaining reset time; repeatedly entering `4d` would move the recorded reset. Usage observations stay in your local coordinator state, outside the project.

**3. Ask where to continue.**

```bash
usagectl route recommend --type feature --scope small --risk medium --need edit --owner claude-main --workstream search-index --checkpoint search-index
```

With these fresh observations and a matching checkpoint, the recommendation is to **switch to `codex-main`** because Claude is below reserve. With no task history or estimates, confidence is low: start with a small step. This recommends a tool; it does not launch it or transfer your conversation.

**4. Generate the resume prompt and paste it into Codex.** Open Codex in the same project directory, then use this terminal command to obtain the prompt:

```bash
usagectl handoff resume --workstream search-index --to codex-main
```

The generated prompt tells Codex what to read and requires these checks before editing:

```bash
usagectl handoff verify --workstream search-index
usagectl handoff claim --workstream search-index --to codex-main
```

If verification reports a mismatch, reconcile the changed Git state before continuing. Keep one tool writing this workstream at a time. The checkpoint describes uncommitted work; it does not copy files to another machine or worktree.

**5. Finish a bounded step and save again.** Ask Codex to finish the indexer tests, run them, and report the results. At the next boundary, use `$handoff` followed by `$checkpoint`. You can later follow the same process in reverse with `--to claude-main`.

You now have shared decisions, a concrete next action, and a checked code state when changing tools. See [the daily workflow](GUIDE.md#two-accounts-daily-workflow) to record task outcomes and build usage-estimation history.

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
