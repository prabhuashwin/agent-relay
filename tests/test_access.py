import concurrent.futures
import json
import os
from unittest import mock

from tests.helpers import CtlCase, call


class AccessTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()

    def configure(self, **kwargs):
        from usagekit import access
        values = dict(name='phone', mode='lan', origin='https://relay.home:8443',
                      bind_address='192.168.1.20', port=8770)
        values.update(kwargs)
        return access.configure(self.paths, self.tmp, **values)

    def test_profiles_require_https_and_private_interface_for_nonpublic(self):
        from usagekit import access
        from usagekit.errors import CtlError
        for change in ({'origin': 'http://relay.home'}, {'origin': 'https://relay.home/path'},
                       {'origin': 'https://relay.home?q=x'}, {'bind_address': '0.0.0.0'},
                       {'bind_address': '8.8.8.8'}, {'origin': 'https://user:secret@relay.home'},
                       {'bind_address': 'fd00::1%eth0\n    respond hacked'},
                       {'bind_address': 'fd00::1%eth0'}, {'origin': 'https://[fd00::1%eth0]'},
                       {'origin': 'https://relay.home\nmalicious'}, {'name': '../escape'}):
            with self.subTest(change=change), self.assertRaises(CtlError):
                self.configure(**change)
        self.assertEqual(self.configure()['mode'], 'lan')
        private = self.configure(name='vpn', mode='private', bind_address='100.80.1.2')
        self.assertEqual(private['bind_address'], '100.80.1.2')
        self.configure(name='web', mode='public', origin='https://relay.example.com', bind_address='0.0.0.0')
        with self.assertRaises(CtlError):
            self.configure(name='bad', mode='public', origin='https://192.168.1.20')
        with self.assertRaises(CtlError):
            access.load_profile(self.paths, 'phone', os.path.join(self.tmp, 'other'))

    def test_pairing_one_use_session_expiry_and_hash_only_storage(self):
        from usagekit import access
        self.configure()
        with mock.patch('usagekit.access.time.time', return_value=1000):
            code = access.pair_code(self.paths, 'phone')
            session = access.pair(self.paths, 'phone', code, 'My phone')
            self.assertIsNotNone(session)
            self.assertIsNone(access.pair(self.paths, 'phone', code, 'Replay'))
            self.assertEqual(access.authenticate(self.paths, 'phone', session['token'])['label'], 'My phone')
            with open(access.db_path(self.paths), 'rb') as handle:
                raw = handle.read()
            self.assertNotIn(code.encode(), raw)
            self.assertNotIn(session['token'].encode(), raw)
        with mock.patch('usagekit.access.time.time', return_value=1000 + 8 * 3600 + 1):
            self.assertIsNone(access.authenticate(self.paths, 'phone', session['token']))

    def test_expiry_revoke_reconfigure_and_profile_isolation(self):
        from usagekit import access
        self.configure()
        self.configure(name='other', port=8771)
        with mock.patch('usagekit.access.time.time', return_value=1000):
            code = access.pair_code(self.paths, 'phone')
        with mock.patch('usagekit.access.time.time', return_value=1601):
            self.assertIsNone(access.pair(self.paths, 'phone', code, 'late'))
            session = access.pair(self.paths, 'phone', access.pair_code(self.paths, 'phone'), 'phone')
            self.assertIsNone(access.authenticate(self.paths, 'other', session['token']))
            access.revoke(self.paths, 'phone', session['id'])
            self.assertIsNone(access.authenticate(self.paths, 'phone', session['token']))
            session = access.pair(self.paths, 'phone', access.pair_code(self.paths, 'phone'), 'phone')
            self.configure(origin='https://new.home:8443')
            self.assertIsNone(access.authenticate(self.paths, 'phone', session['token']))

    def test_concurrent_pairing_only_one_wins_and_failures_are_bounded(self):
        from usagekit import access
        self.configure()
        code = access.pair_code(self.paths, 'phone')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: access.pair(self.paths, 'phone', code, 'phone'), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        with mock.patch('usagekit.access.time.time', return_value=2000):
            for _ in range(20):
                access.pair(self.paths, 'phone', 'invalid', 'phone')
            code = access.pair_code(self.paths, 'phone')
            self.assertIsNone(access.pair(self.paths, 'phone', code, 'phone'))
        with mock.patch('usagekit.access.time.time', return_value=2061):
            self.assertIsNotNone(access.pair(self.paths, 'phone', code, 'phone'))

    def test_caddy_profiles_bind_correct_interface_without_plaintext_redirect_listener(self):
        from usagekit import access
        for mode, bind, origin in [('lan', '192.168.1.20', 'https://relay.home:8443'),
                                   ('private', '100.80.1.2', 'https://relay.vpn:8443'),
                                   ('public', '0.0.0.0', 'https://relay.example.com')]:
            profile = self.configure(mode=mode, bind_address=bind, origin=origin)
            rendered = access.caddyfile(profile)
            self.assertIn('bind ' + bind, rendered)
            self.assertIn('127.0.0.1:8770', rendered)
            self.assertIn('auto_https disable_redirects', rendered)
            self.assertEqual('tls internal' in rendered, mode != 'public')

    def test_cli_status_never_prints_session_secrets(self):
        from usagekit import access
        self.configure()
        session = access.pair(self.paths, 'phone', access.pair_code(self.paths, 'phone'), 'phone')
        result = call('board', 'access', 'sessions', '--profile', 'phone')
        self.assertEqual(result.code, 0, result.err)
        self.assertIn('phone', result.out)
        self.assertNotIn(session['token'], result.out)
        self.assertNotIn(session['csrf'], result.out)

    def test_cli_serve_and_startup_use_profile_without_changing_local_default(self):
        from usagekit import access
        from usagekit.startup import launch_config
        root = self.make_repo()
        access.configure(self.paths, root, 'phone', 'private', 'https://relay.vpn:8443', '100.80.1.2', 8770)
        with mock.patch('usagekit.remote_dashboard.serve') as remote:
            result = call('board', 'serve', '--access-profile', 'phone')
            self.assertEqual(result.code, 0, result.err)
            self.assertEqual(remote.call_args.args[2], 'phone')
        result = launch_config(self.paths, root, 8766, None, None, access_profile='phone')
        self.assertIn('--access-profile', result['command'])
        self.assertEqual(result['port'], 8770)
        self.assertNotIn('--access-profile', launch_config(self.paths, root, 8766, None, None)['command'])

    def test_revision_is_checked_inside_pair_and_session_transactions(self):
        from usagekit import access
        old = self.configure()
        newer = self.configure(origin='https://new.home:8443')
        code = access.pair_code(self.paths, 'phone')
        self.assertIsNone(access.pair(self.paths, 'phone', code, 'phone', expected_revision=old['revision']))
        session = access.pair(self.paths, 'phone', code, 'phone', expected_revision=newer['revision'])
        self.assertIsNotNone(session)
        self.assertIsNone(access.authenticate(self.paths, 'phone', session['token'], expected_revision=old['revision']))

    def test_reconfigure_during_code_issuance_cannot_create_new_scope_code(self):
        from usagekit import access
        from usagekit.errors import CtlError
        old = self.configure()
        def change_profile(*_args):
            self.configure(origin='https://new.home:8443')
            return old
        with mock.patch('usagekit.access.load_profile', side_effect=change_profile):
            with self.assertRaises(CtlError):
                access.pair_code(self.paths, 'phone')
        with access.database(self.paths) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM codes').fetchone()[0], 0)
