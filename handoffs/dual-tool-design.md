# Dual Claude Code + Codex support: design (binding for all workers)

Repo: C:\GitCode\claude-setup (branch main, clean at start). Nobody commits, pushes, or calls paid/live services.
Python 3 stdlib only (Python 3.12 here, must run on 3.9+). No pytest here: tests use `unittest`, run with
`python -m unittest discover -s tests -t .` from the repo root.
Host is Windows with Git Bash. The Bash guard hook blocks any Bash command whose TEXT contains the words git + push,
or `aws`. Write such content with the Write/Edit tools, never through a Bash heredoc or sed.

## Verified facts (official docs, 2026-10-31; codex-cli 0.134.0)
- Codex instructions: `~/.codex/AGENTS.md` (or CODEX_HOME), project AGENTS.md walking root to cwd, 32 KiB default cap.
- Codex user skills: `$HOME/.agents/skills/<name>/SKILL.md`, frontmatter `name` + `description`, invoked as `$name`.
- Codex rules: `~/.codex/rules/*.rules`, Starlark `prefix_rule(pattern=[...], decision="forbidden", justification="...",
  match=[...], not_match=[...])`; union at one position is a nested list. Test:
  `codex execpolicy check --rules <file> -- <cmd...>`, prints JSON with the strictest decision. Prefix rules only.
- Codex hooks exist but need per-hook trust review and are "a guardrail, not enforcement": DEFERRED, not installed.
- Codex usage: only `/status` and chatgpt.com/codex/settings/usage. No documented programmatic interface. Manual only.
- Claude status line stdin has `rate_limits.five_hour|seven_day.{used_percentage (0-100), resets_at (epoch seconds)}`,
  subscribers only, windows may be absent. Status line does not run in the VS Code extension, so wiring is deferred;
  only a parser for this documented shape ships.
- Not every plan has a 5-hour or weekly window. Some plans have model-specific weekly limits. Usage is shared with other
  surfaces (claude.ai; ChatGPT), so consumption attribution is never certain.

## Layout
shared/skills/{handoff,decide,recap,checkpoint}.tmpl.md   body+frontmatter with {{tokens}}
shared/tool-vars.json                                     token values per tool
shared/render_skills.py                                   renders templates for a tool into an out dir
claude-files/skills/crew/                                 stays; handoff/decide/recap SKILL.md removed (now rendered)
codex-files/rules/claude-setup.rules                      forbidden rules
AGENTS.md (root)                                          source of the Codex project block (like root CLAUDE.md)
coordinator/usagectl.py, coordinator/usagekit/*.py        the coordinator
tests/                                                    unittest suite; tests/golden/ fixtures
install.sh                                                single bash installer

## Installer (`install.sh [--tool claude|codex|both] [--dry-run] [--skip-self-test] <project-folder>`)
- Options in any order relative to the folder. No --tool means claude. `install.sh <folder>` must behave as today for Claude.
- No args, -h, --help: usage, exit 1 as today. Bad --tool value or unknown option: exit 2, nothing changed.
- Order: parse, preflight, (dry-run: print plan, exit 0), backup, install, self-test, exit.
- Preflight validates EVERYTHING before any write, exit nonzero and change nothing on failure:
  Python 3, target folder, user+project settings.json valid JSON objects (only when tool includes claude), CLAUDE.md
  markers (claude) and AGENTS.md markers (codex), source files exist. Today damaged markers just print a note; now fail.
- Dry-run must not create, modify or delete anything (no backup dirs, no mkdir, no log writes). Prints each action
  as `would ...`. Preflight failures still exit nonzero in dry-run.
- claude mode: everything install.sh does now. Output files must be identical to before, except new lines of stdout.
- codex mode: skips ~/.claude and .claude/ and CLAUDE.md entirely. Writes rendered skills to `$HOME/.agents/skills/<name>/`
  with a `.claude-setup` marker file in each dir; a pre-existing skill dir WITHOUT the marker is foreign: skip it, keep it,
  print a warning, never overwrite. Rules to `${CODEX_HOME:-$HOME/.codex}/rules/claude-setup.rules` (own file; never touch
  default.rules or config.toml). AGENTS.md block in project with the same marker logic as CLAUDE.md
  (`<!-- claude-setup:start -->`...end), source root AGENTS.md; created with `# Project notes` header if absent; warn if
  file exceeds 32768 bytes. On the kit itself (SELF=1) leave AGENTS.md unchanged.
- both: both of the above.
- All modes: `handoffs/` and `DECISIONS.md` (if missing; never overwritten).
- codex/both also: coordinator copied to `${CLAUDE_SETUP_HOME:-$HOME/.claude-setup}/coordinator/` (no __pycache__), plus
  `bin/usagectl` (sh shim) and `bin/usagectl.cmd`; the `checkpoint` skill is installed for each tool in the mode.
  Never touches `config.json` or `state/` there. Prints a PATH hint; never edits shell profiles. claude mode installs no
  coordinator and no checkpoint skill.
- Backups: `~/.claude/backups/claude-setup/` as today, plus: before overwriting, copy existing user-level agents, skills,
  scripts (not logs), Codex rules, our Codex skills, coordinator code into the user backup dir; project AGENTS.md into the
  project backup dir. Keep two backup dirs per run; keep "10 newest" pruning.
- Self-tests: existing ones keep their printed text, but every FAILED and INVALID now increments a counter and the installer
  exits 1 at the end. Add codex: `codex execpolicy check` says git-push forbidden and `git status` not forbidden when
  codex is on PATH (else print `skipped: codex not on PATH`, not a failure); rendered skills have frontmatter; coordinator:
  `usagectl selftest` in a temp state dir. --skip-self-test skips them (tests use it for speed).
- RTK: detect via `command -v rtk` then `$HOME/.headroom/bin/rtk`; print found path or
  `RTK: not found; plain commands work, filter output with grep/tail`. Never fails.
- Windows: paths passed to native Python go through existing `winpath`. Written text uses LF.
- Rendering: `{{token}}` via shared/tool-vars.json. Rendered Claude handoff/decide/recap MUST be byte-identical to
  today's claude-files/skills/*/SKILL.md (snapshot to tests/golden/claude/ BEFORE removing them). Unknown token: render fails.
  Codex: `$handoff`, `$decide`, no `/clear`, no Bash guard/Edit tool notes. The DECISIONS.md header text quoted inside
  decide stays literal for both (it is a shared repo file).
