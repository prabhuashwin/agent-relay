import threading
import itertools
import json
import os
import unittest
from pathlib import Path
from unittest import mock
from tests.helpers import CtlCase
from usagekit.errors import CtlError


class RelayReliabilityTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account('codex-main', 'codex')

    def test_failed_attempt_has_retry_and_recovery_preserves_success(self):
        from usagekit.live_usage import ProviderPoller
        poller = ProviderPoller(self.paths, 'codex-main', threading.Lock())
        with mock.patch('usagekit.live_usage.refresh_codex') as fetch:
            poller.tick(0)
            success = poller.status()['last_success']
            fetch.side_effect = CtlError('do not expose arbitrary exception text')
            poller.tick(60)
            health = poller.status()
            self.assertEqual(health['failures'], 1)
            self.assertEqual(health['last_success'], success)
            self.assertIsNotNone(health['next_attempt'])
            self.assertNotIn('arbitrary', health['error'])
            fetch.side_effect = None
            poller.tick(120)
            self.assertEqual(poller.status()['failures'], 0)
            self.assertIsNone(poller.status()['error'])

    def test_supervisor_retry_is_bounded(self):
        from usagekit.relay_supervisor import retry_delay
        self.assertEqual([retry_delay(i) for i in range(1, 7)], [5, 10, 20, 40, 60, None])

    def test_startup_config_uses_explicit_paths_without_credentials(self):
        from usagekit.startup import launch_config
        result = launch_config(self.paths, self.tmp, 8766, 'codex-main', None)
        self.assertEqual(result['cwd'], self.tmp)
        self.assertIn('--codex-account', result['command'])
        self.assertEqual(result['env']['CLAUDE_SETUP_HOME'], self.paths.home)
        self.assertNotIn('TOKEN', str(result))

    @unittest.skipUnless(os.name == 'nt', 'Windows supervisor')
    def test_supervisor_stops_after_six_crashes_without_killing_other_processes(self):
        from usagekit.relay_supervisor import supervise
        path = Path(self.tmp) / 'startup.json'
        path.write_text(json.dumps({'enabled': True, 'command': ['fake-python'],
            'cwd': self.tmp, 'env': {}, 'port': 8766}), encoding='utf-8')
        with mock.patch('subprocess.Popen') as launch, \
                mock.patch('usagekit.windows_job.own_tree', return_value=123), \
                mock.patch('usagekit.windows_job.resume_child') as resume, \
                mock.patch('usagekit.windows_job.close_tree') as close, \
                mock.patch('time.monotonic', side_effect=itertools.count(0, 60)), \
                mock.patch('time.sleep'):
            launch.return_value.poll.return_value = 1
            launch.return_value.pid = 12345
            supervise(path)
        self.assertEqual(launch.call_count, 6)
        self.assertEqual(resume.call_count, 6)
        self.assertTrue(launch.call_args.kwargs['creationflags'] & 0x4)
        launch.return_value.terminate.assert_not_called()
        status = json.loads(path.with_suffix('.status.json').read_text())
        self.assertEqual(status['state'], 'stopped_after_failures')
        self.assertEqual(sum(call.args == (123,) for call in close.call_args_list), 6)

    @unittest.skipUnless(os.name == 'nt', 'Windows supervisor')
    def test_disabled_supervisor_never_launches(self):
        from usagekit.relay_supervisor import supervise
        path = Path(self.tmp) / 'startup.json'
        path.write_text('{"enabled":false}', encoding='utf-8')
        with mock.patch('subprocess.Popen') as launch:
            supervise(path)
        launch.assert_not_called()

    def test_claude_error_category_survives_bounded_worker(self):
        from usagekit.claude_quota import read_quota
        from usagekit.errors import ProviderError
        with mock.patch('subprocess.run', return_value=mock.Mock(returncode=0,
                stdout='{"error":"Sign in required", "kind":"sign_in"}')):
            with self.assertRaises(ProviderError) as error:
                read_quota()
        self.assertEqual(error.exception.kind, 'sign_in')
