import io
import json
import os
import subprocess
import unittest
from unittest import mock

from tests.helpers import (CtlCase, NOW, SESSION, WEEKLY, call, git_available, make_cfg, make_obs, utc, usage,
                           WEEK_RESET)

MODEL_WIN = {"id": "opus_week", "kind": "weekly", "scope": "model:opus", "units": "percent", "reserve": 5}


def state(wcfg, obs, now=NOW, cfg=None):
    cfg = cfg or make_cfg()
    return usage.window_state(wcfg, obs, utc(now), cfg)


class WindowStateTests(unittest.TestCase):
    def test_unknown_without_observation(self):
        s = state(WEEKLY, None)
        self.assertEqual(s["state"], "unknown")

    def test_available_with_usable_and_reserve(self):
        s = state(WEEKLY, make_obs(70, "2026-11-02T08:00:00Z", WEEK_RESET))
        self.assertEqual((s["state"], s["usable"], s["below_reserve"]), ("available", 60, False))

    def test_below_reserve(self):
        s = state(WEEKLY, make_obs(8, "2026-11-02T08:00:00Z", WEEK_RESET))
        self.assertEqual((s["state"], s["usable"], s["below_reserve"]), ("available", 0, True))

    def test_stale_by_age_uses_kind_threshold(self):
        # session threshold 60 minutes
        old = state(SESSION, make_obs(50, "2026-11-02T07:50:00Z", "2026-11-02T12:00:00Z"))
        fresh = state(SESSION, make_obs(50, "2026-11-02T08:10:00Z", "2026-11-02T12:00:00Z"))
        self.assertEqual((old["state"], old["reason"]), ("stale", "old"))
        self.assertEqual(fresh["state"], "available")
        # weekly threshold 720 minutes
        self.assertEqual(state(WEEKLY, make_obs(50, "2026-11-01T20:00:00Z", WEEK_RESET))["state"], "stale")
        self.assertEqual(state(WEEKLY, make_obs(50, "2026-11-01T21:30:00Z", WEEK_RESET))["state"], "available")

    def test_passed_reset_is_stale_not_full_allowance(self):
        s = state(WEEKLY, make_obs(5, "2026-10-30T09:00:00Z", "2026-11-01T00:00:00Z"))
        self.assertEqual((s["state"], s["reason"]), ("stale", "reset-passed"))
        self.assertEqual(s["remaining"], 5)       # never reset to a full allowance
        self.assertIsNone(s["usable"])

    def test_reset_boundary(self):
        at_boundary = state(WEEKLY, make_obs(50, "2026-11-02T08:00:00Z", "2026-11-02T09:00:00Z"))
        just_before = state(WEEKLY, make_obs(50, "2026-11-02T08:00:00Z", "2026-11-02T09:00:01Z"))
        self.assertEqual(at_boundary["reason"], "reset-passed")
        self.assertEqual(just_before["state"], "available")

    def test_exhausted_before_reset_stays_exhausted_despite_age(self):
        s = state(WEEKLY, make_obs(0, "2026-10-28T09:00:00Z", WEEK_RESET))
        self.assertEqual(s["state"], "exhausted")

    def test_exhausted_after_reset_passed_is_stale(self):
        s = state(WEEKLY, make_obs(0, "2026-10-28T09:00:00Z", "2026-11-01T00:00:00Z"))
        self.assertEqual((s["state"], s["reason"]), ("stale", "reset-passed"))

    def test_exhausted_without_reset_only_while_fresh(self):
        self.assertEqual(state(WEEKLY, make_obs(0, "2026-11-02T08:00:00Z"))["state"], "exhausted")
        self.assertEqual(state(WEEKLY, make_obs(0, "2026-11-01T08:00:00Z"))["state"], "stale")

    def test_account_state_precedence(self):
        av, ex, un, st = ({"state": s} for s in ("available", "exhausted", "unknown", "stale"))
        self.assertEqual(usage.account_state([av, ex, un, st]), "exhausted")
        self.assertEqual(usage.account_state([av, un, st]), "unknown")
        self.assertEqual(usage.account_state([av, st]), "stale")
        self.assertEqual(usage.account_state([av]), "available")
        self.assertEqual(usage.account_state([]), "unknown")   # zero windows

    def test_applicable_windows_and_model_scope(self):
        acct = {"windows": [WEEKLY, MODEL_WIN], "default_model": None}
        self.assertEqual([w["id"] for w in usage.applicable_windows(acct)], ["weekly"])
        self.assertEqual([w["id"] for w in usage.applicable_windows(acct, "opus")], ["weekly", "opus_week"])
        self.assertEqual([w["id"] for w in usage.applicable_windows(acct, "sonnet")], ["weekly"])
        acct["default_model"] = "opus"
        self.assertEqual([w["id"] for w in usage.applicable_windows(acct)], ["weekly", "opus_week"])


