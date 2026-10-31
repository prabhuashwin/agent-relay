"""Deterministic routing: which account should take the next piece of work.

No static task-type -> provider map. `type` only keys history. Never compares percentages across accounts.
"""

from . import history, pacing, usage
from .timeutil import fmt_local, parse_ts

NEUTRAL = 0.5
HARD = ("incompatible", "exhausted", "refresh", "below_reserve", "too_large")
CONF_RANK = {"user": 2, "medium": 2, "low": 1}


class Request:
    def __init__(self, type, scope, risk, need=(), priority="normal", owner=None, checkpoint=None,
                 workstream=None, model=None, estimates=None, deadline=None):
        self.type, self.scope, self.risk = type, scope, risk
        self.need = list(need)
        self.priority, self.owner = priority, owner
        self.checkpoint = checkpoint      # slug (already validated by the caller) or None
        self.workstream, self.model = workstream, model
        self.estimates = estimates or {}  # {(account, window): number}
        self.deadline = deadline          # datetime.date or None


def _evaluate(alias, ctx):
    cfg, req, now, zone = ctx["cfg"], ctx["req"], ctx["now"], ctx["zone"]
    acct = cfg["accounts"][alias]
    routing = cfg["routing"]
    wins = usage.applicable_windows(acct, req.model)
    states = usage.account_window_states(cfg, ctx["index"], alias, now, req.model)
    ev = {"alias": alias, "provider": acct["provider"], "flags": [], "notes": [], "estimates": {},
          "state": usage.account_state(states), "windows": states, "over_pace_info": [], "paces": {},
          "ratio": None, "usable_by_window": {}}
    flags, notes = ev["flags"], ev["notes"]
    missing = [c for c in req.need if c not in acct["capabilities"]]
    if missing:
        flags.append("incompatible")
        notes.append("lacks capability: %s" % ", ".join(missing))
        ev["missing"] = missing
    exhausted = [s for s in states if s["state"] == usage.EXHAUSTED]
    if exhausted:
        flags.append("exhausted")
        notes.append("exhausted: " + ", ".join("%s (reset %s)" % (s["window"], s["resets_at"] or "unknown")
                                               for s in exhausted))
    if not states:
        flags.append("refresh")
        notes.append("no usage windows configured; add one or record usage first")
    for s in states:
        if s["state"] in (usage.UNKNOWN, usage.STALE):
            if "refresh" not in flags:
                flags.append("refresh")
            notes.append("%s is %s (%s): needs a fresh observation" % (s["window"], s["state"], s["reason"]))
    below = [s for s in states if s["state"] == usage.AVAILABLE and s["below_reserve"]]
    if below:
        flags.append("below_reserve")
        notes.append("at or below reserve: %s" % ", ".join(s["window"] for s in below))
    ev["below_windows"] = below

    overhead = 0.0
    if req.owner and alias != req.owner:
        overhead = routing["switch_overhead_with_checkpoint" if req.checkpoint
                           else "switch_overhead_without_checkpoint"]
    ev["overhead"] = overhead

    est_by_window = {}
    for s in states:
        wid = s["window"]
        if (alias, wid) in req.estimates:
            e = {"value": req.estimates[(alias, wid)], "confidence": "user", "samples": None}
        else:
            e = history.estimate(ctx["tasks"], alias, req.type, req.scope, wid, routing["min_history_samples"])
            e = {"value": e["value"], "confidence": e["confidence"], "samples": e["samples"]}
        est_by_window[wid] = e
        ev["estimates"][wid] = e
    too_large = []
    for s in states:
        e = est_by_window[s["window"]]
        if s["state"] == usage.AVAILABLE and not s["below_reserve"] and e["value"] is not None \
                and e["value"] * (1 + overhead) > s["usable"]:
            too_large.append(s)
            notes.append("estimate %s (+%d%% switch overhead) exceeds usable %s in %s" % (
                _n(e["value"]), round(overhead * 100), _n(s["usable"]), s["window"]))
    if too_large:
        flags.append("too_large")
    ev["too_large_windows"] = too_large

    ratios = []
    for w in wins:
        if w["kind"] != "weekly":
            continue
        p = pacing.pace_window(cfg, zone, now, w, ctx["index"].get((alias, w["id"]), []), req.deadline)
        ev["paces"][w["id"]] = p
        if p["room_today"] is None:
            continue
        if p["daily_target"]:
            ratios.append(p["room_today"] / p["daily_target"])
        e = est_by_window[w["id"]]["value"]
        over = (e > p["room_today"]) if e is not None else p["room_today"] < 0
        if over:
            ev["over_pace_info"].append({"window": w["id"], "room": p["room_today"], "target": p["daily_target"],
                                         "estimate": e})
    ev["ratio"] = min(ratios) if ratios else None
    ev["over_pace"] = bool(ev["over_pace_info"]) and req.deadline is None
    if ev["over_pace"]:
        flags.append("over_pace")
        notes.append("over weekly pace today: " + ", ".join(
            "%s (room %s)" % (i["window"], _n(i["room"])) for i in ev["over_pace_info"]))
    hard = [f for f in flags if f in HARD or (f == "over_pace" and req.priority == "low")]
    ev["hard"] = hard
    ev["suitable"] = not hard
    return ev


