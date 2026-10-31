"""Weekly pacing: local guidance only, never a provider limit."""

import datetime as dt

from . import usage
from .errors import CtlError
from .timeutil import DAYS


def _day_weight(day, reset, zone, weights, deadline):
    weight = float(weights[DAYS[day.weekday()]])
    if deadline is not None:
        weight = max(weight, 1.0)
    if day == zone.local_date(reset):
        weight *= zone.day_fraction(reset)
    return weight


def plan_weight(now, reset, zone, weights, deadline=None):
    """Weighted workdays from today to the reset (or deadline). Today counts full unless it is the reset date."""
    today = zone.local_date(now)
    reset_date = zone.local_date(reset)
    end = reset_date
    if deadline is not None:
        if deadline < today:
            raise CtlError("deadline %s is in the past" % deadline.isoformat())
        end = min(deadline, reset_date)
    total, day = 0.0, today
    while day <= end:
        total += _day_weight(day, reset, zone, weights, deadline)
        day += dt.timedelta(days=1)
    return round(total, 6)


def next_workday(now, zone, weights):
    day = zone.local_date(now) + dt.timedelta(days=1)
    for _ in range(14):
        if weights[DAYS[day.weekday()]] > 0:
            return day
        day += dt.timedelta(days=1)
    return None


def _baseline(observations, latest_obs, zone, now):
    today = zone.local_date(now)
    same = [o for o in observations
            if usage.same_cycle(o.get("resets_at"), latest_obs.get("resets_at")) and zone.local_date(o["observed_dt"]) == today]
    return min(same, key=lambda o: o["observed_dt"]) if same else latest_obs


def pace_window(cfg, zone, now, wcfg, observations, deadline=None):
    """Pacing for one window. Returns a dict; target/room are None when no guidance is possible."""
    obs = usage.latest(observations)
    st = usage.window_state(wcfg, obs, now, cfg)
    out = {"window": wcfg["id"], "kind": wcfg["kind"], "scope": wcfg["scope"], "units": wcfg["units"],
           "state": st["state"], "reason": st["reason"], "remaining": st["remaining"], "reserve": wcfg["reserve"],
           "resets_at": st["resets_at"], "weighted_days": None, "baseline": None, "daily_target": None,
           "used_today": None, "room_today": None, "deadline_override": deadline is not None, "message": None}
    if st["state"] != usage.AVAILABLE:
        out["message"] = "state is %s (%s): no target" % (st["state"], st["reason"])
        return out
    if obs["reset_dt"] is None:
        out["message"] = "no reset timestamp: no target"
        return out
    w = plan_weight(now, obs["reset_dt"], zone, cfg["workday_weights"], deadline)
    out["weighted_days"] = w
    if w <= 0:
        out["message"] = "no planned workdays before reset"
        return out
    base = _baseline(observations, obs, zone, now)
    today_weight = _day_weight(zone.local_date(now), obs["reset_dt"], zone,
                               cfg["workday_weights"], deadline)
    target = max(0, base["remaining"] - wcfg["reserve"]) * min(1.0, today_weight / w)
    used = max(0, base["remaining"] - obs["remaining"])
    out.update(baseline=base["remaining"], daily_target=round(target, 6), used_today=round(used, 6),
               room_today=round(target - used, 6))
    if deadline is not None:
        out["message"] = "deadline override"
    return out


def pace_account(cfg, zone, now, alias, index, deadline=None):
    """Weekly pacing entries for an account, with session windows shown beside them."""
    acct = cfg["accounts"][alias]
    sessions = []
    for w in acct["windows"]:
        if w["kind"] == "session":
            st = usage.window_state(w, usage.latest(index.get((alias, w["id"]), [])), now, cfg)
            sessions.append({"window": w["id"], "units": w["units"], "state": st["state"],
                             "remaining": st["remaining"], "usable": st["usable"], "scope": w["scope"]})
    entries = []
    for w in acct["windows"]:
        if w["kind"] != "weekly":
            continue
        p = pace_window(cfg, zone, now, w, index.get((alias, w["id"]), []), deadline)
        p["session"] = sessions
        model = w["scope"].split(":", 1)[1] if w["scope"].startswith("model:") else acct.get("default_model")
        relevant = {x["id"] for x in usage.applicable_windows(acct, model)}
        active = [s for s in sessions if s["window"] in relevant]
        blocked = [s["window"] for s in active if s["state"] == usage.EXHAUSTED or s["usable"] == 0]
        uncertain = [s["window"] for s in active if s["state"] in (usage.UNKNOWN, usage.STALE)]
        p["today_limit"] = max(0, p["room_today"]) if p["room_today"] is not None else None
        p["today_limit_note"] = "weekly pacing only; session allowances are separate and not converted"
        if blocked:
            p["today_limit"] = 0
            p["today_limit_note"] = "blocked by session window(s): " + ", ".join(blocked)
        elif uncertain:
            p["today_limit"] = None
            p["today_limit_note"] = "refresh session window(s): " + ", ".join(uncertain)
        entries.append(p)
    return entries
