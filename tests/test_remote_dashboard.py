import io
import json
import threading
import http.client
import importlib.util
import unittest
from unittest import mock

from tests.helpers import CtlCase


class RemoteDashboardTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account('codex-main', 'codex')
        self.root = self.make_repo()
        from usagekit import access
        from usagekit.dashboard import make_server
        from usagekit.remote_dashboard import Gateway
        self.profile = access.configure(self.paths, self.root, 'phone', 'lan',
                      'https://relay.home:8443', '192.168.1.20', 8770)
        self.backend = make_server(self.paths, self.root, 0)
        self.thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.app = Gateway(self.paths, self.profile, self.backend)
        self.cookie = ''

    def stop(self):
        self.backend.shutdown()
        self.backend.server_close()
        self.thread.join(timeout=5)

    def request(self, path, body=None, headers=None, method=None):
        raw = json.dumps(body).encode() if body is not None else b''
        env = dict(PATH_INFO=path, QUERY_STRING='', REQUEST_METHOD=method or ('POST' if body is not None else 'GET'),
                   CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json', REMOTE_ADDR='127.0.0.1',
                   HTTP_HOST='relay.home:8443', HTTP_ORIGIN='https://relay.home:8443', HTTP_COOKIE=self.cookie)
        env['wsgi.input'] = io.BytesIO(raw)
        env['wsgi.url_scheme'] = 'https'
        env.update(headers or {})
        response = {}
        def start(status, fields):
            response.update(status=int(status.split()[0]), headers=dict(fields))
        response['body'] = b''.join(self.app(env, start))
        return response

    def pair(self):
        from usagekit import access
        result = self.request('/api/pair', {'code': access.pair_code(self.paths, 'phone'), 'label': 'Phone'})
        self.assertEqual(result['status'], 200)
        self.cookie = result['headers']['Set-Cookie'].split(';')[0]
        return json.loads(result['body'])['action_token']

    def test_no_anonymous_data_and_pairing_cookie_security(self):
        self.assertEqual(self.request('/api/status')['status'], 401)
        self.assertIn(b'Pair this device', self.request('/')['body'])
        self.assertEqual(self.request('/api/pair', {'code': 'invalid', 'label': 'phone'})['status'], 401)
        from usagekit import access
        result = self.request('/api/pair', {'code': access.pair_code(self.paths, 'phone'), 'label': 'Phone'})
        for flag in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/', '__Host-RelaySession='):
            self.assertIn(flag, result['headers']['Set-Cookie'])
        self.cookie = result['headers']['Set-Cookie'].split(';')[0]
        result = self.request('/api/status')
        self.assertEqual(result['status'], 200)
        state = json.loads(result['body'])
        self.assertTrue(state['remote_access']['authenticated'])
        self.assertNotEqual(state['action_token'], self.backend.action_token)

    def test_host_origin_transport_and_csrf_are_checked_before_actions(self):
        token = self.pair()
        with mock.patch('usagekit.live_usage.refresh_codex') as fetch:
            for headers in ({'HTTP_HOST': 'evil.example'}, {'HTTP_ORIGIN': 'https://evil.example'},
                            {'HTTP_ORIGIN': ''}, {'HTTP_SEC_FETCH_SITE': 'cross-site'},
                            {'wsgi.url_scheme': 'http'}, {'REMOTE_ADDR': '192.168.1.3'},
                            {'HTTP_X_RELAY_TOKEN': 'wrong'}):
                result = self.request('/api/usage/refresh', {'account': 'codex-main'},
                                      dict(HTTP_X_RELAY_TOKEN=token, **headers) if 'HTTP_X_RELAY_TOKEN' not in headers else headers)
                self.assertEqual(result['status'], 403, headers)
            fetch.assert_not_called()
            from usagekit import live_usage
            fetch.return_value = live_usage.snapshot(self.paths)
            self.assertEqual(self.request('/api/usage/refresh', {'account': 'codex-main'},
                                         {'HTTP_X_RELAY_TOKEN': token})['status'], 200)
            fetch.assert_called_once()

    def test_logout_revocation_and_profile_change_deny_old_sessions(self):
        from usagekit import access
        token = self.pair()
        result = self.request('/api/logout', {}, {'HTTP_X_RELAY_TOKEN': token})
        self.assertEqual(result['status'], 200)
        self.assertEqual(self.request('/api/usage')['status'], 401)
        self.pair()
        access.revoke(self.paths, 'phone', 'all')
        self.assertEqual(self.request('/api/usage')['status'], 401)
        self.pair()
        access.configure(self.paths, self.root, 'phone', 'lan', 'https://new.home:8443', '192.168.1.20', 8770)
        self.assertEqual(self.request('/api/usage')['status'], 503)

    def test_fixed_routes_bounded_bodies_and_no_identity_header_bypass(self):
        self.assertEqual(self.request('/api/usage', headers={'HTTP_X_FORWARDED_USER': 'owner'})['status'], 401)
        token = self.pair()
        self.assertEqual(self.request('/api/check', {}, {'HTTP_X_RELAY_TOKEN': token})['status'], 404)
        self.assertEqual(self.request('/api/usage', method='DELETE')['status'], 405)
        self.assertEqual(self.request('/api/usage/refresh', {},
                         {'HTTP_X_RELAY_TOKEN': token, 'CONTENT_LENGTH': '9000'})['status'], 413)
        self.assertEqual(self.request('/api/usage/refresh', [], {'HTTP_X_RELAY_TOKEN': token})['status'], 400)

    def test_transfer_still_requires_source_confirmation_and_consumes_ticket(self):
        from tests.helpers import call
        self.add_account('destination', 'codex')
        prepared = call('handoff', 'prepare', '--workstream', 'mobile', '--owner', 'codex-main',
                        '--goal', 'Test transfer', '--next', 'Continue')
        self.assertEqual(prepared.code, 0, prepared.err)
        token = self.pair()
        headers = {'HTTP_X_RELAY_TOKEN': token}
        body = {'workstream': 'mobile', 'owner': 'codex-main', 'source_stopped': False}
        self.assertEqual(self.request('/api/release', body, headers)['status'], 409)
        body['source_stopped'] = True
        result = self.request('/api/release', body, headers)
        self.assertEqual(result['status'], 200, result['body'])
        body = {'workstream': 'mobile', 'to': 'destination', 'ticket': json.loads(result['body'])['ticket']}
        result = self.request('/api/claim', body, headers)
        self.assertEqual(result['status'], 200, result['body'])
        self.assertEqual(self.request('/api/claim', body, headers)['status'], 409)

    @unittest.skipUnless(importlib.util.find_spec('waitress'), 'install optional remote requirements')
    def test_waitress_http_path_for_all_three_profiles(self):
        from waitress import create_server
        from usagekit import access, live_usage
        from usagekit.remote_dashboard import Gateway
        for mode, address, origin in [('lan', '192.168.1.20', 'https://relay.home:8443'),
                                      ('private', '100.80.1.2', 'https://relay.vpn:8443'),
                                      ('public', '0.0.0.0', 'https://relay.example.com')]:
            profile = access.configure(self.paths, self.root, 'phone', mode, origin, address, 8770)
            channels = {}
            gateway = create_server(Gateway(self.paths, profile, self.backend), host='127.0.0.1', port=0,
                                    map=channels, url_scheme='https', max_request_body_size=8192,
                                    clear_untrusted_proxy_headers=True)
            thread = threading.Thread(target=gateway.run, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', int(gateway.effective_port), timeout=5)
            try:
                headers = {'Host': origin.removeprefix('https://'), 'Origin': origin, 'Content-Type': 'application/json'}
                connection.request('GET', '/api/status', headers=dict(headers, **{'X-Forwarded-User':'owner'}))
                response = connection.getresponse(); response.read()
                self.assertEqual(response.status, 401, mode)
                connection.request('POST', '/api/pair', json.dumps({'code': access.pair_code(self.paths, 'phone'), 'label':'phone'}), headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200, mode)
                headers['Cookie'] = response.getheader('Set-Cookie').split(';')[0]
                headers['X-Relay-Token'] = json.loads(response.read())['action_token']
                with mock.patch('usagekit.live_usage.refresh_codex', return_value=live_usage.snapshot(self.paths)) as fetch:
                    connection.request('POST', '/api/usage/refresh', json.dumps({'account':'codex-main'}), headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200, mode)
                    self.assertIn('accounts', json.loads(response.read()))
                    fetch.assert_called_once()
            finally:
                connection.close()
                gateway.task_dispatcher.shutdown(cancel_pending=True, timeout=5)
                for channel in list(channels.values()):
                    channel.close()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
