# Working with Claude Code and Codex (setup kit)

## Install
Needs Git Bash (Windows) or bash, plus Python 3.9+ on PATH. Codex is optional (needed only to run its self-test). Give it a project folder (`.` is allowed):
    bash <path-to>/claude-setup/install.sh /path/to/project                 # Claude only, as before
    bash <path-to>/claude-setup/install.sh --tool codex /path/to/project    # Codex only
    bash <path-to>/claude-setup/install.sh --tool both .                    # both, from inside a project
    bash <path-to>/claude-setup/install.sh --tool both --dry-run .          # plan only, nothing written
Options (`--tool claude|codex|both`, `--dry-run`, `--skip-self-test`) go before or after the folder. Bad `--tool` or an unknown option: exit 2, nothing changed. Order of events: parse, preflight (validates Python, folder, settings JSON, CLAUDE.md/AGENTS.md markers, source files; any failure exits 1 and writes nothing), dry-run stops here, backup, install, self-tests. Any failed self-test makes the installer exit 1. `--skip-self-test` skips them.

What each mode does:
- **claude, user level** (shared by all projects, refreshed on every run): agents, skills and hook scripts in `~/.claude/agents/`, `skills/`, `scripts/`; status line and hooks in `~/.claude/settings.json`.
- **claude, project level**: the CLAUDE.md block, a `permissions` block in `.claude/settings.json`.
- **codex, user level**: skills `handoff`, `decide`, `recap`, `checkpoint` in `~/.agents/skills/<name>/` (each with a `.claude-setup` marker file; a skill folder without the marker is yours, so it is skipped with a warning and never overwritten); rules in `${CODEX_HOME:-~/.codex}/rules/claude-setup.rules` (its own file; `default.rules` and `config.toml` are never touched). No hooks are installed for Codex.
- **codex, project level**: an `AGENTS.md` block between `<!-- claude-setup:start -->` and `<!-- claude-setup:end -->` (file created with a `# Project notes` header if missing; a warning if the file passes 32 KiB, Codex's default cap).
- **codex and both**: the coordinator is copied to `${CLAUDE_SETUP_HOME:-~/.claude-setup}/coordinator/` with launchers `bin/usagectl` and `bin/usagectl.cmd`. `config.json` and `state/` there are never touched. `both` also installs the `checkpoint` skill for Claude (an existing `~/.claude/skills/checkpoint/` without a `.claude-setup` marker is yours and is skipped with a warning).
- **all modes**: a `handoffs/` folder and a `DECISIONS.md` decision log (created only if missing, never overwritten).
- Backups go to `~/.claude/backups/claude-setup/` (also in Codex mode): one `user-*` and one `proj-*` folder per run, the 10 newest kept. Existing agents, skills, scripts, Codex rules, our Codex skills, coordinator code and the project's AGENTS.md are copied there before being overwritten. Running the installer on the kit folder itself leaves its CLAUDE.md and AGENTS.md unchanged. Safe to re-run.
- Old per-project installs are migrated automatically (the old copies are removed).
- **PATH**: the installer prints `usagectl: add <home>/.claude-setup/bin to your PATH` and does not edit your shell profile. Add it yourself, or call the launcher by full path.
- **RTK** (token-saving command wrapper): found via `command -v rtk`, then `~/.headroom/bin/rtk`. The installer prints the path or `RTK: not found; plain commands work, filter output with grep/tail`. It never fails the install; without RTK, run plain commands and filter with `grep`/`tail`.
After changing agents/skills/scripts/rules/coordinator: run the installer once against any project. After changing CLAUDE.md, AGENTS.md or `project-settings.json`: run it on each project.
Then start a NEW session in that folder (old sessions don't pick up changes).

Preview (`--dry-run` prints each action as `would ...` and changes nothing, not even backup folders):
    Preflight (tool: both)...
    Preflight: OK
    would install skill handoff to ~/.agents/skills/handoff
    would write rules to ~/.codex/rules/claude-setup.rules (default.rules and config.toml untouched)
    would add or refresh the claude-setup block in <project>/AGENTS.md (your own notes kept)
    Dry run complete: nothing was changed.

## New project checklist
1. Run the installer with the project folder.
2. In the first session (Sonnet is fine), ask: "Fill in the Project notes section of CLAUDE.md:
   how to build and run tests (with output filtered to failures), the folder layout,
   and anything off-limits. Keep it under 25 lines."
3. Work as usual; /handoff creates handoffs/ entries as you go.
Codex: same, but ask it to fill in the Project notes section of AGENTS.md, and use `$handoff` etc. Codex has no session hook, so its AGENTS.md block tells it to read `handoffs/INDEX.md` and the last 10 lines of `DECISIONS.md` first.

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

## Shared and provider-specific
| Capability | Claude Code | Codex |
|---|---|---|
| Handoff, decide, recap, checkpoint skills | `/handoff` ... (user-level `~/.claude/skills/`) | `$handoff` ... (`~/.agents/skills/`), same template |
| `handoffs/` and `DECISIONS.md` | one shared copy in the project | same files |
| Project instructions | `CLAUDE.md` block | `AGENTS.md` block |
| Forbidden commands | Bash guard hook + `permissions` deny | `claude-setup.rules` (prefix rules only) |
| Context check, session brief, status line | hooks | none; no hooks installed |
| Subagents (`worker`, `reviewer`, `scout`, `oracle`) and `/crew` | yes | no |
| Model assignment | agent frontmatter in `claude-files/agents/` | Codex's own config (`~/.codex/config.toml`) |
| Usage coordinator (`usagectl`) | shared; one config and state under `~/.claude-setup/` | |

Model assignments are not shared: change Claude's in the agent files, Codex's in its own config. The kit never edits `config.toml`.

## Two accounts: first-run setup
`usagectl` needs a Python 3.9+ launcher; install with `--tool codex` or `both` first. State lives in `~/.claude-setup/` (or `CLAUDE_SETUP_HOME`). If that folder is inside a git work tree and not ignored, `usagectl` refuses to write (exit 2) so usage data cannot be committed.

**No windows are preset.** Plans differ: some have a 5-hour window, some a weekly one, some model-specific weekly limits, some none. Add only what your own panels show. Aliases are lower-case (`claude-main`), never e-mail addresses.

    $ usagectl init
    created ~/.claude-setup/config.json
    $ usagectl account add --account claude-main --provider claude --plan max --capability edit --capability review --default-model opus
    added account claude-main (claude, max)
    $ usagectl account add --account codex-main --provider codex --plan plus --capability edit
    $ usagectl window add --account claude-main --id five_hour --kind session --units percent --reserve 10
    added window five_hour (session, percent) to claude-main
    $ usagectl window add --account claude-main --id seven_day --kind weekly --units percent --reserve 10
    $ usagectl window add --account codex-main --id weekly --kind weekly --units percent --reserve 10
    $ usagectl config validate
    config ok

`--reserve` is the amount you want to keep untouched (here 10%). `--kind` is `session`, `weekly` or `other`; `--scope model:<name>` makes a window apply only to that model. `init` never overwrites an existing config (exit 2); `config show` prints it. Edit `config.json` by hand for `timezone` (`local`, `+05:30`, or an IANA name; on Windows an IANA name may need `pip install tzdata`), `workday_weights` (weekend 0 by default), `preferred_provider` and `stale_after_minutes`. Unknown keys are rejected.

## Two accounts: daily workflow
1. **Morning snapshot.** Read Claude `/usage` and Codex `/status` (or chatgpt.com/codex/settings/usage). Record each window:

       $ usagectl usage record --account claude-main --window five_hour --remaining 80 --resets-in 3h20m
       recorded claude-main/five_hour: 80 percent remaining, resets 2026-10-31 14:30+05:30
       $ usagectl usage record --account claude-main --window seven_day --remaining 60 --resets-at 2026-11-04T09:00
       $ usagectl usage record --account codex-main --window weekly --remaining 70 --no-reset --confidence low --source chatgpt-panel

   Exactly one of `--resets-at`, `--resets-in`, `--no-reset` is required. Times without a zone are read in the configured timezone and stored as UTC.
2. **Status and pace.**

       $ usagectl usage status
       claude-main (claude, max): available
         seven_day [weekly, shared]: available
           remaining 60 percent, usable 50, reserve 10, resets 2026-11-04 09:00+05:30, observed 2026-10-31 11:10+05:30
       $ usagectl pace show
       claude-main:
         seven_day: daily target 21.0526 percent over 2.375 weighted days; used today 0; room today 21.0526
           session five_hour: available, usable 70 percent
           today limit: 21.0526 percent

   Pace spreads the weekly remainder over your planned workdays before the reset. `--deadline 2026-11-02` counts every day through that date and labels the result `deadline override`. Percentages are never compared across accounts.
3. **Route.** Ask where the next task should run:

       $ usagectl route recommend --type refactor --scope medium --risk medium --need edit --workstream search-index
       recommended: claude-main   action: start   confidence: low
       uncertainty: no usage estimate for this task type and scope (not enough history, none given with --estimate)
       next: Take a smaller step first, and record it with usagectl task start / task finish to build history.

   Useful flags: `--owner A` (the account already on this workstream, so it stays unless unsuitable), `--estimate claude-main:seven_day=30`, `--checkpoint SLUG`, `--priority`, `--model`, `--deadline`, `--json`. `--type` only keys your history; there is no fixed task-to-provider map.
4. **Record the task** so estimates improve (record a fresh observation with the same reset time before finishing):

       $ usagectl task start --id t2 --type refactor --scope medium --account claude-main --workstream search-index
       started task t2 on claude-main (2 window snapshot(s))
       $ usagectl usage record --account claude-main --window seven_day --remaining 44 --resets-at 2026-11-04T09:00
       $ usagectl task finish --id t2 --result verified --sole-use --note "indexer done"
       finished task t2: verified; attribution clean
       usage deltas: five_hour=n/a (no-newer-observation), seven_day=6

   Add `--sole-use` only if nothing else used that account meanwhile; otherwise attribution is `uncertain`. A different reset cycle (reset times more than 15 minutes apart) between start and finish gives `n/a (reset-cycle-changed)`. Drop an abandoned task with `usagectl task cancel --id ID` so it does not mark later tasks uncertain. Estimates need `min_history_samples` (3, at least 1) clean samples for medium confidence.
5. **Checkpoint at a boundary, before exhaustion.** Run `/handoff` (or `$handoff`), then `/checkpoint` (`$checkpoint`), which runs:

       $ usagectl handoff prepare --workstream search-index --owner claude-main --goal "Add search indexer" --next "Write tests for indexer.py" --done "indexer.py drafted" --remaining tests --verify "python -m unittest=>not run=>fail" --decision "use inverted index"
       checkpoint written: <project>/handoffs/search-index.checkpoint.md
       uncommitted paths: 5; head: 970412e6...

   It writes `handoffs/<slug>.checkpoint.md` (readable sections plus one JSON block that is the only machine source: branch, commits, changed files, a hash of uncommitted changes). It holds no usage data and no account names beyond the owner alias. It runs read-only git commands and never adds, commits, stashes or resets. Commit your own work first if you want it in the checkpoint's changed-file list.
6. **Resume in the other tool.** Once the owner's windows are low, routing says `switch`, and its `next:` line names this command:

       $ usagectl handoff resume --workstream search-index --to codex-main
       You are resuming workstream 'search-index' as account 'codex-main' (codex).
       Goal: Add search indexer
       ...
       Verify first: run `usagectl handoff verify --workstream search-index`; it must report a match before you edit anything.

   Paste the printed prompt into the other tool. There, verify, then claim:

       $ usagectl handoff verify --workstream search-index
       ok: repository matches checkpoint search-index
       $ usagectl handoff claim --workstream search-index --to codex-main
       codex-main now owns search-index

   `claim` sets the owner and logs an owner change; there is no `--force`. One writer per workstream: use a separate git worktree for parallel work. `handoff prepare` by a different account exits 3 unless `--take-over`.

### Manual snapshot import
A snapshot file records several windows at once (all-or-nothing: one bad entry imports nothing):

    {"schema":1,"observations":[
      {"account":"codex-main","window":"weekly","remaining":70,"units":"percent","resets_at":"2026-11-05T09:00","source":"manual","confidence":"medium"},
      {"account":"codex-main","window":"five_hour","remaining":90,"units":"percent","resets_at":"2026-10-31T16:00"}]}

    $ usagectl usage import snap.json          # or "-" to read stdin
    imported 2 observation(s): codex-main/weekly, codex-main/five_hour

For the Claude status line JSON (fields `rate_limits.five_hour` and `rate_limits.seven_day`, each with `used_percentage` and `resets_at` as epoch seconds; subscribers only, either window may be absent):

    $ usagectl usage import - --format claude-statusline --account claude-main < statusline.json
    imported 2 observation(s): claude-main/five_hour, claude-main/seven_day

It converts used to remaining (100 minus used) and only fills windows you configured with the ids `five_hour` and `seven_day`. If none match, it exits 2.

## Automation: done and deferred
| Implemented | Deferred |
|---|---|
| Claude hooks (context check, Bash guard, session brief) | Codex hooks (they need per-hook trust review and are a guardrail, not enforcement) |
| Codex rules file, `$skills`, AGENTS.md block | Automatic reading of Codex usage (no documented interface; manual only) |
| Manual usage records and snapshot import, Claude status line JSON parser | Wiring the Claude status line into usage (it does not run in the VS Code extension) |
| Pace, routing, task history, checkpoints, resume/claim | Launching one tool from the other |
| | Background polling |

## Limits to keep in mind
- Everything `usagectl` prints is local planning guidance. It does not enforce, predict or guarantee a provider quota.
- Usage is shared with other surfaces (claude.ai, ChatGPT), so what a task consumed is never certain; `attribution: uncertain` is common.
- Codex rules are prefix matches: `git push` is forbidden, `git -C dir push` or a command inside a wrapper (`sh -c`) may not be seen. Treat them as a guardrail; the Claude Bash guard looks through wrappers.
- Percentages are not comparable across accounts: 20% of one plan is not 20% of another.
- Daily targets distribute the available weekly budget by each day's configured weight. A zero-weight day gets zero; the reset day's fractional weight applies to both the total and that day's share.
- `today_limit` is weekly pacing guidance, not a conversion of session capacity. Session and weekly percentages have different denominators and are shown separately. Exhausted or reserved session capacity blocks work; unknown or stale session usage requires a refresh.
- Routing needs estimates for every applicable window before reporting medium confidence. Partial estimates keep confidence low and recommend a smaller step.
- Wait advice uses the latest blocking reset per account, then the earliest eligible account. A blocker without a reset prevents predicting that account's recovery. Refresh usage at the suggested time; a reset does not guarantee that the task will fit.
- A window whose reset time has passed is `stale (reset-passed)`, never treated as full. Record a fresh observation.
- Observations older than `stale_after_minutes` (session 60, weekly 720) are stale too.
- Paid fallback is off by default (`spending_policy`). When nothing is suitable, routing says so and exits 4; it never buys anything.

## usagectl exit codes
| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | invalid input or config, unknown account/window/task, refused to write |
| 3 | git mismatch on handoff verify/resume/claim, or checkpoint owned by another account |
| 4 | no suitable account (`route recommend`) |

Errors are one line on stderr, never a traceback. Every data command accepts `--json`. `usagectl selftest` runs 19 internal checks in a temp folder. Set `USAGECTL_NOW=2026-11-06T00:00:00Z` to test with a fixed clock.

## Recovery
- **Git mismatch on resume** (exit 3): the message lists each difference (`branch differs`, `uncommitted modified: same files but different content than the checkpoint`, ahead/behind/diverged). Switch to the checkpoint's branch yourself or use a separate worktree, then re-run `verify`. Use `handoff resume --show-anyway` only to read the prompt. Nothing here discards, stashes or commits your changes; the new session must ask you before touching them. If the work genuinely moved on, have the current owner write a new checkpoint.
- **Malformed `config.json`**: `usagectl` exits 2 with `config is not valid JSON: ...` and the position. Fix the file, or move it aside and run `init` again (then re-add accounts). Check with `config validate`.
- **Malformed state**: unreadable lines in `state/usage.jsonl` are skipped with a warning (`warning: 1 unreadable line(s) in usage.jsonl were ignored`). Delete the bad line, or the file to start over. Observations lost that way make windows `unknown` until you record again.
- **Installer-overwritten files**: copy from `~/.claude/backups/claude-setup/user-<timestamp>/` or `<project>-<timestamp>/` back to where they came from.
- **Settings JSON invalid**: the installer stops before writing (exit 1) and names the file.

## Uninstall and rollback
Nothing here is automatic; delete by hand. Always safe to keep: `handoffs/`, `DECISIONS.md`, and your own notes in `CLAUDE.md`/`AGENTS.md`. To roll back the last install instead, restore from the newest `~/.claude/backups/claude-setup/` folders.
- **Claude** (`--tool claude`): delete the `claude-setup:start` to `claude-setup:end` block from each project's `CLAUDE.md`; remove the `permissions` entries you do not want from `.claude/settings.json`; remove our `statusLine` and `hooks` entries from `~/.claude/settings.json` (the ones pointing at `~/.claude/scripts/`); delete `~/.claude/agents/{worker,reviewer,scout,oracle}.md`, `~/.claude/skills/{crew,handoff,decide,recap}` and the scripts `bash-guard`, `context-check`, `session-brief`, `statusline` (`.sh`/`.ps1`, plus `context-check.log`) in `~/.claude/scripts/`. Other projects share these, so only do it when no project needs them.
- **Codex** (`--tool codex`): delete the block between the `claude-setup:start` and `claude-setup:end` markers from each project's `AGENTS.md`; delete each folder in `~/.agents/skills/` that contains a `.claude-setup` marker file (`handoff`, `decide`, `recap`, `checkpoint`; leave folders without the marker, they are yours); delete `${CODEX_HOME:-~/.codex}/rules/claude-setup.rules` (leave `default.rules` and `config.toml`); delete `~/.claude-setup/coordinator/` and `~/.claude-setup/bin/`. Keep `~/.claude-setup/config.json` and `state/` if you want your usage history; delete the whole `~/.claude-setup/` to remove it.
- **Both**: do both lists. Also remove `~/.claude/skills/checkpoint`.
- Remove the PATH entry you added for `~/.claude-setup/bin`.

## Tests
From the repo root (the installer tests make this take a few minutes):

    python -m unittest discover -s tests -t .

## Changing the kit
Edit files under `claude-files/`, `codex-files/`, `shared/`, `coordinator/` (or `CLAUDE.md`, `AGENTS.md`), re-run the installer (see Install for which runs are needed), then commit the kit (it is a git repo). Skill text lives in `shared/skills/*.tmpl.md` and is rendered per tool; do not edit rendered copies.

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
