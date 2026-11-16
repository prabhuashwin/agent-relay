"""Command line: argument parsing, dispatch, text and JSON output. Errors are one line on stderr, never a traceback."""

import argparse
import json
import math
import os
import re
import sys

from . import VERSION, checkpoint_lock, collectors, config, gitutil, handoff, history, pacing, routing, store, usage
from .config import ALIAS_RE, SLUG_RE
from .errors import CtlError, EXIT_CONFLICT
from .timeutil import fmt_local, fmt_utc, now as clock_now, parse_date, parse_duration, parse_ts

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SCOPES = ("small", "medium", "large")


class CtlParser(argparse.ArgumentParser):
    def error(self, message):
        raise CtlError(message)


def _number(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("not a number: %r" % text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError("must be finite: %r" % text)
    return int(value) if value == int(value) and "." not in text and "e" not in text.lower() else value


def _estimate_arg(text):
    m = re.fullmatch(r"([^:=]+):([^=]+)=(.+)", text)
    if not m:
        raise argparse.ArgumentTypeError("expected ACCOUNT:WINDOW=NUMBER, got %r" % text)
    value = _number(m.group(3))
    if value < 0:
        raise argparse.ArgumentTypeError("estimate must not be negative")
    return (m.group(1), m.group(2), value)


# ---------- output helpers ----------

def _emit(args, data, lines):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print("\n".join(lines))


def _n(v):
    return "-" if v is None else ("%g" % round(v, 4) if isinstance(v, (int, float)) else str(v))


def _context(need_config=True):
    paths = config.get_paths()
    cfg = config.load(paths)
    return paths, cfg, config.zone_of(cfg), clock_now()


def _strip_obs(index):
    return index


# ---------- setup commands ----------

def cmd_init(args):
    paths = config.get_paths()
    if os.path.exists(paths.config):
        raise CtlError("config already exists at %s; overwriting is not offered (edit it, or delete it yourself)"
                       % paths.config)
    cfg = config.default_config()
    config.save(cfg, paths)
    _emit(args, {"created": paths.config}, ["created %s" % paths.config,
                                            "next: usagectl account add --account A --provider claude|codex --plan X"])
    return 0


def cmd_account_add(args):
    paths, cfg, _z, _n_ = _context()
    if not ALIAS_RE.match(args.account):
        raise CtlError("invalid account alias %r (lowercase letters, digits, - and _; never an e-mail)" % args.account)
    if args.account in cfg["accounts"]:
        raise CtlError("account %r already exists" % args.account)
    cfg["accounts"][args.account] = {"provider": args.provider, "plan": args.plan,
                                     "capabilities": list(dict.fromkeys(args.capability or [])),
                                     "default_model": args.default_model, "models": {}, "windows": []}
    config.save(cfg, paths)
    _emit(args, {"account": args.account}, ["added account %s (%s, %s)" % (args.account, args.provider, args.plan)])
    return 0


def cmd_window_add(args):
    paths, cfg, _z, _n_ = _context()
    acct = cfg["accounts"].get(args.account)
    if acct is None:
        raise CtlError("unknown account %r" % args.account)
    acct["windows"].append({"id": args.id, "kind": args.kind, "scope": args.scope, "units": args.units,
                            "reserve": args.reserve})
    config.save(cfg, paths)
    _emit(args, {"account": args.account, "window": args.id},
          ["added window %s (%s, %s) to %s" % (args.id, args.kind, args.units, args.account)])
    return 0


def cmd_config_show(args):
    _p, cfg, _z, _n_ = _context()
    print(json.dumps(cfg, indent=2, sort_keys=True))
    return 0


def cmd_config_validate(args):
    _context()
    _emit(args, {"valid": True}, ["config ok"])
    return 0


def cmd_config_capture(args):
    paths, cfg, _z, _n = _context()
    if args.account:
        collectors.require_provider(cfg, args.account, 'claude')
    cfg['claude_capture_account'] = args.account
    config.save(cfg, paths)
    _emit(args, {'claude_capture_account': args.account}, ['Claude capture: ' + (args.account or 'disabled')])
    return 0


def cmd_usage_fetch(args):
    paths, cfg, zone, now = _context()
    recs = collectors.fetch_codex(paths, cfg, zone, now, args.account, args.timeout)
    _emit(args, {'observations': recs}, ['Fetched %d window(s) from the logged-in Codex CLI account into %s' % (len(recs), args.account)])
    return 0


def cmd_usage_capture(args):
    paths, cfg, zone, now = _context()
    if cfg.get('claude_capture_account'):
        collectors.capture_claude(paths, cfg, zone, now, sys.stdin.read())
    return 0


# ---------- usage ----------

def cmd_usage_record(args):
    paths, cfg, zone, now = _context()
    observed = parse_ts(args.observed_at, zone) if args.observed_at else now
    raw = {"account": args.account, "window": args.window, "remaining": args.remaining,
           "observed_at": fmt_utc(observed), "source": args.source, "confidence": args.confidence}
    if args.units is not None:
        raw["units"] = args.units
    if args.resets_at is not None:
        raw["resets_at"] = args.resets_at if re.search(r"(Z|[+-]\d\d:?\d\d)$", args.resets_at) \
            else fmt_utc(parse_ts(args.resets_at, zone))
    elif args.resets_in is not None:
        raw["resets_at"] = fmt_utc(observed + parse_duration(args.resets_in))
    rec = usage.parse_observation(raw, cfg, zone, now)
    store.append_jsonl(paths, paths.usage, [rec])
    _emit(args, rec, ["recorded %s/%s: %s %s remaining, resets %s" % (
        rec["account"], rec["window"], _n(rec["remaining"]), rec["units"],
        fmt_local(parse_ts(rec["resets_at"], zone), zone) if rec["resets_at"] else "never/unknown")])
    return 0


def _read_input(name):
    try:
        if name == "-":
            return sys.stdin.read()
        with open(name, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError as exc:
        raise CtlError("cannot read %s: %s" % (name, exc))


def cmd_usage_import(args):
    paths, cfg, zone, now = _context()
    text = _read_input(args.file)
    if args.format == "claude-statusline":
        recs = usage.parse_claude_statusline(text, cfg, zone, now, args.account)
    else:
        recs = usage.parse_snapshot(text, cfg, zone, now, args.account)
    store.append_jsonl(paths, paths.usage, recs)  # one write: all or nothing
    _emit(args, {"imported": len(recs), "observations": recs},
          ["imported %d observation(s): %s" % (len(recs), ", ".join("%s/%s" % (r["account"], r["window"]) for r in recs))])
    return 0


def cmd_usage_status(args):
    paths, cfg, zone, now = _context()
    index, bad = usage.load_index(paths)
    st = usage.status(cfg, index, now, zone)
    lines = []
    if bad:
        lines.append("warning: %d unreadable line(s) in usage.jsonl were ignored" % bad)
    if not st:
        lines.append("no accounts configured")
    for alias, a in st.items():
        lines.append("%s (%s, %s): %s" % (alias, a["provider"], a["plan"], a["state"]))
        if not a["windows"]:
            lines.append("  no windows configured: state unknown")
        for w in a["windows"]:
            lines.append("  %s [%s, %s]: %s%s" % (w["window"], w["kind"], w["scope"], w["state"],
                                                 "" if w["reason"] in ("ok",) else " (%s)" % w["reason"]))
            if w["remaining"] is not None:
                reset = fmt_local(parse_ts(w["resets_at"], zone), zone) if w["resets_at"] else "no reset known"
                lines.append("    remaining %s %s, usable %s, reserve %s, resets %s, observed %s" % (
                    _n(w["remaining"]), w["units"], _n(w["usable"]), _n(w["reserve"]), reset,
                    fmt_local(parse_ts(w["observed_at"], zone), zone)))
                if w["state"] == "stale" and w["reason"] == "reset-passed":
                    lines.append("    the reset time passed: record a fresh observation (not treated as full)")
    _emit(args, {"accounts": st, "ignored_lines": bad}, lines)
    return 0


# ---------- pace ----------

def cmd_pace_show(args):
    paths, cfg, zone, now = _context()
    deadline = parse_date(args.deadline) if args.deadline else None
    index, _bad = usage.load_index(paths)
    data, lines = {}, []
    for alias in sorted(cfg["accounts"]):
        entries = pacing.pace_account(cfg, zone, now, alias, index, deadline)
        data[alias] = entries
        lines.append(alias + ":")
        if not entries:
            lines.append("  no weekly window: no pacing")
        for p in entries:
            tag = " [deadline override]" if p["deadline_override"] else ""
            if p["daily_target"] is None:
                lines.append("  %s: %s%s" % (p["window"], p["message"], tag))
            else:
                lines.append("  %s%s: daily target %s %s over %s weighted days; used today %s; room today %s" % (
                    p["window"], tag, _n(p["daily_target"]), p["units"], _n(p["weighted_days"]),
                    _n(p["used_today"]), _n(p["room_today"])))
            for s in p["session"]:
                lines.append("    session %s: %s, usable %s %s" % (s["window"], s["state"], _n(s["usable"]), s["units"]))
            if p["today_limit"] is not None:
                lines.append("    today limit: %s %s" % (_n(p["today_limit"]), p["units"]))
            if p.get("today_limit_note"):
                lines.append("    note: " + p["today_limit_note"])
    _emit(args, {"deadline": args.deadline, "accounts": data}, lines)
    return 0


# ---------- routing ----------

def _validate_checkpoint(slug):
    """The checkpoint file must exist under the current git root. Returns (root, path)."""
    if not SLUG_RE.match(slug):
        raise CtlError("invalid checkpoint slug %r" % slug)
    root = gitutil.git_root()
    if root is None:
        raise CtlError("--checkpoint needs a git work tree; none found from the current directory")
    path = handoff.checkpoint_path(root, slug)
    if not os.path.isfile(path):
        raise CtlError("no checkpoint at %s; run the checkpoint skill first" % path)
    return root, path


def cmd_route_recommend(args):
    paths, cfg, zone, now = _context()
    if args.refresh:
        aliases = [a for a, c in cfg['accounts'].items() if c['provider'] == 'codex']
        alias = args.codex_account or (aliases[0] if len(aliases) == 1 else None)
        if not alias:
            raise CtlError('Select --codex-account for refresh (the alias must match the CLI login)')
        collectors.fetch_codex(paths, cfg, zone, now, alias, args.timeout)
    if not ALIAS_RE.match(args.type):
        raise CtlError("invalid --type %r (lowercase letters, digits, - and _)" % args.type)
    if args.owner and args.owner not in cfg["accounts"]:
        raise CtlError("unknown owner account %r" % args.owner)
    if args.workstream and not SLUG_RE.match(args.workstream):
        raise CtlError("invalid --workstream slug %r" % args.workstream)
    checkpoint, ckpt_note = args.checkpoint, None
    if checkpoint:
        root, _path = _validate_checkpoint(checkpoint)
        ok, why = handoff.routing_checkpoint_status(root, checkpoint, args.workstream or checkpoint)
        if not ok:   # unusable checkpoint: counts as none (higher switching overhead, no rebalance)
            checkpoint, ckpt_note = None, "checkpoint %r not valid, treated as none: %s" % (args.checkpoint, why)
    estimates = {}
    for acct, win, value in args.estimate or []:
        usage.find_window(cfg, acct, win)
        estimates[(acct, win)] = value
    deadline = parse_date(args.deadline) if args.deadline else None
    index, _bad = usage.load_index(paths)
    tasks, owner_events = history.load_tasks(paths)
    req = routing.Request(args.type, args.scope, args.risk, args.need or [], args.priority, args.owner,
                          checkpoint, args.workstream or args.checkpoint, args.model, estimates, deadline)
    result = routing.recommend(cfg, zone, now, index, tasks, owner_events, req)
    if ckpt_note:
        result["reasons"].append(ckpt_note)
    lines = ["recommended: %s   action: %s   confidence: %s" % (result["recommended"] or "none", result["action"],
                                                               result["confidence"])]
    lines += ["- " + r for r in result["reasons"]]
    if result["uncertainty"]:
        lines.append("uncertainty: " + result["uncertainty"])
    lines.append("next: " + (result["next_step"] or ""))
    _emit(args, result, lines)
    return result["exit_code"]


# ---------- tasks ----------

def cmd_task_start(args):
    paths, cfg, zone, now = _context()
    if not TASK_ID_RE.match(args.id):
        raise CtlError("invalid task id %r" % args.id)
    if not ALIAS_RE.match(args.type):
        raise CtlError("invalid --type %r" % args.type)
    if args.account not in cfg["accounts"]:
        raise CtlError("unknown account %r" % args.account)
    if args.workstream and not SLUG_RE.match(args.workstream):
        raise CtlError("invalid --workstream slug %r" % args.workstream)
    tasks, _ev = history.load_tasks(paths)
    if args.id in tasks:
        raise CtlError("task id %r already exists" % args.id)
    index, _bad = usage.load_index(paths)
    ev = history.start_event(cfg, index, args.id, args.type, args.scope, args.account, args.workstream, now)
    store.append_jsonl(paths, paths.tasks, [ev])
    _emit(args, ev, ["started task %s on %s (%d window snapshot(s))" % (args.id, args.account, len(ev["windows"]))])
    return 0


def cmd_task_finish(args):
    paths, cfg, zone, now = _context()
    tasks, _ev = history.load_tasks(paths)
    index, _bad = usage.load_index(paths)
    ev = history.finish_event(cfg, index, tasks, args.id, args.result, args.sole_use, args.note, now)
    store.append_jsonl(paths, paths.tasks, [ev])
    deltas = ", ".join("%s=%s" % (w, _n(d["delta"]) if d["delta"] is not None else "n/a (%s)" % d["reason"])
                       for w, d in ev["deltas"].items()) or "no windows"
    lines = ["finished task %s: %s; attribution %s" % (args.id, args.result, ev["attribution"]),
             "usage deltas: " + deltas]
    if ev["attribution_reasons"]:
        lines.append("attribution uncertain: " + "; ".join(ev["attribution_reasons"]))
    _emit(args, ev, lines)
    return 0


def cmd_task_cancel(args):
    paths, cfg, zone, now = _context()
    tasks, _ev = history.load_tasks(paths)
    t = tasks.get(args.id)
    if t is None:
        raise CtlError("unknown or already cancelled task id %r" % args.id)
    if t["finish"] is not None:
        raise CtlError("task %r is already finished" % args.id)
    ev = {"event": "cancel", "id": args.id, "at": fmt_utc(now)}
    store.append_jsonl(paths, paths.tasks, [ev])
    _emit(args, ev, ["cancelled task %s" % args.id])
    return 0


# ---------- handoff ----------

def _mismatch_exit(args, mismatches, extra=None):
    for m in mismatches:
        print(m, file=sys.stderr)
    if getattr(args, "json", False):
        out = {"ok": False, "mismatches": mismatches}
        out.update(extra or {})
        print(json.dumps(out, indent=2, sort_keys=True))
    return EXIT_CONFLICT


def _load_for(slug):
    handoff.check_slug(slug)
    root = handoff.require_root()
    path = handoff.checkpoint_path(root, slug)
    return root, path, handoff.load_checkpoint(path)


def _owner_event(paths, ws, frm, to, now):
    store.append_jsonl(paths, paths.tasks, [{"event": "owner-change", "workstream": ws, "from": frm, "to": to,
                                             "at": fmt_utc(now)}])


@checkpoint_lock.command
def cmd_handoff_prepare(args):
    paths, cfg, _z, now = _context()
    handoff.check_slug(args.workstream)
    if args.owner not in cfg["accounts"]:
        raise CtlError("unknown owner account %r" % args.owner)
    verify = [handoff.parse_verify_arg(v) for v in args.verify or []]
    if not args.goal.strip() or not args.next.strip():
        raise CtlError("--goal and --next must not be empty")
    root = handoff.require_root()
    path = handoff.checkpoint_path(root, args.workstream)
    old = handoff.load_checkpoint(path) if os.path.exists(path) else None
    changed = old is not None and old["owner"] != args.owner
    if changed:
        from .continuity import managed
        if managed(paths, root, args.workstream):
            raise CtlError('This workstream uses board release/claim; transfer ownership there before preparing.', EXIT_CONFLICT)
    if changed and not args.take_over:
        raise CtlError("checkpoint %s is owned by %s, not %s; the owner must hand over (usagectl handoff claim), "
                       "or pass --take-over if you are sure they stopped" % (args.workstream, old["owner"], args.owner),
                       EXIT_CONFLICT)
    data = handoff.build_checkpoint(root, args.workstream, args.owner, args.goal, args.next, fmt_utc(now),
                                    args.accept or [], args.done or [], args.remaining or [], verify,
                                    args.failure or [], args.decision or [], args.base)
    handoff.write_checkpoint(path, data)
    if changed:
        _owner_event(paths, args.workstream, old["owner"], args.owner, now)
    _emit(args, {"path": path, "checkpoint": data},
          ["checkpoint written: " + path,
           "uncommitted paths: %d; head: %s" % (len(data["uncommitted"]["paths"]), data["head_commit"] or "none")])
    return 0


def cmd_handoff_verify(args):
    root, _path, data = _load_for(args.workstream)
    handoff.check_name_matches(data, args.workstream)
    mism = handoff.compare(root, data)
    if mism:
        return _mismatch_exit(args, mism)
    _emit(args, {"ok": True, "mismatches": []}, ["ok: repository matches checkpoint %s" % args.workstream])
    return 0


def cmd_handoff_resume(args):
    _p, cfg, _z, _n_ = _context()
    acct = cfg["accounts"].get(args.to)
    if acct is None:
        raise CtlError("unknown account %r" % args.to)
    root, _path, data = _load_for(args.workstream)
    mism = handoff.compare(root, data)
    from .continuity import managed, latest_verification
    prompt = handoff.resume_prompt(acct["provider"], data, "handoffs/%s.checkpoint.md" % args.workstream, args.to,
                                  latest_verification(_p, root, args.workstream))
    if managed(_p, root, args.workstream):
        prompt = '\n'.join(line for line in prompt.splitlines() if not line.startswith('Then take ownership:'))
        if data['owner'] != args.to:
            prompt += '\nDo not edit yet. Use usagectl board release/claim to transfer ownership, then obtain its resume prompt.'
        else:
            prompt += '\nThis account already owns the checkpoint. Future transfers must use usagectl board release/claim.'
    if mism:
        if not args.show_anyway:
            return _mismatch_exit(args, mism)
        _mismatch_exit(args, mism, {"prompt": prompt, "provider": acct["provider"]})
        if not args.json:
            print("--- prompt shown anyway; the repository does NOT match the checkpoint ---")
            print(prompt)
        return EXIT_CONFLICT
    _emit(args, {"ok": True, "provider": acct["provider"], "prompt": prompt}, [prompt])
    return 0


@checkpoint_lock.command
def cmd_handoff_claim(args):
    paths, cfg, _z, now = _context()
    if args.to not in cfg["accounts"]:
        raise CtlError("unknown account %r" % args.to)
    root, path, data = _load_for(args.workstream)
    handoff.check_name_matches(data, args.workstream)
    mism = handoff.compare(root, data)
    if mism:
        return _mismatch_exit(args, mism)
    previous = data["owner"]
    if previous != args.to:
        from .continuity import managed
        if managed(paths, root, args.workstream):
            raise CtlError('This workstream uses board release/claim; release the source and claim with its ticket.', EXIT_CONFLICT)
        data["owner"] = args.to
        handoff.write_checkpoint(path, data)
        _owner_event(paths, args.workstream, previous, args.to, now)
    _emit(args, {"ok": True, "workstream": args.workstream, "from": previous, "to": args.to,
                 "changed": previous != args.to},
          ["%s now owns %s" % (args.to, args.workstream) if previous != args.to
           else "%s already owns %s" % (args.to, args.workstream)])
    return 0


def _add_handoff(top, leaf):
    hp = top.add_parser("handoff", help="checkpoint handoffs between accounts").add_subparsers(
        dest="verb", parser_class=CtlParser)
    hp.required = True
    p = leaf(hp, "prepare", cmd_handoff_prepare)
    p.add_argument("--workstream", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--next", required=True)
    for name in ("accept", "done", "remaining", "verify", "failure", "decision"):
        p.add_argument("--" + name, action="append")
    p.add_argument("--base")
    p.add_argument("--take-over", action="store_true")
    v = leaf(hp, "verify", cmd_handoff_verify)
    v.add_argument("--workstream", required=True)
    r = leaf(hp, "resume", cmd_handoff_resume)
    r.add_argument("--workstream", required=True)
    r.add_argument("--to", required=True)
    r.add_argument("--show-anyway", action="store_true")
    c = leaf(hp, "claim", cmd_handoff_claim)
    c.add_argument("--workstream", required=True)
    c.add_argument("--to", required=True)


# ---------- selftest ----------

def cmd_selftest(args):
    from . import selftest
    return selftest.run(json_out=args.json)


# ---------- parser ----------

def build_parser():
    p = CtlParser(prog="usagectl", description="Local usage coordinator for Claude Code and Codex accounts.")
    p.add_argument("--version", action="version", version="usagectl " + VERSION)
    top = p.add_subparsers(dest="noun", parser_class=CtlParser)
    top.required = True

    def common():
        c = CtlParser(add_help=False)
        c.add_argument("--json", action="store_true", help="machine-readable output")
        return c

    def leaf(parent, name, func, **kw):
        sp = parent.add_parser(name, parents=[common()], **kw)
        sp.set_defaults(func=func)
        return sp

    leaf(top, "init", cmd_init, help="write the default config").add_argument(
        "--force-not-allowed", action="store_true", help="accepted but overwriting is never allowed")

    acct = top.add_parser("account").add_subparsers(dest="verb", parser_class=CtlParser)
    acct.required = True
    a = leaf(acct, "add", cmd_account_add)
    a.add_argument("--account", required=True)
    a.add_argument("--provider", required=True, choices=config.PROVIDERS)
    a.add_argument("--plan", required=True)
    a.add_argument("--capability", action="append")
    a.add_argument("--default-model")

    win = top.add_parser("window").add_subparsers(dest="verb", parser_class=CtlParser)
    win.required = True
    w = leaf(win, "add", cmd_window_add)
    w.add_argument("--account", required=True)
    w.add_argument("--id", required=True)
    w.add_argument("--kind", required=True, choices=config.KINDS)
    w.add_argument("--units", required=True)
    w.add_argument("--reserve", required=True, type=_number)
    w.add_argument("--scope", default="shared")

    cfgp = top.add_parser("config").add_subparsers(dest="verb", parser_class=CtlParser)
    cfgp.required = True
    leaf(cfgp, "show", cmd_config_show)
    leaf(cfgp, "validate", cmd_config_validate)
    capture = leaf(cfgp, 'capture-claude', cmd_config_capture).add_mutually_exclusive_group(required=True)
    capture.add_argument('--account')
    capture.add_argument('--disable', action='store_true')

    us = top.add_parser("usage").add_subparsers(dest="verb", parser_class=CtlParser)
    us.required = True
    r = leaf(us, "record", cmd_usage_record)
    r.add_argument("--account", required=True)
    r.add_argument("--window", required=True)
    r.add_argument("--remaining", required=True, type=_number)
    r.add_argument("--units")
    reset = r.add_mutually_exclusive_group(required=True)
    reset.add_argument("--resets-at")
    reset.add_argument("--resets-in")
    reset.add_argument("--no-reset", action="store_true")
    r.add_argument("--observed-at")
    r.add_argument("--source", default="manual")
    r.add_argument("--confidence", choices=usage.CONFIDENCES, default="medium")
    i = leaf(us, "import", cmd_usage_import)
    i.add_argument("file", metavar="FILE|-")
    i.add_argument("--format", choices=("snapshot", "claude-statusline"), default="snapshot")
    i.add_argument("--account")
    leaf(us, "status", cmd_usage_status)
    fetch = leaf(us, 'fetch', cmd_usage_fetch)
    fetch.add_argument('--account', required=True)
    fetch.add_argument('--timeout', type=_number, default=20)
    leaf(us, 'capture-claude', cmd_usage_capture)

    pc = top.add_parser("pace").add_subparsers(dest="verb", parser_class=CtlParser)
    pc.required = True
    leaf(pc, "show", cmd_pace_show).add_argument("--deadline")

    rt = top.add_parser("route").add_subparsers(dest="verb", parser_class=CtlParser)
    rt.required = True
    route_parent = CtlParser(add_help=False)
    rr = route_parent
    rr.add_argument("--type", required=True)
    rr.add_argument("--scope", required=True, choices=SCOPES)
    rr.add_argument("--risk", required=True, choices=("low", "medium", "high"))
    rr.add_argument("--need", action="append")
    rr.add_argument("--priority", choices=("low", "normal", "high"), default="normal")
    rr.add_argument("--owner")
    rr.add_argument("--checkpoint")
    rr.add_argument("--workstream")
    rr.add_argument("--model")
    rr.add_argument("--estimate", action="append", type=_estimate_arg)
    rr.add_argument("--deadline")
    rr.add_argument('--refresh', action='store_true', help='fetch Codex usage before advice; use existing Claude capture')
    rr.add_argument('--codex-account', help='alias for the logged-in Codex CLI account')
    rr.add_argument('--timeout', type=_number, default=20)
    for parent, name in ((rt, 'recommend'), (top, 'advise')):
        parser = parent.add_parser(name, parents=[common(), route_parent])
        parser.set_defaults(func=cmd_route_recommend)

    tk = top.add_parser("task").add_subparsers(dest="verb", parser_class=CtlParser)
    tk.required = True
    ts = leaf(tk, "start", cmd_task_start)
    ts.add_argument("--id", required=True)
    ts.add_argument("--type", required=True)
    ts.add_argument("--scope", required=True, choices=SCOPES)
    ts.add_argument("--account", required=True)
    ts.add_argument("--workstream")
    tf = leaf(tk, "finish", cmd_task_finish)
    tf.add_argument("--id", required=True)
    tf.add_argument("--result", required=True, choices=("verified", "partial", "failed"))
    tf.add_argument("--sole-use", action="store_true")
    tf.add_argument("--note")

    tc = leaf(tk, "cancel", cmd_task_cancel)
    tc.add_argument("--id", required=True)

    _add_handoff(top, leaf)
    from .board_cli import add_parser as add_board
    add_board(top, leaf)
    leaf(top, "selftest", cmd_selftest, help="run an internal check in a temporary state directory")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):   # piped Windows output defaults to a legacy code page
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        args = build_parser().parse_args(argv)
        return args.func(args) or 0
    except CtlError as exc:
        print("usagectl: %s" % exc.message, file=sys.stderr)
        return exc.code
    except SystemExit as exc:  # --help / --version
        return exc.code if isinstance(exc.code, int) else 0
    except BrokenPipeError:
        return 0
    except Exception as exc:  # never show a traceback
        print("usagectl: internal error: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
