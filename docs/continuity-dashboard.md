# Local continuity dashboard

V1 runs on Python's standard library, with no Node dependencies, model calls,
automatic task launching, or hosted service. Codex account polling is opt-in;
Claude supports opt-in experimental account polling or response-driven terminal capture.

## Start

Run from the repository you want to track:

```text
usagectl board serve --port 8765
```

For account-wide Codex updates, including usage on other devices, run
`python coordinator/usagectl.py board serve --port 8766 --codex-account codex-main`
from this checkout. The alias must match the signed-in CLI account. The server fetches
immediately and every 60 seconds, even with the browser closed. Failures back off up
to 15 minutes and retain the last successful observation. The card shows sync status;
failed polling hides the current percentage until a successful read. Manual refresh
can retry immediately. This is near-real-time polling, not a provider push feed.
The computer must remain awake and the server running. The loopback UI is not
accessible from a phone.

To enable both providers, run:

```text
python coordinator/usagectl.py board serve --port 8766 --codex-account codex-main --experimental-claude-account claude-main
```

Claude polls its undocumented account quota endpoint every 180 seconds, independently
of local model activity, with a manual refresh button. It reads the existing local
Claude Code `.credentials.json` under `CLAUDE_CONFIG_DIR` or `~/.claude` (Windows/Linux).
Aliases must match the logged-in accounts; they do not select credentials. Tokens are
never copied into Relay storage, logs, browser responses, or command arguments.
Redirects are rejected. Requests have a 25-second total deadline; failures preserve
history, display unavailable status, and back off to at most 15 minutes. Expired login
requires signing in through Claude Code again; Relay does not refresh or rewrite tokens.
All configured windows must be present and valid before any observation is saved.
Fable is matched to its model-scoped quota, not its share of the overall weekly budget.
This experimental endpoint can change or disappear. The terminal capture fallback
alone does not independently refresh mobile usage.

Use the printed `http://127.0.0.1:8765` URL, not a network address or hostname alias.
Ctrl+C stops the server. **Reload workspace** reads local files and current Git state.
**Refresh usage** on each Codex card performs a bounded quota read through the signed-in
Codex CLI. The alias must match that login; clicking a different alias does not switch
credentials. Fetches have a 20-second collector timeout (cleanup may take longer),
only one runs per server at once, and failures retain previous observations.

While the page is visible, it reads local usage every five seconds. This picks up
Claude terminal captures and CLI/manual imports, without calling either provider.
Polling stops in hidden tabs. Each window shows reading age, freshness and source.
Source and exact timestamps are under Observation details. Local polling never
rewrites observation timestamps. A polling failure is shown above the account cards.
When observations change, routing is marked outdated until you reload the workspace;
successful explicit Codex refresh also reloads routing. Account updates preserve
workstream selection, transfer inputs and copied resume prompts.

Claude capture is opt-in. When disabled, its card shows the exact enable command:

```text
usagectl config capture-claude --account YOUR_CLAUDE_ALIAS
```

The installed Claude terminal status line must receive quota data after a response.
Enabling capture alone does not generate a reading. The dashboard cannot force Claude
to respond, fetch Claude on demand, or capture native IDE usage. Separate model
allowances remain manual where unsupported. Stale/unknown readings stay marked as such.

The board scans `handoffs/*.checkpoint.md`. It does not invent tasks from prose.
Use the existing checkpoint skill, or:

```text
usagectl handoff prepare --workstream my-task --owner YOUR_ACCOUNT --goal "Ship the change" --next "Run integration checks" --accept "The integration scenario passes"
usagectl board status --type feature --scope small --risk medium --json
```

Routing uses existing capability, reserve, freshness, history and switching-overhead
rules. The task/scope/risk selectors are explicit inputs, not inferred facts. Account
aliases do not select credentials. A transfer changes ownership metadata; it does
not prove quota availability or start a destination session.

## Verification

```text
usagectl board check --workstream my-task --timeout 60 -- python -m unittest discover -q
```

The command executes locally without a shell, under the project's current directory
and environment. Supply an executable plus arguments; shell pipelines are not
interpreted. Only run commands you trust. HTTP deliberately has no command-execution
endpoint. Timeout is 1–120 seconds; the default is 60. The process timeout does not
guarantee termination of independently detached child processes.

The stored record includes exit status, start/end repository fingerprints, timestamps,
and at most the last 8 KiB of output. This local output may contain sensitive test
details. Only the latest check per workstream is displayed. No checks means `not-run`.
If inputs change during execution, a zero exit code is not labelled passed. Any later
repository fingerprint change makes evidence stale, conservatively including unrelated
unignored edits. Ignored files, environment variables, dependencies outside the repo,
external services, and transient changes restored before the end are not fingerprinted.
Checkpoint files themselves are excluded by the existing fingerprint logic.

Manually supplied checkpoint verification is separate, labelled reported. Neither
a passing command nor matching checkpoint automatically accepts the whole task.

Resume prompts from both `handoff resume` and `board claim` include the recorded
task context and latest local executed-check status. An unavailable evidence read
is labelled `unavailable`, not passed; this does not undo a completed claim. Command
arguments and timestamps are included, but captured output is not copied into the
prompt. Status describes prompt-generation time; verify again before editing.
Long context lists show the first twelve items and point back to the checkpoint.

## Ownership transfers

1. Stop the source agent's edits and prepare a matching checkpoint.
2. Release explicitly, attesting the source writer stopped:

```text
usagectl board release --workstream my-task --owner SOURCE_ACCOUNT --source-stopped --json
```