- checkpoint.tmpl.md: gather facts, run `~/.claude-setup/bin/usagectl handoff prepare ...`, report resume prompt. Runs after
  the handoff skill at a meaningful boundary and before exhaustion.
- Root AGENTS.md: short. Sessions (read handoffs/INDEX.md + last 10 lines of DECISIONS.md at start since no session hook),
  one writer per workstream, worktrees for parallel work, keep output small (RTK fallback: plain commands + grep/tail),
  safety (no push, aws, gh writes, paid calls), never discard/stash/commit/overwrite user changes when resuming, `$handoff`
  `$decide` `$recap` `$checkpoint`, `usagectl` commands. No Claude-only concepts (crew, Task agents, hooks).
- .gitignore: add `__pycache__/`, `*.pyc`, `.claude-setup/`.

## Coordinator paths and files
Home: CLAUDE_SETUP_HOME, else `$HOME/.claude-setup` (use env HOME before expanduser). `config.json`, `state/usage.jsonl`,
`state/tasks.jsonl`. Atomic config writes (tmp + os.replace), JSONL appends with LF. If home is inside a git work tree and not
ignored (`git check-ignore`), refuse to write: exit 2. Git missing: skip check. Clock: env USAGECTL_NOW (ISO UTC) overrides now
for tests. Exit codes: 0 ok, 2 invalid input/config, 3 git mismatch or owner conflict, 4 no suitable account. All data commands
accept `--json`. Errors go to stderr, one clear line, never a traceback.

## Config (config.json, version 1)
{"version":1,"timezone":"local"|IANA|"+05:30","stale_after_minutes":{"session":60,"weekly":720,"other":720},
 "workday_weights":{"mon":1,"tue":1,"wed":1,"thu":1,"fri":1,"sat":0,"sun":0},"preferred_provider":null,
 "spending_policy":{"paid_api_fallback":false,"credit_purchases":false,"paid_resets":false},
 "routing":{"switch_overhead_with_checkpoint":0.15,"switch_overhead_without_checkpoint":0.5,"switch_margin":0.25,
            "switch_cooldown_hours":4,"min_history_samples":3},
 "accounts":{"<alias>":{"provider":"claude|codex","plan":"max","capabilities":[...],"default_model":null,"models":{},
   "windows":[{"id":"five_hour","kind":"session|weekly|other","scope":"shared|model:<name>","units":"percent|messages|credits|<word>",
               "reserve":10}]}}}
