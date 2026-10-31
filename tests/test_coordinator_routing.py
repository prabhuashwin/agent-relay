import os
import unittest

from tests.helpers import CtlCase, NOW, SESSION, WEEKLY, WEEK_RESET, call, git_available

MODEL_WIN = {"id": "opus_week", "kind": "weekly", "scope": "model:opus", "units": "percent", "reserve": 5}


class RouteCase(CtlCase):
    def rec(self, *extra, **kw):
        r = self.recommend(*extra, **kw)
        self.assertIn(r.code, (0, 4), r.err)
        return r.json, r.code

    def single(self, weekly=70, session=80, alias="acct-a"):
        self.init()
        self.add_account(alias)
        self.record(alias, "weekly", weekly, resets_at=WEEK_RESET)
        self.record(alias, "five_hour", session, resets_in="3h")


class SelectionTests(RouteCase):
    def test_start_ranks_by_own_account_room_not_percentage_across_accounts(self):
        self.two_accounts()
        # acct-a already used a lot today: its room_today / daily_target is lower
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET, observed_at="2026-11-02T08:00:00Z")
        self.record("acct-a", "weekly", 60, resets_at=WEEK_RESET)
        data, code = self.rec()
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "start", 0))

    def test_alias_breaks_ties(self):
        self.two_accounts()
        self.assertEqual(self.rec()[0]["recommended"], "acct-a")

    def test_preferred_provider_outranks_room(self):
        self.two_accounts()
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET, observed_at="2026-11-02T08:00:00Z")
        self.record("acct-a", "weekly", 60, resets_at=WEEK_RESET)
        self.edit_config(lambda c: c.update(preferred_provider="claude"))
        self.assertEqual(self.rec()[0]["recommended"], "acct-a")

    def test_verified_rate_ranks_when_enough_samples(self):
        self.two_accounts()
        for acct, result in (("acct-a", "failed"), ("acct-b", "verified")):
            for i in range(3):
                tid = "%s-%d" % (acct, i)
                self.append_task_event({"event": "start", "id": tid, "type": "refactor", "scope": "small",
                                        "account": acct, "at": "2026-10-30T0%d:00:00Z" % (i * 2 + 1), "windows": {}})
                self.append_task_event({"event": "finish", "id": tid, "result": result, "deltas": {},
                                        "attribution": "uncertain", "at": "2026-10-30T0%d:30:00Z" % (i * 2 + 1)})
        self.assertEqual(self.rec()[0]["recommended"], "acct-b")

    def test_owner_continuity_even_when_other_account_ranks_higher(self):
        self.two_accounts()
        self.record("acct-b", "weekly", 80, resets_at=WEEK_RESET, observed_at="2026-11-02T08:00:00Z")
        self.record("acct-b", "weekly", 70, resets_at=WEEK_RESET)
        data, _ = self.rec("--owner", "acct-b")
        self.assertEqual((data["recommended"], data["action"]), ("acct-b", "continue"))

    def test_explanation_lists_rejected_accounts(self):
        self.two_accounts()
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        data, _ = self.rec()
        self.assertEqual(data["recommended"], "acct-b")
        self.assertTrue(any(r.startswith("acct-a rejected") and "exhausted" in r for r in data["reasons"]))
        self.assertFalse(data["accounts"]["acct-a"]["suitable"])
        self.assertIn("exhausted", data["accounts"]["acct-a"]["flags"])

    def test_capability_filtering(self):
        self.two_accounts()
        self.edit_config(lambda c: c["accounts"]["acct-a"].update(capabilities=["edit"]))
        self.edit_config(lambda c: c["accounts"]["acct-b"].update(capabilities=["edit", "browse"]))
        data, _ = self.rec("--need", "browse")
        self.assertEqual(data["recommended"], "acct-b")
        self.assertIn("incompatible", data["accounts"]["acct-a"]["flags"])

    def test_text_output(self):
        self.two_accounts()
        r = call("route", "recommend", "--type", "refactor", "--scope", "small", "--risk", "low")
        self.assertEqual(r.code, 0)
        self.assertIn("recommended: acct-a", r.out)
        self.assertIn("next:", r.out)