3. Copy the returned ticket, then claim and obtain the resume prompt:

```text
usagectl board claim --workstream my-task --to DESTINATION_ACCOUNT --ticket RETURNED_TICKET --json
```

The destination must be configured with `edit` capability. The same source account
can reclaim released work if you decide not to switch. Tickets are single-use and
bound to the exact checkpoint. Repository changes, checkpoint edits, and re-preparing
invalidate the release. Refresh the checkpoint and release again to recover.

Conflict messages retain their failure exit code and include recovery guidance.
See [handoff recovery](handoff-recovery.md) for matching the correct worktree,
preserving edits, refreshing context, rerunning checks and replacing old tickets.

CLI prepare/claim and board release/claim share an OS file lock for their short
checkpoint operations. After a workstream first uses board release, ownership changes
must use board claim; legacy claim and prepare `--take-over` cannot bypass it. This
does not lock editors, manually edited checkpoint files, or older installed versions.
Use one current installation and one writer per workstream. A source-stopped checkbox
is an attestation, not process detection.

The Markdown owner is authoritative. If a process crashes between its Markdown and
SQLite writes, inspect that owner and refresh/release before proceeding; these files
are not a distributed transaction. If routing-history logging fails after a successful
claim, the response includes a warning and resume prompt; ownership has changed, but
cooldown history may be unavailable. Do not retry a consumed ticket.

## Storage and boundaries

Checkpoints stay in the project. Release tickets and verification records live in
`~/.claude-setup/state/continuity.sqlite3` (or `CLAUDE_SETUP_HOME`), keyed by canonical
worktree path. Moving a checkout starts a separate local history. The lock file lives
in that worktree's Git metadata directory and contains no task information.

The default HTTP server binds only to IPv4 loopback, checks Host/Origin, requires a
per-server token for mutations, and serves only three fixed static assets. Do not
expose that server directly through a proxy. Optional personal remote profiles use
an authenticated Waitress gateway behind Caddy HTTPS instead. See
[remote access](remote-access.md) for Wi-Fi, private-network and public-domain modes,
pairing, session revocation and setup. This remains a personal tool, not a multi-user
service.

## Windows automatic startup (V2 first increment)

From this checkout, enable hidden startup at your Windows login:

```text
python coordinator/usagectl.py board startup enable --port 8766 --codex-account codex-main --experimental-claude-account claude-main
python coordinator/usagectl.py board startup status
python coordinator/usagectl.py board startup disable
```

Enable starts Relay immediately and creates a current-user Startup shortcut. Stop a
manually launched server on the same port first. Disable removes the shortcut and
waits for the owned supervisor to stop. It does not stop unrelated servers.
The supervisor uses a Windows Job Object to clean up its dashboard and collector
processes, prevents duplicates per state home, and retries crashes after 5, 10, 20,
40 and 60 seconds. Six consecutive short-lived failures stop recovery; inspect the
port, source checkout and Python path, then disable/enable. Five minutes of stable
running resets the crash counter. Startup status reports the last supervisor event,
not a guarantee of provider connectivity.

Configuration and status are stored in `~/.claude-setup/state/relay-startup*`; paths
and aliases are saved, never login tokens. Keep this checkout and Python installed
at the same locations, or reinstall startup after moving them. Windows login and an
awake computer are required; this is not a system service or a hosted dashboard.

Account errors show last successful sync, failed attempts, next retry and recovery
instructions. Claude sign-in/rate-limit/connection failures are distinguished;
ambiguous Codex failures suggest checking both CLI sign-in and compatibility.
Manual failures update the same health state. Authentication stays in each provider's CLI.

## Seven-day history and reserve alerts

Expand **Usage history · 7 days** under any account limit to see saved readings
over the last seven days, with an exact timestamp/value table. History reuses local
observations; opening it never calls a provider. Each hour retains its first, lowest,
highest and last reading. Values show remaining quota, not total consumption.
No observations means an explicit empty state; missing periods are not filled in.

Lines stop at reset-cycle changes and gaps over two hours. Reset timestamps within
15 minutes are treated as one cycle. A changed/unknown reset or an increase with no
reset information breaks the line; uncertain boundaries are labeled reset unknown.
Manual corrections can also produce a boundary. Charts are historical even when
the current provider sync fails. Percent charts use a 0–100 scale; other units scale
to the largest displayed reading. The table provides exact values and reset times.

Dashboard banners appear when a fresh reading is at or below its configured reserve
(including zero). Thresholds use each window's existing `reserve` in config.json.
Stale/future/invalid readings, passed resets and failed provider/manual/local reads
do not produce active alerts. A later successful sync restores eligibility; retries
alone do not. Banners recheck expiry every five seconds while the page is visible.
These are dashboard-only alerts, with no Windows notifications or background delivery.

Restart the Python dashboard after updating backend code, then reload the browser.
For the startup-managed instance in this checkout, preserve its account options:

```text
python coordinator/usagectl.py board startup disable
python coordinator/usagectl.py board startup enable --port 8766 --codex-account codex-main --experimental-claude-account claude-main
```

## Validation commands

```text
python -m unittest tests.test_continuity -q
python -m unittest discover -s tests -p "test_coordinator*.py" -q
node --check coordinator/usagekit/dashboard_assets/app.js
node tests/test_dashboard_ui.js
python -m unittest tests.test_live_usage tests.test_collectors -q
python -m unittest tests.test_usage_history -q
```

Node is needed only for that optional JavaScript syntax check, not to run the dashboard.
