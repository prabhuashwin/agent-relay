"""Optional end-to-end TLS test. Uses only loopback and an isolated, untrusted CA."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time
import unittest
from unittest import mock

from tests.helpers import CtlCase


@unittest.skipUnless(os.environ.get('RELAY_TEST_CADDY') and importlib.util.find_spec('waitress'),
                     'set RELAY_TEST_CADDY and install remote requirements for local TLS smoke test')
class RemoteTLSTests(CtlCase):
    def test_pair_and_refresh_through_real_caddy_tls_and_waitress(self):
        from waitress import create_server
        from usagekit import access, live_usage
        from usagekit.dashboard import make_server
        from usagekit.remote_dashboard import Gateway
        self.init()
        self.add_account('codex-main', 'codex')
        root = self.make_repo()
        with socket.socket() as free:
            free.bind(('127.0.0.1', 0))
            tls_port = free.getsockname()[1]
        origin = 'https://localhost:' + str(tls_port)
        profile = access.configure(self.paths, root, 'phone', 'lan', origin, '192.168.1.20', 8770)
        backend = make_server(self.paths, root, 0)
        backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
        backend_thread.start()
        channels = {}
        gateway = create_server(Gateway(self.paths, profile, backend), host='127.0.0.1', port=0,
                                map=channels, url_scheme='https', clear_untrusted_proxy_headers=True)
        gateway_thread = threading.Thread(target=gateway.run, daemon=True)
        gateway_thread.start()
        directory = Path(self.tmp) / 'caddy-test'
        directory.mkdir()
        # Test-only overrides: never bind the actual LAN address or install CA trust.
        text = access.caddyfile(profile).replace('    admin off', '    admin off\n    skip_install_trust')
        text = text.replace('bind 192.168.1.20', 'bind 127.0.0.1')
        text = text.replace('127.0.0.1:8770', '127.0.0.1:' + str(gateway.effective_port))
        caddyfile = directory / 'Caddyfile'
        caddyfile.write_text(text, encoding='utf-8')
        env = dict(os.environ, APPDATA=str(directory / 'appdata'),
                   XDG_DATA_HOME=str(directory / 'data'), XDG_CONFIG_HOME=str(directory / 'config'))
        process, connection = None, None
        try:
            with (directory / 'caddy.log').open('wb') as log:
                process = subprocess.Popen([os.environ['RELAY_TEST_CADDY'], 'run', '--config', str(caddyfile),
                                            '--adapter', 'caddyfile'], env=env, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=log,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                self.assertIsNone(process.poll(), 'Caddy exited before local TLS was ready')
                certificates = list(directory.rglob('root.crt'))
                if certificates:
                    try:
                        context = ssl.create_default_context(cafile=str(certificates[0]))
                        connection = http.client.HTTPSConnection('localhost', tls_port, context=context, timeout=2)
                        connection.request('GET', '/api/usage')
                        response = connection.getresponse(); response.read()
                        self.assertEqual(response.status, 401)
                        break
                    except (OSError, http.client.HTTPException):
                        if connection:
                            connection.close()
                        connection = None
                time.sleep(0.1)
            self.assertIsNotNone(connection, 'Local TLS did not become ready within 20 seconds')
            headers = {'Origin': origin, 'Content-Type':'application/json'}
            connection.request('POST', '/api/pair', json.dumps({'code':access.pair_code(self.paths, 'phone'), 'label':'TLS phone'}), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            headers['Cookie'] = response.getheader('Set-Cookie').split(';')[0]
            headers['X-Relay-Token'] = json.loads(response.read())['action_token']
            with mock.patch('usagekit.live_usage.refresh_codex', return_value=live_usage.snapshot(self.paths)) as fetch:
                connection.request('POST', '/api/usage/refresh', json.dumps({'account':'codex-main'}), headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn('accounts', json.loads(response.read()))
                fetch.assert_called_once()
        finally:
            if connection:
                connection.close()
            if process:
                process.terminate()
                process.wait(timeout=5)
            gateway.task_dispatcher.shutdown(cancel_pending=True, timeout=5)
            for channel in list(channels.values()):
                channel.close()
            gateway_thread.join(timeout=5)
            backend.shutdown(); backend.server_close(); backend_thread.join(timeout=5)