Alias regex ^[a-z0-9][a-z0-9_-]{0,31}$; aliases only, never e-mails. Unknown keys rejected at every level. No preset windows:
never assume a plan has hourly/daily/weekly limits. An account may have zero windows. zoneinfo may lack data on Windows:
if an IANA name fails, exit 2 saying use a fixed offset, "local", or `pip install tzdata`. IANA tests skip when tzdata is absent.

## Commands (`usagectl <noun> <verb>` style, consistent)
usagectl init [--force-not-allowed]            write default config; refuses to overwrite (exit 2)
usagectl account add --account A --provider P --plan X [--capability C]... [--default-model M]
usagectl window add --account A --id W --kind K --units U --reserve N [--scope shared|model:M]
usagectl config show | config validate
usagectl usage record --account A --window W --remaining N [--units U] (--resets-at TS | --resets-in 3h20m | --no-reset)
                      [--observed-at TS] [--source manual] [--confidence high|medium|low]
usagectl usage import FILE|- [--format snapshot|claude-statusline] [--account A]
usagectl usage status [--json]
usagectl pace show [--deadline DATE] [--json]
usagectl route recommend --type T --scope small|medium|large --risk low|medium|high [--need C]... [--priority low|normal|high]
                      [--owner A] [--checkpoint SLUG] [--workstream SLUG] [--model M] [--estimate A:W=N]... [--deadline DATE] [--json]
usagectl task start --id ID --type T --scope S --account A [--workstream SLUG]
usagectl task finish --id ID --result verified|partial|failed [--sole-use] [--note TEXT]
usagectl handoff prepare|verify|resume|claim ...   (see Handoffs)
usagectl selftest   usagectl --version

## Usage semantics
Observation: account, window, remaining, units, resets_at(UTC|null), observed_at(UTC), source, confidence.
Reject: unknown account/window, units mismatch, negative, percent>100, bool, NaN/Infinity (use parse_constant), unknown fields,
observed_at more than 5 min in the future, resets_at <= observed_at. Import is all-or-nothing. Snapshot file:
{"schema":1,"observations":[...]}. Naive timestamps are read in the configured timezone; stored always as `...Z`; shown in it.
claude-statusline format maps used_percentage to remaining=100-used, resets_at from epoch, source=claude-statusline, confidence high;
only windows configured with the ids five_hour / seven_day; absent windows ignored; none usable: exit 2.

Window state at `now`, latest observation by observed_at:
- unknown: none.
- exhausted: remaining<=0 and (resets_at future, or no reset and not stale).
- stale: resets_at passed (reason `reset-passed`: NEVER treat as full allowance, ask for a fresh observation), or age >
  stale_after_minutes[kind] (reason `old`).
- available: otherwise. Plus usable=max(0,remaining-reserve), below_reserve=usable==0.
Account state for a set of windows: exhausted > unknown > stale > available; zero windows = unknown.
Applicable windows: scope shared, plus model:<m> when m is the task --model or else default_model.

## Pacing (per window of kind weekly; local guidance only, never provider limit)
W = sum over local dates d from today up to the reset date of weight(d); reset date's weight is multiplied by the fraction of that
local day before the reset; today counts at full weight. Today == reset date uses the fraction measured from midnight too.
daily_target=(remaining-reserve)/W clamped at >=0. Use baseline: earliest observation today in the same reset cycle (same resets_at)
if any, so the target does not shrink as work proceeds: daily_target=(baseline-reserve)/W, used_today=baseline-latest,
room_today=daily_target-used_today. W==0: target null, message `no planned workdays before reset`.
Stale/unknown/exhausted: no target, state printed. No reset timestamp: no target, say so.
Deadline DATE: W counts each date through min(deadline, reset) at max(weight,1); labelled `deadline override`. Reserves and
provider windows are still honoured. Output shows session windows beside weekly: `today_limit`=min(room_today, session usable)
only when units match; otherwise both printed, never converted. Never compare percentages across accounts.

