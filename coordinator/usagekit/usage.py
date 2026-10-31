"""Usage observations: validation, import, and window/account state."""

import datetime as dt
import json
import math

from . import store
from .errors import CtlError
from .timeutil import UTC, fmt_utc, parse_ts

OBS_FIELDS = ("account", "window", "remaining", "units", "resets_at", "observed_at", "source", "confidence")
CONFIDENCES = ("high", "medium", "low")
FUTURE_SLACK = dt.timedelta(minutes=5)

AVAILABLE, EXHAUSTED, STALE, UNKNOWN = "available", "exhausted", "stale", "unknown"


def _reject_constant(name):
    raise ValueError("non-finite number %s" % name)


def loads_strict(text):
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise CtlError("invalid JSON: %s" % exc)


def find_window(cfg, account, window):
    acct = cfg["accounts"].get(account)
    if acct is None:
        raise CtlError("unknown account %r" % (account,))
    for w in acct["windows"]:
        if w["id"] == window:
            return w
    raise CtlError("unknown window %r on account %r" % (window, account))


RESET_TOLERANCE = dt.timedelta(minutes=15)


def same_cycle(a, b):
    """True when two resets_at strings (or None) belong to the same reset cycle (within 15 minutes)."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(parse_ts(a, UTC) - parse_ts(b, UTC)) <= RESET_TOLERANCE
    except CtlError:
        return a == b


def parse_observation(raw, cfg, zone, now, default_account=None):
    """Validate one raw observation dict; return the normalized record (strings stored as UTC Z)."""
    if not isinstance(raw, dict):
        raise CtlError("observation must be an object")
    extra = sorted(set(raw) - set(OBS_FIELDS))
    if extra:
        raise CtlError("unknown observation field(s): %s" % ", ".join(extra))
    account = raw.get("account", default_account)
    if default_account is not None and raw.get("account", default_account) != default_account:
        raise CtlError("observation account %r does not match --account %r" % (raw.get("account"), default_account))
    if not isinstance(account, str):
        raise CtlError("observation needs an account")
    window = raw.get("window")
    if not isinstance(window, str):
        raise CtlError("observation needs a window")
    wcfg = find_window(cfg, account, window)
    remaining = raw.get("remaining")
    if isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
        raise CtlError("remaining must be a number")
    if not math.isfinite(remaining):
        raise CtlError("remaining must be finite")
    if remaining < 0:
        raise CtlError("remaining must not be negative")
    units = raw.get("units", wcfg["units"])
    if units != wcfg["units"]:
        raise CtlError("units %r do not match window %s units %r" % (units, window, wcfg["units"]))
    if units == "percent" and remaining > 100:
        raise CtlError("remaining percent cannot exceed 100")
    observed = parse_ts(raw["observed_at"], zone) if raw.get("observed_at") is not None else now
    if observed > now + FUTURE_SLACK:
        raise CtlError("observed_at is more than 5 minutes in the future")
    resets = None
    if raw.get("resets_at") is not None:
        resets = parse_ts(raw["resets_at"], zone)
        if resets <= observed:
            raise CtlError("resets_at must be after observed_at")
    confidence = raw.get("confidence", "medium")
    if confidence not in CONFIDENCES:
        raise CtlError("confidence must be high, medium or low")
    source = raw.get("source", "manual")
    if not isinstance(source, str) or not source:
        raise CtlError("source must be a non-empty string")
    return {"account": account, "window": window, "remaining": remaining, "units": units,
            "resets_at": fmt_utc(resets) if resets else None, "observed_at": fmt_utc(observed),
            "source": source, "confidence": confidence}


def parse_snapshot(text, cfg, zone, now, default_account=None):
    doc = loads_strict(text)
    if not isinstance(doc, dict) or set(doc) - {"schema", "observations"} or doc.get("schema") != 1 \
            or not isinstance(doc.get("observations"), list):
        raise CtlError('snapshot must be {"schema": 1, "observations": [...]}')
    if not doc["observations"]:
        raise CtlError("snapshot has no observations")
    out = []
    for i, raw in enumerate(doc["observations"], 1):
        try:
            out.append(parse_observation(raw, cfg, zone, now, default_account))
        except CtlError as exc:
            raise CtlError("observation %d: %s (nothing imported)" % (i, exc.message))
    return out


STATUSLINE_WINDOWS = ("five_hour", "seven_day")


def parse_claude_statusline(text, cfg, zone, now, account):
    """Map the documented Claude status line JSON (rate_limits.five_hour|seven_day) to observations."""
    if not account:
        raise CtlError("--account is required for --format claude-statusline")
    doc = loads_strict(text)
    limits = doc.get("rate_limits") if isinstance(doc, dict) else None
    if not isinstance(limits, dict):
        raise CtlError("no rate_limits in input; nothing usable (windows are only present for subscribers)")
    acct = cfg["accounts"].get(account)
    if acct is None:
        raise CtlError("unknown account %r" % account)
    configured = {w["id"]: w for w in acct["windows"]}
    out = []
    for wid in STATUSLINE_WINDOWS:
        entry = limits.get(wid)
        if entry is None or wid not in configured or configured[wid]["units"] != "percent" \
                or configured[wid]["scope"] != "shared":
            continue
        if not isinstance(entry, dict):
            raise CtlError("rate_limits.%s must be an object" % wid)
        used, reset = entry.get("used_percentage"), entry.get("resets_at")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) \
                or not 0 <= used <= 100:
            raise CtlError("rate_limits.%s.used_percentage must be a number from 0 to 100" % wid)
        if isinstance(reset, bool) or not isinstance(reset, (int, float)) or not math.isfinite(reset) or reset <= 0:
            raise CtlError("rate_limits.%s.resets_at must be epoch seconds" % wid)
        reset_dt = dt.datetime.fromtimestamp(reset, UTC)
        raw = {"account": account, "window": wid, "remaining": 100 - used,
               "resets_at": fmt_utc(reset_dt), "observed_at": fmt_utc(now),
               "source": "claude-statusline", "confidence": "high"}
        out.append(parse_observation(raw, cfg, zone, now, account))
    if not out:
        raise CtlError("no usable windows: account %r needs configured percent windows five_hour/seven_day "
                       "present in the input" % account)
    return out


# ---------- loading ----------

def load_index(paths):
    """Return ({(account, window): [obs sorted by observed_at]}, bad_line_count). obs carry parsed datetimes."""
    records, bad = store.read_jsonl(paths.usage)
    index = {}
    for rec in records:
        try:
            o = dict(rec)
            o["observed_dt"] = parse_ts(rec["observed_at"], _UTC_ZONE)
            o["reset_dt"] = parse_ts(rec["resets_at"], _UTC_ZONE) if rec.get("resets_at") else None
            if isinstance(rec["remaining"], bool) or not isinstance(rec["remaining"], (int, float)) \
                    or not math.isfinite(rec["remaining"]):
                raise CtlError("bad remaining")
            key = (rec["account"], rec["window"])
        except (CtlError, KeyError, TypeError):
            bad += 1
            continue
        index.setdefault(key, []).append(o)
    for lst in index.values():
        lst.sort(key=lambda o: o["observed_dt"])  # stable: later file position wins ties
    return index, bad


class _Utc:
    tz = UTC

    def localize(self, naive):
        return naive.replace(tzinfo=UTC)


_UTC_ZONE = _Utc()


def latest(observations):
    return observations[-1] if observations else None


# ---------- state ----------

def applicable_windows(acct, model=None):
    """Shared windows plus model:<m> windows for the task model (or the account default)."""
    m = model or acct.get("default_model")
    return [w for w in acct["windows"] if w["scope"] == "shared" or (m and w["scope"] == "model:%s" % m)]


def window_state(wcfg, obs, now, cfg):
    base = {"window": wcfg["id"], "kind": wcfg["kind"], "scope": wcfg["scope"], "units": wcfg["units"],
            "reserve": wcfg["reserve"], "state": UNKNOWN, "reason": "no-observation", "remaining": None,
            "usable": None, "below_reserve": False, "resets_at": None, "observed_at": None,
            "confidence": None, "age_minutes": None}
    if obs is None:
        return base
    age = (now - obs["observed_dt"]).total_seconds() / 60.0
    remaining = obs["remaining"]
    base.update(remaining=remaining, resets_at=obs.get("resets_at"), observed_at=obs.get("observed_at"),
                confidence=obs.get("confidence"), age_minutes=round(age, 1))
    stale_after = cfg["stale_after_minutes"][wcfg["kind"]]
    reset = obs["reset_dt"]
    reset_future = reset is not None and reset > now
    reset_passed = reset is not None and reset <= now
    old = age > stale_after
    if remaining <= 0 and reset_future:
        state, reason = EXHAUSTED, "exhausted-until-reset"
    elif reset_passed:
        state, reason = STALE, "reset-passed"
    elif old:
        state, reason = STALE, "old"
    elif remaining <= 0:
        state, reason = EXHAUSTED, "exhausted-no-reset"
    else:
        state, reason = AVAILABLE, "ok"
    base.update(state=state, reason=reason)
    if state == AVAILABLE:
        usable = max(0, remaining - wcfg["reserve"])
        base.update(usable=usable, below_reserve=usable == 0)
    return base


def account_state(states):
    names = [s["state"] for s in states]
    if not names:
        return UNKNOWN
    for s in (EXHAUSTED, UNKNOWN, STALE):
        if s in names:
            return s
    return AVAILABLE


def account_window_states(cfg, index, alias, now, model=None, all_windows=False):
    acct = cfg["accounts"][alias]
    wins = acct["windows"] if all_windows else applicable_windows(acct, model)
    return [window_state(w, latest(index.get((alias, w["id"]), [])), now, cfg) for w in wins]


def status(cfg, index, now, zone):
    out = {}
    for alias, acct in sorted(cfg["accounts"].items()):
        states = account_window_states(cfg, index, alias, now, all_windows=True)
        out[alias] = {"provider": acct["provider"], "plan": acct["plan"],
                      "state": account_state(states), "windows": states}
    return out
