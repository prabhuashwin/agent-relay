"""Regression tests for the dual-tool review findings (handoffs/dual-tool-review.md)."""
import io
import json
import os
import shutil
import subprocess
import sys
import unittest

from tests.helpers import CtlCase, NOW, WEEK_RESET, call, make_cfg, make_obs, utc, WEEKLY
from tests.test_coordinator_handoff import HandoffCase, WS
from tests.test_coordinator_routing import RouteCase
from tests.test_install import InstallBase, fwd, write, BASH

from usagekit import cli, config, handoff, history, pacing, usage
from usagekit.timeutil import Zone


class CooldownWithoutWorkstream(RouteCase):          # blocking 1
    def test_checkpoint_alone_still_respects_cooldown(self):
        self.two_accounts()
        self.make_repo("ws")
        self.append_task_event({"event": "owner-change", "workstream": "ws", "from": "acct-b", "to": "acct-a",
                                "at": "2026-11-02T08:00:00Z"})
        args = ["--owner", "acct-a", "--checkpoint", "ws", "--estimate", "acct-a:weekly=20"]   # no --workstream
        self.assertEqual(self.rec(*args)[0]["action"], "continue")


class ResetCycleTolerance(CtlCase):                  # blocking 4
    def test_same_cycle_helper(self):
        a = "2026-11-06T12:00:00Z"
        self.assertTrue(usage.same_cycle(a, "2026-11-06T12:02:00Z"))
        self.assertTrue(usage.same_cycle(a, "2026-11-06T11:46:00Z"))
        self.assertFalse(usage.same_cycle(a, "2026-11-06T12:16:00Z"))
        self.assertFalse(usage.same_cycle(a, "2026-11-13T12:00:00Z"))
        self.assertTrue(usage.same_cycle(None, None))
        self.assertFalse(usage.same_cycle(a, None))

    def test_task_delta_survives_resets_in_jitter(self):
        self.init()
        self.add_account("acct-a")
        self.set_now("2026-11-02T09:00:00Z")
        self.record("acct-a", "weekly", 70, resets_in="4d")
        self.assertEqual(call("task", "start", "--id", "t1", "--type", "x", "--scope", "small",
                              "--account", "acct-a").code, 0)
        self.set_now("2026-11-02T09:03:00Z")
        self.record("acct-a", "weekly", 60, resets_in="4d")      # resets_at is 3 minutes later
        r = call("task", "finish", "--id", "t1", "--result", "verified", "--sole-use", "--json")
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(r.json["deltas"]["weekly"], {"delta": 10, "reason": None})

    def test_pacing_baseline_uses_same_cycle_observations(self):
        cfg = make_cfg({"a": [WEEKLY]})
        zone = Zone("+00:00")
        obs = [make_obs(70, "2026-11-02T08:00:00Z", "2026-11-06T12:00:00Z"),
               make_obs(60, "2026-11-02T08:30:00Z", "2026-11-06T12:01:00Z")]
        base = pacing._baseline(obs, obs[1], zone, utc("2026-11-02T09:00:00Z"))
        self.assertEqual(base["remaining"], 70)


class Utf8Output(CtlCase):                           # blocking 7
    def test_non_ascii_output_on_ascii_stream(self):
        self.init()
        raw_out, raw_err = io.BytesIO(), io.BytesIO()
        old = sys.stdout, sys.stderr
        out_w = io.TextIOWrapper(raw_out, encoding="ascii")
        err_w = io.TextIOWrapper(raw_err, encoding="ascii")
        sys.stdout, sys.stderr = out_w, err_w
        try:
            code = cli.main(["task", "cancel", "--id", "caf\u00e9"])
            sys.stdout.flush(); sys.stderr.flush()
        finally:
            sys.stdout, sys.stderr = old
        self.assertNotEqual(code, 0)
        self.assertIn("caf\u00e9", raw_err.getvalue().decode("utf-8"))