@unittest.skipUnless(git_available(), "git not available")
class RebalanceTests(RouteCase):
    def setUp(self):
        super().setUp()
        self.two_accounts()      # acct-a room today = 60/4.5 = 13.33
        self.make_repo("ws")

    def test_small_overshoot_never_flips_owner(self):
        data, _ = self.rec("--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=15")
        self.assertIn("over_pace", data["accounts"]["acct-a"]["flags"])
        self.assertTrue(data["accounts"]["acct-a"]["suitable"])
        self.assertEqual((data["recommended"], data["action"]), ("acct-a", "continue"))

    def test_large_overshoot_with_checkpoint_switches(self):
        data, code = self.rec("--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=20")
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "switch", 0))
        self.assertIn("handoff resume", data["next_step"])

    def test_no_rebalance_without_checkpoint_or_for_high_priority(self):
        args = ["--owner", "acct-a", "--estimate", "acct-a:weekly=20"]
        self.assertEqual(self.rec(*args)[0]["recommended"], "acct-a")
        self.assertEqual(self.rec(*args, "--checkpoint", "ws", "--priority", "high")[0]["recommended"], "acct-a")

    def test_cooldown_blocks_rebalance(self):
        args = ["--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=20", "--workstream", "ws"]
        self.append_task_event({"event": "owner-change", "workstream": "ws", "from": "acct-b", "to": "acct-a",
                                "at": "2026-11-02T08:00:00Z"})
        self.assertEqual(self.rec(*args)[0]["action"], "continue")
        os.remove(self.paths.tasks)
        self.append_task_event({"event": "owner-change", "workstream": "ws", "from": "acct-b", "to": "acct-a",
                                "at": "2026-11-02T04:00:00Z"})     # 5h ago > 4h cooldown
        self.assertEqual(self.rec(*args)[0]["action"], "switch")
        os.remove(self.paths.tasks)
        self.append_task_event({"event": "owner-change", "workstream": "other", "from": "x", "to": "y",
                                "at": "2026-11-02T08:00:00Z"})     # other workstream: no effect
        self.assertEqual(self.rec(*args)[0]["action"], "switch")

    def test_account_change_between_tasks_also_starts_cooldown(self):
        for tid, acct, at in (("t1", "acct-b", "2026-11-02T07:00:00Z"), ("t2", "acct-a", "2026-11-02T08:00:00Z")):
            self.append_task_event({"event": "start", "id": tid, "type": "x", "scope": "small", "account": acct,
                                    "workstream": "ws", "at": at, "windows": {}})
        args = ["--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=20", "--workstream", "ws"]
        self.assertEqual(self.rec(*args)[0]["action"], "continue")

    def test_no_rebalance_when_other_account_is_also_over_pace(self):
        args = ["--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=20",
                "--estimate", "acct-b:weekly=30"]
        self.assertEqual(self.rec(*args)[0]["recommended"], "acct-a")

    def test_deadline_ignores_pace(self):
        args = ["--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=20",
                "--deadline", "2026-11-04"]
        data, _ = self.rec(*args)
        self.assertEqual(data["action"], "continue")
        self.assertNotIn("over_pace", data["accounts"]["acct-a"]["flags"])

    def test_checkpoint_validation(self):
        self.assertEqual(self.recommend("--checkpoint", "missing").code, 2)
        self.assertEqual(self.recommend("--checkpoint", "Bad Slug").code, 2)
        os.chdir(self.tmp)       # not a git work tree
        r = self.recommend("--checkpoint", "ws")
        self.assertEqual(r.code, 2)
        self.assertNotIn("Traceback", r.err)