class StatusCliTests(CtlCase):
    def status(self):
        r = call("usage", "status", "--json")
        self.assertEqual(r.code, 0, r.err)
        return r.json

    def test_missing_usage_is_unknown(self):
        self.init()
        self.add_account("acct-a")
        st = self.status()["accounts"]["acct-a"]
        self.assertEqual(st["state"], "unknown")
        self.assertTrue(all(w["state"] == "unknown" for w in st["windows"]))

    def test_malformed_lines_are_ignored_and_reported(self):
        self.init()
        self.add_account("acct-a")
        self.record("acct-a", "weekly", 50, resets_at=WEEK_RESET)
        with open(self.paths.usage, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("not json\n{\"account\": \"acct-a\"}\n[1,2]\n")
        data = self.status()
        self.assertEqual(data["ignored_lines"], 3)
        weekly = [w for w in data["accounts"]["acct-a"]["windows"] if w["window"] == "weekly"][0]
        self.assertEqual(weekly["state"], "available")
        self.assertIn("warning", call("usage", "status").out)

    def test_only_malformed_means_unknown(self):
        self.init()
        self.add_account("acct-a")
        os.makedirs(self.paths.state)
        with open(self.paths.usage, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("garbage\n")
        self.assertEqual(self.status()["accounts"]["acct-a"]["state"], "unknown")

    def test_latest_observation_by_observed_at_wins(self):
        self.init()
        self.add_account("acct-a")
        self.record("acct-a", "weekly", 40, resets_at=WEEK_RESET, observed_at="2026-11-02T08:00:00Z")
        self.record("acct-a", "weekly", 55, resets_at=WEEK_RESET, observed_at="2026-11-02T06:00:00Z")
        w = [w for w in self.status()["accounts"]["acct-a"]["windows"] if w["window"] == "weekly"][0]
        self.assertEqual(w["remaining"], 40)

    def test_passed_reset_is_reported_and_not_full(self):
        self.init()
        self.add_account("acct-a")
        self.record("acct-a", "weekly", 5, resets_at="2026-10-31T00:00:00Z", observed_at="2026-10-30T09:00:00Z")
        w = [w for w in self.status()["accounts"]["acct-a"]["windows"] if w["window"] == "weekly"][0]
        self.assertEqual((w["state"], w["reason"], w["remaining"]), ("stale", "reset-passed", 5))
        self.assertIn("not treated as full", call("usage", "status").out)

    def test_multiple_simultaneous_windows_and_model_limit(self):
        self.init()
        self.add_account("acct-a", windows=[WEEKLY, SESSION, MODEL_WIN])
        self.record("acct-a", "weekly", 60, resets_at=WEEK_RESET)
        self.record("acct-a", "five_hour", 0, resets_in="2h")
        self.record("acct-a", "opus_week", 30, resets_at=WEEK_RESET)
        st = self.status()["accounts"]["acct-a"]
        states = {w["window"]: w["state"] for w in st["windows"]}
        self.assertEqual(states, {"weekly": "available", "five_hour": "exhausted", "opus_week": "available"})
        self.assertEqual(st["state"], "exhausted")

    def test_zero_windows_account(self):
        self.init()
        self.add_account("acct-a", windows=[])
        st = self.status()["accounts"]["acct-a"]
        self.assertEqual((st["state"], st["windows"]), ("unknown", []))
        self.assertIn("no windows configured", call("usage", "status").out)

    def test_no_session_window_and_only_session_window(self):
        self.init()
        self.add_account("weekly-only", windows=[WEEKLY])
        self.add_account("session-only", windows=[SESSION])
        self.record("weekly-only", "weekly", 50, resets_at=WEEK_RESET)
        self.record("session-only", "five_hour", 50, resets_in="2h")
        accts = self.status()["accounts"]
        self.assertEqual(accts["weekly-only"]["state"], "available")
        self.assertEqual(accts["session-only"]["state"], "available")


class RecordValidationTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account("acct-a")

    def rec(self, *extra, remaining="50", window="weekly", account="acct-a"):
        return call("usage", "record", "--account", account, "--window", window, "--remaining", remaining, *extra)

    def test_rejections_exit_2_with_one_line(self):
        cases = [
            self.rec("--no-reset", account="nobody"),
            self.rec("--no-reset", window="nope"),
            self.rec("--no-reset", "--units", "messages"),
            self.rec("--no-reset", remaining="-1"),
            self.rec("--no-reset", remaining="101"),
            self.rec("--no-reset", remaining="nan"),
            self.rec("--no-reset", remaining="inf"),
            self.rec("--no-reset", remaining="abc"),
            self.rec("--no-reset", "--observed-at", "2026-11-02T09:06:00Z"),
            self.rec("--resets-at", "2026-11-02T08:00:00Z"),
            self.rec("--resets-at", "2026-11-02T09:00:00Z"),
            self.rec("--resets-in", "soon"),
            self.rec("--no-reset", "--confidence", "certain"),
        ]
        for r in cases:
            self.assertEqual(r.code, 2, r.out + r.err)
            self.assertNotIn("Traceback", r.err)
            self.assertEqual(len(r.err.strip().splitlines()), 1, r.err)
        self.assertFalse(os.path.exists(self.paths.usage))

    def test_future_slack_five_minutes_allowed(self):
        self.assertEqual(self.rec("--no-reset", "--observed-at", "2026-11-02T09:05:00Z").code, 0)

    def test_percent_100_ok_and_non_percent_may_exceed(self):
        self.assertEqual(self.rec("--no-reset", remaining="100").code, 0)
        self.edit_config(lambda c: c["accounts"]["acct-a"]["windows"].append(
            {"id": "msgs", "kind": "other", "scope": "shared", "units": "messages", "reserve": 0}))
        self.assertEqual(self.rec("--no-reset", remaining="500", window="msgs").code, 0)

    def test_naive_timestamps_use_configured_timezone_and_store_utc(self):
        self.edit_config(lambda c: c.update(timezone="+05:30"))
        r = self.rec("--observed-at", "2026-11-02T14:00:00", "--resets-at", "2026-11-06T18:00:00")
        self.assertEqual(r.code, 0, r.err)
        with open(self.paths.usage, encoding="utf-8") as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec["observed_at"], "2026-11-02T08:30:00Z")
        self.assertEqual(rec["resets_at"], "2026-11-06T12:30:00Z")
        self.assertIn("+05:30", call("usage", "status").out)

    def test_resets_in(self):
        self.rec("--resets-in", "3h20m")
        with open(self.paths.usage, encoding="utf-8") as fh:
            self.assertEqual(json.loads(fh.readline())["resets_at"], "2026-11-02T12:20:00Z")

    def test_jsonl_is_lf_only(self):
        self.rec("--no-reset")
        with open(self.paths.usage, "rb") as fh:
            self.assertNotIn(b"\r", fh.read())


class ImportTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account("acct-a")

    def write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content))
        return path

    def obs(self, **kw):
        base = {"account": "acct-a", "window": "weekly", "remaining": 50, "resets_at": WEEK_RESET}
        base.update(kw)
        return base

    def test_snapshot_import_ok(self):
        p = self.write("s.json", {"schema": 1, "observations": [self.obs(), self.obs(window="five_hour", resets_at=None)]})
        r = call("usage", "import", p, "--json")
        self.assertEqual((r.code, r.json["imported"]), (0, 2))

    def test_import_is_all_or_nothing(self):
        bad = [self.obs(), self.obs(remaining=-3)]
        r = call("usage", "import", self.write("s.json", {"schema": 1, "observations": bad}))
        self.assertEqual(r.code, 2)
        self.assertIn("nothing imported", r.err)
        self.assertFalse(os.path.exists(self.paths.usage))

    def test_import_rejects_bad_shapes(self):
        for name, content in {
            "bool": {"schema": 1, "observations": [self.obs(remaining=True)]},
            "unknown-field": {"schema": 1, "observations": [self.obs(extra=1)]},
            "bad-schema": {"schema": 2, "observations": [self.obs()]},
            "extra-top": {"schema": 1, "observations": [self.obs()], "x": 1},
            "empty": {"schema": 1, "observations": []},
            "nan": '{"schema": 1, "observations": [{"account": "acct-a", "window": "weekly", "remaining": NaN}]}',
            "inf": '{"schema": 1, "observations": [{"account": "acct-a", "window": "weekly", "remaining": Infinity}]}',
            "junk": "{not json",
        }.items():
            r = call("usage", "import", self.write(name + ".json", content))
            self.assertEqual(r.code, 2, name)
            self.assertNotIn("Traceback", r.err)
        self.assertFalse(os.path.exists(self.paths.usage))

    def test_import_missing_file(self):
        self.assertEqual(call("usage", "import", os.path.join(self.tmp, "nope.json")).code, 2)

    def test_import_from_stdin_with_default_account(self):
        doc = {"schema": 1, "observations": [{"window": "weekly", "remaining": 40}]}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(doc))):
            r = call("usage", "import", "-", "--account", "acct-a")
        self.assertEqual(r.code, 0, r.err)

    def statusline(self, five=None, seven=None):
        limits = {}
        if five:
            limits["five_hour"] = {"used_percentage": five[0], "resets_at": five[1]}
        if seven:
            limits["seven_day"] = {"used_percentage": seven[0], "resets_at": seven[1]}
        return {"model": {"id": "x"}, "rate_limits": limits}

    def test_claude_statusline_import(self):
        self.edit_config(lambda c: c["accounts"]["acct-a"]["windows"].__setitem__(0, dict(WEEKLY, id="seven_day")))
        doc = self.statusline(five=(23.5, 1793620800), seven=(41.2, 1793966400))
        r = call("usage", "import", self.write("sl.json", doc), "--format", "claude-statusline", "--account", "acct-a",
                 "--json")
        self.assertEqual(r.code, 0, r.err)
        obs = {o["window"]: o for o in r.json["observations"]}
        self.assertAlmostEqual(obs["five_hour"]["remaining"], 76.5)
        self.assertAlmostEqual(obs["seven_day"]["remaining"], 58.8)
        self.assertEqual(obs["five_hour"]["resets_at"], "2026-11-02T12:00:00Z")
        self.assertEqual((obs["five_hour"]["source"], obs["five_hour"]["confidence"]), ("claude-statusline", "high"))

    def test_statusline_absent_window_ignored_and_none_usable_fails(self):
        self.edit_config(lambda c: c["accounts"]["acct-a"]["windows"].__setitem__(0, dict(WEEKLY, id="seven_day")))
        one = self.write("one.json", self.statusline(five=(10, 1793620800)))
        r = call("usage", "import", one, "--format", "claude-statusline", "--account", "acct-a", "--json")
        self.assertEqual((r.code, r.json["imported"]), (0, 1))
        # no configured window matches -> exit 2
        self.edit_config(lambda c: c["accounts"]["acct-a"].update(windows=[dict(WEEKLY)]))
        r = call("usage", "import", one, "--format", "claude-statusline", "--account", "acct-a")
        self.assertEqual(r.code, 2)
        r = call("usage", "import", self.write("none.json", {"rate_limits": {}}), "--format", "claude-statusline",
                 "--account", "acct-a")
        self.assertEqual(r.code, 2)
        r = call("usage", "import", self.write("nl.json", {"model": 1}), "--format", "claude-statusline",
                 "--account", "acct-a")
        self.assertEqual(r.code, 2)

    def test_statusline_invalid_values_and_missing_account(self):
        p = self.write("bad.json", self.statusline(five=(101, 1793620800)))
        self.assertEqual(call("usage", "import", p, "--format", "claude-statusline", "--account", "acct-a").code, 2)
        p = self.write("ok.json", self.statusline(five=(10, 1793620800)))
        self.assertEqual(call("usage", "import", p, "--format", "claude-statusline").code, 2)
        p = self.write("bool.json", self.statusline(five=(True, 1793620800)))
        self.assertEqual(call("usage", "import", p, "--format", "claude-statusline", "--account", "acct-a").code, 2)
        self.assertFalse(os.path.exists(self.paths.usage))


