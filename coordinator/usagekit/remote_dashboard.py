"""Authenticated personal gateway; TLS terminates at a same-machine Caddy proxy.

Only generated, bounded HTTP requests reach the private legacy backend. Neither
the gateway nor that backend binds to a network interface.
"""
import http.client
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
import ipaddress
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit

from . import access
from .errors import CtlError

COOKIE = '__Host-RelaySession'
READ_ROUTES = ('/', '/app.js', '/style.css', '/api/status', '/api/usage')
WRITE_ROUTES = ('/api/usage/refresh', '/api/release', '/api/claim')


class Gateway:
    def __init__(self, paths, profile, backend):
        self.paths, self.profile, self.backend = paths, profile, backend
        self.assets = Path(__file__).with_name('dashboard_assets')

    def reply(self, start, status, body, mime='application/json', extra=()):
        if mime == 'application/json':
            body = json.dumps(body).encode('utf-8')
        headers = [('Content-Type', mime + '; charset=utf-8'), ('Content-Length', str(len(body))),
                   ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Referrer-Policy', 'no-referrer'), ('Strict-Transport-Security', 'max-age=31536000'),
                   ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
        start(str(status) + ' ' + HTTPStatus(status).phrase, headers + list(extra))
        return [body]

    def __call__(self, env, start):
        try:
            return self.handle(env, start)
        except (CtlError, OSError, sqlite3.Error, http.client.HTTPException, ValueError):
            return self.reply(start, 503, {'error': 'Remote access unavailable. Check Relay on the computer.'})

    def handle(self, env, start):
        method, path = env.get('REQUEST_METHOD'), env.get('PATH_INFO', '')
        origin = self.profile['origin']
        try:
            loopback = ipaddress.ip_address(env.get('REMOTE_ADDR', '')).is_loopback
        except ValueError:
            loopback = False
        if (not loopback or env.get('wsgi.url_scheme') != 'https' or
                env.get('HTTP_HOST') != urlsplit(origin).netloc or
                env.get('HTTP_ORIGIN', origin) != origin or
                env.get('HTTP_SEC_FETCH_SITE', 'none') not in ('same-origin', 'none') or
                (method == 'POST' and env.get('HTTP_ORIGIN') != origin)):
            return self.reply(start, 403, {'error': 'Use the configured HTTPS URL directly.'})
        current = access.load_profile(self.paths, self.profile['name'], self.profile['root'])
        if current['revision'] != self.profile['revision']:
            return self.reply(start, 503, {'error': 'Access profile changed. Restart Relay with the updated profile.'})
        if method not in ('GET', 'POST'):
            return self.reply(start, 405, {'error': 'Method not allowed.'})
        query = env.get('QUERY_STRING', '')
        if len(query) > 4096 or (query and path != '/api/status'):
            return self.reply(start, 400, {'error': 'Invalid query.'})
        body = None
        if method == 'POST':
            try:
                length = int(env.get('CONTENT_LENGTH', '0'))
                if length > 8192:
                    return self.reply(start, 413, {'error': 'Request too large.'})
                if length < 1 or env.get('CONTENT_TYPE') != 'application/json':
                    raise ValueError()
                raw = env['wsgi.input'].read(length)
                if len(raw) != length:
                    raise ValueError()
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                return self.reply(start, 400, {'error': 'Expected a small JSON object.'})
        if method == 'POST' and path == '/api/pair':
            session = access.pair(self.paths, self.profile['name'], body.get('code'), body.get('label'), self.profile['revision'])
            if not session:
                return self.reply(start, 401, {'error': 'Pairing failed. Check the code or wait a minute and retry.'})
            access.audit(self.paths, self.profile['name'], session['id'], 'pair', 200)
            cookie = COOKIE + '=' + session['token'] + '; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=' + str(access.SESSION_SECONDS)
            return self.reply(start, 200, {'action_token': session['csrf']}, extra=[('Set-Cookie', cookie)])
        cookie = SimpleCookie()
        try:
            cookie.load(env.get('HTTP_COOKIE', ''))
        except CookieError:
            pass
        token = cookie[COOKIE].value if COOKIE in cookie else ''
        session = access.authenticate(self.paths, self.profile['name'], token, self.profile['revision'])
        if method == 'GET' and (path == '/login.js' or (path == '/' and not session)):
            name, mime = ('login.js', 'text/javascript') if path == '/login.js' else ('login.html', 'text/html')
            return self.reply(start, 200, (self.assets / name).read_bytes(), mime)
        if method == 'GET' and path == '/style.css':
            return self.reply(start, 200, (self.assets / 'style.css').read_bytes(), 'text/css')
        if not session:
            return self.reply(start, 401, {'error': 'Pair this device to access Relay.'})
        if method == 'POST':
            csrf = env.get('HTTP_X_RELAY_TOKEN', '')
            if not isinstance(csrf, str) or not secrets.compare_digest(csrf, session['csrf']):
                return self.reply(start, 403, {'error': 'Refresh Relay before taking an action.'})
            if path == '/api/logout':
                access.revoke(self.paths, self.profile['name'], session['id'])
                return self.reply(start, 200, {'signed_out': True}, extra=[('Set-Cookie', COOKIE +
                    '=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0')])
        if path not in (READ_ROUTES if method == 'GET' else WRITE_ROUTES):
            return self.reply(start, 404, {'error': 'Not found.'})
        if method == 'POST':
            access.audit(self.paths, self.profile['name'], session['id'], path, 0)
        status, response, mime = self.forward(method, path, query, body)
        if mime == 'application/json':
            response = json.loads(response)
            if 'action_token' in response:
                response['action_token'] = session['csrf']
            response['remote_access'] = dict(authenticated=True, label=session['label'], expires=session['expires'],
                                           mode=self.profile['mode'])
        if method == 'POST':
            try:
                access.audit(self.paths, self.profile['name'], session['id'], path, status)
            except (OSError, sqlite3.Error):
                if isinstance(response, dict):
                    response['warning'] = 'Action returned a result, but its audit completion could not be saved.'
        return self.reply(start, status, response, mime)

    def forward(self, method, path, query, body):
        # Ignore all user-provided proxy/identity headers, cookies and upstream tokens.
        connection = http.client.HTTPConnection('127.0.0.1', self.backend.server_port, timeout=35)
        headers = {'Host': '127.0.0.1:' + str(self.backend.server_port)}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode('utf-8')
            headers.update({'Content-Type': 'application/json', 'X-Relay-Token': self.backend.action_token})
        try:
            connection.request(method, path + ('?' + query if query else ''), body=raw, headers=headers)
            response = connection.getresponse()
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise CtlError('Backend response too large')
            return response.status, data, response.getheader('Content-Type', 'application/json').split(';')[0]
        finally:
            connection.close()


def require_waitress():
    try:
        from waitress import create_server
    except ImportError:
        manifest = Path(__file__).resolve().parent.parent / 'requirements-remote.txt'
        raise CtlError('Remote access requires Waitress in this Python environment. Run: '
                       'python -m pip install -r "' + str(manifest) + '"') from None
    return create_server


def serve(paths, root, profile_name, codex_account=None, claude_account=None):
    from .dashboard import make_server
    create_server = require_waitress()
    profile = access.load_profile(paths, profile_name, root)
    backend = make_server(paths, root, 0, codex_account, claude_account)
    gateway, thread = None, None
    try:
        gateway = create_server(Gateway(paths, profile, backend), host='127.0.0.1', port=profile['port'],
            threads=4, connection_limit=64, channel_timeout=45, max_request_header_size=16384,
            max_request_body_size=8192, clear_untrusted_proxy_headers=True, expose_tracebacks=False,
            url_scheme='https')
        thread = threading.Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        for poller in backend.provider_pollers:
            poller.start()
        print('Relay gateway: 127.0.0.1:%d; HTTPS proxy required at %s' % (profile['port'], profile['origin']), flush=True)
        gateway.run()
    except KeyboardInterrupt:
        pass
    except OSError:
        raise CtlError('Cannot start the loopback gateway. Check its configured port.') from None
    finally:
        if gateway:
            gateway.close()
            gateway.task_dispatcher.shutdown(cancel_pending=True, timeout=5)
        if thread:
            backend.shutdown()
            thread.join(timeout=5)
        for poller in backend.provider_pollers:
            poller.stop()
        backend.server_close()
