"""Tests for shared/render_skills.py."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(REPO, "shared")
GOLDEN = os.path.join(REPO, "tests", "golden", "claude")
sys.path.insert(0, SHARED)
import render_skills  # noqa: E402

NAMES = ("handoff", "decide", "recap", "checkpoint")


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


class TestRender(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="cs-render-")
        self.addCleanup(shutil.rmtree, self.out, True)

    def render(self, tool, names=None):
        return render_skills.render(tool, self.out, names)

    def test_claude_is_byte_identical_to_snapshot(self):
        self.render("claude", ["handoff", "decide", "recap"])
        for n in ("handoff", "decide", "recap"):
            self.assertEqual(read_bytes(os.path.join(self.out, n, "SKILL.md")),
                             read_bytes(os.path.join(GOLDEN, n + ".md")), n)

    def test_all_templates_render_for_both_tools_with_frontmatter(self):
        for tool in ("claude", "codex"):
            out = os.path.join(self.out, tool)
            self.assertEqual(render_skills.render(tool, out), sorted(NAMES))
            for n in NAMES:
                b = read_bytes(os.path.join(out, n, "SKILL.md"))
                self.assertNotIn(b"\r", b)
                self.assertNotIn(b"{{", b)
                lines = b.decode("utf-8").split("\n")
                self.assertEqual(lines[0], "---")
                self.assertEqual(lines[1], "name: " + n)
                self.assertTrue(lines[2].startswith("description: "))
                self.assertEqual(lines[3], "---")

    def test_codex_wording(self):
        self.render("codex")
        txt = {n: read_bytes(os.path.join(self.out, n, "SKILL.md")).decode("utf-8") for n in NAMES}
        for n, t in txt.items():
            self.assertNotIn("/clear", t, n)
            self.assertNotIn("Bash guard", t, n)
            self.assertNotIn("Edit tool", t, n)
        self.assertIn("Use on $handoff", txt["handoff"])
        self.assertIn("Use on $decide", txt["decide"])
        self.assertIn("Use on $recap", txt["recap"])
        self.assertIn("save it with $handoff", txt["recap"])
        self.assertIn("Start the new session with:", txt["handoff"])

    def test_decisions_header_stays_literal_for_both_tools(self):
        line = "Append-only, one line per decision, newest last. Add a row with `/decide <decision> -- <why>`; " \
               "`/handoff` also adds the session's new decisions."
        for tool in ("claude", "codex"):
            out = os.path.join(self.out, tool)
            render_skills.render(tool, out, ["decide"])
            self.assertIn(line, read_bytes(os.path.join(out, "decide", "SKILL.md")).decode("utf-8"))

    def test_checkpoint_mentions_usagectl_and_never_git_writes(self):
        self.render("claude", ["checkpoint"])
        t = read_bytes(os.path.join(self.out, "checkpoint", "SKILL.md")).decode("utf-8")
        self.assertIn("~/.claude-setup/bin/usagectl handoff prepare", t)
        self.assertIn("/checkpoint", t)

    def test_unknown_token_fails_and_writes_nothing(self):
        shared = os.path.join(self.out, "shared")
        shutil.copytree(SHARED, shared, ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(shared, "skills", "recap.tmpl.md"), "a", newline="\n") as f:
            f.write("{{nope}}\n")
        out = os.path.join(self.out, "o")
        with self.assertRaises(ValueError) as cm:
            render_skills.render("claude", out, None, shared_dir=shared)
        self.assertIn("nope", str(cm.exception))
        self.assertFalse(os.path.exists(out))

    def test_unknown_tool_and_skill_fail(self):
        with self.assertRaises(ValueError):
            self.render("nosuchtool")
        with self.assertRaises(ValueError):
            self.render("claude", ["nosuchskill"])

    def test_every_token_used_is_defined_for_every_tool(self):
        with open(os.path.join(SHARED, "tool-vars.json"), encoding="utf-8") as f:
            v = json.load(f)
        self.assertEqual(set(v["claude"]), set(v["codex"]))

    def test_cli(self):
        r = subprocess.run([sys.executable, os.path.join(SHARED, "render_skills.py"), "--tool", "codex",
                            "--out", self.out, "--skills", "decide,recap"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "decide", "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "handoff")))
        r = subprocess.run([sys.executable, os.path.join(SHARED, "render_skills.py"), "--tool", "codex",
                            "--out", self.out, "--skills", "bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("bogus", r.stderr)


if __name__ == "__main__":
    unittest.main()
