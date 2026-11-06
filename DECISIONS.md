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
| 2026-10-31 | Shared skills render from templates per tool; Claude output stays byte-identical | One workflow source for both tools, with golden tests guarding the Claude-only install | dual-tool.md |
| 2026-10-31 | Codex hooks deferred; Codex rules are the only installed guardrail | Per-hook trust review would add setup friction; rules can be checked with execpolicy | dual-tool.md |
| 2026-10-31 | Usage is recorded by hand; Claude status line import ships as a parser only | Codex has no documented usage interface, and the status line does not run in the VS Code extension | dual-tool.md |
| 2026-10-31 | Coordinator state lives in ~/.claude-setup, outside repos | Keeps usage data and account aliases out of Git | dual-tool.md |
| 2026-10-31 | Same reset cycle means resets within 15 minutes | Relative --resets-in values differ each call, so exact matching broke pacing and task deltas | dual-tool.md |
| 2026-10-31 | Damaged markers, malformed settings and failed self-tests now fail the install | Intentional stricter behaviour: failing before any write beats a partial install | dual-tool.md |
| 2026-10-31 | Supersede manual-only usage: bounded Codex app-server reads and opt-in Claude terminal capture | Supported quota fields feed existing recommendations without model turns; separate Fable allowance and native IDE capture remain manual | automatic-usage-plan.md |
| 2026-11-06 | Keep checkpoint goals/owners in Markdown; store board release tickets and executed checks outside Git | Reuse existing workflows without making tracking updates invalidate repository fingerprints | continuity-dashboard.md |
| 2026-11-06 | Require explicit source release and shared checkpoint-writer locks for board transfers | Prevent stale tickets and cooperating CLI/dashboard writers from overwriting each other's state | continuity-dashboard.md |
| 2026-11-06 | Separate executed verification from reported checks; mark repository changes stale | A matching checkpoint or agent claim alone is not evidence that tests passed | continuity-dashboard.md |
| 2026-11-06 | Use neutral light surfaces and progressive disclosure for the dashboard | User requested a simpler modern UI; keep critical status visible while reducing text density | continuity-dashboard.md |
| 2026-11-06 | Separate explicit Codex quota fetches from five-second local observation polling | Show fresh data where supported without implying Claude has an on-demand quota endpoint | continuity-dashboard.md |
| 2026-11-06 | Add opt-in account polling: Codex 60s, experimental Claude 180s, bounded reads and backoff | User needs mobile consumption reflected without local model activity; undocumented Claude source remains clearly labeled | continuity-dashboard.md |
| 2026-11-06 | Use current-user Windows login startup with bounded recovery and owned process-tree cleanup | Keep Relay available without an admin service; disable must stop only its own processes | continuity-dashboard.md |
| 2026-11-06 | Reuse local seven-day observations with hourly extrema and fresh dashboard reserve alerts | Avoid extra provider reads; preserve reset boundaries and suppress stale or failed-sync warnings | continuity-dashboard.md |
