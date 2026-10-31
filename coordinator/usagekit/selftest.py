"""Built-in self-test: fake accounts in a temporary state directory. Never touches the real home."""

import contextlib
import io
import json
import os
import shutil
import tempfile

from . import cli, config, gitutil

NOW = "2026-11-02T09:00:00Z"  # a Monday
ENV_KEYS = ("CLAUDE_SETUP_HOME", "HOME", "USERPROFILE", "USAGECTL_NOW")


def _call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def run(json_out=False):
    saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
    saved_skip = gitutil.SKIP_HOME_CHECK
    tmp = tempfile.mkdtemp(prefix="usagectl-selftest-")
    checks, failures = [], []

    def check(name, cond, detail=""):
        checks.append(name)
        if not cond:
            failures.append("%s %s" % (name, detail))

    try:
        os.environ["CLAUDE_SETUP_HOME"] = os.path.join(tmp, "home")
        os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(tmp, "user")
        os.environ["USAGECTL_NOW"] = NOW
        gitutil.SKIP_HOME_CHECK = True

        check("init", _call(["init"])[0] == 0)
        check("init refuses overwrite", _call(["init"])[0] == 2)
        paths = config.get_paths()
        cfg = config.load(paths)
        cfg["timezone"] = "+00:00"
        config.save(cfg, paths)
        for alias, provider in (("fake-one", "claude"), ("fake-two", "codex")):
            check("account add " + alias, _call(["account", "add", "--account", alias, "--provider", provider,
                                                 "--plan", "test", "--capability", "edit"])[0] == 0)
            check("window weekly", _call(["window", "add", "--account", alias, "--id", "weekly", "--kind", "weekly",
                                          "--units", "percent", "--reserve", "10"])[0] == 0)
            check("window session", _call(["window", "add", "--account", alias, "--id", "five_hour", "--kind",
                                           "session", "--units", "percent", "--reserve", "5"])[0] == 0)
        check("config validate", _call(["config", "validate"])[0] == 0)
        check("record weekly", _call(["usage", "record", "--account", "fake-one", "--window", "weekly",
                                      "--remaining", "60", "--resets-in", "4d"])[0] == 0)
        check("record session", _call(["usage", "record", "--account", "fake-one", "--window", "five_hour",
                                       "--remaining", "80", "--resets-in", "3h"])[0] == 0)
        snap = os.path.join(tmp, "snap.json")
        with open(snap, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"schema": 1, "observations": [
                {"account": "fake-two", "window": "weekly", "remaining": 50, "resets_at": "2026-11-06T09:00:00Z"},
                {"account": "fake-two", "window": "five_hour", "remaining": 70, "resets_at": "2026-11-02T12:00:00Z"},
            ]}, fh)
        check("import snapshot", _call(["usage", "import", snap])[0] == 0)
        code, out, _ = _call(["usage", "status", "--json"])
        status = json.loads(out) if code == 0 else {}
        check("status available", status.get("accounts", {}).get("fake-one", {}).get("state") == "available")
        check("pace", _call(["pace", "show", "--json"])[0] == 0)
        code, out, _ = _call(["route", "recommend", "--type", "refactor", "--scope", "small", "--risk", "low",
                              "--need", "edit", "--json"])
        rec = json.loads(out) if code == 0 else {}
        check("route recommends an account", rec.get("recommended") in ("fake-one", "fake-two"), out[:80])
        check("task start", _call(["task", "start", "--id", "st-1", "--type", "refactor", "--scope", "small",
                                   "--account", "fake-one"])[0] == 0)
        os.environ["USAGECTL_NOW"] = "2026-11-02T10:00:00Z"
        check("record later", _call(["usage", "record", "--account", "fake-one", "--window", "weekly",
                                     "--remaining", "55", "--resets-in", "3d23h"])[0] == 0)
        check("task finish", _call(["task", "finish", "--id", "st-1", "--result", "verified", "--sole-use"])[0] == 0)
        check("rejects bad input", _call(["usage", "record", "--account", "fake-one", "--window", "weekly",
                                          "--remaining", "150", "--no-reset"])[0] == 2)
    finally:
        gitutil.SKIP_HOME_CHECK = saved_skip
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)

    if json_out:
        print(json.dumps({"ok": not failures, "checks": len(checks), "failures": failures}, indent=2))
    elif failures:
        for f in failures:
            print("selftest FAILED: " + f)
    else:
        print("selftest ok (%d checks)" % len(checks))
    return 1 if failures else 0
