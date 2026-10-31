"""Tests for install.sh. Runs it through bash with HOME, USERPROFILE, CODEX_HOME and
CLAUDE_SETUP_HOME all inside a temp directory. Never touches the real home.

Most runs use --skip-self-test (PowerShell hook runs are slow on Windows); a few
tests exercise the self-tests, using copies of the kit that are broken for real.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WIN = os.name == "nt"
GOLDEN = os.path.join(REPO, "tests", "golden", "claude")


def _find_bash():
    if IS_WIN:
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.exists(p):
                return p
        return None  # never fall back to the WSL bash in System32
    return shutil.which("bash")


BASH = _find_bash()
REAL_CODEX = shutil.which("codex")


def fwd(p):
    return str(p).replace("\\", "/")


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, newline="\n" if "b" not in mode else None) as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def snapshot(root, skip=()):
    """{relative path: sha256 or '<dir>'} for everything under root."""
    out = {}
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root).replace("\\", "/")
        if rel_d != ".":
            out[rel_d] = "<dir>"
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            with open(p, "rb") as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return {k: v for k, v in out.items() if not any(k == s or k.startswith(s + "/") for s in skip)}


def path_without(*names):
    """PATH with every directory that holds one of the named executables removed."""
    keep = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and any(os.path.exists(os.path.join(d, n + e)) for n in names for e in ("", ".exe", ".cmd", ".bat")):
            continue
        keep.append(d)
    return os.pathsep.join(keep)


FAKE_CODEX = """#!/bin/sh
# fake codex for tests: forbids anything with "push" in its arguments
case "$*" in
  *execpolicy*check*) ;;
  *) exit 0 ;;
esac
case "$*" in
  *push*) echo '{"matchedRules":[{"prefixRuleMatch":{"decision":"forbidden"}}],"decision":"forbidden"}' ;;
  *) echo '{"matchedRules":[]}' ;;
