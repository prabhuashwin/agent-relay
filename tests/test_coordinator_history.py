import json
import unittest

from tests.helpers import CtlCase, WEEKLY, WEEK_RESET, call


class HistoryCase(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account("acct-a", windows=[WEEKLY])

    def at(self, hour, minute=0):
        self.set_now("2026-11-02T%02d:%02d:00Z" % (hour, minute))

    def start(self, tid, hour, minute=0, typ="refactor", scope="small", account="acct-a", **kw):
        self.at(hour, minute)
        argv = ["task", "start", "--id", tid, "--type", typ, "--scope", scope, "--account", account, "--json"]
        for k, v in kw.items():
            argv += ["--" + k, v]
        r = call(*argv)
        self.assertEqual(r.code, 0, r.err)
        return r.json

    def finish(self, tid, hour, minute=0, result="verified", sole=True):
        self.at(hour, minute)
        argv = ["task", "finish", "--id", tid, "--result", result, "--json"] + (["--sole-use"] if sole else [])
        r = call(*argv)
        self.assertEqual(r.code, 0, r.err)
        return r.json

    def rec(self, remaining, hour, minute=0, resets_at=WEEK_RESET):
        self.at(hour, minute)
        self.record("acct-a", "weekly", remaining, resets_at=resets_at)

    def run_task(self, tid, hour, before, after, **kw):
        sole = kw.pop("sole", True)
        result = kw.pop("result", "verified")
        self.rec(before, hour)
        self.start(tid, hour, **kw)
        self.rec(after, hour, 30)
        return self.finish(tid, hour, 30, result=result, sole=sole)

    def estimate(self, *extra, typ="refactor"):
        self.at(15)
        self.record("acct-a", "weekly", 50, resets_at=WEEK_RESET)
        r = self.recommend(*extra, typ=typ)
        return r.json["accounts"]["acct-a"]["estimates"]["weekly"]


class TaskRecordTests(HistoryCase):
    def test_start_snapshots_latest_observation(self):
        self.rec(60, 9)
        ev = self.start("t1", 9, 10, workstream="ws-one")
        self.assertEqual(ev["windows"]["weekly"]["remaining"], 60)
        self.assertEqual(ev["workstream"], "ws-one")
        with open(self.paths.tasks, "rb") as fh:
            raw = fh.read()
        self.assertNotIn(b"\r", raw)
        self.assertEqual(json.loads(raw.splitlines()[0])["event"], "start")

    def test_clean_delta(self):
        ev = self.run_task("t1", 9, 60, 55)
        self.assertEqual(ev["deltas"]["weekly"], {"delta": 5, "reason": None})
        self.assertEqual(ev["attribution"], "clean")

    def test_without_sole_use_attribution_is_uncertain(self):
        ev = self.run_task("t1", 9, 60, 55, sole=False)
        self.assertEqual(ev["deltas"]["weekly"]["delta"], 5)
        self.assertEqual(ev["attribution"], "uncertain")
        self.assertIn("--sole-use not given", ev["attribution_reasons"])

    def test_overlapping_tasks_are_uncertain_even_with_sole_use(self):
        self.rec(60, 9)
        self.start("t1", 9)
        self.rec(58, 9, 30)
        self.start("t2", 9, 30)
        self.rec(55, 10)
        first = self.finish("t1", 10)
        self.rec(50, 10, 30)
        second = self.finish("t2", 10, 30)
        self.assertEqual((first["attribution"], second["attribution"]), ("uncertain", "uncertain"))
        self.assertIn("overlapped", " ".join(second["attribution_reasons"]))

    def test_sequential_tasks_stay_clean(self):
        self.run_task("t1", 9, 60, 58)
        ev = self.run_task("t2", 11, 58, 56)
        self.assertEqual(ev["attribution"], "clean")

    def test_other_account_does_not_count_as_overlap(self):
        self.add_account("acct-b", windows=[WEEKLY])
        self.rec(60, 9)
        self.start("t1", 9, account="acct-b")
        self.rec(55, 9, 30)
        self.start("t2", 9, 30)
        self.rec(50, 10)
        self.assertEqual(self.finish("t2", 10)["attribution"], "clean")

    def test_negative_delta_is_an_anomaly(self):
        ev = self.run_task("t1", 9, 60, 70)
        self.assertEqual(ev["deltas"]["weekly"], {"delta": None, "reason": "negative-delta"})
        self.assertEqual(ev["attribution"], "uncertain")

    def test_reset_cycle_change_gives_null_delta(self):
        self.rec(60, 9)
        self.start("t1", 9)
        self.rec(95, 9, 30, resets_at="2026-11-13T12:00:00Z")
        ev = self.finish("t1", 9, 30)
        self.assertEqual(ev["deltas"]["weekly"]["reason"], "reset-cycle-changed")
        self.assertEqual(ev["attribution"], "uncertain")

    def test_no_newer_observation(self):
        self.rec(60, 9)
        self.start("t1", 9)
        ev = self.finish("t1", 9)
        self.assertEqual(ev["deltas"]["weekly"], {"delta": None, "reason": "no-newer-observation"})

    def test_window_without_observation_at_start(self):
        self.start("t1", 9)
        self.rec(55, 9, 30)
        ev = self.finish("t1", 9, 30)
        self.assertEqual(ev["deltas"], {})

    def test_bad_task_commands(self):
        self.start("t1", 9)
        self.assertEqual(call("task", "start", "--id", "t1", "--type", "x", "--scope", "small",
                              "--account", "acct-a").code, 2)
        self.assertEqual(call("task", "start", "--id", "t2", "--type", "x", "--scope", "small",
                              "--account", "ghost").code, 2)
        self.assertEqual(call("task", "start", "--id", "t2", "--type", "x", "--scope", "huge",
                              "--account", "acct-a").code, 2)
        self.assertEqual(call("task", "start", "--id", "bad id!", "--type", "x", "--scope", "small",
                              "--account", "acct-a").code, 2)
        self.assertEqual(call("task", "finish", "--id", "nope", "--result", "verified").code, 2)
        self.finish("t1", 9)
        self.assertEqual(call("task", "finish", "--id", "t1", "--result", "verified").code, 2)
        self.assertEqual(call("task", "finish", "--id", "t1", "--result", "great").code, 2)


class EstimateTests(HistoryCase):
    def three_clean(self, typ="refactor"):
        for tid, hour, drop in (("c1", 9, 4), ("c2", 11, 6), ("c3", 13, 5)):
            self.run_task(tid + typ, hour, 80 - hour, 80 - hour - drop, typ=typ)

    def test_insufficient_history_has_no_estimate(self):
        self.run_task("c1", 9, 70, 66)
        self.run_task("c2", 11, 66, 60)
        e = self.estimate()
        self.assertEqual((e["value"], e["confidence"], e["samples"]), (None, None, 2))

    def test_three_clean_samples_give_median_medium(self):
        self.three_clean()
        e = self.estimate()
        self.assertEqual((e["value"], e["confidence"], e["samples"]), (5, "medium", 3))

    def test_uncertain_samples_give_low_confidence(self):
        for tid, hour, drop in (("u1", 9, 4), ("u2", 11, 6), ("u3", 13, 5)):
            self.run_task(tid, hour, 80 - hour, 80 - hour - drop, sole=False)
        e = self.estimate()
        self.assertEqual((e["value"], e["confidence"]), (5, "low"))

    def test_failed_and_partial_tasks_still_count(self):
        self.run_task("f1", 9, 71, 67, result="failed")
        self.run_task("f2", 11, 69, 63, result="partial")
        self.run_task("f3", 13, 67, 62, result="verified")
        self.assertEqual(self.estimate()["value"], 5)

    def test_samples_are_keyed_by_type_and_scope(self):
        self.three_clean(typ="refactor")
        self.assertIsNone(self.estimate(typ="docs")["value"])
        self.assertIsNone(self.recommend(typ="refactor", scope="large").json["accounts"]["acct-a"]
                          ["estimates"]["weekly"]["value"])

    def test_user_estimate_overrides_history(self):
        self.three_clean()
        e = self.estimate("--estimate", "acct-a:weekly=12")
        self.assertEqual((e["value"], e["confidence"]), (12, "user"))

    def test_bad_estimate_arguments(self):
        self.rec(50, 9)
        for bad in ("acct-a:weekly", "acct-a:weekly=-1", "acct-a:weekly=abc", "ghost:weekly=1", "acct-a:nope=1",
                    "acct-a:weekly=nan"):
            self.assertEqual(self.recommend("--estimate", bad).code, 2, bad)


if __name__ == "__main__":
    unittest.main()
