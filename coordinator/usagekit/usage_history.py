"""Local seven-day history and fresh reserve warnings; never contacts providers."""
import datetime as dt
import math

from . import usage
from .timeutil import fmt_utc


def valid_value(observation, window):
    value = observation.get('remaining')
    return (observation.get('units') == window['units'] and
            not isinstance(value, bool) and isinstance(value, (int, float)) and
            math.isfinite(value) and value >= 0 and
            (window['units'] != 'percent' or value <= 100))


def annotate(window, observations, cfg, clock):
    start = clock - dt.timedelta(days=7)
    buckets = {}
    cycle, anchor, previous = 0, None, None
    boundary = None
    for observation in observations:
        stamp = observation['observed_dt']
        if not start <= stamp <= clock or not valid_value(observation, window):
            continue
        reset = observation.get('resets_at')
        if previous is not None and (not usage.same_cycle(anchor, reset) or
                (reset is None and observation['remaining'] > previous['remaining'])):
            cycle += 1
            boundary = 'reset-changed' if anchor is not None and reset is not None else 'reset-unknown'
            anchor = reset
        elif previous is None:
            anchor = reset
        point = {key: observation.get(key) for key in
                 ('observed_at', 'remaining', 'resets_at', 'source')}
        point['cycle'] = cycle
        point['boundary'] = boundary
        bucket = buckets.setdefault((cycle, stamp.replace(minute=0, second=0, microsecond=0)), [])
        bucket.append(point)
        previous = observation
    points = []
    for bucket in buckets.values():
        # Keep the actual timestamps, including brief low/high readings.
        keep = {0, len(bucket) - 1,
                min(range(len(bucket)), key=lambda i: bucket[i]['remaining']),
                max(range(len(bucket)), key=lambda i: bucket[i]['remaining'])}
        points.extend(bucket[i] for i in sorted(keep))
    window['history'] = {'from': fmt_utc(start), 'to': fmt_utc(clock), 'points': points}
    window['reserve_alert'] = None
    window['alert_expires_at'] = None
    latest = usage.latest(observations)
    if latest is None or not valid_value(latest, window):
        return
    stamp = latest['observed_dt']
    expires = stamp + dt.timedelta(minutes=cfg['stale_after_minutes'][window['kind']])
    if latest['reset_dt'] is not None:
        expires = min(expires, latest['reset_dt'])
    if stamp <= clock < expires and window['state'] in ('available', 'exhausted'):
        window['alert_expires_at'] = fmt_utc(expires)
        if latest['remaining'] <= window['reserve']:
            window['reserve_alert'] = 'exhausted' if latest['remaining'] == 0 else 'reserve'
