"""Opt-in, experimental subscription quota reads. No model requests or token writes."""
import json
import math
import os
import subprocess
import sys
from pathlib import Path
import urllib.error
import urllib.request

from . import collectors, store, usage
from .errors import CtlError, ProviderError
from .timeutil import fmt_utc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward authorization to a redirect destination.


def read_token():
    directory = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    try:
        with (directory / '.credentials.json').open(encoding='utf-8') as stream:
            credentials = json.load(stream)
        token = credentials['claudeAiOauth']['accessToken']
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError()
        return token
    except (OSError, ValueError, KeyError, TypeError):
        raise ProviderError('Claude local login unavailable. Open Claude Code and sign in; file-based credentials are required.', 'sign_in') from None


def _read_quota():
    request = urllib.request.Request('https://api.anthropic.com/api/oauth/usage', headers={
        'Authorization': 'Bearer ' + read_token(), 'anthropic-beta': 'oauth-2025-04-20',
        'Accept': 'application/json', 'User-Agent': 'AgentRelay/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError()
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        if code in (401, 403):
            raise ProviderError('Claude quota access denied. Open Claude Code and sign in again; this experimental endpoint may be unavailable.', 'sign_in') from None
        if code == 429:
            raise ProviderError('Claude quota requests are rate limited; wait before retrying.', 'rate_limited') from None
        raise CtlError('Claude quota endpoint returned an error; previous observations were kept.') from None
    except (OSError, ValueError):
        raise ProviderError('Claude quota read failed; previous observations were kept.', 'connection') from None


def read_quota():
    # A process deadline also bounds DNS/TLS and slow-drip responses, unlike a
    # socket inactivity timeout. Credentials never enter argv or stdout.
    script = ('import sys,json; sys.path.insert(0,sys.argv[1]); '
              'from usagekit.claude_quota import _read_quota; '
              'from usagekit.errors import CtlError\n'
              'try: print(json.dumps({"data":_read_quota()}))\n'
              'except CtlError as e: print(json.dumps({"error":str(e),"kind":getattr(e,"kind","unavailable")}))')
    try:
        result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve().parent.parent)],
            capture_output=True, text=True, timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
        if 'data' in payload:
            return payload['data']
        if isinstance(payload.get('error'), str):
            raise ProviderError(payload['error'], payload.get('kind', 'unavailable'))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    raise ProviderError('Claude quota read failed or timed out; previous observations were kept.', 'connection')


def parse_quota(doc, cfg, zone, clock, alias):
    account = collectors.require_provider(cfg, alias, 'claude')
    if not isinstance(doc, dict):
        raise CtlError('Claude returned no usable quota data')
    rows = []
    for window in account['windows']:
        if window['scope'] == 'shared':
            key = {'session': 'five_hour', 'weekly': 'seven_day'}.get(window['kind'])
        elif window['scope'].startswith('model:') and window['kind'] == 'weekly':
            key = 'seven_day_' + window['scope'].split(':', 1)[1]
        else:
            key = None
        data = doc.get(key)
        if window['scope'].startswith('model:') and window['kind'] == 'weekly':
            # Newer responses identify model windows in a typed limits array.
            model = window['scope'].split(':', 1)[1].casefold()
            matches = []
            limits = doc.get('limits', [])
            if not isinstance(limits, list):
                raise CtlError('Claude returned malformed scoped limits')
            for item in limits:
                if not isinstance(item, dict) or item.get('kind') != 'weekly_scoped':
                    continue
                scope = item.get('scope')
                if not isinstance(scope, dict) or scope.get('surface') is not None:
                    continue
                identity = scope.get('model')
                if isinstance(identity, dict) and model in [str(identity.get(k) or '').casefold() for k in ('id', 'display_name')]:
                    matches.append(item)
            if len(matches) > 1:
                raise CtlError('Claude returned ambiguous model quota windows')
            if matches:
                data = {'utilization': matches[0].get('percent'), 'resets_at': matches[0].get('resets_at')}
        if not isinstance(data, dict) or window['units'] != 'percent':
            raise CtlError('Claude did not return configured window %s; no observations changed.' % window['id'])
        used = data.get('utilization')
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
            raise CtlError('Claude returned an invalid used percentage')
        reset = data.get('resets_at')
        if reset is not None and not isinstance(reset, str):
            raise CtlError('Claude returned an invalid reset timestamp')
        rows.append(usage.parse_observation(dict(account=alias, window=window['id'], remaining=100-used,
            units='percent', resets_at=reset, observed_at=fmt_utc(clock),
            source='claude-oauth-experimental', confidence='high'), cfg, zone, clock))
    if not rows:
        raise CtlError('Configure Claude quota windows first')
    return rows


def fetch_claude(paths, cfg, zone, clock, alias):
    collectors.require_provider(cfg, alias, 'claude')
    rows = parse_quota(read_quota(), cfg, zone, clock, alias)
    store.append_jsonl(paths, paths.usage, rows)
    return rows
