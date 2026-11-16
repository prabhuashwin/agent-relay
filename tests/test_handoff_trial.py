import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


class HandoffTrialTests(unittest.TestCase):
    def test_unchanged_crlf_fixture_is_not_an_edit(self):
        trial = self.load_trial()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            trial.write_task(repo)
            (repo / 'tags.py').write_bytes(trial.SOURCE.replace('\n', '\r\n').encode())
            process = mock.Mock()
            process.poll.side_effect = [None, 0]
            process.returncode = 0
            with mock.patch.object(trial.subprocess, 'Popen', return_value=process), \
                    mock.patch.object(trial.time, 'sleep'), \
                    mock.patch.object(trial, 'evaluate', return_value=False), \
                    mock.patch.object(trial, 'stop_process'):
                result = trial.live(root, repo, {}, 'test', 'codex', 10)
            self.assertIsNone(result['first_observed_edit_seconds'])
            self.assertIsNone(result['first_observed_edit_passed'])

    def test_posix_cleanup_includes_descendants_of_exited_parent(self):
        trial = self.load_trial()
        process = mock.Mock(pid=123)
        process.poll.return_value = 0
        with mock.patch.object(trial.os, 'name', 'posix'), \
                mock.patch.object(trial.signal, 'SIGKILL', 9, create=True), \
                mock.patch.object(trial.os, 'killpg', create=True) as kill:
            trial.stop_process(process)
        kill.assert_called_once_with(123, 9)
        process.wait.assert_called_once_with(timeout=10)

    def test_first_edit_failure_is_distinct_from_eventual_passing_edit(self):
        trial = self.load_trial()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            trial.write_task(repo)
            process = mock.Mock()
            process.poll.side_effect = [None, None, None, 0]
            process.returncode = 0
            edits = iter([trial.SOURCE + '# wrong first edit\n',
                          trial.SOURCE.replace('.lower()', '.casefold()'), None])
            def advance(_seconds):
                source = next(edits)
                if source:
                    (repo / 'tags.py').write_text(source)
            with mock.patch.object(trial.subprocess, 'Popen', return_value=process), \
                    mock.patch.object(trial.time, 'sleep', side_effect=advance), \
                    mock.patch.object(trial, 'evaluate', side_effect=[False, True, True]), \
                    mock.patch.object(trial, 'stop_process'):
                result = trial.live(root, repo, {}, 'test', 'codex', 10)
            self.assertFalse(result['first_observed_edit_passed'])
            self.assertIsNotNone(result['first_correct_change_seconds'])
            self.assertTrue(result['final_check_passed'])

    def load_trial(self):
        path = Path(__file__).resolve().parents[1] / 'docs/demo/compare_handoffs.py'
        spec = importlib.util.spec_from_file_location('trial', path)
        trial = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(trial)
        return trial

    def test_monitor_failure_stops_live_process_and_records_outcome(self):
        trial = self.load_trial()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            trial.write_task(repo)
            (root / 'prompt.txt').write_text('test')
            process = mock.Mock()
            process.poll.return_value = None
            process.returncode = 1
            def edit(_seconds):
                (repo / 'tags.py').write_text('changed')
            with mock.patch.object(trial.subprocess, 'Popen', return_value=process), \
                    mock.patch.object(trial.time, 'sleep', side_effect=edit), \
                    mock.patch.object(trial, 'evaluate', side_effect=OSError('fixture unavailable')), \
                    mock.patch.object(trial, 'stop_process') as stop:
                result = trial.live(root, repo, {}, 'test', 'codex', 10)
            stop.assert_called_once_with(process)
            self.assertIn('fixture unavailable', result['harness_error'])
            self.assertTrue((root / 'result.json').exists())

    def test_fixture_exposes_unicode_gap_and_preserves_duplicates(self):
        path = Path(__file__).resolve().parents[1] / 'docs/demo/compare_handoffs.py'
        spec = importlib.util.spec_from_file_location('trial', path)
        trial = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(trial)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            trial.write_task(repo)
            failed = subprocess.run([sys.executable, 'check.py'], cwd=repo, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            source = repo / 'tags.py'
            source.write_text(source.read_text().replace('.lower()', '.casefold()'))
            passed = subprocess.run([sys.executable, 'check.py'], cwd=repo, capture_output=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)
