"""Simulated Claude -> Codex -> Claude workflow through the real CLI (temp repo, fake accounts, fixed clock)."""

import json
import os
import unittest

from tests import test_coordinator_handoff as base
from tests.helpers import WEEK_RESET, call

WS = "billing-refactor"
NEXT_WEEK_RESET = "2026-11-13T12:00:00Z"


class WorkflowTests(base.HandoffCase):
    """acct-a is the Claude account, acct-b the Codex account (both created by HandoffCase.setUp)."""

    def snapshot(self, *obs):
        path = os.path.join(self.tmp, "snap-%d.json" % len(os.listdir(self.tmp)))
        doc = {"schema": 1, "observations": [
            {"account": a, "window": w, "remaining": r, "resets_at": reset, "observed_at": at,
             "source": "manual", "confidence": "high"} for a, w, r, reset, at in obs]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        r = call("usage", "import", path)
        self.assertEqual(r.code, 0, r.err)

    def route(self, *extra):
        r = call("route", "recommend", "--type", "refactor", "--scope", "small", "--risk", "low", "--json", *extra)
        return r.json, r.code

    def task(self, tid, account, result, sole=True):
        r = call("task", "start", "--id", tid, "--type", "refactor", "--scope", "small", "--account", account,
                 "--workstream", WS)
        self.assertEqual(r.code, 0, r.err)
        return lambda: self.assertEqual(
            call("task", "finish", "--id", tid, "--result", result, *(["--sole-use"] if sole else [])).code, 0)

    def test_claude_to_codex_to_claude(self):
        # 1. Claude owns the workstream and has uncommitted work.
        self.snapshot(("acct-a", "weekly", 60, WEEK_RESET, NOW_S), ("acct-a", "five_hour", 50, "2026-11-02T12:00:00Z", NOW_S),
                      ("acct-b", "weekly", 80, WEEK_RESET, NOW_S), ("acct-b", "five_hour", 90, "2026-11-02T13:00:00Z", NOW_S))
        finish_t1 = self.task("t1", "acct-a", "partial")
        self.write("a.txt", "one\nclaude edit\n")
        self.write("billing.py", "def total():\n    return 1\n")
        r = call("handoff", "prepare", "--workstream", WS, "--owner", "acct-a", "--goal", "split billing",
                 "--next", "finish total() and run tests", "--done", "extracted total()",
                 "--verify", "python -m unittest=>1 failure=>fail")
        self.assertEqual(r.code, 0, r.err)

        # 2. Claude runs out: the snapshot shows it exhausted and recommend says switch to Codex.
        self.set_now("2026-11-02T09:30:00Z")
        self.snapshot(("acct-a", "weekly", 0, WEEK_RESET, "2026-11-02T09:30:00Z"))
        finish_t1()
        status = call("usage", "status", "--json").json["accounts"]
        self.assertEqual(status["acct-a"]["state"], "exhausted")
        self.assertEqual(status["acct-b"]["state"], "available")
        data, code = self.route("--owner", "acct-a", "--checkpoint", WS, "--workstream", WS)
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "switch", 0))
        self.assertIn("handoff resume --workstream %s --to acct-b" % WS, data["next_step"])

        # 3. Codex claims (verification passes: nothing moved) and gets a Codex-style prompt.
        claim = call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(claim.code, 0, claim.err)
        resume = call("handoff", "resume", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(resume.code, 0, resume.err)
        self.assertIn("$handoff", resume.out)
        self.assertIn("Never discard, stash, commit, or overwrite", resume.out)
        self.assertEqual(self.ckpt(WS)["owner"], "acct-b")

        # 4. Codex finishes, commits, and checkpoints. Claude can no longer claim the old state.
        self.set_now("2026-11-02T10:00:00Z")
        finish_t2 = self.task("t2", "acct-b", "verified")
        self.g("add", ".")
        self.g("commit", "-q", "-m", "split billing")
        r = call("handoff", "prepare", "--workstream", WS, "--owner", "acct-b", "--goal", "split billing",
                 "--next", "review the diff", "--done", "total() done", "--verify", "python -m unittest=>ok=>pass")
        self.assertEqual(r.code, 0, r.err)
        self.set_now("2026-11-02T10:30:00Z")
        self.snapshot(("acct-b", "weekly", 70, WEEK_RESET, "2026-11-02T10:30:00Z"))
        finish_t2()
        self.assertEqual(self.ckpt(WS)["uncommitted"]["paths"], [])

        # 5. Friday after noon: the old Claude reset time has passed, so its numbers are stale and a refresh is
        #    demanded (never treated as full). Codex's observation is old too.
        self.set_now("2026-11-06T13:00:00Z")
        status = call("usage", "status", "--json").json["accounts"]
        wk = [w for w in status["acct-a"]["windows"] if w["window"] == "weekly"][0]
        self.assertEqual((wk["state"], wk["reason"]), ("stale", "reset-passed"))
        data, code = self.route("--owner", "acct-b")
        self.assertEqual(data["action"], "refresh")
        self.assertEqual(data["recommended"], "acct-b")

        # 6. Fresh snapshot: Claude is full again, but Codex is still suitable, so continuity holds.
        self.snapshot(("acct-a", "weekly", 95, NEXT_WEEK_RESET, "2026-11-06T13:05:00Z"),
                      ("acct-a", "five_hour", 90, "2026-11-06T18:00:00Z", "2026-11-06T13:05:00Z"),
                      ("acct-b", "weekly", 40, NEXT_WEEK_RESET, "2026-11-06T13:05:00Z"),
                      ("acct-b", "five_hour", 80, "2026-11-06T18:00:00Z", "2026-11-06T13:05:00Z"))
        self.set_now("2026-11-06T13:10:00Z")
        data, code = self.route("--owner", "acct-b", "--checkpoint", WS, "--workstream", WS)
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "continue", 0))

        # 7. Codex works more, then is exhausted; the checkpoint is current, so switch back to Claude.
        finish_t3 = self.task("t3", "acct-b", "partial")
        self.write("notes.md", "follow-up\n")
        self.g("add", "notes.md")
        self.g("commit", "-q", "-m", "notes")
        self.write("scratch.txt", "uncommitted codex work\n")
        r = call("handoff", "prepare", "--workstream", WS, "--owner", "acct-b", "--goal", "split billing",
                 "--next", "wire up the report", "--failure", "report test still red")
        self.assertEqual(r.code, 0, r.err)
        self.set_now("2026-11-06T14:00:00Z")
        self.snapshot(("acct-b", "weekly", 0, NEXT_WEEK_RESET, "2026-11-06T14:00:00Z"))
        finish_t3()
        data, code = self.route("--owner", "acct-b", "--checkpoint", WS, "--workstream", WS)
        self.assertEqual((data["recommended"], data["action"], code), ("acct-a", "switch", 0))

        # 8. Claude resumes only when the repository still matches; then verifies and claims.
        self.write("scratch.txt", "someone changed it\n")
        refused = call("handoff", "claim", "--workstream", WS, "--to", "acct-a")
        self.assertEqual(refused.code, 3)
        self.assertEqual(self.ckpt(WS)["owner"], "acct-b")
        self.write("scratch.txt", "uncommitted codex work\n")
        self.assertEqual(self.verify(WS).code, 0)
        resume = call("handoff", "resume", "--workstream", WS, "--to", "acct-a")
        self.assertEqual(resume.code, 0, resume.err)
        self.assertIn("/handoff", resume.out)
        self.assertNotIn("$handoff", resume.out)
        self.assertEqual(call("handoff", "claim", "--workstream", WS, "--to", "acct-a").code, 0)
        finish_t4 = self.task("t4", "acct-a", "verified", sole=False)
        self.set_now("2026-11-06T14:30:00Z")
        self.snapshot(("acct-a", "weekly", 93, NEXT_WEEK_RESET, "2026-11-06T14:30:00Z"))
        finish_t4()

        # Owner changes were logged (each starts a cooldown); outcomes were recorded for every task.
        events = [(e["from"], e["to"]) for e in self.owner_events()]
        self.assertEqual(events, [("acct-a", "acct-b"), ("acct-b", "acct-a")])
        tasks, _ = base.history.load_tasks(self.paths)
        self.assertEqual({t: (v["account"], v["result"]) for t, v in tasks.items()},
                         {"t1": ("acct-a", "partial"), "t2": ("acct-b", "verified"),
                          "t3": ("acct-b", "partial"), "t4": ("acct-a", "verified")})
        self.assertEqual(self.ckpt(WS)["owner"], "acct-a")


NOW_S = "2026-11-02T09:00:00Z"


if __name__ == "__main__":
    unittest.main()