class CredentialStripping(unittest.TestCase):        # blocking 6
    def test_forms(self):
        s = handoff.strip_credentials
        self.assertEqual(s("alice@host.example:team/repo.git"), "host.example:team/repo.git")
        self.assertEqual(s("host.example:team/repo.git"), "host.example:team/repo.git")
        self.assertEqual(s("/home/alice/secret/proj"), "proj")
        self.assertEqual(s("../up/proj/"), "proj")
        self.assertEqual(s("C:\\Users\\alice\\proj"), "proj")
        self.assertEqual(s("C:/Users/alice/proj"), "proj")
        self.assertEqual(s("https://u:tok@github.com/a/b.git?x=1"), "https://github.com/a/b.git")
        self.assertIsNone(s(None))


class NestedRepoVerify(HandoffCase):                 # blocking 5
    def nested(self, rel):
        full = os.path.join(self.repo, rel)
        os.makedirs(full)
        self.g("init", "-q", "-b", "main", cwd=full)
        with open(os.path.join(full, "f.txt"), "w", newline="\n") as fh:
            fh.write("one\n")
        self.g("add", ".", cwd=full)
        self.g("commit", "-q", "-m", "n1", cwd=full)
        return full

    def test_untracked_nested_repo_change_is_detected(self):
        full = self.nested("vendor")
        self.prepared()
        self.assertEqual(self.verify().code, 0)
        with open(os.path.join(full, "f.txt"), "w", newline="\n") as fh:
            fh.write("two\n")
        self.assert_mismatch("uncommitted modified")

    def test_untracked_nested_repo_new_commit_is_detected(self):
        full = self.nested("vendor")
        self.prepared()
        with open(os.path.join(full, "g.txt"), "w", newline="\n") as fh:
            fh.write("g\n")
        self.g("add", ".", cwd=full)
        self.g("commit", "-q", "-m", "n2", cwd=full)
        self.assert_mismatch("uncommitted modified")

    def test_submodule_content_change_is_detected(self):
        full = self.nested("sub")
        self.g("add", "sub")
        self.g("commit", "-q", "-m", "add sub")
        with open(os.path.join(full, "f.txt"), "w", newline="\n") as fh:
            fh.write("dirty1\n")
        self.prepared()
        self.assertEqual(self.verify().code, 0)
        with open(os.path.join(full, "f.txt"), "w", newline="\n") as fh:
            fh.write("dirty2\n")
        self.assert_mismatch("uncommitted modified")


class CheckpointCommitAndName(HandoffCase):          # non-blocking
    def test_committing_only_the_checkpoint_still_verifies(self):
        self.prepared()
        self.g("add", "handoffs/%s.checkpoint.md" % WS)
        self.g("commit", "-q", "-m", "checkpoint")
        self.assertEqual(self.verify().code, 0)

    def test_other_commit_alongside_checkpoint_is_still_ahead(self):
        self.prepared()
        self.write("c.txt", "c\n")
        self.g("add", "c.txt", "handoffs/%s.checkpoint.md" % WS)
        self.g("commit", "-q", "-m", "both")
        self.assert_mismatch("head ahead")

    def test_verify_and_claim_check_workstream_matches_file_name(self):
        self.prepared()
        shutil.copy(self.ckpt_path(), self.ckpt_path("renamed"))
        r = call("handoff", "verify", "--workstream", "renamed")
        self.assertEqual(r.code, 3, r.out + r.err)
        self.assertIn("is for workstream", r.err)
        r = call("handoff", "claim", "--workstream", "renamed", "--to", "acct-b")
        self.assertEqual(r.code, 3, r.out + r.err)