@unittest.skipUnless(git_available(), "git not available")
class HomeInGitRepoTests(CtlCase):
    def make(self):
        repo = os.path.join(self.tmp, "somerepo")
        subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
        return repo

    def test_state_dir_inside_repo_is_refused(self):
        repo = self.make()
        os.environ["CLAUDE_SETUP_HOME"] = os.path.join(repo, "state-home")
        r = call("init")
        self.assertEqual(r.code, 2)
        self.assertIn("git work tree", r.err)
        self.assertFalse(os.path.exists(os.path.join(repo, "state-home")))

    def test_ignored_dir_inside_repo_is_allowed(self):
        repo = self.make()
        with open(os.path.join(repo, ".gitignore"), "w") as fh:
            fh.write(".claude-setup/\n")
        os.environ["CLAUDE_SETUP_HOME"] = os.path.join(repo, ".claude-setup")
        self.assertEqual(call("init").code, 0)

    def test_usage_append_also_refused(self):
        self.init()
        self.add_account("acct-a")
        repo = self.make()
        os.environ["CLAUDE_SETUP_HOME"] = os.path.join(repo, "h")
        # config would not load here; copy it in directly, as someone moving the folder might
        os.makedirs(os.path.join(repo, "h"))
        with open(os.path.join(repo, "h", "config.json"), "w") as fh, open(self.paths.config) as src:
            fh.write(src.read())
        r = call("usage", "record", "--account", "acct-a", "--window", "weekly", "--remaining", "5", "--no-reset")
        self.assertEqual(r.code, 2)
        self.assertFalse(os.path.exists(os.path.join(repo, "h", "state")))


