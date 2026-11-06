"""Loopback UI with explicit bounded quota refresh; no arbitrary command execution."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

from . import continuity, live_usage
from .errors import CtlError


def make_server(paths, root, port=8765, codex_account=None, claude_account=None):
    if not 0 <= port <= 65535:
        raise CtlError('port must be between 0 and 65535')
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).with_name('dashboard_assets')
    usage_refresh_lock = threading.Lock()
    poller = live_usage.ProviderPoller(paths, codex_account, usage_refresh_lock) if codex_account else None
    claude_poller = live_usage.ProviderPoller(paths, claude_account, usage_refresh_lock,
        interval=180, provider='claude') if claude_account else None
    pollers = [item for item in (poller, claude_poller) if item]

    def polling_metadata(result):
        for item in pollers:
            if item.alias in result.get('accounts', {}):
                result['accounts'][item.alias]['polling'] = item.status()
                result['accounts'][item.alias]['can_refresh'] = True
        return result

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, mime='application/json'):
            if mime == 'application/json':
                body = json.dumps(body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            address = '127.0.0.1:%d' % self.server.server_port
            return (self.headers.get('Host') == address and
                    self.headers.get('Origin', 'http://' + address) == 'http://' + address and
                    self.headers.get('Sec-Fetch-Site', 'same-origin') in ('same-origin', 'none'))

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {'error': 'Use the printed loopback URL directly.'})
            url = urlsplit(self.path)
            try:
                if url.path == '/api/usage':
                    result = polling_metadata(live_usage.snapshot(paths))
                    result['action_token'] = token
                    return self.send(200, result)
                if url.path == '/api/status':
                    query = parse_qs(url.query)
                    kind = query.get('type', ['feature'])[0]
                    scope = query.get('scope', ['small'])[0]
                    risk = query.get('risk', ['medium'])[0]
                    if kind not in ('feature', 'bugfix', 'refactor', 'review') or scope not in ('small', 'medium', 'large') or risk not in ('low', 'medium', 'high'):
                        raise CtlError('invalid routing inputs')
                    result = polling_metadata(continuity.snapshot(paths, root, kind, scope, risk))
                    result['action_token'] = token
                    return self.send(200, result)
                files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                         '/style.css': ('style.css', 'text/css')}
                if url.path not in files:
                    return self.send(404, {'error': 'not found'})
                name, mime = files[url.path]
                return self.send(200, (assets / name).read_bytes(), mime)
            except (CtlError, OSError) as exc:
                return self.send(400, {'error': str(exc)})

        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-Relay-Token', ''), token):
                return self.send(403, {'error': 'Refresh the dashboard before taking an action.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 8192 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('expected a small JSON request')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('expected an object')
                if self.path == '/api/usage/refresh':
                    if not usage_refresh_lock.acquire(blocking=False):
                        return self.send(409, {'error': 'A usage refresh is already running. Wait for it to finish.'})
                    try:
                        alias = body.get('account')
                        if claude_poller and alias == claude_poller.alias:
                            result = live_usage.refresh_claude(paths, alias)
                        else:
                            result = live_usage.refresh_codex(paths, alias)
                        for item in pollers:
                            if alias == item.alias:
                                item.record_success()
                        polling_metadata(result)
                    except Exception as exc:
                        for item in pollers:
                            if body.get('account') == item.alias:
                                item.record_failure(exc)
                        raise
                    finally:
                        usage_refresh_lock.release()
                    result['action_token'] = token
                    return self.send(200, result)
                slug = body.get('workstream')
                if not isinstance(slug, str):
                    raise ValueError('workstream is required')
                if self.path == '/api/release':
                    result = continuity.release(paths, root, slug, body.get('owner'), body.get('source_stopped'))
                elif self.path == '/api/claim':
                    target = body.get('to')
                    if not isinstance(target, str):
                        raise ValueError('destination is required')
                    result = continuity.claim(paths, root, slug, target, body.get('ticket'))
                else:
                    return self.send(404, {'error': 'not found'})
                return self.send(200, result)
            except (ValueError, CtlError, OSError) as exc:
                return self.send(409, {'error': str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.provider_poller = poller
    server.provider_pollers = pollers
    server.action_token = token
    return server


def serve(paths, root, port, codex_account=None, claude_account=None):
    try:
        server = make_server(paths, root, port, codex_account, claude_account)
    except OSError as exc:
        raise CtlError('cannot start dashboard: %s' % exc)
    print('Agent Relay: http://127.0.0.1:%d (Ctrl+C to stop)' % server.server_port, flush=True)
    try:
        for item in server.provider_pollers:
            item.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for item in server.provider_pollers:
            item.stop()
        server.server_close()
