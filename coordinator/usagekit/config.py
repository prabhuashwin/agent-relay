"""Paths, config defaults, validation, atomic load/save."""

import copy
import json
import math
import os
import re
import tempfile

from . import gitutil
from .errors import CtlError
from .timeutil import DAYS, Zone

ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
UNITS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
KINDS = ("session", "weekly", "other")
PROVIDERS = ("claude", "codex")

DEFAULT_CONFIG = {
    "version": 1,
    "timezone": "local",
    "stale_after_minutes": {"session": 60, "weekly": 720, "other": 720},
    "workday_weights": {"mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 0, "sun": 0},
    "preferred_provider": None,
    "claude_capture_account": None,
    "spending_policy": {"paid_api_fallback": False, "credit_purchases": False, "paid_resets": False},
    "routing": {"switch_overhead_with_checkpoint": 0.15, "switch_overhead_without_checkpoint": 0.5,
                "switch_margin": 0.25, "switch_cooldown_hours": 4, "min_history_samples": 3},
    "accounts": {},
}


class Paths:
    def __init__(self, home):
        self.home = home
        self.config = os.path.join(home, "config.json")
        self.state = os.path.join(home, "state")
        self.usage = os.path.join(self.state, "usage.jsonl")
        self.tasks = os.path.join(self.state, "tasks.jsonl")


def get_paths():
    home = os.environ.get("CLAUDE_SETUP_HOME")
    if not home:
        base = os.environ.get("HOME") or os.environ.get("USERPROFILE") or os.path.expanduser("~")
        home = os.path.join(base, ".claude-setup")
    return Paths(os.path.abspath(home))


def ensure_writable(paths):
    gitutil.ensure_home_safe(paths.home)


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


# ---------- validation ----------

def _keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise CtlError("config: %s must be an object" % where)
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise CtlError("config: unknown key(s) in %s: %s" % (where, ", ".join(map(str, extra))))


def _num(v, where, minimum=0, maximum=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise CtlError("config: %s must be a number" % where)
    if v < minimum or (maximum is not None and v > maximum):
        raise CtlError("config: %s out of range" % where)


def _bool(v, where):
    if not isinstance(v, bool):
        raise CtlError("config: %s must be true or false" % where)


def fill_defaults(raw):
    """Fill missing optional keys. Does not hide unknown keys (validate rejects those)."""
    if not isinstance(raw, dict):
        raise CtlError("config: top level must be an object")
    cfg = copy.deepcopy(raw)
    for key, default in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and key != "accounts" and isinstance(cfg[key], dict):
            for k2, v2 in default.items():
                cfg[key].setdefault(k2, v2)
    accounts = cfg.get("accounts")
    if isinstance(accounts, dict):
        for acct in accounts.values():
            if not isinstance(acct, dict):
                continue
            acct.setdefault("capabilities", [])
            acct.setdefault("default_model", None)
            acct.setdefault("models", {})
            acct.setdefault("windows", [])
            if isinstance(acct["windows"], list):
                for w in acct["windows"]:
                    if isinstance(w, dict):
                        w.setdefault("scope", "shared")
                        w.setdefault("reserve", 0)
    return cfg


def validate(cfg):
    _keys(cfg, DEFAULT_CONFIG.keys(), "top level")
    if cfg.get("version") != 1 or isinstance(cfg.get("version"), bool):
        raise CtlError("config: version must be 1")
    tz = cfg["timezone"]
    if not isinstance(tz, str):
        raise CtlError("config: timezone must be a string")
    Zone(tz)
    _keys(cfg["stale_after_minutes"], KINDS, "stale_after_minutes")
    for k in KINDS:
        _num(cfg["stale_after_minutes"].get(k), "stale_after_minutes.%s" % k, minimum=0.001)
    _keys(cfg["workday_weights"], DAYS, "workday_weights")
    for d in DAYS:
        _num(cfg["workday_weights"].get(d), "workday_weights.%s" % d)
    if cfg["preferred_provider"] not in (None,) + PROVIDERS:
        raise CtlError("config: preferred_provider must be null, claude or codex")
    sp = cfg["spending_policy"]
    _keys(sp, DEFAULT_CONFIG["spending_policy"], "spending_policy")
    for k in DEFAULT_CONFIG["spending_policy"]:
        _bool(sp.get(k), "spending_policy.%s" % k)
    rt = cfg["routing"]
    _keys(rt, DEFAULT_CONFIG["routing"], "routing")
    for k in DEFAULT_CONFIG["routing"]:
        _num(rt.get(k), "routing.%s" % k)
    if rt["min_history_samples"] < 1:
        raise CtlError("config: routing.min_history_samples must be at least 1")
    accounts = cfg["accounts"]
    if not isinstance(accounts, dict):
        raise CtlError("config: accounts must be an object")
    for alias, acct in accounts.items():
        _validate_account(alias, acct)
    capture = cfg.get("claude_capture_account")
    if capture is not None and (not isinstance(capture, str) or capture not in accounts or accounts[capture]['provider'] != 'claude'):
        raise CtlError('config: claude_capture_account must name a configured Claude account or be null')
    return cfg


def _validate_account(alias, acct):
    if not ALIAS_RE.match(alias):
        raise CtlError("config: invalid account alias %r (lowercase letters, digits, - and _; no e-mails)" % alias)
    where = "accounts.%s" % alias
    _keys(acct, ("provider", "plan", "capabilities", "default_model", "models", "windows"), where)
    if acct.get("provider") not in PROVIDERS:
        raise CtlError("config: %s.provider must be claude or codex" % where)
    if not isinstance(acct.get("plan"), str) or not acct["plan"]:
        raise CtlError("config: %s.plan must be a non-empty string" % where)
    caps = acct["capabilities"]
    if not isinstance(caps, list) or not all(isinstance(c, str) and c for c in caps):
        raise CtlError("config: %s.capabilities must be a list of strings" % where)
    if acct["default_model"] is not None and not (isinstance(acct["default_model"], str) and acct["default_model"]):
        raise CtlError("config: %s.default_model must be null or a string" % where)
    if not isinstance(acct["models"], dict):
        raise CtlError("config: %s.models must be an object" % where)
    wins = acct["windows"]
    if not isinstance(wins, list):
        raise CtlError("config: %s.windows must be a list" % where)
    seen = set()
    for w in wins:
        _validate_window(alias, w, seen)


def _validate_window(alias, w, seen):
    where = "accounts.%s.windows" % alias
    _keys(w, ("id", "kind", "scope", "units", "reserve"), where)
    wid = w.get("id")
    if not isinstance(wid, str) or not ALIAS_RE.match(wid):
        raise CtlError("config: %s: invalid window id %r" % (where, wid))
    if wid in seen:
        raise CtlError("config: %s: duplicate window id %r" % (where, wid))
    seen.add(wid)
    if w.get("kind") not in KINDS:
        raise CtlError("config: window %s kind must be one of %s" % (wid, "/".join(KINDS)))
    scope = w.get("scope")
    if not (scope == "shared" or (isinstance(scope, str) and re.fullmatch(r"model:\S+", scope))):
        raise CtlError("config: window %s scope must be shared or model:<name>" % wid)
    units = w.get("units")
    if not isinstance(units, str) or not UNITS_RE.match(units):
        raise CtlError("config: window %s units must be a lowercase word (percent, messages, credits...)" % wid)
    _num(w.get("reserve"), "window %s reserve" % wid, maximum=100 if units == "percent" else None)


# ---------- load / save ----------

def load(paths=None):
    paths = paths or get_paths()
    try:
        with open(paths.config, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except FileNotFoundError:
        raise CtlError("no config at %s; run: usagectl init" % paths.config)
    except OSError as exc:
        raise CtlError("cannot read config: %s" % exc)
    try:
        raw = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise CtlError("config is not valid JSON: %s" % exc)
    cfg = fill_defaults(raw)
    validate(cfg)
    return cfg


def _reject_constant(name):
    raise ValueError("non-finite number %s" % name)


def save(cfg, paths=None):
    paths = paths or get_paths()
    validate(cfg)
    ensure_writable(paths)
    os.makedirs(paths.home, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=paths.home)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(cfg, indent=2) + "\n")
        os.replace(tmp, paths.config)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def zone_of(cfg):
    return Zone(cfg["timezone"])