## History and estimates
task start logs the latest observation of each window. task finish computes per-window delta=start.remaining-end.remaining when
end observation is newer than start, same reset cycle, delta>=0; else delta null with a reason. attribution=`clean` only when
--sole-use and no other task overlapped on that account and no delta anomaly; otherwise `uncertain`.
Estimate for (account, type, scope, window): median of samples of same account+type+scope with non-null delta and non-failed... include
partial/failed since they consumed usage. >=min_history_samples clean: confidence medium. Else >=min with uncertain included: low.
Else none: insufficient. --estimate overrides: confidence `user`. Tokens/API prices are never used.

## Routing (deterministic; no static task-type→provider map; `type` only keys history)
Per account: incompatible(need not in capabilities) / exhausted / refresh(unknown|stale) / below_reserve / too_large(estimate*(1+overhead)
> usable; overhead applies only when account != owner and owner set; with/without checkpoint value) / over_pace (soft; estimate>room_today,
or room_today<0 with no estimate; ignored under --deadline). priority low: over_pace is hard (`wait`).
suitable = none of the hard ones.
Selection:
1. owner suitable: stay (action continue), unless rebalance: estimate known, owner over_pace, (estimate-room)/target>=switch_margin, a valid
   checkpoint given, other suitable account not over_pace, priority!=high, and no owner change in the workstream within cooldown (from
   tasks.jsonl events). Small usage changes therefore never flip the owner.
2. owner needs refresh: action refresh for that account, do not switch.
3. owner not suitable, or none: rank suitable by (not over_pace, is preferred, verified-rate if >=min samples, room_today/daily_target own-account
   ratio, alias). action `switch` if owner set else `start`. Switching without checkpoint: next step says prepare a checkpoint first.
4. none suitable: action precedence refresh (list accounts), reduce-scope (some too_large with usable>0), wait (earliest reset among exhausted/
   below_reserve; or next planned workday), blocked (all incompatible, naming the capability). Exit 4. If spending_policy allows paid fallback,
   mention it as an option for the user; never act on it. Default: state that paid fallback is disabled.
Insufficient history with no --estimate: keep the recommendation, confidence low, `uncertainty` text, next_step recommends a smaller step and a task
record. high risk adds that review is needed. Explanation: short lines, one per decisive factor, listing rejected accounts and why.
Output keys: recommended, action, confidence, reasons[], uncertainty, next_step, accounts{alias:{suitable,flags,estimates}}.

## Handoffs (checkpoint)
File `handoffs/<slug>.checkpoint.md`: rendered markdown sections plus one fenced ```json block that is the only machine source. Fields:
schema, workstream, owner, goal, acceptance[], repo{name, remote(credentials stripped)}, branch, base_commit, head_commit, changed_files[]
(base..HEAD), uncommitted{paths[], diff_sha256}, done[], remaining[], verification[{command,result,status}], failures[], decisions[],
next_action, prepared_at. Written next to the shared handoffs/. No account identifiers or usage data in it.
Git facts come from read-only git commands only; exclude `handoffs/*.checkpoint.md` from uncommitted and hash. diff hash covers `git diff HEAD` plus
the bytes of untracked files. Slug regex ^[a-z0-9][a-z0-9-]{0,63}$.
- handoff prepare --workstream S --owner A --goal G --next N [--accept X]... [--done X]... [--remaining X]... [--verify 'CMD=>RESULT=>pass|fail']...
  [--failure X]... [--decision X]... [--base REF] [--take-over] : existing checkpoint with a different owner: exit 3 unless --take-over. Prints path.
- handoff verify --workstream S: compares repo, branch, head (ahead/behind/diverged via merge-base), uncommitted set and hash. Exit 0 or 3 with one line
  per mismatch. Read-only.
- handoff resume --workstream S --to A: verify, then print the resume prompt for that account's provider. Mismatch: exit 3, no prompt unless --show-anyway.
  Prompt holds: goal, checkpoint path, branch/commit, next action, verify first, never discard, stash, commit or overwrite user changes.
- handoff claim --workstream S --to A: verify must pass, sets owner, appends an owner-change event to tasks.jsonl. --force not offered.
No command ever runs git add/commit/stash/checkout/reset/clean. One writer: owner field. Different branch or missing work on mismatch: message suggests a
separate worktree for parallel tasks.