def _n(v):
    return ("%g" % round(v, 4)) if isinstance(v, (int, float)) else str(v)


def _rank_key(ev, ctx):
    cfg = ctx["cfg"]
    preferred = cfg["preferred_provider"] is not None and ev["provider"] == cfg["preferred_provider"]
    rate = history.verified_rate(ctx["tasks"], ev["alias"], ctx["req"].type, cfg["routing"]["min_history_samples"])
    ratio = ev["ratio"]
    return (ev["over_pace"], not preferred, -(NEUTRAL if rate is None else rate),
            -(NEUTRAL if ratio is None else ratio), ev["alias"])


def _rank_reason(ev, ctx):
    bits = []
    if ctx["cfg"]["preferred_provider"] == ev["provider"]:
        bits.append("preferred provider")
    if ev["ratio"] is not None:
        bits.append("%d%% of its own daily target left" % round(max(ev["ratio"], 0) * 100))
    return ", ".join(bits)


def _spending_line(cfg):
    sp = cfg["spending_policy"]
    allowed = [k.replace("_", " ") for k, v in sp.items() if v]
    if not allowed:
        return "paid fallback is disabled (spending_policy defaults off)"
    return "spending policy allows: %s; that is your decision, this tool never acts on it" % ", ".join(allowed)


def recommend(cfg, zone, now, index, tasks, owner_events, req):
    ctx = {"cfg": cfg, "zone": zone, "now": now, "index": index, "tasks": tasks, "req": req}
    evals = {a: _evaluate(a, ctx) for a in sorted(cfg["accounts"])}
    rt = cfg["routing"]
    result = {"recommended": None, "action": None, "confidence": "low", "reasons": [], "uncertainty": None,
              "next_step": None, "accounts": {}, "exit_code": 0}
    for a, ev in evals.items():
        result["accounts"][a] = {"suitable": ev["suitable"], "state": ev["state"], "flags": ev["flags"],
                                 "notes": ev["notes"], "estimates": ev["estimates"]}
    reasons = result["reasons"]
    owner = req.owner
    chosen, action = None, None
    suitable = [e for e in evals.values() if e["suitable"]]

    if owner and evals[owner]["suitable"]:
        oe = evals[owner]
        chosen, action = owner, "continue"
        reasons.append("%s is suitable; staying for continuity" % owner)
        rebalance = _rebalance(oe, evals, ctx, owner_events)
        if rebalance:
            chosen, action = rebalance[0], "switch"
            reasons[:] = ["%s is over its weekly pace and the task would overshoot today's room by %d%% of the daily "
                          "target (margin %d%%)" % (owner, round(rebalance[1] * 100), round(rt["switch_margin"] * 100)),
                          "%s is suitable and within pace" % chosen]
    elif owner and evals[owner]["state"] in (usage.UNKNOWN, usage.STALE) and "incompatible" not in evals[owner]["flags"]:
        chosen, action = owner, "refresh"
        reasons.append("%s needs a fresh usage observation before any decision; not switching" % owner)
        result["next_step"] = ("Record fresh usage for %s (usagectl usage record / usage import), then run this again."
                               % owner)
    elif suitable:
        ranked = sorted(suitable, key=lambda e: _rank_key(e, ctx))
        chosen = ranked[0]["alias"]
        action = "switch" if owner else "start"
        why = _rank_reason(ranked[0], ctx)
        reasons.append("%s ranks first%s" % (chosen, " (" + why + ")" if why else ""))
        if owner:
            reasons.append("owner %s is not suitable: %s" % (owner, "; ".join(evals[owner]["flags"])))
    else:
        _none_suitable(result, evals, ctx)
        _explain_rejected(result, evals, None)
        return result

    result["recommended"], result["action"] = chosen, action
    _explain_rejected(result, evals, chosen)
    if action != "refresh":
        _finish_advice(result, evals[chosen], ctx, switching=(action == "switch"))
    return result


def _rebalance(oe, evals, ctx, owner_events):
    """Return (target_alias, overshoot_fraction) or None. Small usage changes never flip the owner."""
    req, rt = ctx["req"], ctx["cfg"]["routing"]
    if not oe["over_pace"] or req.priority == "high" or not req.checkpoint:
        return None
    if history.in_cooldown(ctx["tasks"], owner_events, req.workstream, ctx["now"], rt["switch_cooldown_hours"]):
        return None
    worst = 0.0
    for i in oe["over_pace_info"]:
        if i["estimate"] is not None and i["target"]:
            worst = max(worst, (i["estimate"] - i["room"]) / i["target"])
    if worst < rt["switch_margin"]:
        return None
    others = sorted((e for e in evals.values() if e["suitable"] and not e["over_pace"] and e["alias"] != oe["alias"]),
                    key=lambda e: _rank_key(e, ctx))
    return (others[0]["alias"], worst) if others else None