esac
"""
FAKE_RTK = "#!/bin/sh\necho rtk-stub\n"


@unittest.skipIf(BASH is None, "Git Bash not found")
class InstallBase(unittest.TestCase):
    kit = REPO  # kit folder whose install.sh is run

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cs-inst-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.tmp, "proj")
        self.cx = os.path.join(self.tmp, "codexhome")
        self.cs = os.path.join(self.tmp, "cshome")
        self.bindir = os.path.join(self.tmp, "fakebin")
        self.other = os.path.join(self.tmp, "elsewhere")
        self.tmpdir = os.path.join(self.tmp, "tmpdir")
        for d in (self.home, self.proj, self.cx, self.cs, self.bindir, self.other, self.tmpdir):
            os.makedirs(d)
        write(os.path.join(self.bindir, "codex"), FAKE_CODEX)
        os.chmod(os.path.join(self.bindir, "codex"), 0o755)
        self.rtk = False
        self.codex_on_path = True

    # ---- helpers ----
    def env(self):
        e = dict(os.environ)
        for k in ("HOME", "USERPROFILE"):
            e[k] = fwd(self.home)
        e["CODEX_HOME"] = fwd(self.cx)
        e["CLAUDE_SETUP_HOME"] = fwd(self.cs)
        for k in ("TMPDIR", "TMP", "TEMP"):
            e[k] = fwd(self.tmpdir)
        e.pop("USAGECTL_NOW", None)
        if self.rtk:
            write(os.path.join(self.bindir, "rtk"), FAKE_RTK)
            os.chmod(os.path.join(self.bindir, "rtk"), 0o755)
            base = os.environ.get("PATH", "")
        else:
            base = path_without("rtk")
        if self.codex_on_path:
            e["PATH"] = self.bindir + os.pathsep + base
        else:
            e["PATH"] = path_without("rtk", "codex")  # fake bin dir left out too
        return e

    def run_install(self, *args, kit=None):
        kit = kit or self.kit
        script = fwd(os.path.join(kit, "install.sh"))
        return subprocess.run([BASH, script, *args], env=self.env(), cwd=self.other,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)

    def install(self, *opts, skip=True, expect=0, kit=None, target=None):
        args = list(opts)
        if skip:
            args.append("--skip-self-test")
        args.append(fwd(target or self.proj))
        r = self.run_install(*args, kit=kit)
        self.assertEqual(r.returncode, expect, "rc=%s\nSTDOUT:\n%s\nSTDERR:\n%s" % (r.returncode, r.stdout, r.stderr))
        return r

    def tree(self, skip_backups=False):
        return snapshot(self.tmp, skip=("home/.claude/backups",) if skip_backups else ())

    def make_kit_copy(self):
        dst = os.path.join(self.tmp, "kit")
        os.makedirs(dst)
        shutil.copy2(os.path.join(REPO, "install.sh"), dst)
        for f in ("CLAUDE.md", "AGENTS.md"):
            shutil.copy2(os.path.join(REPO, f), dst)
        for d in ("claude-files", "shared", "codex-files", "coordinator"):
            shutil.copytree(os.path.join(REPO, d), os.path.join(dst, d),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return dst

    def user_backup(self):
        root = os.path.join(self.home, ".claude", "backups", "claude-setup")
        dirs = sorted(d for d in os.listdir(root) if d.startswith("user-"))
        self.assertTrue(dirs, "no user backup folder")
        return os.path.join(root, dirs[-1])

    def project_backup(self):
        root = os.path.join(self.home, ".claude", "backups", "claude-setup")
        dirs = sorted(d for d in os.listdir(root) if not d.startswith("user-"))
        self.assertTrue(dirs, "no project backup folder")
        return os.path.join(root, dirs[-1])

    def backup_dirs(self):
        root = os.path.join(self.home, ".claude", "backups", "claude-setup")
        return sorted(os.listdir(root)) if os.path.isdir(root) else []

    def settings(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)


SCRIPT_EXT = ".ps1" if IS_WIN else ".sh"
CLAUDE_SCRIPTS = ["bash-guard", "context-check", "session-brief", "statusline"]


class TestClaudeMode(InstallBase):
    def test_default_is_claude_and_matches_previous_file_list(self):
        self.install()
        self._golden_and_hooks()
        c = os.path.join(self.home, ".claude")
        got = sorted(k for k, v in snapshot(c, skip=("backups",)).items() if v != "<dir>")
        want = sorted(
            ["agents/oracle.md", "agents/reviewer.md", "agents/scout.md", "agents/worker.md", "settings.json",
             "skills/crew/SKILL.md", "skills/decide/SKILL.md", "skills/handoff/SKILL.md", "skills/recap/SKILL.md"]
            + ["scripts/%s%s" % (s, SCRIPT_EXT) for s in CLAUDE_SCRIPTS])
        self.assertEqual(got, want)
        proj = sorted(k for k, v in snapshot(self.proj).items() if v != "<dir>")
        self.assertEqual(proj, [".claude/settings.json", "CLAUDE.md", "DECISIONS.md"])
        self.assertTrue(os.path.isdir(os.path.join(self.proj, "handoffs")))
        # nothing Codex-related
        self.assertFalse(os.path.exists(os.path.join(self.home, ".agents")))
        self.assertEqual(os.listdir(self.cx), [])
        self.assertEqual(os.listdir(self.cs), [])  # coordinator not installed in claude mode

    def _golden_and_hooks(self):
        for n in ("handoff", "decide", "recap"):
            with open(os.path.join(GOLDEN, n + ".md"), "rb") as f:
                want = f.read()
            with open(os.path.join(self.home, ".claude", "skills", n, "SKILL.md"), "rb") as f:
                self.assertEqual(f.read(), want, n)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "skills", "checkpoint")))
        self._hooks()

    def _hooks(self):
        s = self.settings(os.path.join(self.home, ".claude", "settings.json"))
        self.assertIn("statusline.", s["statusLine"]["command"])
        h = s["hooks"]
        self.assertEqual(len(h["UserPromptSubmit"]), 1)
        self.assertIn("context-check", json.dumps(h["UserPromptSubmit"]))
        ss = {g.get("matcher"): g for g in h["SessionStart"]}
        self.assertEqual(sorted(ss), ["compact", "startup|resume|clear"])
        self.assertIn("just compacted", json.dumps(ss["compact"]))
        self.assertIn("session-brief", json.dumps(ss["startup|resume|clear"]))
        self.assertEqual(len(h["PreToolUse"]), 1)
        self.assertEqual(h["PreToolUse"][0]["matcher"], "Bash")
        self.assertIn("bash-guard", json.dumps(h["PreToolUse"]))
        p = self.settings(os.path.join(self.proj, ".claude", "settings.json"))
        self.assertIn("Bash(git push:*)", p["permissions"]["deny"])
        self.assertIn("Bash(git status:*)", p["permissions"]["allow"])
        self.assertNotIn("hooks", p)

    def test_explicit_tool_claude_same_as_default(self):
        self.install("--tool", "claude")
        c = os.path.join(self.home, ".claude")
        got = sorted(k for k, v in snapshot(c, skip=("backups",)).items() if v != "<dir>")
        self.assertEqual(len(got), 9 + len(CLAUDE_SCRIPTS))
        self.assertTrue(os.path.isfile(os.path.join(self.proj, "CLAUDE.md")))
        self.assertFalse(os.path.exists(os.path.join(self.proj, "AGENTS.md")))
        self.assertEqual(os.listdir(self.cs), [])

    def test_claude_mode_refreshes_stale_project_copies(self):
        for f in ("agents/scout.md", "statusline.ps1", "context-check.log"):
            write(os.path.join(self.proj, ".claude", f), "old")
        write(os.path.join(self.proj, ".claude", "skills", "handoff", "SKILL.md"), "old")
        self.install()
        for f in ("agents", "skills", "statusline.ps1", "context-check.log"):
            self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude", f)), f)


class TestCodexAndBoth(InstallBase):
    def test_codex_only(self):
        self.install("--tool", "codex")
        for n in ("handoff", "decide", "recap", "checkpoint"):
            d = os.path.join(self.home, ".agents", "skills", n)
            self.assertTrue(os.path.isfile(os.path.join(d, "SKILL.md")), n)
            self.assertTrue(os.path.isfile(os.path.join(d, ".claude-setup")), n)
        txt = read(os.path.join(self.home, ".agents", "skills", "handoff", "SKILL.md"))
        self.assertIn("$handoff", txt)
        self.assertNotIn("/clear", txt)
        self.assertEqual(read(os.path.join(self.cx, "rules", "claude-setup.rules")),
                         read(os.path.join(REPO, "codex-files", "rules", "claude-setup.rules")))
        self.assertTrue(os.path.isfile(os.path.join(self.cs, "coordinator", "usagectl.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.cs, "bin", "usagectl")))
        self.assertTrue(os.path.isfile(os.path.join(self.cs, "bin", "usagectl.cmd")))
        self.assertFalse(os.path.exists(os.path.join(self.cs, "coordinator", "__pycache__")))
        a = read(os.path.join(self.proj, "AGENTS.md"))
        self.assertTrue(a.startswith("# Project notes"))
        self.assertIn("<!-- claude-setup:start -->", a)
        self.assertIn("<!-- claude-setup:end -->", a)
        # Claude parts untouched
        self.assertFalse(os.path.exists(os.path.join(self.proj, "CLAUDE.md")))
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude")))
        c = os.path.join(self.home, ".claude")
        for x in ("settings.json", "agents", "skills", "scripts"):
            self.assertFalse(os.path.exists(os.path.join(c, x)), x)
        self.assertTrue(os.path.isdir(os.path.join(self.proj, "handoffs")))
        self.assertTrue(os.path.isfile(os.path.join(self.proj, "DECISIONS.md")))

    def test_both(self):
        r = self.install("--tool", "both")
        self.assertIn("Self-tests skipped", r.stdout)
        self.assertNotIn("self-test: OK", r.stdout)
        c = os.path.join(self.home, ".claude")
        self.assertTrue(os.path.isfile(os.path.join(c, "settings.json")))
        self.assertTrue(os.path.isfile(os.path.join(c, "skills", "checkpoint", "SKILL.md")))
        self.assertIn("/checkpoint", read(os.path.join(c, "skills", "checkpoint", "SKILL.md")))
        self.assertIn("$checkpoint", read(os.path.join(self.home, ".agents", "skills", "checkpoint", "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.proj, "CLAUDE.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.proj, "AGENTS.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.cs, "coordinator", "usagectl.py")))
        for n in ("handoff", "decide", "recap"):
            with open(os.path.join(GOLDEN, n + ".md"), "rb") as f:
                with open(os.path.join(c, "skills", n, "SKILL.md"), "rb") as g:
                    self.assertEqual(f.read(), g.read())

    def test_agents_md_size_warning(self):
        write(os.path.join(self.proj, "AGENTS.md"), "x" * 40000 + "\n")
        r = self.install("--tool", "codex")
        self.assertIn("32768", r.stdout)

    def test_kit_itself_agents_md_unchanged(self):
        kit = self.make_kit_copy()
        before = {f: read(os.path.join(kit, f)) for f in ("AGENTS.md", "CLAUDE.md")}
        r = self.install("--tool", "both", kit=kit, target=kit)
        self.assertIn("AGENTS.md: this is the kit itself", r.stdout)
        for f, t in before.items():
            self.assertEqual(read(os.path.join(kit, f)), t)


class TestOptions(InstallBase):
    def test_option_order(self):
        for args in (["--tool", "codex", "--dry-run", fwd(self.proj)],
                     [fwd(self.proj), "--dry-run", "--tool", "codex"],
                     ["--dry-run", fwd(self.proj), "--tool=codex"]):
            r = self.run_install(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Dry run (tool: codex)", r.stdout)
        r = self.run_install(fwd(self.proj), "--tool", "codex", "--skip-self-test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.proj, "AGENTS.md")))
        self.assertFalse(os.path.exists(os.path.join(self.proj, "CLAUDE.md")))

    def test_invalid_options_change_nothing(self):
        before = self.tree()
        p = fwd(self.proj)
        cases = [(["--tool", "bogus", p], 2), (["--tool", "Claude", p], 2), ([p, "--tool"], 2), (["--wat", p], 2),
                 ([p, p + "/x"], 2), (["--tool", p], 2), ([], 1), (["-h"], 1), (["--help", p], 1),
                 (["--dry-run"], 1), ([fwd(self.proj) + "-missing"], 1)]
        for args, rc in cases:
            r = self.run_install(*args)
            self.assertEqual(r.returncode, rc, "%s -> %s\n%s%s" % (args, r.returncode, r.stdout, r.stderr))
            if rc == 1 and not args[-1:] == [fwd(self.proj) + "-missing"]:
                self.assertIn("Usage", r.stdout)
        self.assertEqual(before, self.tree())


class TestPreservation(InstallBase):
    def seed(self):
        c = os.path.join(self.home, ".claude")
        write(os.path.join(c, "settings.json"), json.dumps({
            "model": "opus", "env": {"A": "1"},
            "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "my-edit-hook"}]}],
                      "Stop": [{"hooks": [{"type": "command", "command": "my-stop"}]}]}}, indent=2))
        write(os.path.join(c, "skills", "mine", "SKILL.md"), "my own claude skill")
        write(os.path.join(c, "agents", "mine.md"), "my agent")
        write(os.path.join(self.proj, ".claude", "settings.json"),
              json.dumps({"permissions": {"allow": ["Bash(make:*)"], "deny": ["Bash(rm:*)"]}, "env": {"P": "1"}}))
        write(os.path.join(self.proj, "CLAUDE.md"), "# Mine\n\nclaude notes\n")
        write(os.path.join(self.proj, "AGENTS.md"), "# Mine\n\ncodex notes\n")
        write(os.path.join(self.proj, "DECISIONS.md"), "# Decisions\n\n| 2020-01-01 | keep me | y | - |\n")
        write(os.path.join(self.cx, "config.toml"), 'model = "x"\n')
        write(os.path.join(self.cx, "rules", "default.rules"), 'prefix_rule(pattern=["ls"], decision="allow")\n')
        write(os.path.join(self.home, ".agents", "skills", "foreign", "SKILL.md"), "foreign skill")
        write(os.path.join(self.home, ".agents", "skills", "recap", "SKILL.md"), "foreign recap, no marker")

    def test_existing_content_preserved(self):
        self.seed()
        r = self.install("--tool", "both")
        c = os.path.join(self.home, ".claude")
        s = self.settings(os.path.join(c, "settings.json"))
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["env"], {"A": "1"})
        self.assertIn("my-stop", json.dumps(s["hooks"]["Stop"]))
        self.assertIn("my-edit-hook", json.dumps(s["hooks"]["PreToolUse"]))
        self.assertIn("bash-guard", json.dumps(s["hooks"]["PreToolUse"]))
        self.assertEqual(read(os.path.join(c, "skills", "mine", "SKILL.md")), "my own claude skill")
        self.assertEqual(read(os.path.join(c, "agents", "mine.md")), "my agent")
        p = self.settings(os.path.join(self.proj, ".claude", "settings.json"))
        self.assertEqual(p["env"], {"P": "1"})
        self.assertIn("Bash(make:*)", p["permissions"]["allow"])
        self.assertIn("Bash(rm:*)", p["permissions"]["deny"])
        self.assertIn("Bash(git push:*)", p["permissions"]["deny"])
        self.assertIn("claude notes", read(os.path.join(self.proj, "CLAUDE.md")))
        self.assertIn("codex notes", read(os.path.join(self.proj, "AGENTS.md")))
        self.assertIn("keep me", read(os.path.join(self.proj, "DECISIONS.md")))
        self.assertEqual(read(os.path.join(self.cx, "config.toml")), 'model = "x"\n')
        self.assertEqual(read(os.path.join(self.cx, "rules", "default.rules")),
                         'prefix_rule(pattern=["ls"], decision="allow")\n')
        sk = os.path.join(self.home, ".agents", "skills")
        self.assertEqual(read(os.path.join(sk, "foreign", "SKILL.md")), "foreign skill")
        self.assertEqual(read(os.path.join(sk, "recap", "SKILL.md")), "foreign recap, no marker")
        self.assertFalse(os.path.exists(os.path.join(sk, "recap", ".claude-setup")))
        self.assertIn("not managed by claude-setup", r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(sk, "handoff", ".claude-setup")))  # ours still installed

    def test_config_json_and_state_preserved(self):
        self.install("--tool", "codex")
        write(os.path.join(self.cs, "config.json"), '{"version":1}\n')
        write(os.path.join(self.cs, "state", "usage.jsonl"), '{"x":1}\n')
        write(os.path.join(self.cs, "coordinator", "stale.py"), "old")
        self.install("--tool", "codex")
        self.assertEqual(read(os.path.join(self.cs, "config.json")), '{"version":1}\n')
        self.assertEqual(read(os.path.join(self.cs, "state", "usage.jsonl")), '{"x":1}\n')
        self.assertFalse(os.path.exists(os.path.join(self.cs, "coordinator", "stale.py")))


class TestBackups(InstallBase):
    def test_every_overwritten_asset_is_backed_up(self):
        c = os.path.join(self.home, ".claude")
        old = {
            os.path.join(c, "settings.json"): '{"model": "old"}',
            os.path.join(c, "agents", "scout.md"): "old scout",
            os.path.join(c, "skills", "handoff", "SKILL.md"): "old handoff",
            os.path.join(c, "skills", "crew", "SKILL.md"): "old crew",
            os.path.join(c, "scripts", "bash-guard" + SCRIPT_EXT): "old guard",
            os.path.join(self.cx, "rules", "claude-setup.rules"): "old rules",
            os.path.join(self.home, ".agents", "skills", "decide", "SKILL.md"): "old codex decide",
            os.path.join(self.home, ".agents", "skills", "decide", ".claude-setup"): "x",
            os.path.join(self.cs, "coordinator", "usagectl.py"): "old coordinator",
            os.path.join(self.cs, "bin", "usagectl"): "old shim",
            os.path.join(self.proj, "CLAUDE.md"): "old claude md\n",
            os.path.join(self.proj, "AGENTS.md"): "old agents md\n",
            os.path.join(self.proj, ".claude", "settings.json"): '{"env": {"Q": "1"}}',
        }
        for p, t in old.items():
            write(p, t)
        write(os.path.join(c, "scripts", "context-check.log"), "log must not matter")
        self.install("--tool", "both")
        ub, pb = self.user_backup(), self.project_backup()
        self.assertEqual(len(self.backup_dirs()), 2)
        want = {
            os.path.join(ub, "settings.json"): old[os.path.join(c, "settings.json")],
            os.path.join(ub, "agents", "scout.md"): "old scout",
            os.path.join(ub, "skills", "handoff", "SKILL.md"): "old handoff",
            os.path.join(ub, "skills", "crew", "SKILL.md"): "old crew",
            os.path.join(ub, "scripts", "bash-guard" + SCRIPT_EXT): "old guard",
            os.path.join(ub, "codex-rules", "claude-setup.rules"): "old rules",
            os.path.join(ub, "codex-skills", "decide", "SKILL.md"): "old codex decide",
            os.path.join(ub, "coordinator", "coordinator", "usagectl.py"): "old coordinator",
            os.path.join(ub, "coordinator", "bin", "usagectl"): "old shim",
            os.path.join(pb, "CLAUDE.md"): "old claude md\n",
            os.path.join(pb, "AGENTS.md"): "old agents md\n",
            os.path.join(pb, "dot-claude", "settings.json"): '{"env": {"Q": "1"}}',
        }
        for p, t in want.items():
            self.assertTrue(os.path.isfile(p), "missing backup " + p)
            self.assertEqual(read(p), t, p)

    def test_foreign_codex_skill_not_backed_up_as_ours(self):
        write(os.path.join(self.home, ".agents", "skills", "decide", "SKILL.md"), "foreign")
        self.install("--tool", "codex")
        self.assertFalse(os.path.exists(os.path.join(self.user_backup(), "codex-skills", "decide")))


class TestDryRun(InstallBase):
    def test_dry_run_leaves_tree_byte_identical(self):
        for tool, populate in (("both", False), ("claude", True), ("codex", True), ("both", True)):
            if populate and not os.path.exists(os.path.join(self.home, ".claude", "settings.json")):
                self.install("--tool", "both")
                write(os.path.join(self.proj, "CLAUDE.md"), "# edited\n")
            before = self.tree()
            r = self.run_install("--dry-run", "--tool", tool, fwd(self.proj))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("would ", r.stdout)
            self.assertEqual(before, self.tree(), "dry run changed the tree (%s, populated=%s)" % (tool, populate))

    def test_dry_run_reports_foreign_skill_skip(self):
        write(os.path.join(self.home, ".agents", "skills", "handoff", "SKILL.md"), "foreign")
        r = self.run_install("--dry-run", "--tool", "codex", fwd(self.proj))
        self.assertIn("would skip skill handoff", r.stdout)

    def test_preflight_failure_in_dry_run_is_nonzero(self):
        write(os.path.join(self.home, ".claude", "settings.json"), "{not json")
        before = self.tree()
        r = self.run_install("--dry-run", "--tool", "claude", fwd(self.proj))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not valid JSON", r.stdout)
        self.assertEqual(before, self.tree())


class TestPreflightFailures(InstallBase):
    def assert_fails_unchanged(self, *opts, expect_text):
        before = self.tree()
        r = self.run_install("--skip-self-test", *opts, fwd(self.proj))
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn(expect_text, r.stdout + r.stderr)
        self.assertIn("nothing was changed", r.stdout)
        self.assertEqual(before, self.tree())

    def test_malformed_user_settings(self):
        write(os.path.join(self.home, ".claude", "settings.json"), '{"a": ')
        self.assert_fails_unchanged("--tool", "both", expect_text="not valid JSON")

    def test_malformed_project_settings(self):
        write(os.path.join(self.proj, ".claude", "settings.json"), "nope")
        self.assert_fails_unchanged(expect_text="not valid JSON")

    def test_settings_not_an_object(self):
        write(os.path.join(self.home, ".claude", "settings.json"), "[1, 2]")
        self.assert_fails_unchanged(expect_text="JSON object")

    def test_damaged_claude_md_markers(self):
        write(os.path.join(self.proj, "CLAUDE.md"), "notes\n<!-- claude-setup:start -->\nhalf a block\n")
        self.assert_fails_unchanged(expect_text="CLAUDE.md")

    def test_damaged_agents_md_markers(self):
        write(os.path.join(self.proj, "AGENTS.md"), "<!-- claude-setup:end -->\nreversed\n<!-- claude-setup:start -->\n")
        self.assert_fails_unchanged("--tool", "codex", expect_text="AGENTS.md")

    def test_damaged_markers_only_matter_for_the_selected_tool(self):
        write(os.path.join(self.proj, "CLAUDE.md"), "<!-- claude-setup:start -->\nbroken\n")
        write(os.path.join(self.home, ".claude", "settings.json"), "{bad")
        self.install("--tool", "codex")
        write(os.path.join(self.proj, "AGENTS.md"), "<!-- claude-setup:start -->\nbroken\n")
        os.remove(os.path.join(self.proj, "CLAUDE.md"))
        os.remove(os.path.join(self.home, ".claude", "settings.json"))
        self.install("--tool", "claude")

    def test_missing_kit_file(self):
        kit = self.make_kit_copy()
        os.remove(os.path.join(kit, "codex-files", "rules", "claude-setup.rules"))
        before = self.tree()
        r = self.run_install("--tool", "codex", "--skip-self-test", fwd(self.proj), kit=kit)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kit file missing", r.stdout)
        self.assertEqual(before, self.tree())

    def test_unknown_template_token_fails_render(self):
        kit = self.make_kit_copy()
        with open(os.path.join(kit, "shared", "skills", "recap.tmpl.md"), "a", newline="\n") as f:
            f.write("{{no_such_token}}\n")
        before = self.tree()
        r = self.run_install("--skip-self-test", fwd(self.proj), kit=kit)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no_such_token", r.stdout + r.stderr)
        self.assertEqual(before, self.tree())


class TestIdempotence(InstallBase):
    def test_reinstall_is_identical_apart_from_backups(self):
        write(os.path.join(self.proj, "CLAUDE.md"), "# Mine\nnotes\n")
        write(os.path.join(self.proj, "AGENTS.md"), "# Mine\ncodex notes\n")
        self.install("--tool", "both")
        first = self.tree(skip_backups=True)
        self.install("--tool", "both")
        self.assertEqual(first, self.tree(skip_backups=True))
        self.assertGreaterEqual(len(self.backup_dirs()), 4)
        for f in ("CLAUDE.md", "AGENTS.md"):
            t = read(os.path.join(self.proj, f))
            self.assertEqual(t.count("<!-- claude-setup:start -->"), 1, f)
            self.assertEqual(t.count("<!-- claude-setup:end -->"), 1, f)

    def test_backup_pruning_keeps_ten(self):
        root = os.path.join(self.home, ".claude", "backups", "claude-setup")
        for i in range(12):
            write(os.path.join(root, "old-%02d" % i, "f"), "x")
            t = 1_600_000_000 + i
            os.utime(os.path.join(root, "old-%02d" % i), (t, t))
        r = self.install()
        self.assertEqual(len(self.backup_dirs()), 10)
        self.assertIn("Pruned 4 old backup(s)", r.stdout)


class TestRtk(InstallBase):
    def dry(self):
        r = self.run_install("--dry-run", fwd(self.proj))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_rtk_found_on_path(self):
        self.rtk = True
        self.assertIn("RTK: found at", self.dry().stdout)

    def test_rtk_found_in_headroom(self):
        write(os.path.join(self.home, ".headroom", "bin", "rtk"), FAKE_RTK)
        os.chmod(os.path.join(self.home, ".headroom", "bin", "rtk"), 0o755)
        r = self.dry()
        self.assertIn("RTK: found at", r.stdout)
        self.assertIn(".headroom", r.stdout)

    def test_rtk_missing(self):
        self.assertIn("RTK: not found; plain commands work, filter output with grep/tail", self.dry().stdout)

    def test_rtk_message_also_printed_by_a_real_install(self):
        self.assertIn("RTK: not found", self.install("--tool", "codex").stdout)


class TestSelfTests(InstallBase):
    def test_all_self_tests_pass(self):
        r = self.install("--tool", "both", skip=False)
        for t in ("Context check self-test: OK", "Context check (post-compact) self-test: OK", "Bash guard self-test: OK",
                  "Bash guard multi-line self-test: OK", "Session brief self-test: OK", "user settings.json: OK",
                  "project settings.json: OK", "Codex rules self-test: OK", "Codex skills self-test: OK",
                  "Coordinator self-test: OK"):
            self.assertIn(t, r.stdout)
        self.assertNotIn("FAILED", r.stdout)

    def test_failed_claude_self_test_exits_1(self):
        kit = self.make_kit_copy()
        broken = os.path.join(kit, "claude-files", "scripts", "context-check" + SCRIPT_EXT)
        write(broken, "exit 3\n" if IS_WIN else "#!/usr/bin/env bash\nexit 3\n")
        r = self.install(skip=False, expect=1, kit=kit)
        self.assertIn("Context check self-test: FAILED", r.stdout)
        self.assertIn("self-test(s) failed", r.stdout)

    def test_codex_missing_is_skipped_not_failed(self):
        self.codex_on_path = False
        r = self.install("--tool", "codex", skip=False)
        self.assertIn("Codex rules self-test: skipped: codex not on PATH", r.stdout)

    def test_codex_self_test_failures_exit_1(self):
        # permissive codex stub, broken decide template, broken coordinator: three failures, counted
        kit = self.make_kit_copy()
        write(os.path.join(self.bindir, "codex"), "#!/bin/sh\necho '{\"matchedRules\":[]}'\n")
        write(os.path.join(kit, "shared", "skills", "decide.tmpl.md"), "no frontmatter here\n")
        write(os.path.join(kit, "coordinator", "usagectl.py"), "import sys\nsys.exit(1)\n")
        r = self.install("--tool", "codex", skip=False, expect=1, kit=kit)
        self.assertIn("Codex rules self-test: FAILED", r.stdout)
        self.assertIn("Codex skills self-test: FAILED", r.stdout)
        self.assertIn("Coordinator self-test: FAILED", r.stdout)
        self.assertIn("3 self-test(s) failed", r.stdout)


@unittest.skipIf(REAL_CODEX is None, "codex not installed")
class TestRealCodexExecpolicy(unittest.TestCase):
    RULES = os.path.join(REPO, "codex-files", "rules", "claude-setup.rules")

    def check(self, *cmd):
        r = subprocess.run([REAL_CODEX, "execpolicy", "check", "--rules", self.RULES, "--", *cmd],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           shell=IS_WIN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_forbidden(self):
        for cmd in (("git", "push", "origin", "main"), ("aws", "s3", "ls"), ("gh", "pr", "merge", "3"),
                    ("gh", "repo", "delete", "a/b"), ("gh", "release", "create", "v1")):
            self.assertEqual(self.check(*cmd).get("decision"), "forbidden", cmd)

    def test_not_forbidden(self):
        for cmd in (("git", "status"), ("git", "pull"), ("gh", "pr", "view", "3"), ("ls",)):
            self.assertNotEqual(self.check(*cmd).get("decision"), "forbidden", cmd)


if __name__ == "__main__":
    unittest.main()
