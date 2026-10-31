"""Supported usage collectors. No model turns, credential reads, or background polling."""
import datetime as dt
import json
import math
import os
import queue
import shutil
import signal
import subprocess
import threading
import time

from . import store, usage
from .errors import CtlError
from .timeutil import UTC, fmt_utc


def codex_command():
    exe = shutil.which('codex')
    if not exe:
        raise CtlError('Codex CLI not found on PATH; install it and sign in first')
    # npm on Windows installs a cmd shim; use its JS entry point directly when available.
    if os.name == 'nt' and exe.lower().endswith(('.cmd', '.bat')):
        script = os.path.join(os.path.dirname(exe), 'node_modules', '@openai', 'codex', 'bin', 'codex.js')
        node = shutil.which('node')
        if node and os.path.isfile(script):
            return [node, script, 'app-server', '--listen', 'stdio://']
    return [exe, 'app-server', '--listen', 'stdio://']


def fetch_rate_limits(timeout=20, command=None):
    """Read limits from the logged-in CLI account; always stop the owned process."""
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise CtlError('timeout must be greater than zero and at most 60 seconds')
    command = command or codex_command()
    deadline = time.monotonic() + timeout
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                start_new_session=os.name != 'nt',
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except OSError:
        raise CtlError('Could not start Codex app-server; check the CLI installation')
    messages = queue.Queue()

    def read():
        try:
            while True:
                line = proc.stdout.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    messages.put(None)
                    return
                messages.put(line)
        except (OSError, ValueError, UnicodeError):
            pass
        finally:
            messages.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()

    def send(message):
        try:
            proc.stdin.write(json.dumps(message) + '\n')
            proc.stdin.flush()
        except (OSError, ValueError):
            raise CtlError('Codex app-server closed its input unexpectedly')

    def response(rid):
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise CtlError('Codex usage fetch timed out; existing observations were kept')
            try:
                line = messages.get(timeout=left)
            except queue.Empty:
                raise CtlError('Codex usage fetch timed out; existing observations were kept')
            if line is None:
                raise CtlError('Codex app-server closed before returning usage')
            try:
                msg = json.loads(line)
            except ValueError:
                raise CtlError('Codex app-server returned invalid JSON')
            if not isinstance(msg, dict) or msg.get('id') != rid:
                continue
            if 'error' in msg:
                # Do not echo provider errors, which could contain account or authentication details.
                raise CtlError('Codex rejected the usage request; check sign-in and app-server compatibility')
            if 'result' not in msg:
                raise CtlError('Codex app-server response has no result')
            return msg['result']

    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {
            'name': 'claude_setup_usage', 'title': 'Usage coordinator', 'version': '1.0'}}})
        response(1)
        send({'method': 'initialized', 'params': {}})
        send({'id': 2, 'method': 'account/rateLimits/read'})
        return response(2)
    finally:
        if proc.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            else:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name != 'nt':
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    proc.kill()
                proc.wait(timeout=3)
        reader.join(timeout=1)
        proc.stdin.close()
        proc.stdout.close()


def require_provider(cfg, alias, provider):
    account = cfg['accounts'].get(alias)
    if not account or account['provider'] != provider:
        raise CtlError('Choose a configured %s account alias' % provider.capitalize())
    return account


def parse_codex(result, cfg, zone, now, alias):
    acct = require_provider(cfg, alias, 'codex')
    if not isinstance(result, dict):
        raise CtlError('Codex returned no usable rate limits')
    buckets = result.get('rateLimitsByLimitId')
    bucket = buckets.get('codex') if isinstance(buckets, dict) else result.get('rateLimits')
    if not isinstance(bucket, dict) or bucket.get('limitId') not in (None, 'codex'):
        raise CtlError('Codex usage bucket is missing; existing observations were kept')
    configured = [w for w in acct['windows'] if w['scope'] == 'shared']
    if not configured:
        raise CtlError('Configure Codex shared quota windows before fetching usage')
    mapped = {}
    for slot in ('primary', 'secondary'):
        data = bucket.get(slot)
        if data is None:
            continue
        if not isinstance(data, dict):
            raise CtlError('Malformed Codex quota window')
        duration = data.get('windowDurationMins')
        kind = {300: 'session', 10080: 'weekly'}.get(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
        matches = [w for w in configured if w['kind'] == kind and w['units'] == 'percent'] if kind else []
        if len(matches) != 1 or matches[0]['id'] in mapped:
            raise CtlError('Codex returned an unknown or ambiguous quota window; review account window configuration')
        used, reset = data.get('usedPercent'), data.get('resetsAt')
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
            raise CtlError('Invalid Codex used percentage')
        if isinstance(reset, bool) or not isinstance(reset, (int, float)) or not math.isfinite(reset):
            raise CtlError('Invalid Codex reset time')
        try:
            reset_iso = fmt_utc(dt.datetime.fromtimestamp(reset, UTC))
        except (ValueError, OverflowError, OSError):
            raise CtlError('Invalid Codex reset time')
        w = matches[0]
        mapped[w['id']] = usage.parse_observation(dict(account=alias, window=w['id'], remaining=100-used,
            units='percent', resets_at=reset_iso, observed_at=fmt_utc(now), source='codex-app-server', confidence='high'),
            cfg, zone, now)
    if set(mapped) != {w['id'] for w in configured}:
        raise CtlError('Codex did not return every configured shared window; refresh failed without changing history')
    return list(mapped.values())


def fetch_codex(paths, cfg, zone, now, alias, timeout=20):
    require_provider(cfg, alias, 'codex')
    result = fetch_rate_limits(timeout)
    recs = parse_codex(result, cfg, zone, now, alias)
    store.append_jsonl(paths, paths.usage, recs)
    return recs


def capture_claude(paths, cfg, zone, now, text):
    alias = cfg.get('claude_capture_account')
    if not alias:
        return []
    require_provider(cfg, alias, 'claude')
    doc = usage.loads_strict(text)
    if not isinstance(doc, dict) or not doc.get('rate_limits'):
        return []  # Normal before Claude's first response; never invent a fresh observation.
    recs = usage.parse_claude_statusline(text, cfg, zone, now, alias)
    index, _ = usage.load_index(paths)
    fresh = []
    for rec in recs:
        old = usage.latest(index.get((alias, rec['window']), []))
        if old and old.get('source') == rec['source'] and old['remaining'] == rec['remaining'] \
                and old.get('resets_at') == rec['resets_at'] and 0 <= (now-old['observed_dt']).total_seconds() < 60:
            continue
        fresh.append(rec)
    store.append_jsonl(paths, paths.usage, fresh)
    return fresh
