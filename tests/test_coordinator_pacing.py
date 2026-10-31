import datetime as dt
import unittest

from tests.helpers import CtlCase, SESSION, WEEKLY, WEEK_RESET, call, tzdata_available, utc
from usagekit import pacing
from usagekit.errors import CtlError
from usagekit.timeutil import Zone, fmt_local, fmt_utc, parse_date, parse_duration, parse_ts

WEIGHTS = {"mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 0, "sun": 0}


class TimeUtilTests(unittest.TestCase):
    def test_parse_ts_forms(self):
        z = Zone("+05:30")
        self.assertEqual(fmt_utc(parse_ts("2026-11-02T14:00:00", z)), "2026-11-02T08:30:00Z")
        self.assertEqual(fmt_utc(parse_ts("2026-11-02T14:00:00Z", z)), "2026-11-02T14:00:00Z")
        self.assertEqual(fmt_utc(parse_ts("2026-11-02T14:00:00-03:00", z)), "2026-11-02T17:00:00Z")

    def test_parse_ts_invalid(self):
        for bad in ("yesterday", "", 5, None, True):
            with self.assertRaises(CtlError):
                parse_ts(bad, Zone("+00:00"))

    def test_fixed_offsets(self):
        for ok in ("+00:00", "-08:00", "+14:00", "+05:45"):
            Zone(ok)
        for bad in ("+15:00", "+05:60", "+5", "Mars/Olympus"):
            with self.assertRaises(CtlError):
                Zone(bad)

    def test_local_zone_works(self):
        z = Zone("local")
        self.assertIsNotNone(z.to_local(utc("2026-11-02T09:00:00Z")))

    def test_fmt_local(self):
        self.assertEqual(fmt_local(utc("2026-11-02T09:00:00Z"), Zone("+05:30")), "2026-11-02 14:30+05:30")

    def test_durations_and_dates(self):
        self.assertEqual(parse_duration("3h20m"), dt.timedelta(hours=3, minutes=20))
        self.assertEqual(parse_duration("1d2h"), dt.timedelta(days=1, hours=2))
        for bad in ("", "0m", "abc", "3x", "-1h"):
            with self.assertRaises(CtlError):
                parse_duration(bad)
        self.assertEqual(parse_date("2026-11-02"), dt.date(2026, 11, 2))
        with self.assertRaises(CtlError):
            parse_date("11/02/2026")

    def test_day_fraction_fixed_offset(self):
        z = Zone("+05:30")
        self.assertAlmostEqual(z.day_fraction(utc("2026-11-09T05:00:00Z")), 10.5 / 24)

    @unittest.skipUnless(tzdata_available(), "tzdata not installed")
    def test_dst_day_lengths_with_iana(self):
        z = Zone("America/New_York")
        start, end = z.day_bounds(dt.date(2026, 11, 1))   # fall back: 25-hour day
        self.assertEqual(end - start, dt.timedelta(hours=25))
        start, end = z.day_bounds(dt.date(2026, 3, 8))    # spring forward: 23-hour day
        self.assertEqual(end - start, dt.timedelta(hours=23))
        self.assertAlmostEqual(z.day_fraction(utc("2026-11-01T17:00:00Z")), 13 / 25)

    @unittest.skipUnless(tzdata_available(), "tzdata not installed")
    def test_dst_weighted_days_with_iana(self):
        z = Zone("America/New_York")
        # Sunday 2026-11-01 (25h day, weight 0) then Monday: reset Mon 12:00 EST = 17:00Z
        w = pacing.plan_weight(utc("2026-10-30T12:00:00Z"), utc("2026-11-02T17:00:00Z"), z, WEIGHTS)
        self.assertAlmostEqual(w, 1 + 0 + 0 + 0.5)   # Fri full, Sat 0, Sun 0, Mon half


class WeightedDaysTests(unittest.TestCase):
    def w(self, now, reset, zone="+00:00", weights=WEIGHTS, deadline=None):
        return pacing.plan_weight(utc(now), utc(reset), Zone(zone), weights, deadline)

    def test_workweek_with_partial_reset_day(self):
        self.assertAlmostEqual(self.w("2026-11-02T09:00:00Z", WEEK_RESET), 4.5)

    def test_today_equals_reset_date_uses_fraction(self):
        self.assertAlmostEqual(self.w("2026-11-02T09:00:00Z", "2026-11-02T18:00:00Z"), 0.75)

    def test_weekend_has_no_weight(self):
        self.assertAlmostEqual(self.w("2026-11-07T09:00:00Z", "2026-11-09T12:00:00Z"), 0.5)
        self.assertEqual(self.w("2026-11-07T09:00:00Z", "2026-11-08T12:00:00Z"), 0)

    def test_weights_are_used(self):
        weights = dict(WEIGHTS, mon=2, tue=0.5)
        self.assertAlmostEqual(self.w("2026-11-02T09:00:00Z", "2026-11-04T00:00:00Z", weights=weights), 2 + 0.5 + 0)

    def test_timezone_changes_the_local_day(self):
        weights = {d: 0 for d in WEIGHTS}
        weights["mon"] = 1
        now, reset = "2026-11-02T20:00:00Z", "2026-11-09T05:00:00Z"
        # +05:30: now is Tue 01:30; only the final Monday (10:30 local) counts
        self.assertAlmostEqual(self.w(now, reset, "+05:30", weights), 10.5 / 24, places=5)
        # UTC: today is still Monday (full) plus Monday 05:00
        self.assertAlmostEqual(self.w(now, reset, "+00:00", weights), 1 + 5 / 24, places=5)

    def test_deadline_counts_each_date_at_least_one(self):
        now, reset = "2026-11-07T09:00:00Z", "2026-11-13T12:00:00Z"
        self.assertAlmostEqual(self.w(now, reset), 4.5)
        self.assertAlmostEqual(self.w(now, reset, deadline=dt.date(2026, 11, 9)), 3)
        self.assertAlmostEqual(self.w(now, reset, deadline=dt.date(2026, 11, 20)), 6.5)

    def test_deadline_in_past_rejected(self):
        with self.assertRaises(CtlError):
            self.w("2026-11-07T09:00:00Z", "2026-11-13T12:00:00Z", deadline=dt.date(2026, 11, 6))

    def test_next_workday(self):
        self.assertEqual(pacing.next_workday(utc("2026-11-06T09:00:00Z"), Zone("+00:00"), WEIGHTS), dt.date(2026, 11, 9))
        self.assertIsNone(pacing.next_workday(utc("2026-11-06T09:00:00Z"), Zone("+00:00"), {d: 0 for d in WEIGHTS}))


class PaceCliTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account("acct-a")

    def pace(self, *extra):
        r = call("pace", "show", "--json", *extra)
        self.assertEqual(r.code, 0, r.err)
        return r.json["accounts"]["acct-a"][0]

    def test_weekly_formula(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        p = self.pace()
        self.assertAlmostEqual(p["weighted_days"], 4.5)
        self.assertAlmostEqual(p["daily_target"], 60 / 4.5, places=5)
        self.assertEqual((p["used_today"], p["state"]), (0, "available"))
        self.assertAlmostEqual(p["room_today"], 60 / 4.5, places=5)

    def test_baseline_keeps_target_stable_as_work_proceeds(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        first = self.pace()["daily_target"]
        self.set_now("2026-11-02T15:00:00Z")
        self.record("acct-a", "weekly", 60, resets_at=WEEK_RESET)
        p = self.pace()
        self.assertEqual(p["daily_target"], first)           # does not shrink
        self.assertEqual((p["baseline"], p["used_today"]), (70, 10))
        self.assertAlmostEqual(p["room_today"], 60 / 4.5 - 10, places=5)

    def test_new_day_gets_new_baseline(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.set_now("2026-11-03T09:00:00Z")
        self.record("acct-a", "weekly", 55, resets_at=WEEK_RESET)
        p = self.pace()
        self.assertAlmostEqual(p["weighted_days"], 3.5)
        self.assertAlmostEqual(p["daily_target"], 45 / 3.5, places=5)
        self.assertEqual(p["used_today"], 0)

    def test_baseline_ignores_other_reset_cycle(self):
        self.record("acct-a", "weekly", 20, resets_at="2026-11-02T10:00:00Z", observed_at="2026-11-02T08:00:00Z")
        self.set_now("2026-11-02T10:30:00Z")
        self.record("acct-a", "weekly", 100, resets_at="2026-11-09T00:00:00Z")
        p = self.pace()
        self.assertEqual((p["baseline"], p["used_today"]), (100, 0))
        self.assertAlmostEqual(p["daily_target"], 90 / 5, places=5)  # Mon..Fri; reset date Monday has fraction 0

    def test_no_planned_workdays(self):
        self.set_now("2026-11-07T09:00:00Z")
        self.record("acct-a", "weekly", 70, resets_at="2026-11-08T12:00:00Z")
        p = self.pace()
        self.assertIsNone(p["daily_target"])
        self.assertEqual(p["message"], "no planned workdays before reset")

    def test_no_target_for_stale_unknown_exhausted_or_no_reset(self):
        self.assertEqual(self.pace()["state"], "unknown")
        self.assertIsNone(self.pace()["daily_target"])
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        p = self.pace()
        self.assertEqual(p["state"], "exhausted")
        self.assertIsNone(p["daily_target"])
        self.set_now("2026-11-03T10:00:00Z")      # observation now 25h old
        p = self.pace()
        self.assertEqual(p["state"], "exhausted")  # exhausted before reset stays exhausted
        self.record("acct-a", "weekly", 50)
        p = self.pace()
        self.assertEqual(p["message"], "no reset timestamp: no target")
        self.set_now("2026-11-05T10:00:00Z")
        self.assertIn("stale", self.pace()["message"])

    def test_session_percent_is_kept_separate_from_weekly_percent(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-a", "five_hour", 80, resets_in="3h")
        p = self.pace()
        self.assertAlmostEqual(p["today_limit"], 60 / 4.5, places=5)
        self.assertEqual(p["session"][0]["usable"], 75)
        self.record("acct-a", "five_hour", 8, resets_in="3h", observed_at="2026-11-02T09:00:00Z")
        self.assertAlmostEqual(self.pace()["today_limit"], 60 / 4.5, places=5)
        self.assertEqual(self.pace()["session"][0]["usable"], 3)

    def test_session_different_units_never_converted(self):
        self.edit_config(lambda c: c["accounts"]["acct-a"].update(
            windows=[dict(WEEKLY), dict(SESSION, units="messages", reserve=5)]))
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-a", "five_hour", 40, resets_in="3h")
        p = self.pace()
        self.assertAlmostEqual(p["today_limit"], 60 / 4.5, places=5)
        self.assertEqual((p["session"][0]["usable"], p["session"][0]["units"]), (35, "messages"))
        self.assertIn("not converted", p["today_limit_note"])
        self.assertIn("session", call("pace", "show").out)

    def test_deadline_override_label_and_reserve_still_honoured(self):
        self.set_now("2026-11-07T09:00:00Z")
        self.record("acct-a", "weekly", 70, resets_at="2026-11-13T12:00:00Z")
        p = self.pace("--deadline", "2026-11-09")
        self.assertTrue(p["deadline_override"])
        self.assertEqual(p["message"], "deadline override")
        self.assertAlmostEqual(p["daily_target"], 60 / 3)       # (remaining - reserve) / 3, not remaining / 3
        self.assertIn("deadline override", call("pace", "show", "--deadline", "2026-11-09").out)
        self.assertFalse(self.pace()["deadline_override"])

    def test_deadline_override_with_below_reserve_gives_zero_target(self):
        self.record("acct-a", "weekly", 8, resets_at=WEEK_RESET)
        p = self.pace("--deadline", "2026-11-03")
        self.assertEqual(p["daily_target"], 0)

    def test_deadline_in_past_or_invalid_exit_2(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.assertEqual(call("pace", "show", "--deadline", "2026-11-01").code, 2)
        self.assertEqual(call("pace", "show", "--deadline", "soon").code, 2)

    def test_accounts_without_weekly_window_have_no_pacing(self):
        self.add_account("session-only", windows=[SESSION])
        self.record("session-only", "five_hour", 50, resets_in="2h")
        r = call("pace", "show", "--json")
        self.assertEqual(r.json["accounts"]["session-only"], [])
        self.assertIn("no weekly window", call("pace", "show").out)

    def test_zero_window_account(self):
        self.add_account("empty", windows=[])
        self.assertEqual(call("pace", "show", "--json").json["accounts"]["empty"], [])


if __name__ == "__main__":
    unittest.main()
