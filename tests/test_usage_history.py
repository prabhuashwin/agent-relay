from unittest import mock
import json
import threading
import urllib.request

from tests.helpers import CtlCase
from usagekit import live_usage, store


class UsageHistoryTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account('codex-main', 'codex')

    def window(self):
        return live_usage.snapshot(self.paths)['accounts']['codex-main']['windows'][0]

    def test_seven_days_exclude_future_and_old_and_do_not_fetch(self):
        self.record('codex-main', 'weekly', 80, observed_at='2026-10-26T08:59:00Z')
        self.record('codex-main', 'weekly', 70, observed_at='2026-10-26T09:00:00Z')
        self.record('codex-main', 'weekly', 50)
        records, _ = store.read_jsonl(self.paths.usage)
        store.append_jsonl(self.paths, self.paths.usage, [dict(records[-1], observed_at='2026-11-03T09:00:00Z')])
        with mock.patch('usagekit.collectors.fetch_codex') as fetch:
            result = self.window()
        fetch.assert_not_called()
        self.assertIn('history', result)
        self.assertEqual([p['remaining'] for p in result['history']['points']], [70, 50])
        self.assertIsNone(result['reserve_alert'])

    def test_hourly_sampling_preserves_extrema_and_reset_boundaries(self):
        for minute, remaining in [(0, 80), (5, 30), (10, 90), (15, 60), (20, 50)]:
            self.record('codex-main', 'weekly', remaining,
                        observed_at='2026-11-02T08:%02d:00Z' % minute,
                        resets_at='2026-11-06T12:00:00Z')
        self.record('codex-main', 'weekly', 100, resets_at='2026-11-13T12:00:00Z')
        result = self.window()
        self.assertIn('history', result)
        points = result['history']['points']
        self.assertEqual([p['remaining'] for p in points], [80, 30, 90, 50, 100])
        self.assertEqual(points[0]['cycle'], points[3]['cycle'])
        self.assertNotEqual(points[3]['cycle'], points[4]['cycle'])

    def test_alert_at_reserve_and_zero_but_not_stale_or_after_reset(self):
        self.record('codex-main', 'weekly', 10, resets_in='4d')
        self.assertEqual(self.window().get('reserve_alert'), 'reserve')
        self.record('codex-main', 'weekly', 0, resets_in='4d')
        self.assertEqual(self.window()['reserve_alert'], 'exhausted')
        self.set_now('2026-11-03T09:00:00Z')
        self.assertIsNone(self.window()['reserve_alert'])
        self.set_now('2026-11-07T09:00:00Z')
        self.assertIsNone(self.window()['reserve_alert'])

    def test_invalid_values_and_units_are_not_history_or_alerts(self):
        self.record('codex-main', 'weekly', 50)
        records, _ = store.read_jsonl(self.paths.usage)
        for change in ({'remaining': -1}, {'remaining': 101}, {'units': 'credits'}):
            store.append_jsonl(self.paths, self.paths.usage, [dict(records[0], **change)])
        result = self.window()
        self.assertIn('history', result)
        self.assertEqual([p['remaining'] for p in result['history']['points']], [50])
        self.assertIsNone(result['reserve_alert'])

    def test_empty_history_and_recovery_above_reserve(self):
        result = self.window()
        self.assertIn('history', result)
        self.assertEqual(result['history']['points'], [])
        self.assertIsNone(result['reserve_alert'])
        self.record('codex-main', 'weekly', 9)
        self.assertEqual(self.window()['reserve_alert'], 'reserve')
        self.record('codex-main', 'weekly', 11)
        self.assertIsNone(self.window()['reserve_alert'])

    def test_reset_jitter_stays_in_cycle_and_unknown_increase_is_labeled(self):
        self.record('codex-main', 'weekly', 40, observed_at='2026-11-02T08:00:00Z',
                    resets_at='2026-11-06T12:00:00Z')
        self.record('codex-main', 'weekly', 30, observed_at='2026-11-02T08:30:00Z',
                    resets_at='2026-11-06T12:10:00Z')
        points = self.window()['history']['points']
        self.assertEqual(points[0]['cycle'], points[1]['cycle'])
        self.record('codex-main', 'weekly', 10)
        self.record('codex-main', 'weekly', 50)
        self.assertEqual(self.window()['history']['points'][-1].get('boundary'), 'reset-unknown')

    def test_http_workspace_and_usage_share_history_without_provider_reads(self):
        from usagekit.dashboard import make_server
        self.record('codex-main', 'weekly', 10, resets_in='4d')
        root = self.make_repo()
        server = make_server(self.paths, root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch('usagekit.collectors.fetch_codex') as fetch:
                results = []
                for endpoint in ('/api/status', '/api/usage'):
                    with urllib.request.urlopen('http://127.0.0.1:%d%s' %
                                                (server.server_port, endpoint)) as response:
                        results.append(json.load(response)['accounts']['codex-main']['windows'][0])
                self.assertEqual(results[0], results[1])
                self.assertEqual(results[0]['reserve_alert'], 'reserve')
                self.assertEqual(results[0]['history']['points'][0]['remaining'], 10)
                fetch.assert_not_called()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
