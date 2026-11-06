import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from tests.helpers import CtlCase


class LiveUsageTests(CtlCase):
    def test_provider_polling_runs_without_browser_and_backs_off(self):
        from usagekit.live_usage import ProviderPoller
        from usagekit.errors import CtlError
        poller = ProviderPoller(self.paths, 'codex-main', threading.Lock(), interval=60)
        with mock.patch('usagekit.live_usage.refresh_codex') as fetch:
            poller.tick(0)
            poller.tick(59)
            self.assertEqual(fetch.call_count, 1)
            fetch.side_effect = CtlError('provider unavailable')
            poller.tick(60)
            self.assertEqual(poller.status()['state'], 'error')
            poller.tick(119)
            self.assertEqual(fetch.call_count, 2)
            poller.tick(120)
            poller.tick(239)
            self.assertEqual(fetch.call_count, 3)
            fetch.side_effect = None
            poller.tick(240)
            self.assertEqual(poller.status()['state'], 'connected')
            self.assertEqual(fetch.call_count, 4)
            poller._status = dict(poller._status, state='error')
            poller.failures = 5
            poller.record_success()
            self.assertEqual(poller.failures, 0)
            self.assertEqual(poller.status()['state'], 'connected')

    def test_provider_polling_does_not_overlap_manual_fetch(self):
        from usagekit.live_usage import ProviderPoller
        lock = threading.Lock()
        poller = ProviderPoller(self.paths, 'codex-main', lock)
        with lock, mock.patch('usagekit.live_usage.refresh_codex') as fetch:
            poller.tick(0)
            fetch.assert_not_called()

    def setUp(self):
        super().setUp()
        self.init()
        self.add_account('codex-main', 'codex')
        self.add_account('claude-main', 'claude')

    def test_local_status_never_fetches_provider(self):
        from usagekit import live_usage
        with mock.patch('usagekit.collectors.fetch_codex') as fetch:
            result = live_usage.snapshot(self.paths)
        fetch.assert_not_called()
        self.assertEqual(result['accounts']['codex-main']['state'], 'unknown')
        self.assertFalse(result['accounts']['claude-main']['capture_enabled'])

    def test_refresh_validates_provider_before_calling(self):
        from usagekit import live_usage
        from usagekit.errors import CtlError
        with mock.patch('usagekit.collectors.fetch_codex') as fetch:
            for alias in ('missing', 'claude-main', None):
                with self.assertRaises(CtlError):
                    live_usage.refresh_codex(self.paths, alias)
        fetch.assert_not_called()

    def test_refresh_writes_and_returns_new_reading(self):
        from usagekit import live_usage
        def fetched(*args, **kwargs):
            self.record('codex-main', 'weekly', 72, resets_in='4d')
            self.record('codex-main', 'five_hour', 81, resets_in='4h')
        with mock.patch('usagekit.collectors.fetch_codex', side_effect=fetched) as fetch:
            result = live_usage.refresh_codex(self.paths, 'codex-main')
        self.assertEqual(fetch.call_args.args[4], 'codex-main')
        self.assertEqual(result['accounts']['codex-main']['state'], 'available')
        self.assertEqual(result['accounts']['codex-main']['windows'][0]['remaining'], 72)

    def test_failure_keeps_old_observation_and_timestamp(self):
        from usagekit import live_usage
        from usagekit.errors import CtlError
        self.record('codex-main', 'weekly', 32, resets_in='4d')
        before = live_usage.snapshot(self.paths)['accounts']['codex-main']['windows']
        with mock.patch('usagekit.collectors.fetch_codex', side_effect=CtlError('timed out')):
            with self.assertRaises(CtlError):
                live_usage.refresh_codex(self.paths, 'codex-main')
        self.assertEqual(before, live_usage.snapshot(self.paths)['accounts']['codex-main']['windows'])

    def test_claude_capture_changes_appear_and_age_normally(self):
        from usagekit import live_usage
        self.edit_config(lambda c: c.update(claude_capture_account='claude-main'))
        self.record('claude-main', 'five_hour', 55, resets_in='4h')
        result = live_usage.snapshot(self.paths)['accounts']['claude-main']
        self.assertTrue(result['capture_enabled'])
        self.assertEqual(result['windows'][1]['remaining'], 55)
        self.set_now('2026-11-02T11:00:00Z')
        result = live_usage.snapshot(self.paths)['accounts']['claude-main']
        self.assertEqual(result['windows'][1]['state'], 'stale')

    def test_http_refresh_is_protected_and_single_flight(self):
        from usagekit.dashboard import make_server
        from usagekit import live_usage
        server = make_server(self.paths, self.tmp, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:%d' % server.server_port
        entered, finish = threading.Event(), threading.Event()
        def fetch(*args):
            entered.set()
            finish.wait(5)
            return live_usage.snapshot(self.paths)
        try:
            with mock.patch('usagekit.continuity.snapshot', return_value={'accounts': {'same_snapshot': True}}), mock.patch('usagekit.live_usage.snapshot', side_effect=AssertionError('must not reread usage')):
                with urllib.request.urlopen(url + '/api/status') as response:
                    self.assertTrue(json.load(response)['accounts']['same_snapshot'])
            with urllib.request.urlopen(url + '/api/usage') as response:
                payload = json.load(response)
            headers = {'Content-Type': 'application/json'}
            body = json.dumps({'account': 'codex-main'}).encode()
            def request():
                return urllib.request.urlopen(urllib.request.Request(url + '/api/usage/refresh', data=body, headers=headers))
            with self.assertRaises(urllib.error.HTTPError) as denied:
                request()
            self.assertEqual(denied.exception.code, 403)
            headers['X-Relay-Token'] = payload['action_token']
            with mock.patch('usagekit.live_usage.refresh_codex', side_effect=fetch):
                responses = []
                def first_request():
                    with request() as response:
                        responses.append(response.status)
                worker = threading.Thread(target=first_request)
                worker.start()
                self.assertTrue(entered.wait(3))
                with self.assertRaises(urllib.error.HTTPError) as conflict:
                    request()
                self.assertEqual(conflict.exception.code, 409)
                finish.set()
                worker.join(5)
                self.assertEqual(responses, [200])
        finally:
            finish.set()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
