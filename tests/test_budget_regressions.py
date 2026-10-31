"""Regression coverage for the independent quota-coordinator validation."""
import unittest

from tests.helpers import make_cfg, make_obs, utc, WEEKLY, SESSION
from usagekit import pacing, routing
from usagekit.timeutil import Zone


class BudgetRegressions(unittest.TestCase):
    def setUp(self):
        self.now = utc("2026-11-02T09:00:00Z")
        self.zone = Zone("+00:00")
        self.cfg = make_cfg({"a": [WEEKLY, SESSION]})
        self.index = {}
        self.observe("a", "weekly", 60, "2026-11-04T00:00:00Z")
        self.observe("a", "five_hour", 80, "2026-11-02T12:00:00Z")

    def observe(self, alias, window, value, reset):
        self.index[alias, window] = [make_obs(value, "2026-11-02T09:00:00Z", reset)]

    def pace(self):
        return pacing.pace_account(self.cfg, self.zone, self.now, "a", self.index)[0]

    def route(self, **kwargs):
        return routing.recommend(self.cfg, self.zone, self.now, self.index, {}, [],
                                 routing.Request("edit", "large", "low", **kwargs))

    def test_weighted_today_gets_its_share(self):
        self.cfg["workday_weights"].update(mon=2, tue=1)
        self.assertAlmostEqual(self.pace()["daily_target"], 50 * 2 / 3, places=5)

    def test_nonworking_today_gets_zero(self):
        self.cfg["workday_weights"]["mon"] = 0
        self.assertEqual(self.pace()["daily_target"], 0)

    def test_reset_today_never_allocates_more_than_available(self):
        self.observe("a", "weekly", 60, "2026-11-02T12:00:00Z")
        self.assertEqual(self.pace()["daily_target"], 50)

    def test_exhausted_session_blocks_today(self):
        self.observe("a", "five_hour", 0, "2026-11-02T12:00:00Z")
        p = self.pace()
        self.assertEqual(p["today_limit"], 0)
        self.assertIn("five_hour", p["today_limit_note"])

    def test_unknown_session_requires_refresh(self):
        del self.index["a", "five_hour"]
        self.assertIsNone(self.pace()["today_limit"])

    def test_percentages_in_different_windows_are_not_compared(self):
        self.observe("a", "five_hour", 8, "2026-11-02T12:00:00Z")
        self.assertEqual(self.pace()["today_limit"], 25)
        self.assertIn("not converted", self.pace()["today_limit_note"])

    def test_partial_estimate_is_explicitly_uncertain(self):
        r = self.route(estimates={("a", "weekly"): 1})
        self.assertEqual(r["confidence"], "low")
        self.assertIn("five_hour", r["uncertainty"])
        self.assertIn("smaller step", r["next_step"])

    def test_complete_estimates_allow_medium_confidence(self):
        self.assertEqual(self.route(estimates={("a", "weekly"): 1, ("a", "five_hour"): 2})["confidence"], "medium")

    def test_wait_requires_all_windows_to_reset(self):
        self.observe("a", "weekly", 0, "2026-11-04T00:00:00Z")
        self.observe("a", "five_hour", 0, "2026-11-02T12:00:00Z")
        self.assertEqual(self.route()["wait_until"], "2026-11-04T00:00:00Z")

    def test_wait_chooses_earliest_account_recovery(self):
        self.cfg["accounts"]["b"] = dict(self.cfg["accounts"]["a"])
        self.observe("a", "weekly", 0, "2026-11-04T00:00:00Z")
        self.observe("a", "five_hour", 0, "2026-11-02T12:00:00Z")
        self.observe("b", "weekly", 0, "2026-11-03T00:00:00Z")
        self.observe("b", "five_hour", 0, "2026-11-02T13:00:00Z")
        self.assertEqual(self.route()["wait_until"], "2026-11-03T00:00:00Z")

    def test_unknown_blocker_reset_does_not_promise_recovery(self):
        self.observe("a", "weekly", 0, None)
        self.observe("a", "five_hour", 0, "2026-11-02T12:00:00Z")
        self.assertIsNone(self.route()["wait_until"])

    def test_pacing_wait_cannot_hide_a_later_quota_reset(self):
        self.observe("a", "five_hour", 0, "2026-11-05T12:00:00Z")
        r = self.route(priority="low", estimates={("a", "weekly"): 30})
        self.assertEqual(r["wait_until"], "2026-11-05T12:00:00Z")

    def test_stale_session_requires_refresh(self):
        self.now = utc("2026-11-02T10:30:00Z")
        self.assertIsNone(self.pace()["today_limit"])
        self.assertIn("refresh", self.pace()["today_limit_note"])

    def test_session_reserve_blocks_today(self):
        self.observe("a", "five_hour", 5, "2026-11-02T12:00:00Z")
        self.assertEqual(self.pace()["today_limit"], 0)