class SwitchingTests(RouteCase):
    def test_exhausted_owner_switches_and_asks_for_checkpoint(self):
        self.two_accounts()
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        data, code = self.rec("--owner", "acct-a")
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "switch", 0))
        self.assertIn("Prepare a checkpoint first", data["next_step"])

    @unittest.skipUnless(git_available(), "git not available")
    def test_switch_with_checkpoint_points_to_resume(self):
        self.two_accounts()
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        self.make_repo("ws")
        data, _ = self.rec("--owner", "acct-a", "--checkpoint", "ws", "--workstream", "ws")
        self.assertIn("handoff resume --workstream ws --to acct-b", data["next_step"])

    @unittest.skipUnless(git_available(), "git not available")
    def test_switching_overhead_with_and_without_checkpoint(self):
        self.two_accounts(b_weekly=30)       # acct-b usable 20
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        est = ["--estimate", "acct-b:weekly=15"]
        data, code = self.rec("--owner", "acct-a", *est)           # 15 * 1.5 = 22.5 > 20
        self.assertEqual((data["action"], code), ("reduce-scope", 4))
        self.assertIn("too_large", data["accounts"]["acct-b"]["flags"])
        self.make_repo("ws")
        data, code = self.rec("--owner", "acct-a", "--checkpoint", "ws", *est)   # 15 * 1.15 = 17.25 <= 20
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "switch", 0))
        data, _ = self.rec(*est)           # no owner: no switching overhead
        self.assertEqual(data["recommended"], "acct-b")

    def test_overhead_not_applied_to_the_owner(self):
        self.two_accounts()
        data, _ = self.rec("--owner", "acct-a", "--estimate", "acct-a:weekly=55")   # 55 <= usable 60
        self.assertEqual(data["action"], "continue")
        data, code = self.rec("--owner", "acct-b", "--estimate", "acct-a:weekly=55", "--estimate", "acct-b:weekly=75")
        self.assertEqual(data["accounts"]["acct-a"]["suitable"], False)    # 55 * 1.5 > 60
        self.assertEqual(data["accounts"]["acct-b"]["suitable"], False)    # 75 > usable 70
        self.assertEqual((data["action"], code), ("reduce-scope", 4))


class NoneSuitableTests(RouteCase):
    def test_insufficient_reserves_wait_for_earliest_reset(self):
        self.two_accounts(a_weekly=8, b_weekly=9)
        data, code = self.rec()
        self.assertEqual((data["action"], code, data["recommended"]), ("wait", 4, None))
        self.assertEqual(data["wait_until"], WEEK_RESET)
        self.assertIn("below_reserve", data["accounts"]["acct-a"]["flags"])
        self.assertIn("paid fallback is disabled", data["next_step"])

    def test_exhausted_accounts_wait_until_earliest_reset(self):
        self.two_accounts()
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        self.record("acct-b", "weekly", 0, resets_at="2026-11-04T00:00:00Z")
        data, code = self.rec()
        self.assertEqual((data["action"], code, data["wait_until"]), ("wait", 4, "2026-11-04T00:00:00Z"))

    def test_exhausted_session_window_blocks_even_with_weekly_room(self):
        self.single()
        self.record("acct-a", "five_hour", 0, resets_in="2h")
        data, code = self.rec()
        self.assertEqual((data["action"], code, data["wait_until"]), ("wait", 4, "2026-11-02T11:00:00Z"))

    def test_refresh_when_everything_is_unknown_or_stale(self):
        self.init()
        self.add_account("acct-a")
        self.add_account("acct-b", "codex")
        data, code = self.rec()
        self.assertEqual((data["action"], code), ("refresh", 4))
        self.assertIn("acct-a", data["next_step"])
        self.assertIn("acct-b", data["next_step"])

    def test_owner_needing_refresh_is_not_abandoned(self):
        self.init()
        self.add_account("acct-a")
        self.add_account("acct-b", "codex")
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET, observed_at="2026-11-01T08:00:00Z")
        self.record("acct-a", "five_hour", 80, resets_in="3h")
        self.record("acct-b", "weekly", 80, resets_at=WEEK_RESET)
        self.record("acct-b", "five_hour", 80, resets_in="3h")
        data, code = self.rec("--owner", "acct-a")
        self.assertEqual((data["recommended"], data["action"], code), ("acct-a", "refresh", 0))
        self.assertIn("fresh", data["next_step"])
        # without an owner the stale account is simply rejected
        self.assertEqual(self.rec()[0]["recommended"], "acct-b")

    def test_passed_reset_requires_refresh_not_full_allowance(self):
        self.init()
        self.add_account("acct-a")
        self.record("acct-a", "five_hour", 80, resets_in="3h")
        self.record("acct-a", "weekly", 5, resets_at="2026-11-02T08:30:00Z", observed_at="2026-11-02T08:00:00Z")
        data, code = self.rec("--owner", "acct-a")
        self.assertEqual((data["action"], data["recommended"]), ("refresh", "acct-a"))
        self.assertIn("refresh", data["accounts"]["acct-a"]["flags"])

    def test_blocked_when_nobody_has_the_capability(self):
        self.two_accounts()
        data, code = self.rec("--need", "browse")
        self.assertEqual((data["action"], code), ("blocked", 4))
        self.assertIn("browse", " ".join(data["reasons"]))

    def test_no_accounts_is_blocked(self):
        self.init()
        data, code = self.rec()
        self.assertEqual((data["action"], code), ("blocked", 4))

    def test_zero_window_account_needs_refresh(self):
        self.init()
        self.add_account("acct-a", windows=[])
        data, code = self.rec()
        self.assertEqual((data["action"], code), ("refresh", 4))
        self.assertIn("no usage windows", " ".join(data["accounts"]["acct-a"]["notes"]))

    def test_low_priority_treats_over_pace_as_hard(self):
        self.single()
        est = ["--estimate", "acct-a:weekly=20"]
        data, code = self.rec(*est)
        self.assertEqual((data["recommended"], code), ("acct-a", 0))
        data, code = self.rec(*est, "--priority", "low")
        self.assertEqual((data["action"], code, data["wait_until"]), ("wait", 4, "2026-11-03"))

    def test_spending_policy_defaults_off_and_is_never_acted_on(self):
        self.two_accounts(a_weekly=8, b_weekly=8)
        data, code = self.rec()
        self.assertIn("paid fallback is disabled", data["next_step"])
        self.edit_config(lambda c: c["spending_policy"].update(paid_api_fallback=True))
        data, code = self.rec()
        self.assertEqual((data["action"], code, data["recommended"]), ("wait", 4, None))
        self.assertIn("allows: paid api fallback", data["next_step"])
        self.assertIn("never acts", data["next_step"])