class TaskCancelAndConfig(CtlCase):                  # non-blocking
    def test_cancelled_task_does_not_make_later_tasks_uncertain(self):
        self.init()
        self.add_account("acct-a")
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        for tid in ("t1", "t2"):
            self.assertEqual(call("task", "start", "--id", tid, "--type", "x", "--scope", "small",
                                  "--account", "acct-a").code, 0)
            if tid == "t1":
                self.assertEqual(call("task", "cancel", "--id", "t1").code, 0)
        self.set_now("2026-11-02T09:30:00Z")
        self.record("acct-a", "weekly", 65, resets_at=WEEK_RESET)
        r = call("task", "finish", "--id", "t2", "--result", "verified", "--sole-use", "--json")
        self.assertEqual(r.json["attribution"], "clean", r.out)
        self.assertNotEqual(call("task", "cancel", "--id", "t1").code, 0)   # already gone
        self.assertNotEqual(call("task", "cancel", "--id", "t2").code, 0)   # finished

    def test_min_history_samples_zero_rejected(self):
        self.init()
        self.edit_config(lambda c: c["routing"].update(min_history_samples=0))
        r = call("config", "validate")
        self.assertNotEqual(r.code, 0)
        self.assertIn("min_history_samples", r.err)


@unittest.skipIf(BASH is None, "Git Bash not found")
class InstallerReview(InstallBase):
    def fails_unchanged(self, *opts, text):
        for extra in ((), ("--dry-run",)):
            before = self.tree()
            r = self.run_install("--skip-self-test", *extra, *opts, fwd(self.proj))
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(text, r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stdout + r.stderr)
            self.assertEqual(before, self.tree())

    def test_wrong_types_in_user_settings(self):                       # blocking 2
        for body, text in (('{"hooks": []}', "hooks"), ('{"hooks": {"SessionStart": {}}}', "hooks.SessionStart"),
                           ('{"hooks": null}', "hooks")):
            write(os.path.join(self.home, ".claude", "settings.json"), body)
            self.fails_unchanged(text=text)

    def test_wrong_types_in_project_settings(self):                   # blocking 2
        for body, text in (('{"permissions": []}', "permissions"), ('{"permissions": {"deny": "x"}}', "permissions.deny"),
                           ('{"permissions": {"allow": {}}}', "permissions.allow"),
                           ('{"hooks": {"UserPromptSubmit": 3}}', "hooks.UserPromptSubmit")):
            write(os.path.join(self.proj, ".claude", "settings.json"), body)
            self.fails_unchanged(text=text)

    def test_file_where_a_folder_is_needed(self):                     # blocking 3
        write(os.path.join(self.proj, "handoffs"), "i am a file")
        self.fails_unchanged(text="handoffs")
        os.remove(os.path.join(self.proj, "handoffs"))
        write(os.path.join(self.cx, "rules"), "i am a file")
        self.fails_unchanged("--tool", "codex", text="rules")

    def test_dry_run_reports_stale_removal_and_pruning(self):
        self.install()
        write(os.path.join(self.proj, ".claude", "statusline.sh"), "old")
        root = os.path.join(self.home, ".claude", "backups", "claude-setup")
        for i in range(10):
            os.makedirs(os.path.join(root, "old-%02d" % i))
        r = self.run_install("--dry-run", fwd(self.proj))
        self.assertIn("would remove stale", r.stdout)
        self.assertIn("statusline.sh", r.stdout)
        self.assertIn("would prune", r.stdout)

    def test_both_keeps_users_own_checkpoint_skill(self):
        mine = os.path.join(self.home, ".claude", "skills", "checkpoint", "SKILL.md")
        write(mine, "mine")
        r = self.install("--tool", "both")
        self.assertIn("not managed by claude-setup", r.stdout)
        with open(mine, encoding="utf-8") as f:
            self.assertEqual(f.read(), "mine")
        os.remove(mine)                      # no folder contents but folder remains: still foreign (no marker)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "skills", "checkpoint", ".claude-setup")))

    def test_both_installs_marked_checkpoint_skill_and_refreshes_it(self):
        self.install("--tool", "both")
        d = os.path.join(self.home, ".claude", "skills", "checkpoint")
        self.assertTrue(os.path.exists(os.path.join(d, ".claude-setup")))
        self.assertIn("CLAUDE_SETUP_HOME", open(os.path.join(d, "SKILL.md"), encoding="utf-8").read())
        write(os.path.join(d, "SKILL.md"), "stale")
        self.install("--tool", "both")
        self.assertIn("usagectl", open(os.path.join(d, "SKILL.md"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
