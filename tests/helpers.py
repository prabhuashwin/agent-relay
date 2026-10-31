"""Shared test helpers for the coordinator tests. Everything runs in temporary directories with fake accounts."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "coordinator"))

from usagekit import cli, config, handoff, usage  # noqa: E402
from usagekit.timeutil import UTC, Zone, parse_ts  # noqa: E402

NOW = "2026-11-02T09:00:00Z"  # a Monday
WEEK_RESET = "2026-11-06T12:00:00Z"  # Friday noon: 4.5 weighted workdays from NOW
ENV_KEYS = ("CLAUDE_SETUP_HOME", "HOME", "USERPROFILE", "USAGECTL_NOW")

WEEKLY = {"id": "weekly", "kind": "weekly", "scope": "shared", "units": "percent", "reserve": 10}
SESSION = {"id": "five_hour", "kind": "session", "scope": "shared", "units": "percent", "reserve": 5}


def git_available():
    return shutil.which("git") is not None


def tzdata_available():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/New_York")
        return True
    except Exception:
        return False


class Result:
    def __init__(self, code, out, err):
        self.code, self.out, self.err = code, out, err

    @property
    def json(self):
        return json.loads(self.out)


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return Result(code, out.getvalue(), err.getvalue())


class CtlCase(unittest.TestCase):
    """Temp home, temp HOME/USERPROFILE, fixed clock. Never touches the real home."""

    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
        self._saved_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="usagectl-test-")
        self.home = os.path.join(self.tmp, "home")
        os.environ["CLAUDE_SETUP_HOME"] = self.home
        os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(self.tmp, "user")
        os.environ["USAGECTL_NOW"] = NOW
        self.paths = config.get_paths()

    def tearDown(self):
        os.chdir(self._saved_cwd)
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ----- setup helpers -----
    def set_now(self, iso):
        os.environ["USAGECTL_NOW"] = iso

    def init(self, tz="+00:00", **overrides):
        self.assertEqual(call("init").code, 0)
        self.edit_config(lambda c: (c.update(timezone=tz), c.update(overrides)))

    def edit_config(self, fn):
        with open(self.paths.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
        fn(cfg)
        with open(self.paths.config, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(cfg, fh, indent=2)

    def add_account(self, alias, provider="claude", caps=("edit", "review"), windows=None, default_model=None):
        wins = [dict(WEEKLY), dict(SESSION)] if windows is None else [dict(w) for w in windows]

        def edit(cfg):
            cfg["accounts"][alias] = {"provider": provider, "plan": "test", "capabilities": list(caps),
                                      "default_model": default_model, "models": {}, "windows": wins}
        self.edit_config(edit)

    def record(self, account, window, remaining, resets_at=None, resets_in=None, observed_at=None, **extra):
        argv = ["usage", "record", "--account", account, "--window", window, "--remaining", str(remaining)]
        if resets_at:
            argv += ["--resets-at", resets_at]
        elif resets_in:
            argv += ["--resets-in", resets_in]
        else:
            argv += ["--no-reset"]
        if observed_at:
            argv += ["--observed-at", observed_at]
        for k, v in extra.items():
            argv += ["--" + k.replace("_", "-"), str(v)]
        r = call(*argv)
        self.assertEqual(r.code, 0, r.err)
        return r

    def two_accounts(self, a_weekly=70, b_weekly=80, a_session=80, b_session=80):
        """acct-a (claude) and acct-b (codex), both fresh with the Friday-noon weekly reset."""
        self.init()
        self.add_account("acct-a", "claude")
        self.add_account("acct-b", "codex")
        for alias, w, s in (("acct-a", a_weekly, a_session), ("acct-b", b_weekly, b_session)):
            self.record(alias, "weekly", w, resets_at=WEEK_RESET)
            self.record(alias, "five_hour", s, resets_in="3h")

    def recommend(self, *extra, typ="refactor", scope="small", risk="low"):
        return call("route", "recommend", "--type", typ, "--scope", scope, "--risk", risk, "--json", *extra)

    def append_task_event(self, event):
        os.makedirs(self.paths.state, exist_ok=True)
        with open(self.paths.tasks, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event) + "\n")

    def make_repo(self, checkpoint_slug=None):
        """A throwaway git repo outside the home; chdir into it. Returns its path."""
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "handoffs"))
        subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
        if checkpoint_slug:   # a valid checkpoint (workstream = slug) matching the empty repo
            data = handoff.build_checkpoint(repo, checkpoint_slug, "acct-a", "test goal", "test next",
                                            "2026-11-02T08:00:00Z")
            handoff.write_checkpoint(handoff.checkpoint_path(repo, checkpoint_slug), data)
        os.chdir(repo)
        return repo


# ----- unit-level builders (no CLI) -----

def make_cfg(accounts=None, **top):
    cfg = config.default_config()
    cfg["timezone"] = "+00:00"
    cfg.update(top)
    for alias, windows in (accounts or {}).items():
        cfg["accounts"][alias] = {"provider": "claude", "plan": "test", "capabilities": [], "default_model": None,
                                  "models": {}, "windows": [dict(w) for w in windows]}
    config.validate(cfg)
    return cfg


def make_obs(remaining, observed_at, resets_at=None):
    zone = Zone("+00:00")
    return {"remaining": remaining, "observed_at": observed_at, "resets_at": resets_at,
            "observed_dt": parse_ts(observed_at, zone), "reset_dt": parse_ts(resets_at, zone) if resets_at else None,
            "confidence": "high"}


def utc(iso):
    return parse_ts(iso, Zone("+00:00"))