class ConfigTests(CtlCase):
    def test_init_refuses_overwrite(self):
        self.assertEqual(call("init").code, 0)
        self.assertEqual(call("init").code, 2)
        self.assertEqual(call("init", "--force-not-allowed").code, 2)

    def test_missing_config_exit_2(self):
        r = call("usage", "status")
        self.assertEqual(r.code, 2)
        self.assertIn("usagectl init", r.err)

    def test_unknown_keys_rejected_at_every_level(self):
        self.init()
        self.add_account("acct-a")
        for edit in (lambda c: c.update(bogus=1),
                     lambda c: c["routing"].update(bogus=1),
                     lambda c: c["spending_policy"].update(bogus=True),
                     lambda c: c["accounts"]["acct-a"].update(bogus=1),
                     lambda c: c["accounts"]["acct-a"]["windows"][0].update(bogus=1),
                     lambda c: c["workday_weights"].update(bogus=1)):
            self.init_fresh = None
            with open(self.paths.config, encoding="utf-8") as fh:
                original = fh.read()
            self.edit_config(edit)
            r = call("config", "validate")
            self.assertEqual(r.code, 2)
            self.assertIn("unknown key", r.err)
            with open(self.paths.config, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(original)
        self.assertEqual(call("config", "validate").code, 0)

    def test_invalid_values_rejected(self):
        self.init()
        self.add_account("acct-a")
        for edit in (lambda c: c.update(version=2),
                     lambda c: c.update(preferred_provider="other"),
                     lambda c: c["spending_policy"].update(paid_api_fallback="yes"),
                     lambda c: c["accounts"].update({"Bad@Example.com": dict(c["accounts"]["acct-a"])}),
                     lambda c: c["accounts"]["acct-a"]["windows"][0].update(kind="daily"),
                     lambda c: c["accounts"]["acct-a"]["windows"][0].update(reserve=-1),
                     lambda c: c["accounts"]["acct-a"]["windows"][0].update(reserve=True),
                     lambda c: c["accounts"]["acct-a"]["windows"].append(dict(c["accounts"]["acct-a"]["windows"][0]))):
            with open(self.paths.config, encoding="utf-8") as fh:
                original = fh.read()
            self.edit_config(edit)
            self.assertEqual(call("config", "validate").code, 2)
            with open(self.paths.config, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(original)

    def test_malformed_config_json(self):
        self.init()
        with open(self.paths.config, "w") as fh:
            fh.write("{oops")
        r = call("config", "show")
        self.assertEqual(r.code, 2)
        self.assertNotIn("Traceback", r.err)

    def test_no_preset_windows_and_defaults(self):
        self.init()
        cfg = json.loads(call("config", "show").out)
        self.assertEqual(cfg["accounts"], {})
        self.assertEqual(cfg["spending_policy"], {"paid_api_fallback": False, "credit_purchases": False,
                                                  "paid_resets": False})
        self.assertEqual(cfg["workday_weights"]["sat"], 0)

    def test_account_and_window_add_via_cli(self):
        self.init()
        self.assertEqual(call("account", "add", "--account", "acct-a", "--provider", "codex", "--plan", "plus",
                              "--capability", "edit", "--capability", "edit").code, 0)
        self.assertEqual(call("account", "add", "--account", "acct-a", "--provider", "codex", "--plan", "x").code, 2)
        self.assertEqual(call("account", "add", "--account", "me@example.com", "--provider", "codex",
                              "--plan", "x").code, 2)
        self.assertEqual(call("window", "add", "--account", "acct-a", "--id", "w", "--kind", "weekly",
                              "--units", "credits", "--reserve", "5", "--scope", "model:gpt").code, 0)
        self.assertEqual(call("window", "add", "--account", "acct-a", "--id", "w", "--kind", "weekly",
                              "--units", "credits", "--reserve", "5").code, 2)
        self.assertEqual(call("window", "add", "--account", "ghost", "--id", "w", "--kind", "weekly",
                              "--units", "credits", "--reserve", "5").code, 2)
        cfg = json.loads(call("config", "show").out)
        self.assertEqual(cfg["accounts"]["acct-a"]["capabilities"], ["edit"])

    def test_iana_timezone_unavailable_message(self):
        self.init()
        self.edit_config(lambda c: c.update(timezone="Not/AZone"))
        r = call("config", "validate")
        self.assertEqual(r.code, 2)
        self.assertIn("fixed offset", r.err)
        self.assertIn("tzdata", r.err)

    def test_no_traceback_on_bad_arguments(self):
        for argv in (["nonsense"], ["usage"], ["route", "recommend"], ["usage", "record", "--remaining", "x"]):
            r = call(*argv)
            self.assertEqual(r.code, 2)
            self.assertNotIn("Traceback", r.err)

    def test_handoff_placeholder_does_not_crash(self):
        r = call("handoff", "verify", "--workstream", "x")
        self.assertEqual(r.code, 2)
        self.assertNotIn("Traceback", r.err)


class SelftestTests(CtlCase):
    def test_selftest_passes_and_leaves_real_home_alone(self):
        r = call("selftest")
        self.assertEqual(r.code, 0, r.out + r.err)
        self.assertIn("selftest ok", r.out)
        self.assertFalse(os.path.exists(self.home))
        self.assertEqual(os.environ["USAGECTL_NOW"], NOW)
        self.assertEqual(os.environ["CLAUDE_SETUP_HOME"], self.home)

    def test_selftest_json(self):
        r = call("selftest", "--json")
        self.assertEqual((r.code, r.json["ok"]), (0, True))


if __name__ == "__main__":
    unittest.main()
