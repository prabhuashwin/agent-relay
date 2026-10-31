"""Task history (tasks.jsonl events) and usage estimates."""

import datetime as dt
import statistics

from . import store, usage
from .errors import CtlError
from .timeutil import fmt_utc, parse_ts


def _utc_zone():
    return usage._UTC_ZONE


def snapshot(cfg, index, alias):
    """Latest observation of each configured window of the account."""
    out = {}
    for w in cfg["accounts"][alias]["windows"]:
        o = usage.latest(index.get((alias, w["id"]), []))
        if o is not None:
            out[w["id"]] = {"remaining": o["remaining"], "units": o["units"], "resets_at": o.get("resets_at"),
                            "observed_at": o["observed_at"]}
    return out


def load_tasks(paths):
    """Return (tasks dict id->task, owner_events list). Task times are parsed to datetimes."""
    events, _bad = store.read_jsonl(paths.tasks)
    tasks, owner_events = {}, []
    for e in events:
        try:
            kind = e.get("event")
            if kind == "start":
                tasks[e["id"]] = {"id": e["id"], "type": e["type"], "scope": e["scope"], "account": e["account"],
                                  "workstream": e.get("workstream"), "start": parse_ts(e["at"], _utc_zone()),
                                  "windows": e.get("windows", {}), "finish": None, "result": None,
                                  "deltas": {}, "attribution": None}
            elif kind == "finish" and e["id"] in tasks:
                t = tasks[e["id"]]
                t.update(finish=parse_ts(e["at"], _utc_zone()), result=e.get("result"),
                         deltas=e.get("deltas", {}), attribution=e.get("attribution"))
            elif kind == "cancel" and e["id"] in tasks and tasks[e["id"]]["finish"] is None:
                del tasks[e["id"]]
            elif kind == "owner-change":
                owner_events.append({"workstream": e["workstream"], "at": parse_ts(e["at"], _utc_zone()),
                                     "from": e.get("from"), "to": e.get("to")})
        except (KeyError, CtlError, TypeError, AttributeError):
            continue
    return tasks, owner_events


def start_event(cfg, index, tid, ttype, scope, alias, workstream, now):
    return {"event": "start", "id": tid, "type": ttype, "scope": scope, "account": alias,
            "workstream": workstream, "at": fmt_utc(now), "windows": snapshot(cfg, index, alias)}


def compute_deltas(start_windows, end_windows):
    """Per-window delta=start-end, or null with a reason."""
    out = {}
    for wid, s in start_windows.items():
        e = end_windows.get(wid)
        if e is None:
            out[wid] = {"delta": None, "reason": "no-end-observation"}
        elif e["observed_at"] <= s["observed_at"]:
            out[wid] = {"delta": None, "reason": "no-newer-observation"}
        elif not usage.same_cycle(e["resets_at"], s["resets_at"]):
            out[wid] = {"delta": None, "reason": "reset-cycle-changed"}
        elif s["remaining"] - e["remaining"] < 0:
            out[wid] = {"delta": None, "reason": "negative-delta"}
        else:
            out[wid] = {"delta": s["remaining"] - e["remaining"], "reason": None}
    return out


ANOMALIES = ("negative-delta", "reset-cycle-changed")


def finish_event(cfg, index, tasks, tid, result, sole_use, note, now):
    t = tasks.get(tid)
    if t is None:
        raise CtlError("unknown task id %r" % tid)
    if t["finish"] is not None:
        raise CtlError("task %r is already finished" % tid)
    end = snapshot(cfg, index, t["account"])
    deltas = compute_deltas(t["windows"], end)
    overlap = any(o["id"] != tid and o["account"] == t["account"] and o["start"] < now
                  and (o["finish"] is None or o["finish"] > t["start"]) for o in tasks.values())
    anomaly = any(d["reason"] in ANOMALIES for d in deltas.values())
    clean = bool(sole_use) and not overlap and not anomaly
    reasons = []
    if not sole_use:
        reasons.append("--sole-use not given")
    if overlap:
        reasons.append("another task overlapped on this account")
    if anomaly:
        reasons.append("usage delta anomaly")
    return {"event": "finish", "id": tid, "result": result, "at": fmt_utc(now), "sole_use": bool(sole_use),
            "note": note, "deltas": deltas, "attribution": "clean" if clean else "uncertain",
            "attribution_reasons": reasons}


def estimate(tasks, alias, ttype, scope, window, min_samples):
    """Median consumed amount for (account, type, scope, window), with a confidence label."""
    samples = []
    for t in tasks.values():
        if t["finish"] is None or t["account"] != alias or t["type"] != ttype or t["scope"] != scope:
            continue
        d = t["deltas"].get(window)
        if isinstance(d, dict) and d.get("delta") is not None:
            samples.append((d["delta"], t["attribution"] == "clean"))
    clean = [v for v, c in samples if c]
    if len(clean) >= min_samples:
        return {"value": statistics.median(clean), "confidence": "medium", "samples": len(samples), "clean": len(clean)}
    if len(samples) >= min_samples:
        return {"value": statistics.median([v for v, _ in samples]), "confidence": "low",
                "samples": len(samples), "clean": len(clean)}
    return {"value": None, "confidence": None, "samples": len(samples), "clean": len(clean)}


def verified_rate(tasks, alias, ttype, min_samples):
    done = [t for t in tasks.values() if t["finish"] is not None and t["account"] == alias and t["type"] == ttype]
    if len(done) < min_samples:
        return None
    return sum(1 for t in done if t["result"] == "verified") / len(done)


def last_owner_change(tasks, owner_events, workstream):
    """Most recent time the workstream's account changed (owner-change event or a task on a different account)."""
    if not workstream:
        return None
    times = [e["at"] for e in owner_events if e["workstream"] == workstream]
    ws_tasks = sorted((t for t in tasks.values() if t["workstream"] == workstream), key=lambda t: t["start"])
    prev = None
    for t in ws_tasks:
        if prev is not None and t["account"] != prev:
            times.append(t["start"])
        prev = t["account"]
    return max(times) if times else None


def in_cooldown(tasks, owner_events, workstream, now, hours):
    last = last_owner_change(tasks, owner_events, workstream)
    return last is not None and now - last < dt.timedelta(hours=hours)
