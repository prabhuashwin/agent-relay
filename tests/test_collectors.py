import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests.helpers import CtlCase, call, WEEKLY, SESSION, utc
from usagekit import collectors, usage
from usagekit.errors import CtlError


class CollectorCliTests(CtlCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.add_account('claude-main', 'claude', windows=[SESSION, dict(WEEKLY, id='seven_day'),
                         dict(WEEKLY, id='fable_weekly', scope='model:fable')])
        self.add_account('codex-main', 'codex', windows=[WEEKLY])

    def test_capture_opt_in_and_disable(self):
        r = call('config', 'capture-claude', '--account', 'claude-main')
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(call('config', 'show').json['claude_capture_account'], 'claude-main')
        self.assertEqual(call('config', 'capture-claude', '--disable').code, 0)
        self.assertIsNone(call('config', 'show').json['claude_capture_account'])

    def test_disabled_capture_does_not_read_or_write_usage(self):
        with patch('sys.stdin', io.StringIO('invalid')):
            r = call('usage', 'capture-claude')
        self.assertEqual(r.code, 0, r.err)
        self.assertFalse(os.path.exists(self.paths.usage))

    def test_capture_preserves_fable_and_throttles_identical_values(self):
        self.assertEqual(call('config', 'capture-claude', '--account', 'claude-main').code, 0)
        self.record('claude-main', 'fable_weekly', 36, resets_in='4d')
        payload = json.dumps({'rate_limits': {'five_hour': {'used_percentage': 20,
                              'resets_at': utc('2026-11-02T12:00:00Z').timestamp()},
                              'seven_day': {'used_percentage': 53,
                              'resets_at': utc('2026-11-06T12:00:00Z').timestamp()}}})
        for _ in range(2):
            with patch('sys.stdin', io.StringIO(payload)):
                r = call('usage', 'capture-claude')
                self.assertEqual(r.code, 0, r.err)
        with open(self.paths.usage, encoding='utf-8') as f:
            rows = [json.loads(line) for line in f]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['remaining'], 36)
        self.assertEqual(rows[-1]['remaining'], 47)

    def test_fetch_rejects_claude_before_starting_any_process(self):
        r = call('usage', 'fetch', '--account', 'claude-main')
        self.assertNotEqual(r.code, 0)
        self.assertIn('Codex', r.err)

    def test_advise_without_refresh_uses_existing_engine(self):
        r = call('advise', '--type', 'feature', '--scope', 'small', '--risk', 'low', '--json')
        self.assertEqual(r.code, 4, r.err)
        self.assertEqual(r.json['action'], 'refresh')

    def response(self, duration=10080, used=42):
        return {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': used,
                'windowDurationMins': duration, 'resetsAt': utc('2026-11-06T12:00:00Z').timestamp()}, 'secondary': None}}}

    def test_fetch_stores_remaining_and_does_not_touch_claude(self):
        self.record('claude-main', 'fable_weekly', 36, resets_in='4d')
        with patch.object(collectors, 'fetch_rate_limits', return_value=self.response()):
            r = call('usage', 'fetch', '--account', 'codex-main', '--json')
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(r.json['observations'][0]['remaining'], 58)
        index, _ = usage.load_index(self.paths)
        self.assertEqual(index['claude-main', 'fable_weekly'][0]['remaining'], 36)

    def test_refresh_failure_aborts_advice_and_preserves_state(self):
        self.record('codex-main', 'weekly', 90, resets_in='4d')
        with open(self.paths.usage, 'rb') as f:
            before = f.read()
        with patch.object(collectors, 'fetch_rate_limits', side_effect=CtlError('fetch failed')):
            r = call('advise', '--refresh', '--type', 'feature', '--scope', 'small', '--risk', 'low')
        self.assertNotEqual(r.code, 0)
        self.assertNotIn('recommended:', r.out)
        with open(self.paths.usage, 'rb') as f:
            self.assertEqual(before, f.read())

    def test_missing_or_unconfigured_windows_never_partially_import(self):
        for payload in (self.response(duration=15), {'rateLimits': {}}, self.response(used=101)):
            with self.subTest(payload=payload), patch.object(collectors, 'fetch_rate_limits', return_value=payload):
                self.assertNotEqual(call('usage', 'fetch', '--account', 'codex-main').code, 0)
                self.assertFalse(os.path.exists(self.paths.usage))

    def test_model_specific_limit_not_refreshed_by_shared_codex_read(self):
        self.edit_config(lambda c: c['accounts']['codex-main']['windows'].append(
            dict(WEEKLY, id='special', scope='model:special')))
        with patch.object(collectors, 'fetch_rate_limits', return_value=self.response()):
            self.assertEqual(call('usage', 'fetch', '--account', 'codex-main').code, 0)
        index, _ = usage.load_index(self.paths)
        self.assertNotIn(('codex-main', 'special'), index)

    def test_absent_claude_payload_does_not_refresh_manual_history(self):
        call('config', 'capture-claude', '--account', 'claude-main')
        with patch('sys.stdin', io.StringIO('{}')):
            self.assertEqual(call('usage', 'capture-claude').code, 0)
        self.assertFalse(os.path.exists(self.paths.usage))

    def test_capture_does_not_overwrite_model_scoped_window(self):
        self.edit_config(lambda c: c['accounts']['claude-main']['windows'][1].update(scope='model:fable'))
        call('config', 'capture-claude', '--account', 'claude-main')
        payload = json.dumps({'rate_limits': {'seven_day': {'used_percentage': 53,
                            'resets_at': utc('2026-11-06T12:00:00Z').timestamp()}}})
        with patch('sys.stdin', io.StringIO(payload)):
            self.assertNotEqual(call('usage', 'capture-claude').code, 0)
        self.assertFalse(os.path.exists(self.paths.usage))

    def test_refresh_success_feeds_recommendation(self):
        with patch.object(collectors, 'fetch_rate_limits', return_value=self.response()):
            r = call('advise', '--refresh', '--type', 'feature', '--scope', 'small', '--risk', 'low', '--json')
        self.assertEqual(r.code, 0, r.err)
        self.assertIn('codex-main', r.out)
        index, _ = usage.load_index(self.paths)
        self.assertEqual(index['codex-main', 'weekly'][0]['remaining'], 58)

    def test_multiple_codex_aliases_require_explicit_selection(self):
        self.add_account('other', 'codex', windows=[WEEKLY])
        with patch.object(collectors, 'fetch_rate_limits') as fetch:
            r = call('advise', '--refresh', '--type', 'feature', '--scope', 'small', '--risk', 'low')
        fetch.assert_not_called()
        self.assertIn('--codex-account', r.err)

    def test_statusline_scripts_capture_and_keep_visible_output(self):
        from tests.helpers import ROOT
        from tests.test_install import BASH
        call('config', 'capture-claude', '--account', 'claude-main')
        shutil.copytree(os.path.join(ROOT, 'coordinator'), os.path.join(self.home, 'coordinator'),
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        payload = json.dumps({'model': {'display_name': 'Claude'}, 'rate_limits': {
            'five_hour': {'used_percentage': 20, 'resets_at': utc('2026-11-02T12:00:00Z').timestamp()},
            'seven_day': {'used_percentage': 53, 'resets_at': utc('2026-11-06T12:00:00Z').timestamp()}}})
        commands = []
        if BASH:
            commands.append([BASH, os.path.join(ROOT, 'claude-files/scripts/statusline.sh').replace('\\', '/')])
        ps = shutil.which('pwsh') or shutil.which('powershell')
        if ps:
            commands.append([ps, '-NoProfile', '-File', os.path.join(ROOT, 'claude-files/scripts/statusline.ps1')])
        if not commands:
            self.skipTest('No Bash or PowerShell available')
        for command in commands:
            with self.subTest(command=command):
                if os.path.exists(self.paths.usage):
                    os.unlink(self.paths.usage)
                env = dict(os.environ, CLAUDE_SETUP_HOME=self.home.replace('\\', '/'))
                result = subprocess.run(command, input=payload, capture_output=True, text=True, env=env, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('ctx', result.stdout)
                self.assertNotIn('imported', result.stdout)
                index, _ = usage.load_index(self.paths)
                self.assertEqual(index['claude-main', 'seven_day'][0]['remaining'], 47)


class RpcTests(unittest.TestCase):
    def test_handshake_and_only_rate_limit_request(self):
        script = '''import sys,json
first=json.loads(input()); assert first['method']=='initialize'
print(json.dumps({'id':first['id'],'result':{}}),flush=True)
assert json.loads(input())['method']=='initialized'
req=json.loads(input()); assert req['method']=='account/rateLimits/read'
print(json.dumps({'method':'irrelevant','params':{}}),flush=True)
print(json.dumps({'id':req['id'],'result':{'rateLimits':{'primary':None}}}),flush=True)
sys.stdin.read()
'''
        result = collectors.fetch_rate_limits(3, [sys.executable, '-u', '-c', script])
        self.assertEqual(result, {'rateLimits': {'primary': None}})

    def test_timeout_terminates_child(self):
        actual = subprocess.Popen
        processes = []
        def start(*args, **kwargs):
            p = actual(*args, **kwargs)
            processes.append(p)
            return p
        with patch.object(collectors.subprocess, 'Popen', side_effect=start):
            with self.assertRaisesRegex(CtlError, 'timed out'):
                collectors.fetch_rate_limits(0.2, [sys.executable, '-c', 'import time; time.sleep(30)'])
        self.assertIsNotNone(processes[0].poll())

    def test_provider_error_is_sanitized(self):
        script = "import json; input(); print(json.dumps({'id':1,'error':{'message':'SECRET_TOKEN'}}),flush=True); input()"
        with self.assertRaises(CtlError) as caught:
            collectors.fetch_rate_limits(3, [sys.executable, '-u', '-c', script])
        self.assertNotIn('SECRET_TOKEN', str(caught.exception))

    def test_closed_server_returns_controlled_error(self):
        with self.assertRaisesRegex(CtlError, 'closed'):
            collectors.fetch_rate_limits(3, [sys.executable, '-c', 'pass'])