class DeadlineTests(RouteCase):
    def test_deadline_never_bypasses_reserves_or_provider_limits(self):
        self.single(weekly=12)           # usable 2
        data, code = self.rec("--deadline", "2026-11-03", "--estimate", "acct-a:weekly=5")
        self.assertIn("too_large", data["accounts"]["acct-a"]["flags"])
        self.assertEqual(code, 4)
        self.record("acct-a", "weekly", 8, resets_at=WEEK_RESET)
        data, code = self.rec("--deadline", "2026-11-03")
        self.assertIn("below_reserve", data["accounts"]["acct-a"]["flags"])
        self.assertEqual(code, 4)
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)
        data, code = self.rec("--deadline", "2026-11-03")
        self.assertIn("exhausted", data["accounts"]["acct-a"]["flags"])
        self.assertEqual(code, 4)

    def test_deadline_in_past_is_invalid(self):
        self.single()
        self.assertEqual(self.recommend("--deadline", "2026-11-01").code, 2)


class UncertaintyTests(RouteCase):
    def test_no_history_and_no_estimate_keeps_recommendation_with_low_confidence(self):
        self.single()
        data, code = self.rec()
        self.assertEqual((data["recommended"], code, data["confidence"]), ("acct-a", 0, "low"))
        self.assertIn("no usage estimate", data["uncertainty"])
        self.assertIn("smaller step", data["next_step"])
        self.assertIn("task start", data["next_step"])

    def test_user_estimate_removes_uncertainty(self):
        self.single()
        data, _ = self.rec("--estimate", "acct-a:weekly=5", "--estimate", "acct-a:five_hour=5")
        self.assertEqual(data["confidence"], "medium")
        self.assertIsNone(data["uncertainty"])
        self.assertNotIn("smaller step", data["next_step"])

    def test_high_risk_adds_review(self):
        self.single()
        data, _ = self.rec("--estimate", "acct-a:weekly=5", risk="high")
        self.assertIn("review", data["next_step"])
        self.assertNotIn("review", self.rec("--estimate", "acct-a:weekly=5")[0]["next_step"])

    def test_low_confidence_history_is_flagged(self):
        self.single()
        self.edit_config(lambda c: c["accounts"]["acct-a"].update(windows=[dict(WEEKLY), dict(SESSION)]))
        for i, (before, after) in enumerate(((70, 66), (66, 60), (60, 55))):
            h = 9 + i * 2
            tid = "u%d" % i
            self.append_task_event({"event": "start", "id": tid, "type": "refactor", "scope": "small",
                                    "account": "acct-a", "at": "2026-11-02T%02d:00:00Z" % h, "windows": {}})
            self.append_task_event({"event": "finish", "id": tid, "result": "verified", "attribution": "uncertain",
                                    "at": "2026-11-02T%02d:30:00Z" % h,
                                    "deltas": {"weekly": {"delta": before - after, "reason": None}}})
        self.set_now("2026-11-02T14:00:00Z")
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-a", "five_hour", 80, resets_in="3h")
        data, _ = self.rec("--estimate", "acct-a:five_hour=5")
        self.assertEqual(data["accounts"]["acct-a"]["estimates"]["weekly"]["confidence"], "low")
        self.assertEqual(data["confidence"], "low")
        self.assertIn("few or unattributed", data["uncertainty"])