def _explain_rejected(result, evals, chosen):
    for a, ev in evals.items():
        if a != chosen and not ev["suitable"]:
            detail = "; ".join(ev["notes"]) or ", ".join(ev["flags"])
            result["reasons"].append("%s rejected: %s" % (a, detail))


def _finish_advice(result, ev, ctx, switching):
    req = ctx["req"]
    ests = [e for e in ev["estimates"].values() if e["value"] is not None]
    missing = [wid for wid, e in ev["estimates"].items() if e["value"] is None]
    steps = []
    if switching:
        if req.checkpoint:
            steps.append("Resume on %s with: usagectl handoff resume --workstream %s --to %s"
                         % (ev["alias"], req.workstream or req.checkpoint, ev["alias"]))
        else:
            steps.append("Prepare a checkpoint first (usagectl handoff prepare ...) so work can move without loss")
    if missing:
        result["confidence"] = "low"
        result["uncertainty"] = "no usage estimate for window(s): %s (not enough history or --estimate)" % ", ".join(missing)
        steps.append("Take a smaller step first, and record it with usagectl task start / task finish to build history")
    elif ests:
        result["confidence"] = "medium" if min(CONF_RANK[e["confidence"]] for e in ests) >= 2 else "low"
        if result["confidence"] == "low":
            result["uncertainty"] = "estimates rest on few or unattributed history samples"
    else:
        result["confidence"] = "low"
        result["uncertainty"] = ("no usage estimate for this task type and scope (not enough history, none given "
                                 "with --estimate)")
        steps.append("Take a smaller step first, and record it with usagectl task start / task finish to build history")
    if req.risk == "high":
        steps.append("High risk: plan for a review of the result")
    if not steps:
        steps.append("Proceed on %s" % ev["alias"])
    result["next_step"] = "; ".join(steps) + "."


def _none_suitable(result, evals, ctx):
    cfg, now, zone = ctx["cfg"], ctx["now"], ctx["zone"]
    result["exit_code"] = 4
    compat = [e for e in evals.values() if "incompatible" not in e["flags"]]
    refresh = [e["alias"] for e in compat if "refresh" in e["flags"]]
    reduce = [e for e in compat if e["too_large_windows"] and not e["below_windows"]
              and "exhausted" not in e["flags"] and "refresh" not in e["flags"]]
    spend = _spending_line(cfg)
    reasons = result["reasons"]
    if not evals:
        result["action"] = "blocked"
        reasons.append("no accounts configured")
        result["next_step"] = "Add an account: usagectl account add ...; " + spend + "."
    elif refresh:
        result["action"] = "refresh"
        reasons.append("usage is unknown or stale for: %s" % ", ".join(refresh))
        result["next_step"] = "Record fresh usage for %s, then run this again; %s." % (", ".join(refresh), spend)
    elif reduce:
        result["action"] = "reduce-scope"
        reasons.append("the task is larger than usable allowance on: %s" % ", ".join(e["alias"] for e in reduce))
        result["next_step"] = "Reduce the scope or split the task into smaller steps; %s." % spend
    elif compat:
        result["action"] = "wait"
        candidates = []
        for e in compat:
            blockers = [s for s in e["windows"] if s["state"] == usage.EXHAUSTED or s["below_reserve"]]
            blockers += [s for s in e["too_large_windows"] if s not in blockers]
            if any(not s["resets_at"] or parse_ts(s["resets_at"], zone) <= now for s in blockers):
                continue
            times = [(parse_ts(s["resets_at"], zone), s["resets_at"]) for s in blockers]
            if "over_pace" in e["flags"]:
                nxt = pacing.next_workday(now, zone, cfg["workday_weights"])
                if nxt is None:
                    continue
                times.append((zone.day_bounds(nxt)[0], nxt.isoformat()))
            if times:
                candidates.append(max(times, key=lambda t: t[0]))
        until = min(candidates, key=lambda t: t[0])[1] if candidates else None
        if until is not None:
            reasons.append("earliest account reassessment: %s" % (_show_utc(until, zone) if "T" in until else until))
        if until is None:
            reasons.append("no reset time known")
        result["wait_until"] = until
        result["next_step"] = "Wait%s, then refresh usage and recheck all windows; %s." % (
            " until " + (_show_utc(until, zone) if "T" in until else until) if until else "", spend)
    else:
        result["action"] = "blocked"
        caps = sorted({c for e in evals.values() for c in e.get("missing", [])})
        reasons.append("no account has the needed capability: %s" % ", ".join(caps))
        result["next_step"] = "Add the capability to an account in config, or do this outside the coordinator; %s." % spend


def fmt_utc_now(now):
    from .timeutil import fmt_utc
    return fmt_utc(now)


def _show_utc(text, zone):
    from .timeutil import parse_ts
    return fmt_local(parse_ts(text, zone), zone)
