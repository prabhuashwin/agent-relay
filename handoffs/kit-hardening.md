# Handoff: Kit hardening - Done and committed; next: decision log

**Goal**
Review the kit, fix what contradicted its own cost/safety goals, and wire Fable in as an on-demand agent. Next workstream: a per-project decision log so decisions can be found without reading every handoff.

**Done so far** (all in commit 36f70c0)
- `claude-files/scripts/bash-guard.sh|.ps1`: user-level PreToolUse hook (matcher Bash). Exit 2 on git pushes (through wrappers: rtk proxy, sh -c, git -C, multi-line), standalone `aws`, gh write commands (pr merge, repo delete, release create/delete, api with POST/PUT/PATCH/DELETE or -f/-F). Command is JSON-unescaped before matching.
- `claude-files/scripts/context-check.sh|.ps1`: at >=150k tokens, exit 2 blocks the prompt (stderr message) unless the prompt starts with `/`; 100k-150k stdout nudge; token count resets at the last `"isCompactSummary":true` line; log trimmed to 500 lines. Same compaction fix in `statusline.*`.
- `install.sh`: self-install guard (skips CLAUDE.md block when target == kit), prefers pwsh, registers the guard hook idempotently, prunes backups to 10 newest, 4 self-tests (context check, post-compact, guard, guard multi-line). Fixtures in `claude-files/test-transcript*.jsonl`.
- `claude-files/project-settings.json`: gh deny entries (plain + rtk).
- `claude-files/agents/oracle.md`: Fable agent (`model: fable`), one question, does not edit. Wired into `skills/crew/SKILL.md` at three optional points (risky plan before approval, "Worth escalating", planner/reviewer disagreement). GUIDE.md "Where Fable fits" rewritten.
- Docs: CLAUDE.md safety/context bullets, GUIDE.md table and daily loop, recap skill uses `git log -n 20`.
- Machine: `~/.claude/settings.json` model fable -> opus; branch master -> main; installer run on the kit itself (`.claude/settings.json` committed).
- Opus review: 2 blocking bugs found (escaped `\n` beat the guard; 150k block never cleared after /compact), both fixed and re-verified.

**Decisions and why**
- Hard block at 150k instead of a nudge: the hook log showed four prompts in a row ignored at 107k-133k.
- Guard is a user-level hook, deny list is the second layer: prefix patterns can't see through wrappers; hooks apply to every project.
- Fable as a subagent (`oracle`) not a session model: fresh small context per question is what makes it cheap; main session stays Opus.
- Both .sh and .ps1 kept for every script (installer copies per platform); pwsh preferred for startup time.

**Open issues / gotchas**
- Guard false positive: any Bash command whose TEXT contains the two words "git push" is blocked, including heredocs that write docs mentioning it. Use the Write tool for such files. Consider tightening to only match at a command position (start, or after `;`, `&&`, `|`, `$(`, backtick, or a quote following `-c`).
- Known guard gaps: `/usr/bin/aws`, `aws.exe`; false positive on `grep -r aws .`.
- Not verified: macOS/Linux path, behaviour under pwsh, whether /compact and /clear fire UserPromptSubmit (harmless: slash prompts always pass).
- `rtk` is a Claude-side wrapper, not on the user's terminal PATH; give the user plain commands.
- Sessions started before 2026-10-31 run the old hooks until restarted.

**Next steps** (decision log; user agreed in principle, plan still needs approval via /crew)
1. Add `DECISIONS.md` convention per project: append-only, one line per decision (date | decision | why | handoff file). Installer creates it if missing.
2. Handoff skill: new step that appends this session's new decisions to DECISIONS.md.
3. New `decide` skill: `/decide <text>` appends a dated line with the current handoff topic.
4. SessionStart hook (matchers startup, resume, clear): print `handoffs/INDEX.md` and the last 10 lines of DECISIONS.md into context; register in install.sh with the existing `drop()` pattern.
5. GUIDE.md: Obsidian as a viewer (open the projects' parent folder or symlink handoffs/ + DECISIONS.md into a vault); Notion only as a one-way mirror, not the source.
6. Optional: tighten the guard regex per the false positive above, and add a self-test for a heredoc containing the words.

**Read first**
- `GUIDE.md`
- `claude-files/skills/handoff/SKILL.md`
- `install.sh` (Part 1 hooks ~L60-110; Part 2 project files ~L130-200)
- `claude-files/scripts/context-check.sh` (hook I/O pattern to copy for the SessionStart hook)
- `claude-files/scripts/bash-guard.sh` (regex to tighten)
