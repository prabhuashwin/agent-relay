import os
import sys
import unittest
import json
import threading
import subprocess
import time
import sqlite3
import urllib.request
import urllib.error
from unittest import mock

from tests.test_coordinator_handoff import HandoffCase, WS
from tests.helpers import call


class ContinuityTests(HandoffCase):
    def test_claim_treats_malformed_matching_evidence_as_unavailable(self):
        from usagekit import continuity, handoff
        self.prepared()
        with continuity.database(self.paths) as db:
            db.execute('INSERT INTO checks (repo, slug, record) VALUES (?, ?, ?)',
                       (continuity.repo_key(self.repo), WS,
                        json.dumps({'after': continuity.digest(handoff.current_state(self.repo))})))
            db.commit()
        result = self.board('claim', '--workstream', WS, '--to', 'acct-b',
                            '--ticket', self.release().json['ticket'])
        self.assertEqual(result.code, 0, result.err)
        self.assertIn('Executed verification: unavailable', result.json['prompt'])
        self.assertEqual(self.ckpt()['owner'], 'acct-b')

    def test_claim_survives_unavailable_evidence_after_ownership_changes(self):
        self.prepared()
        ticket = self.release().json['ticket']
        with mock.patch('usagekit.continuity._verification', side_effect=sqlite3.OperationalError('busy')):
            result = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.ckpt()['owner'], 'acct-b')
        self.assertIn('Executed verification: unavailable', result.json['prompt'])
        self.assertIn('Recheck required', result.json['prompt'])

    def test_resume_includes_context_and_separates_reported_checks(self):
        self.write('a.txt', 'unfinished')
        self.prepared('--done', 'Added parser', '--remaining', 'Handle empty input',
                      '--failure', 'Regex approach dropped whitespace',
                      '--decision', 'Preserve whitespace', '--accept', 'Empty input works',
                      '--verify', 'pytest=>agent said passed=>pass')
        result = call('handoff', 'resume', '--workstream', WS, '--to', 'acct-b')
        self.assertEqual(result.code, 0, result.err)
        for text in ('Added parser', 'Handle empty input', 'Regex approach dropped whitespace',
                     'Preserve whitespace', 'Empty input works', 'a.txt',
                     'Executed verification: not-run', 'Reported checks (not executed evidence)'):
            self.assertIn(text, result.out)

    def test_resume_and_claim_show_stale_executed_evidence(self):
        self.prepared()
        self.assertEqual(call('board', 'check', '--workstream', WS, '--',
                              sys.executable, '-c', 'print("private output")').code, 0)
        fresh = call('handoff', 'resume', '--workstream', WS, '--to', 'acct-b')
        self.assertIn('Executed verification: passed', fresh.out)
        self.write('a.txt', 'changed')
        self.prepared()  # Matching checkpoint does not make old test evidence fresh.
        stale = call('handoff', 'resume', '--workstream', WS, '--to', 'acct-b')
        self.assertIn('Executed verification: stale', stale.out)
        self.assertIn('Recheck required', stale.out)
        ticket = self.release().json['ticket']
        claimed = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        self.assertEqual(claimed.code, 0, claimed.err)
        self.assertIn('Executed verification: stale', claimed.json['prompt'])
        self.assertNotIn('output_tail', claimed.json['prompt'])
        self.assertNotIn('Then take ownership:', claimed.json['prompt'])

    def test_changed_tree_claim_explains_recovery_without_changing_owner(self):
        self.prepared()
        ticket = self.release().json['ticket']
        self.write('a.txt', 'changed')
        failed = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        self.assertEqual(failed.code, 3)
        self.assertIn('Recovery:', failed.err)
        self.assertIn('handoff verify --workstream ' + WS, failed.err)
        self.assertIn('acct-a', failed.err)
        self.assertIn('Do not discard', failed.err)
        self.assertEqual(self.ckpt()['owner'], 'acct-a')

    def board(self, *args):
        return call('board', *args, '--json')

    def release(self):
        return self.board('release', '--workstream', WS, '--owner', 'acct-a', '--source-stopped')

    def test_board_unknown_usage_and_reported_checks(self):
        self.prepared('--verify', 'pytest=>reported successful=>pass')
        result = self.board('status')
        self.assertEqual(result.code, 0, result.err)
        item = result.json['workstreams'][0]
        self.assertTrue(item['checkpoint_matches'])
        self.assertEqual(item['verification']['status'], 'not-run')
        self.assertEqual(item['reported_verification'][0]['status'], 'pass')
        self.assertEqual(item['recommendation']['action'], 'refresh')

    def test_transfer_requires_release_and_consumes_ticket(self):
        self.prepared()
        bad = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', 'fake')
        self.assertNotEqual(bad.code, 0)
        release = self.release()
        self.assertEqual(release.code, 0, release.err)
        ticket = release.json['ticket']
        args = ('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        claimed = self.board(*args)
        self.assertEqual(claimed.code, 0, claimed.err)
        self.assertEqual(self.ckpt()['owner'], 'acct-b')
        self.assertIn('acct-b', claimed.json['prompt'])
        self.assertNotEqual(self.board(*args).code, 0)

    def test_release_requires_stopped_confirmation(self):
        self.prepared()
        result = self.board('release', '--workstream', WS, '--owner', 'acct-a')
        self.assertNotEqual(result.code, 0)

    def test_changed_tree_blocks_claim(self):
        self.prepared()
        ticket = self.release().json['ticket']
        self.write('a.txt', 'changed')
        result = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        self.assertNotEqual(result.code, 0)
        self.assertEqual(self.ckpt()['owner'], 'acct-a')

    def test_reprepared_checkpoint_invalidates_release(self):
        self.prepared()
        ticket = self.release().json['ticket']
        self.set_now('2026-11-02T10:00:00Z')
        self.prepared()
        result = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        self.assertNotEqual(result.code, 0)

    def test_executed_check_becomes_stale_after_edit(self):
        self.prepared()
        result = call('board', 'check', '--workstream', WS, '--', sys.executable, '-c', 'print("ok")')
        self.assertEqual(result.code, 0, result.err)
        evidence = self.board('status').json['workstreams'][0]['verification']
        self.assertEqual(evidence['status'], 'passed')
        self.write('a.txt', 'changed')
        evidence = self.board('status').json['workstreams'][0]['verification']
        self.assertEqual(evidence['status'], 'stale')

    def test_check_that_modifies_tree_is_not_verified(self):
        self.prepared()
        code = 'from pathlib import Path; Path("a.txt").write_text("changed")'
        result = call('board', 'check', '--workstream', WS, '--', sys.executable, '-c', code)
        self.assertNotEqual(result.code, 0)
        evidence = self.board('status').json['workstreams'][0]['verification']
        self.assertEqual(evidence['status'], 'changed-during-check')

    def test_failed_check_is_not_passed(self):
        self.prepared()
        result = call('board', 'check', '--workstream', WS, '--', sys.executable, '-c', 'raise SystemExit(4)')
        self.assertEqual(result.code, 1)
        evidence = self.board('status').json['workstreams'][0]['verification']
        self.assertEqual(evidence['status'], 'failed')
        self.assertEqual(evidence['exit_code'], 4)

    def test_other_workstream_cannot_use_ticket(self):
        self.prepared()
        self.prepare(ws='another')
        ticket = self.release().json['ticket']
        result = self.board('claim', '--workstream', 'another', '--to', 'acct-b', '--ticket', ticket)
        self.assertNotEqual(result.code, 0)

    def test_unknown_owner_does_not_break_board(self):
        self.prepared()
        self.edit_config(lambda c: c['accounts'].pop('acct-a'))
        result = self.board('status')
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json['workstreams'][0]['recommendation']['action'], 'blocked')

    def test_audit_failure_returns_committed_claim_with_warning(self):
        self.prepared()
        ticket = self.release().json['ticket']
        with mock.patch('usagekit.store.append_jsonl', side_effect=OSError('disk full')):
            result = self.board('claim', '--workstream', WS, '--to', 'acct-b', '--ticket', ticket)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.ckpt()['owner'], 'acct-b')
        self.assertIn('warning', result.json)
        self.assertIn('prompt', result.json)

    def test_legacy_claim_cannot_bypass_managed_release(self):
        self.prepared()
        self.release()
        result = call('handoff', 'claim', '--workstream', WS, '--to', 'acct-b')
        self.assertNotEqual(result.code, 0)
        self.assertEqual(self.ckpt()['owner'], 'acct-a')

    def test_switch_advice_uses_board_transfer(self):
        self.prepared()
        for account, remaining in [('acct-a', 0), ('acct-b', 80)]:
            self.record(account, 'weekly', remaining, resets_in='4d')
            self.record(account, 'five_hour', remaining, resets_in='4h')
        result = self.board('status').json['workstreams'][0]['recommendation']
        self.assertEqual(result['action'], 'switch')
        self.assertIn('release and claim', result['next_step'])
        self.release()
        prompt = call('handoff', 'resume', '--workstream', WS, '--to', 'acct-b').out
        self.assertIn('Do not edit yet', prompt)
        self.assertNotIn('Then take ownership:', prompt)

    def test_legacy_prepare_waits_for_board_claim(self):
        from tests.helpers import ROOT
        from usagekit import continuity, handoff
        self.prepared()
        ticket = self.release().json['ticket']
        original = handoff.write_checkpoint
        children = []
        def concurrent_write(path, data):
            child = subprocess.Popen([sys.executable, os.path.join(ROOT, 'coordinator', 'usagectl.py'),
                                      'handoff', 'prepare', '--workstream', WS, '--owner', 'acct-b',
                                      '--goal', 'NEW GOAL', '--next', 'new next step'],
                                     cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            children.append(child)
            time.sleep(.2)
            self.assertIsNone(child.poll(), 'legacy writer must wait for the shared lock')
            original(path, data)
        try:
            with mock.patch('usagekit.handoff.write_checkpoint', side_effect=concurrent_write):
                continuity.claim(self.paths, self.repo, WS, 'acct-b', ticket)
            out, err = children[0].communicate(timeout=15)
            self.assertEqual(children[0].returncode, 0, err.decode())
            self.assertEqual(self.ckpt()['goal'], 'NEW GOAL')
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate()

    def test_http_assets_actions_and_origin_protection(self):
        from usagekit.dashboard import make_server
        self.prepared()
        server = make_server(self.paths, self.repo, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:%d' % server.server_port
        try:
            with urllib.request.urlopen(url) as response:
                self.assertIn(b'Agent Relay', response.read())
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            with urllib.request.urlopen(url + '/api/status') as response:
                state = json.load(response)
            body = json.dumps({'workstream': WS, 'owner': 'acct-a', 'source_stopped': True}).encode()
            request = urllib.request.Request(url + '/api/release', data=body,
                                             headers={'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request)
            self.assertEqual(rejected.exception.code, 403)
            request.add_header('X-Relay-Token', state['action_token'])
            request.add_header('Origin', 'https://untrusted.example')
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request)
            self.assertEqual(rejected.exception.code, 403)
            request.remove_header('Origin')
            with urllib.request.urlopen(request) as response:
                self.assertEqual(json.load(response)['status'], 'released')
            request = urllib.request.Request(url + '/api/status', headers={'Host': 'untrusted.example'})
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request)
            self.assertEqual(rejected.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def load_tests(loader, tests, pattern):
    # Reuse the Git fixture without rerunning all inherited checkpoint tests.
    return unittest.TestSuite(ContinuityTests(name) for name in ContinuityTests.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
