import hashlib
import json
import os
import re
import subprocess
import unittest
from unittest import mock

from tests.helpers import CtlCase, NOW, WEEK_RESET, call, git_available

from usagekit import gitutil, handoff, history

GIT_ENV = {"GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author@example.invalid",
           "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
FORBIDDEN = {"add", "commit", "stash", "checkout", "reset", "clean", "fetch", "push", "pull", "rm", "merge",
             "rebase", "switch", "restore", "apply", "init", "update-index", "gc", "tag", "branch", "remote"}
WS = "feat-x"


@unittest.skipUnless(git_available(), "git not available")
class HandoffCase(CtlCase):
    def setUp(self):
        super().setUp()
        self._git_saved = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.init()
        self.add_account("acct-a", "claude")
        self.add_account("acct-b", "codex")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.g("init", "-q", "-b", "main")
        self.write("a.txt", "one\n")
        self.write("b.txt", "two\n")
        self.g("add", ".")
        self.g("commit", "-q", "-m", "first")
        os.chdir(self.repo)

    def tearDown(self):
        for k, v in self._git_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    # ----- helpers -----
    def g(self, *args, cwd=None):
        r = subprocess.run(["git"] + list(args), cwd=cwd or self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def write(self, rel, text):
        full = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", newline="\n") as fh:
            fh.write(text)

    def commit(self, rel, text, msg="more"):
        self.write(rel, text)
        self.g("add", rel)
        self.g("commit", "-q", "-m", msg)

    def prepare(self, owner="acct-a", ws=WS, *extra):
        return call("handoff", "prepare", "--workstream", ws, "--owner", owner, "--goal", "ship x",
                    "--next", "run the tests", *extra)

    def ckpt_path(self, ws=WS):
        return os.path.join(self.repo, "handoffs", ws + ".checkpoint.md")

    def ckpt(self, ws=WS):
        return handoff.load_checkpoint(self.ckpt_path(ws))

    def verify(self, ws=WS):
        return call("handoff", "verify", "--workstream", ws)

    def prepared(self, *extra):
        r = self.prepare("acct-a", WS, *extra)
        self.assertEqual(r.code, 0, r.err)

    def assert_mismatch(self, *phrases):
        r = self.verify()
        self.assertEqual(r.code, 3, r.out + r.err)
        for ph in phrases:
            self.assertIn(ph, r.err)
        self.assertNotIn("Traceback", r.err)
        return r

    def owner_events(self):
        _t, ev = history.load_tasks(self.paths)
        return ev

    def tree_hash(self):
        h = hashlib.sha256()
        for base, dirs, files in os.walk(self.repo):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            for f in sorted(files):
                p = os.path.join(base, f)
                h.update(os.path.relpath(p, self.repo).encode() + b"\0")
                with open(p, "rb") as fh:
                    h.update(fh.read())
        return h.hexdigest()


class RecoveryAndMismatchTests(HandoffCase):
    def test_clean_match_recovers(self):
        self.write("a.txt", "one\nwork\n")
        self.write("new.txt", "fresh\n")
        self.prepared("--done", "started", "--remaining", "finish", "--accept", "tests pass",
                      "--verify", "make test=>3 failed=>fail", "--failure", "flaky", "--decision", "use X")
        data = self.ckpt()
        self.assertEqual(data["branch"], "main")
        self.assertEqual(data["uncommitted"]["paths"], ["a.txt", "new.txt"])
        self.assertEqual(data["verification"], [{"command": "make test", "result": "3 failed", "status": "fail"}])
        self.assertEqual(self.verify().code, 0)
        r = call("handoff", "resume", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(r.code, 0, r.err)
        self.assertIn("ship x", r.out)
        c = call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(c.code, 0, c.err)
        self.assertEqual(self.ckpt()["owner"], "acct-b")

    def test_branch_mismatch(self):
        self.prepared()
        self.g("checkout", "-q", "-b", "other")
        r = self.assert_mismatch("branch differs", "worktree")
        self.assertNotIn("head", r.err)

    def test_head_ahead(self):
        self.prepared()
        self.commit("c.txt", "c\n")
        self.assert_mismatch("head ahead")

    def test_head_behind(self):
        self.commit("c.txt", "c\n")
        self.prepared()
        self.g("reset", "-q", "--hard", "HEAD~1")
        self.assert_mismatch("head behind")

    def test_head_diverged(self):
        self.commit("c.txt", "c\n")
        self.prepared()
        self.g("reset", "-q", "--hard", "HEAD~1")
        self.commit("d.txt", "d\n")
        self.assert_mismatch("head diverged")

    def test_uncommitted_added(self):
        self.write("a.txt", "one\nwork\n")
        self.prepared()
        self.write("extra.txt", "x\n")
        self.assert_mismatch("uncommitted added: extra.txt")

    def test_uncommitted_removed(self):
        self.write("a.txt", "one\nwork\n")
        self.prepared()
        self.g("checkout", "-q", "--", "a.txt")
        self.assert_mismatch("uncommitted removed: a.txt")

    def test_uncommitted_modified(self):
        self.write("a.txt", "one\nwork\n")
        self.prepared()
        self.write("a.txt", "one\nother work\n")
        self.assert_mismatch("uncommitted modified")

    def test_untracked_bytes_are_hashed_with_paths(self):
        self.write("u.txt", "aaaa")
        self.prepared()
        self.write("u.txt", "bbbb")           # same path, same size, different bytes
        self.assert_mismatch("uncommitted modified")
        self.write("u.txt", "aaaa")
        self.assertEqual(self.verify().code, 0)
        os.rename(os.path.join(self.repo, "u.txt"), os.path.join(self.repo, "v.txt"))   # same bytes, other path
        self.assert_mismatch("uncommitted added: v.txt", "uncommitted removed: u.txt")

    def test_repo_differs_by_remote(self):
        self.g("remote", "add", "origin", "https://example.invalid/team/one.git")
        self.prepared()
        self.assertEqual(self.verify().code, 0)
        self.g("remote", "set-url", "origin", "https://example.invalid/team/two.git")
        self.assert_mismatch("repo differs")

    def test_checkpoint_files_do_not_count_as_uncommitted(self):
        self.prepared()
        first = self.ckpt()["uncommitted"]
        self.prepared()
        self.assertEqual(self.ckpt()["uncommitted"], first)
        self.assertEqual(first["paths"], [])
        self.write("handoffs/other.checkpoint.md", "# nothing\n")
        self.assertEqual(self.verify().code, 0)

    def test_detached_head(self):
        self.g("checkout", "-q", "--detach")
        self.prepared()
        self.assertIsNone(self.ckpt()["branch"])
        self.assertEqual(self.verify().code, 0)
        self.g("checkout", "-q", "main")
        self.assert_mismatch("branch differs", "(detached HEAD)")

    def test_repo_with_no_commits(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.g("init", "-q", "-b", "main", cwd=empty)
        os.chdir(empty)
        with open("notes.txt", "w") as fh:
            fh.write("n\n")
        self.assertEqual(self.prepare().code, 0)
        data = handoff.load_checkpoint(os.path.join(empty, "handoffs", WS + ".checkpoint.md"))
        self.assertIsNone(data["head_commit"])
        self.assertIn("notes.txt", data["uncommitted"]["paths"])
        self.assertEqual(self.verify().code, 0)
        with open("more.txt", "w") as fh:
            fh.write("m\n")
        self.assertEqual(self.verify().code, 3)

    def test_staged_changes_in_a_repo_without_commits_count(self):
        empty = os.path.join(self.tmp, "empty2")
        os.makedirs(empty)
        self.g("init", "-q", "-b", "main", cwd=empty)
        os.chdir(empty)
        with open("s.txt", "w") as fh:
            fh.write("s\n")
        self.g("add", "s.txt", cwd=empty)
        self.assertEqual(self.prepare().code, 0)
        data = handoff.load_checkpoint(os.path.join(empty, "handoffs", WS + ".checkpoint.md"))
        self.assertEqual(data["uncommitted"]["paths"], ["s.txt"])


class InputErrorTests(HandoffCase):
    def test_not_a_git_repo_exits_2(self):
        os.chdir(self.tmp)
        for argv in (("prepare", "--workstream", WS, "--owner", "acct-a", "--goal", "g", "--next", "n"),
                     ("verify", "--workstream", WS),
                     ("resume", "--workstream", WS, "--to", "acct-b"),
                     ("claim", "--workstream", WS, "--to", "acct-b")):
            r = call("handoff", *argv)
            self.assertEqual(r.code, 2, argv)
            self.assertNotIn("Traceback", r.err)
            self.assertIn("git", r.err)

    def test_malformed_checkpoint_exits_2(self):
        os.makedirs(os.path.join(self.repo, "handoffs"), exist_ok=True)
        bodies = ["# nothing here\n", "x\n```json\n{not json\n```\n", "x\n```json\n[1, 2]\n```\n",
                  "x\n```json\n{\"schema\": 1}\n```\n", "x\n```json\n{\"schema\": NaN}\n```\n"]
        for body in bodies:
            with open(self.ckpt_path(), "w") as fh:
                fh.write(body)
            for argv in (("verify", "--workstream", WS), ("resume", "--workstream", WS, "--to", "acct-b"),
                         ("claim", "--workstream", WS, "--to", "acct-b")):
                r = call("handoff", *argv)
                self.assertEqual(r.code, 2, (body, argv, r.err))
                self.assertIn("malformed", r.err)
                self.assertNotIn("Traceback", r.err)
            self.assertEqual(self.prepare().code, 2)     # never silently overwritten

    def test_missing_checkpoint_exits_2(self):
        self.assertEqual(self.verify("nope").code, 2)

    def test_invalid_slug_exits_2(self):
        for bad in ("Bad Slug", "-x", "a/b", "", "x" * 65):
            for argv in (("prepare", "--workstream", bad, "--owner", "acct-a", "--goal", "g", "--next", "n"),
                         ("verify", "--workstream", bad), ("resume", "--workstream", bad, "--to", "acct-b"),
                         ("claim", "--workstream", bad, "--to", "acct-b")):
                r = call("handoff", *argv)
                self.assertEqual(r.code, 2, (bad, argv))
                self.assertNotIn("Traceback", r.err)

    def test_bad_arguments_exit_2(self):
        self.assertEqual(self.prepare("nobody").code, 2)
        self.assertEqual(self.prepare("acct-a", WS, "--verify", "no arrows").code, 2)
        self.assertEqual(self.prepare("acct-a", WS, "--verify", "c=>r=>maybe").code, 2)
        self.assertEqual(self.prepare("acct-a", WS, "--base", "no-such-ref").code, 2)
        self.prepared()
        self.assertEqual(call("handoff", "resume", "--workstream", WS, "--to", "ghost").code, 2)


class OwnershipTests(HandoffCase):
    def test_owner_conflict_exit_3_and_take_over(self):
        self.prepared()
        r = self.prepare("acct-b")
        self.assertEqual(r.code, 3)
        self.assertIn("acct-a", r.err)
        self.assertEqual(self.ckpt()["owner"], "acct-a")
        self.assertEqual(self.owner_events(), [])
        r = self.prepare("acct-b", WS, "--take-over")
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(self.ckpt()["owner"], "acct-b")
        self.assertEqual([(e["from"], e["to"]) for e in self.owner_events()], [("acct-a", "acct-b")])

    def test_same_owner_can_re_prepare(self):
        self.prepared()
        self.assertEqual(self.prepare("acct-a").code, 0)
        self.assertEqual(self.owner_events(), [])

    def test_claim_sets_owner_and_logs_event_feeding_cooldown(self):
        self.prepared()
        r = call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(self.ckpt()["owner"], "acct-b")
        tasks, events = history.load_tasks(self.paths)
        self.assertEqual([(e["workstream"], e["from"], e["to"]) for e in events], [(WS, "acct-a", "acct-b")])
        from tests.helpers import utc
        self.assertTrue(history.in_cooldown(tasks, events, WS, utc("2026-11-02T10:00:00Z"), 4))
        self.assertFalse(history.in_cooldown(tasks, events, WS, utc("2026-11-02T14:00:00Z"), 4))
        again = call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(again.code, 0)
        self.assertEqual(len(self.owner_events()), 1)

    def test_claim_refused_on_mismatch(self):
        self.prepared()
        self.commit("c.txt", "c\n")
        r = call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(r.code, 3)
        self.assertIn("head ahead", r.err)
        self.assertEqual(self.ckpt()["owner"], "acct-a")
        self.assertEqual(self.owner_events(), [])

    def test_checkpoint_has_no_usage_or_account_data_beyond_alias(self):
        self.record("acct-a", "weekly", 73.25, resets_at=WEEK_RESET)
        self.edit_config(lambda c: c["accounts"]["acct-a"].update(plan="secretplan-77"))
        self.prepared("--done", "d")
        with open(self.ckpt_path(), encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("73.25", "secretplan-77", "five_hour", "reserve", "acct-b", "claude", "codex"):
            self.assertNotIn(needle, text)
        self.assertIn("acct-a", text)
        self.assertEqual(set(self.ckpt()), set(handoff.FIELDS))

    def test_credentials_stripped_from_remote(self):
        self.g("remote", "add", "origin", "https://someone:ghp_SECRET123@example.invalid/team/repo.git")
        self.prepared()
        with open(self.ckpt_path(), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("ghp_SECRET123", text)
        self.assertNotIn("someone", text)
        self.assertEqual(self.ckpt()["repo"]["remote"], "https://example.invalid/team/repo.git")

    def test_strip_credentials_forms(self):
        s = handoff.strip_credentials
        self.assertEqual(s("https://user:tok@host.example/a/b.git"), "https://host.example/a/b.git")
        self.assertEqual(s("https://tok@host.example/a.git"), "https://host.example/a.git")
        self.assertEqual(s("ssh://git@host.example:2222/a.git"), "ssh://host.example:2222/a.git")
        self.assertEqual(s("https://host.example/a.git?access_token=zzz#frag"), "https://host.example/a.git")
        self.assertEqual(s("git@host.example:team/a.git"), "host.example:team/a.git")
        self.assertEqual(s("/local/path/repo"), "repo")
        self.assertIsNone(s(None))
        self.assertIsNone(s(""))


class ResumeTests(HandoffCase):
    def test_prompts_differ_by_provider_and_forbid_discarding(self):
        self.write("a.txt", "one\nwork\n")
        self.prepared()
        claude = call("handoff", "resume", "--workstream", WS, "--to", "acct-a")
        codex = call("handoff", "resume", "--workstream", WS, "--to", "acct-b")
        self.assertEqual((claude.code, codex.code), (0, 0))
        self.assertNotEqual(claude.out, codex.out)
        self.assertIn("/handoff", claude.out)
        self.assertNotIn("$handoff", claude.out)
        self.assertIn("$handoff", codex.out)
        for out in (claude.out, codex.out):
            self.assertIn("Never discard, stash, commit, or overwrite", out)
            self.assertIn("ship x", out)
            self.assertIn("run the tests", out)
            self.assertIn("handoffs/%s.checkpoint.md" % WS, out)
            self.assertIn("main", out)
            self.assertIn(self.ckpt()["head_commit"], out)
            self.assertIn("handoff verify", out)
        js = call("handoff", "resume", "--workstream", WS, "--to", "acct-b", "--json").json
        self.assertEqual((js["ok"], js["provider"]), (True, "codex"))

    def test_mismatch_gives_exit_3_and_no_prompt_unless_show_anyway(self):
        self.prepared()
        self.commit("c.txt", "c\n")
        r = call("handoff", "resume", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(r.code, 3)
        self.assertEqual(r.out, "")
        self.assertIn("head ahead", r.err)
        r = call("handoff", "resume", "--workstream", WS, "--to", "acct-b", "--show-anyway")
        self.assertEqual(r.code, 3)
        self.assertIn("Never discard, stash, commit, or overwrite", r.out)
        self.assertIn("does NOT match", r.out)


class ReadOnlyTests(HandoffCase):
    def make_dirty(self):
        self.write("a.txt", "one\nstaged\n")
        self.g("add", "a.txt")
        self.write("b.txt", "two\nunstaged\n")
        self.write("untracked.txt", "u\n")

    def status(self):
        return self.g("status", "--porcelain=v1", "-uall")

    def test_verify_changes_nothing(self):
        self.make_dirty()
        self.prepared()
        self.assertEqual(self.verify().code, 0)
        self.write("fresh.txt", "x\n")
        before = (self.tree_hash(), self.status(), self.g("diff", "--cached"), self.g("stash", "list"))
        self.assertEqual(self.verify().code, 3)
        call("handoff", "resume", "--workstream", WS, "--to", "acct-b", "--show-anyway")
        call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
        self.assertEqual(before, (self.tree_hash(), self.status(), self.g("diff", "--cached"),
                                  self.g("stash", "list")))

    def test_git_argv_is_read_only(self):
        self.make_dirty()
        seen = []
        real = subprocess.run

        def spy(argv, *a, **kw):
            seen.append(list(argv))
            return real(argv, *a, **kw)

        with mock.patch.object(gitutil.subprocess, "run", spy):
            self.prepared()
            self.verify()
            call("handoff", "resume", "--workstream", WS, "--to", "acct-b")
            call("handoff", "claim", "--workstream", WS, "--to", "acct-b")
            self.two_checkpoint_route()
        self.assertTrue(seen)
        for argv in seen:
            self.assertEqual(argv[0], "git")
            rest = argv[1:]
            verb = next(x for i, x in enumerate(rest) if not x.startswith("-")
                        and not (i > 0 and rest[i - 1] in ("-C", "-c")))
            self.assertIn(verb, gitutil.READ_ONLY_VERBS, argv)
            self.assertNotIn(verb, FORBIDDEN, argv)

    def two_checkpoint_route(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-b", "weekly", 70, resets_at=WEEK_RESET)
        call("route", "recommend", "--type", "x", "--scope", "small", "--risk", "low", "--owner", "acct-b",
             "--checkpoint", WS)

    def test_runner_refuses_anything_that_writes(self):
        for verb in ("add", "commit", "stash", "checkout", "reset", "clean", "fetch", "push", "pull"):
            with self.assertRaises(handoff.CtlError):
                gitutil._run([verb, "."], cwd=self.repo)
        with self.assertRaises(handoff.CtlError):
            gitutil._run(["-C", self.repo, "commit", "-m", "x"])
        with self.assertRaises(handoff.CtlError):
            gitutil._run(["config", "user.name", "x"], cwd=self.repo)     # config only with --get


class RoutingCheckpointTests(HandoffCase):
    """route recommend --checkpoint: only a parseable checkpoint of the right workstream whose git state
    still verifies counts as a checkpoint; anything else is treated as none (not a crash)."""

    def setUp(self):
        super().setUp()
        for alias, weekly in (("acct-a", 70), ("acct-b", 30)):     # acct-b usable 20
            self.record(alias, "weekly", weekly, resets_at=WEEK_RESET)
            self.record(alias, "five_hour", 80, resets_in="3h")
        self.record("acct-a", "weekly", 0, resets_at=WEEK_RESET)      # owner exhausted
        self.est = ["--estimate", "acct-b:weekly=15"]   # 15*1.15 fits 20; 15*1.5 does not

    def route(self, *extra):
        r = self.recommend("--owner", "acct-a", *self.est, *extra)
        self.assertIn(r.code, (0, 4), r.err)
        self.assertNotIn("Traceback", r.err)
        return r.json, r.code

    def test_valid_checkpoint_counts(self):
        self.prepared()
        data, code = self.route("--checkpoint", WS)
        self.assertEqual((data["recommended"], data["action"], code), ("acct-b", "switch", 0))
        self.assertFalse([r for r in data["reasons"] if "not valid" in r])

    def test_git_state_mismatch_means_no_checkpoint(self):
        self.prepared()
        self.commit("c.txt", "c\n")
        data, code = self.route("--checkpoint", WS)
        self.assertEqual((data["action"], code), ("reduce-scope", 4))
        self.assertTrue([r for r in data["reasons"] if "not valid" in r and "head ahead" in r])

    def test_workstream_mismatch_means_no_checkpoint(self):
        self.prepared()
        data, code = self.route("--checkpoint", WS, "--workstream", "another")
        self.assertEqual(code, 4)
        self.assertTrue([r for r in data["reasons"] if "workstream" in r])
        data, code = self.route("--checkpoint", WS, "--workstream", WS)
        self.assertEqual(code, 0)

    def test_checkpoint_file_for_other_workstream_means_no_checkpoint(self):
        self.prepared()
        os.replace(self.ckpt_path(), self.ckpt_path("renamed"))
        data, code = self.route("--checkpoint", "renamed")
        self.assertEqual(code, 4)

    def test_malformed_checkpoint_means_no_checkpoint(self):
        os.makedirs(os.path.dirname(self.ckpt_path()))
        with open(self.ckpt_path(), "w") as fh:
            fh.write("```json\n{broken\n```\n")
        data, code = self.route("--checkpoint", WS)
        self.assertEqual(code, 4)
        self.assertTrue([r for r in data["reasons"] if "malformed" in r])

    def test_rebalance_needs_a_valid_checkpoint(self):
        self.record("acct-a", "weekly", 70, resets_at=WEEK_RESET)
        self.record("acct-b", "weekly", 80, resets_at=WEEK_RESET)
        args = ["--owner", "acct-a", "--estimate", "acct-a:weekly=20", "--checkpoint", WS]
        self.prepared()
        self.assertEqual(self.recommend(*args).json["action"], "switch")
        self.commit("c.txt", "c\n")      # checkpoint now stale
        self.assertEqual(self.recommend(*args).json["action"], "continue")


if __name__ == "__main__":
    unittest.main()
