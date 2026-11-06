# Usage history and reserve alerts implementation plan

Approved scope: seven days of local usage history per account/limit, clear reset
boundaries, and dashboard-only warnings at configured reserve thresholds.

Architecture: reuse the existing observation snapshot. A dedicated history module
filters seven days, groups reset cycles using the existing 15-minute tolerance,
and retains hourly first/minimum/maximum/last readings. No provider calls or new
storage. Alerts require a fresh, valid observation; failed sync hides alerts.

Implementation stays on the existing continuity-dashboard branch and preserves
the uncommitted workstream. No commit, deployment, or startup restart is included.

- [x] Add tests in `tests/test_usage_history.py` for time bounds, invalid values,
  reset boundaries, hourly extrema, freshness and exact reserve thresholds.
  Run `python -m unittest tests.test_usage_history -q` and confirm missing behavior.
- [x] Add `coordinator/usagekit/usage_history.py`; integrate through
  `live_usage.annotate` with the same snapshot clock in `continuity.py`.
  Verify the new tests and existing live-usage tests.
- [x] Extend `tests/test_dashboard_ui.js` for history, boundary labels, alerts,
  failed sync and local polling failure. Confirm failure before UI changes.
- [x] Add expandable SVG history with timestamp/value table to `app.js`, styling
  in `style.css`. Preserve expanded state; never join reset cycles or long gaps.
  Suppress alerts on provider/manual/local read failures and client-side aging.
- [x] Run focused Python regressions, Node UI checks, syntax and diff checks.
  Update `docs/continuity-dashboard.md` and the existing handoff/index.

Validation uses isolated temporary state and mocked provider reads. Browser visual
QA remains blocked by the previously reported Computer Use restriction.
