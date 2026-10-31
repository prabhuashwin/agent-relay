# Decisions

Append-only, one line per decision, newest last. Add a row with `/decide <decision> -- <why>`; `/handoff` also adds the session's new decisions. Detail lives in the handoff file named in the last column.

| Date | Decision | Why | Handoff |
|---|---|---|---|
| 2026-10-15 | User-level install over per-project copies | One copy to maintain; every project gets hooks and agents without running the installer | kit-rework.md |
| 2026-10-15 | Post-compact note uses SessionStart matcher `compact`, not PreCompact | PreCompact stdout never reaches Claude's context | kit-rework.md |
| 2026-10-15 | Deny rules include `rtk git push` and `rtk aws` | Global CLAUDE.md prefixes all commands with rtk | kit-rework.md |
| 2026-10-15 | Keep `aws` deny in the generic template | Harmless where unused | kit-rework.md |
| 2026-10-15 | Single bash installer, no install.ps1 | Git Bash runs hooks on Windows anyway; a second installer doubled every change | kit-rework.md |
| 2026-10-31 | Hard block at 150k context instead of a nudge | Hook log showed four prompts in a row ignored at 107k-133k | kit-hardening.md |
| 2026-10-31 | Bash guard is a user-level hook; deny list is the second layer | Prefix patterns can't see through wrappers; hooks apply to every project | kit-hardening.md |
| 2026-10-31 | Fable as the `oracle` subagent, not a session model | Fresh small context per question keeps it cheap; main session stays Opus | kit-hardening.md |
| 2026-10-31 | Keep both .sh and .ps1 for every script; prefer pwsh | Installer copies per platform; pwsh has better startup time | kit-hardening.md |
| 2026-10-31 | Decision log is a markdown table in the repo, Obsidian only a viewer | Git-tracked, grep-able, a few hundred tokens at session start; Notion would need a live call | kit-hardening.md |
| 2026-10-31 | Guard regex left matching 'git push' anywhere in a command | A false positive is cheap, a push slipping through a wrapper is not | kit-hardening.md |
