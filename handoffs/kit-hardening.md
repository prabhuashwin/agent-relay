# Handoff: Kit hardening + decision log - Done (commits 36f70c0, bc7373d); no next workstream planned

**Goal**
Harden the kit against its own cost/safety goals, wire Fable in as an on-demand agent, then add a per-project decision log so decisions can be found without reading every handoff.

**Done so far**
- Hardening (36f70c0): `claude-files/scripts/bash-guard.sh|.ps1` (PreToolUse guard: pushes, aws, gh writes), `context-check.*` hard block at 150k with compaction reset, `install.sh` self-install guard + 4 self-tests, `claude-files/agents/oracle.md` (Fable, one question) wired into `skills/crew/SKILL.md`.
- Decision log (bc7373d):
  - `DECISIONS.md` convention: append-only table `| Date | Decision | Why | Handoff |` at project root. Template `claude-files/DECISIONS.md`; installer copies it if missing. Kit's own file seeded with 11 rows.
  - `claude-files/skills/decide/SKILL.md`: `/decide <decision> -- <why>` appends a row.
  - `claude-files/skills/handoff/SKILL.md` step 3: /handoff appends the session's new decisions.
  - `claude-files/scripts/session-brief.sh|.ps1`: SessionStart hook (matcher `startup|resume|clear`) prints `handoffs/INDEX.md` (40 lines) and last 10 lines of `DECISIONS.md`. Registered in `install.sh` (BRIEF_CMD, `drop(ss, "session-brief")`), self-test expects the `[Session brief] Open workstreams` heading.
  - `CLAUDE.md` Sessions bullet; `GUIDE.md` table rows, daily loop, new "Decision log and notes" section (Obsidian viewer, Notion mirror only, guard workaround).
- Installer re-run on the kit and on this machine; all 7 self-tests OK. Opus review: no blockers; 4 nits fixed before commit.

**Decisions and why**
- Hard block at 150k instead of a nudge: hook log showed four prompts in a row ignored at 107k-133k.
- Guard is a user-level hook, deny list is the second layer: prefix patterns can't see through wrappers.
- Fable as the `oracle` subagent, not a session model: fresh small context per question keeps it cheap.
- Both .sh and .ps1 kept for every script; pwsh preferred for startup time.
- Decision log is a markdown table in the repo, Obsidian only a viewer: git-tracked, grep-able by scout, a few hundred tokens at session start; Notion would need a live call every session.
- Guard regex left matching the push command anywhere in a command text: a false positive is cheap (use the Write tool), a push slipping through a wrapper is not.

**Open issues / gotchas**
- Guard false positive: any Bash command whose TEXT contains the two words for pushing is blocked, including heredocs/sed that write docs mentioning it. Use the Write or Edit tool for such files. Documented in GUIDE.md.
- Known guard gaps: `/usr/bin/aws`, `aws.exe`; false positive on `grep -r aws .`.
- `session-brief.sh` uses the shared `field()` helper, so it needs compact JSON (no space after the colon); Claude Code sends compact JSON today. The .ps1 parses properly.
- Not verified: macOS/Linux path, pwsh (not installed here; tested with powershell 5.1), whether SessionStart stdout is injected on `resume` and `clear` (startup confirmed by the self-test).
- `rtk` is not on the terminal PATH in Bash tool calls here; use plain git commands.
- Sessions started before the install still run old hooks; the session brief appears from the next new session.
- `.claude/settings.json` is written with CRLF by Python on Windows; git normalizes it (harmless warning on commit).

**Next steps** (none required; candidates if wanted)
1. Watch the first few sessions: is the session brief worth its tokens, and does /handoff actually append rows? Adjust the 40/10 line caps if INDEX.md grows.
2. Optional `kit-conventions.md` in an Obsidian vault for decisions that apply to every project (hand-kept, see GUIDE.md).
3. Optional: make `field()` in the .sh hooks tolerate `"key": "value"` spacing.

**Read first**
- `GUIDE.md` ("Decision log and notes" section)
- `DECISIONS.md`
- `install.sh` (Part 1 hooks ~L63-120; Part 3 self-tests ~L225-265)
- `claude-files/scripts/session-brief.sh`
- `claude-files/skills/decide/SKILL.md`
