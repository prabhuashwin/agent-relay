# Handoff: Kit rework - Done; kit is generic, user-level, committed locally

**Goal**
Review the claude-setup kit and fix everything found: wrong default install target after the folder move, prose-only safety rules, stale paths, no version control, per-project drift.

**Done so far**
- `install.sh` rewritten: target folder required, Python 3 required, no jq fallback, legacy upgrade code removed. Backups to `~/.claude/backups/claude-setup/`. Commit d64f5fa.
- Agents, skills and hook scripts now install once at user level (`~/.claude/agents`, `skills`, `scripts`); status line, context-check hook and a SessionStart(compact) reminder hook merged into `~/.claude/settings.json`. Per project: CLAUDE.md marker block, `permissions` deny/allow from `claude-files/project-settings.json`, `handoffs/`.
- Deleted `install.ps1`, stale `claude-files/settings.json`, in-kit `backups/` (moved to `~/.claude/backups/claude-setup/Code-20261014-152712`).
- `.gitignore`, `.gitattributes` (LF pinned; global autocrlf would break the bash scripts). Commit 79d29e6.
- All Auxi/OpenKB/Bedrock/machine-path references removed from GUIDE.md, CLAUDE.md, agents, skills. Commit 8fba2e4.
- Installer run against `C:\GitCode\Auxi\Code` (migrated from old per-project layout; old copies removed). Idempotent on re-run. Opus reviewer verdict: Ship.
- User settings: default `model` changed from `fable` to `opus`.

**Decisions and why**
- User-level install over per-project copies: one copy to maintain, every project gets hooks and agents without running the installer.
- SessionStart matcher `compact` instead of PreCompact for the post-compaction note: PreCompact stdout never reaches Claude's context.
- Deny rules include `rtk git push` and `rtk aws` because the global CLAUDE.md prefixes all commands with rtk.
- `aws` deny kept in the generic template: harmless where unused.
- Single bash installer; Git Bash runs hooks on Windows anyway, and install.ps1 doubled every change.

**Open issues / gotchas**
- Kit has no git remote; three local commits only. Push needs the user's OK.
- Sessions opened before 2026-10-15 still run the old project-level hooks until restarted.
- Reviewer non-blocking leftover: a CRLF CLAUDE.md is rewritten as LF by the installer (cosmetic). Backups in `~/.claude/backups/claude-setup/` are never pruned.
- `python3` on this machine is a Windows Store stub; the installer's probe skips it and uses `python`.

**Next steps**
1. Nothing required. Optional: add a remote and push the kit.
2. After a few weeks of use, run /fewer-permission-prompts in a project to tune its allow list.
3. Optional later: SessionStart hook printing the head of `handoffs/INDEX.md` on session open.

**Read first**
- `GUIDE.md`
- `install.sh` (Part 1 user-level ~L45-106, Part 2 project-level ~L108-175)
- `claude-files/project-settings.json`
- `CLAUDE.md` (block source installed into projects)
