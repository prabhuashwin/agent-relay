# Automatic usage implementation plan

Goal: supported Codex rate-limit reads and opt-in Claude status-line capture feed existing recommendations.
Architecture: a bounded stdio RPC client reads Codex limits without model turns; provider parsers validate complete observations before append. Claude scripts feed an opt-in capture command that stores only usage observations. Fable remains manual.
Tech: Python standard library, existing Bash/PowerShell status lines and installer.

- [x] Add failing CLI, schema, capture and RPC lifecycle tests using fake processes/accounts.
- [x] Implement collectors.py with handshake, timeouts, sanitized errors and process cleanup; map quota durations to configured shared windows without guessing model limits.
- [x] Add usage fetch, usage capture-claude, config capture-claude and advise --refresh. Fetch failure must abort advice, preserve history and never launch a model turn.
- [x] Wire existing status scripts to capture when configured; preserve status output and make disabled/missing coordinator a no-op.
- [x] Update docs, preserve existing README walkthrough, and run focused plus full tests.
- [x] Try read-only Codex fetch with the user's existing authentication. No credentials in logs, no purchases/resets, no background monitor. Report live Claude capture as unverified unless observed.

Verification: full suite passed (272 tests, 2 skips for unavailable timezone data; existing unclosed-file warnings). Two additional tests plus the final shared-scope safeguard passed in the focused collector/usage suite (66 tests). Internal selftest passed 19 checks; git diff --check passed.

Local runtime and PowerShell status-line script installed with private backups; opt-in capture enabled. Live Codex refresh and recommendation succeeded, and display preserved IST. Actual Claude emission has not been observed; both scripts were exercised with isolated test payloads. Fable stays manual. No background job, commit or push created.

Sources: https://developers.openai.com/codex/app-server and https://code.claude.com/docs/en/statusline. Codex aliases label the current CLI login; they do not switch authentication. Refresh rejects missing configured shared windows instead of silently keeping a misleading partial snapshot.
