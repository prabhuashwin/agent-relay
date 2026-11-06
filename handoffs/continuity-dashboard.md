# Handoff: Continuity dashboard - history and reserve alerts implemented; restart pending

## Goal
Local UI for checkpoint workstreams, explicit owner transfers, evidence freshness,
explained routing, and account usage history/alerts.

## Done so far
- Branch `feat/continuity-dashboard`; dashboard work collected in `feat: add continuity dashboard`. No push; repository policy reserves that command for the user.
- Approved next increment implemented: seven days of local history per limit and dashboard reserve alerts.
- `usage_history.py` filters invalid/future/old observations, preserves hourly first/low/high/last readings, and separates reset cycles with existing 15-minute tolerance. Unknown reset changes are labeled uncertain.
- Shared-clock enrichment in `live_usage.py` and `continuity.py`; no new provider requests or storage.
- `dashboard_assets/` adds expandable SVG history, exact timestamp/value tables, empty/restart states and reserve banners. Expanded history persists across polls; history clock changes do not invalidate routing.
- Freshness expires on configured age/reset. Provider/manual/local failures suppress alerts. Later successful observations recover manual failures; retries alone do not. Expiry checked every five seconds while visible.
- Read-only review found manual-failure recovery bug; fixed and regression tested. No other important review findings.
- Verification: 63 focused Python tests passed, including seven history/HTTP tests; Node data-flow and syntax checks passed. Local HTTP test proves status/usage share history and never fetch providers.
- Full `python -m unittest discover -s tests -q` run was stopped at the repository's two-minute limit without a result; user can run it locally before pushing.
- Plan: `docs/superpowers/plans/2026-11-06-usage-history.md`; usage/restart guidance in `docs/continuity-dashboard.md`.
- Earlier V2: `startup.py`, `relay_supervisor.py`, `windows_job.py` provide current-user hidden Windows login startup, bounded crash recovery, one state-home lock, and owned process cleanup. Six short-lived crashes stop retries; five minutes stable resets the counter.
- Startup is enabled at :8766 with codex-main and claude-main; startup status reported running when resumed. Earlier disable/re-enable and owned-child crash recovery were live verified. This session did not restart it or fetch live quotas.
- Earlier account polling: Codex every 60s; opt-in experimental Claude every 180s with 25s process deadline; protected manual refresh, backoff and health metadata. Prior live reads succeeded for both; Claude Fable uses model-scoped limits.
- V1: `continuity.py`, `checkpoint_lock.py`, `board_cli.py`, `dashboard.py` implement checkpoint aggregation, release tickets, guarded claims and executed checks. Legacy CLI flows retained except board-managed ownership transfers.
- UI: neutral light theme, compact cards, progressive disclosure, fresh remaining/used percentages and historical stale values. Five-second local polling rejects late responses. Old-server API mismatch shows restart guidance.

## Decisions and why
- Reuse local observations for history; retain hourly extrema and separate reset cycles without extra provider traffic.
- Alert at existing per-window reserves only with fresh valid readings and successful sync; dashboard-only delivery.
- Existing decisions: Markdown owns goals/owners; SQLite outside Git stores releases/checks; transfers require stopped-source confirmation and single-use checkpoint-bound tickets.
- Actual verification stays separate from reported checks; changed repository fingerprints invalidate evidence.

## Open issues / gotchas
- Running :8766 backend has not been restarted for history/alerts. Static assets are served from disk; new UI shows history-unavailable/restart guidance with older backend.
- Browser visual QA remains unverified: browser host unavailable; native Chrome fallback was stopped because policy could not determine current URL. No further UI automation attempted.
- No Windows notifications, private mobile access, or model-task launching. Startup needs Windows login, awake PC, stable checkout/Python paths. Old :8765 server untouched.
- Only machine-readable checkpoints appear. Manual edits/old CLI/independent agents bypass cooperative locks. Fingerprints exclude ignored files, environment and external dependencies.
- Source checkout has new commands; rerun installer to update installed usagectl.

## Next steps
1. User runs `git push -u origin feat/continuity-dashboard`; no remote publication has been performed by the agent.
2. Restart startup-managed Relay to load backend: `python coordinator/usagectl.py board startup disable`, then `python coordinator/usagectl.py board startup enable --port 8766 --codex-account codex-main --experimental-claude-account claude-main`.
3. Reload http://127.0.0.1:8766 and visually check history expansion, reset boundaries, empty states and responsive layout when browser access is available.
4. Consider private mobile access or Windows notifications only with explicit scope. Integrate when requested.

## Read first
- docs/continuity-dashboard.md
- docs/superpowers/plans/2026-11-06-usage-history.md
- coordinator/usagekit/usage_history.py
- coordinator/usagekit/dashboard_assets/app.js
- tests/test_usage_history.py