class ModelScopeTests(RouteCase):
    def test_model_specific_limit_applies_only_to_that_model(self):
        self.init()
        self.add_account("acct-a", windows=[WEEKLY, SESSION, MODEL_WIN])
        self.add_account("acct-b", "codex")
        for alias in ("acct-a", "acct-b"):
            self.record(alias, "weekly", 70, resets_at=WEEK_RESET)
            self.record(alias, "five_hour", 80, resets_in="3h")
        self.record("acct-a", "opus_week", 0, resets_at=WEEK_RESET)
        self.assertEqual(self.rec()[0]["recommended"], "acct-a")
        data, _ = self.rec("--model", "opus")
        self.assertEqual(data["recommended"], "acct-b")
        self.assertIn("exhausted", data["accounts"]["acct-a"]["flags"])
        self.edit_config(lambda c: c["accounts"]["acct-a"].update(default_model="opus"))
        self.assertEqual(self.rec()[0]["recommended"], "acct-b")

    def test_unobserved_model_window_needs_refresh_for_that_model(self):
        self.init()
        self.add_account("acct-a", windows=[WEEKLY, SESSION, MODEL_WIN])
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-a", "five_hour", 80, resets_in="3h")
        self.assertEqual(self.rec()[0]["recommended"], "acct-a")
        data, code = self.rec("--model", "opus")
        self.assertEqual((data["action"], code), ("refresh", 4))


class WindowShapeTests(RouteCase):
    def test_session_only_plan_is_routable_without_pacing(self):
        self.init()
        self.add_account("acct-a", windows=[SESSION])
        self.record("acct-a", "five_hour", 50, resets_in="2h")
        data, code = self.rec("--estimate", "acct-a:five_hour=10")
        self.assertEqual((data["recommended"], code), ("acct-a", 0))
        self.assertNotIn("over_pace", data["accounts"]["acct-a"]["flags"])

    def test_weekly_only_plan_is_routable(self):
        self.init()
        self.add_account("acct-a", windows=[WEEKLY])
        self.record("acct-a", "weekly", 50, resets_at=WEEK_RESET)
        self.assertEqual(self.rec()[0]["recommended"], "acct-a")

    def test_units_are_never_converted_between_windows(self):
        self.init()
        self.add_account("acct-a", windows=[WEEKLY, dict(SESSION, units="messages", reserve=5)])
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-a", "five_hour", 20, resets_in="2h")
        # estimate is per window, in that window's own units: 10 messages fit in usable 15
        self.assertEqual(self.rec("--estimate", "acct-a:five_hour=10")[0]["recommended"], "acct-a")
        self.assertEqual(self.rec("--estimate", "acct-a:five_hour=16")[0]["action"], "reduce-scope")


class InputTests(RouteCase):
    def test_invalid_inputs_exit_2(self):
        self.two_accounts()
        self.assertEqual(self.recommend("--owner", "ghost").code, 2)
        self.assertEqual(call("route", "recommend", "--type", "x", "--scope", "huge", "--risk", "low").code, 2)
        self.assertEqual(call("route", "recommend", "--type", "x", "--scope", "small", "--risk", "none").code, 2)
        self.assertEqual(self.recommend("--workstream", "Bad Slug").code, 2)
        self.assertEqual(self.recommend(typ="Bad Type").code, 2)


if __name__ == "__main__":
    unittest.main()
