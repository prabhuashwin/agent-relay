import json
import threading
import subprocess
import urllib.error
import urllib.request
from unittest import mock

from tests.helpers import CtlCase, SESSION, WEEKLY
from usagekit import config
from usagekit.errors import CtlError
from usagekit.timeutil import now


class ClaudeQuotaTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account('claude-main', windows=[SESSION, WEEKLY,
            dict(WEEKLY, id='fable_weekly', scope='model:fable')])

    def payload(self):
        return {key: {'utilization': value, 'resets_at': '2026-11-06T12:00:00Z'}
                for key, value in [('five_hour', 0), ('seven_day', 63), ('seven_day_fable', 80)]}

    def test_parses_remaining_and_model_window(self):
        from usagekit.claude_quota import parse_quota
        cfg = config.load(self.paths)
        rows = parse_quota(self.payload(), cfg, config.zone_of(cfg), now(), 'claude-main')
        self.assertEqual([r['remaining'] for r in rows], [100, 37, 20])

    def test_missing_or_invalid_window_never_invents_capacity(self):
        from usagekit.claude_quota import parse_quota
        cfg = config.load(self.paths)
        for invalid in [None, True, float('nan'), -1, 101]:
            doc = self.payload()
            doc['seven_day']['utilization'] = invalid
            with self.assertRaises(CtlError):
                parse_quota(doc, cfg, config.zone_of(cfg), now(), 'claude-main')
        doc = self.payload()
        del doc['seven_day_fable']
        with self.assertRaises(CtlError):
            parse_quota(doc, cfg, config.zone_of(cfg), now(), 'claude-main')

    def test_fetch_auth_errors_are_redacted(self):
        from usagekit import claude_quota
        with mock.patch.object(claude_quota, 'read_token', return_value='secret-token'), \
                mock.patch('urllib.request.OpenerDirector.open', side_effect=urllib.error.HTTPError(
                    'https://api.anthropic.com', 401, 'secret-token', {}, None)):
            with self.assertRaises(CtlError) as err:
                claude_quota._read_quota()
        self.assertNotIn('secret-token', str(err.exception))
        self.assertIn('sign in', str(err.exception))

    def test_slow_provider_has_total_deadline(self):
        from usagekit import claude_quota
        with mock.patch('subprocess.run', side_effect=subprocess.TimeoutExpired('quota', 25)) as run:
            with self.assertRaises(CtlError):
                claude_quota.read_quota()
        self.assertEqual(run.call_args.kwargs['timeout'], 25)

    def test_live_schema_scoped_limit_uses_percent_not_weekly_share(self):
        from usagekit.claude_quota import parse_quota
        cfg = config.load(self.paths)
        doc = self.payload()
        del doc['seven_day_fable']
        doc['limits'] = [{'kind': 'weekly_scoped', 'percent': 80,
            'resets_at': '2026-11-06T12:00:00Z',
            'scope': {'model': {'id': None, 'display_name': 'Fable'}, 'surface': None}}]
        doc['weekly_scoped_shares'] = [{'limit_index': 0, 'used_percent_of_weekly': 40}]
        rows = parse_quota(doc, cfg, config.zone_of(cfg), now(), 'claude-main')
        self.assertEqual(rows[-1]['remaining'], 20)
        doc['limits'].append(dict(doc['limits'][0]))
        with self.assertRaises(CtlError):
            parse_quota(doc, cfg, config.zone_of(cfg), now(), 'claude-main')

    def test_claude_poller_uses_explicit_provider(self):
        from usagekit.live_usage import ProviderPoller
        poller = ProviderPoller(self.paths, 'claude-main', threading.Lock(), provider='claude', interval=180)
        with mock.patch('usagekit.live_usage.refresh_claude') as fetch:
            poller.tick(0)
            poller.tick(60)
            fetch.assert_called_once_with(self.paths, 'claude-main')

    def test_refresh_failure_preserves_history(self):
        from usagekit import live_usage, claude_quota
        self.record('claude-main', 'weekly', 30, resets_in='4d')
        before = live_usage.snapshot(self.paths)['accounts']['claude-main']['windows']
        doc = self.payload()
        doc['seven_day_fable'] = None
        with mock.patch.object(claude_quota, 'read_quota', return_value=doc):
            with self.assertRaises(CtlError):
                live_usage.refresh_claude(self.paths, 'claude-main')
        self.assertEqual(before, live_usage.snapshot(self.paths)['accounts']['claude-main']['windows'])

    def test_redirect_cannot_forward_credentials(self):
        from usagekit.claude_quota import NoRedirect
        req = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
                                     headers={'Authorization': 'Bearer secret'})
        self.assertIsNone(NoRedirect().redirect_request(req, None, 302, '', {}, 'https://example.com'))

    def test_http_claude_refresh_requires_explicit_server_opt_in(self):
        from usagekit import dashboard, live_usage
        for enabled in (False, True):
            server = dashboard.make_server(self.paths, self.tmp, port=0,
                claude_account='claude-main' if enabled else None)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            url = 'http://127.0.0.1:%d' % server.server_port
            try:
                with urllib.request.urlopen(url + '/api/usage') as response:
                    data = json.load(response)
                self.assertEqual(data['accounts']['claude-main']['can_refresh'], enabled)
                req = urllib.request.Request(url + '/api/usage/refresh',
                    data=json.dumps({'account': 'claude-main'}).encode(),
                    headers={'Content-Type': 'application/json', 'X-Relay-Token': data['action_token']})
                with mock.patch('usagekit.live_usage.refresh_claude', return_value=live_usage.snapshot(self.paths)) as fetch:
                    if enabled:
                        with urllib.request.urlopen(req) as response:
                            self.assertEqual(json.load(response)['accounts']['claude-main']['polling']['state'], 'connected')
                        fetch.assert_called_once()
                    else:
                        with self.assertRaises(urllib.error.HTTPError):
                            urllib.request.urlopen(req)
                        fetch.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
