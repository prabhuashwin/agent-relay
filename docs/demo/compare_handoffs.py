"""Small, opt-in live handoff pilot. Default invocation only prepares a fixture."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'coordinator/usagectl.py'
SOURCE = 'def normalize_tags(values):\n    return [v.strip().lower() for v in values if v.strip()]\n'
BASE_CHECK = "from tags import normalize_tags\nassert normalize_tags([' A ', '', 'A']) == ['a', 'a']\n"
CHECK = BASE_CHECK + "assert normalize_tags(['Stra\\u00dfe', 'STRASSE']) == ['strasse', 'strasse']\nprint('all checks passed')\n"
NOTE = """Goal: normalize tags using Unicode caseless matching, trim surrounding whitespace,
drop blank entries, preserve order and duplicates. Work is unfinished.
Completed: ASCII normalization works in tags.py. Last check: python check.py passed
before the Unicode regression case was added to check.py. That check has not rerun.
Failed attempt: using a set removed meaningful duplicates; do not repeat it.
Decision: preserve duplicate tags and their order.
Next action: fix Unicode normalization in tags.py, then run python check.py.
Acceptance: both ASCII/blank handling and the Unicode regression pass.
"""


def write_task(repo):
    repo.mkdir(parents=True, exist_ok=True)
    (repo / 'tags.py').write_text(SOURCE, encoding='utf-8')
    (repo / 'check.py').write_text(CHECK, encoding='utf-8')


def prepare(mode, provider):
    root = Path(tempfile.mkdtemp(prefix='relay-comparison-'))
    repo = root / 'repo'
    write_task(repo)
    (repo / '.gitignore').write_text('__pycache__/\n', encoding='utf-8')
    env = dict(os.environ, CLAUDE_SETUP_HOME=str(root / 'state'))
    # Use the signed-in CLIs, not unrelated API credentials inherited by the shell.
    for key in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY'):
        env.pop(key, None)

    def run(*args):
        return subprocess.run(args, cwd=repo, env=env, text=True, capture_output=True,
                              check=True, timeout=30).stdout

    def relay(*args):
        return run(sys.executable, str(CLI), *args)

    run('git', 'init', '-q', '-b', 'main')
    (repo / 'check.py').write_text(BASE_CHECK, encoding='utf-8')
    run('git', 'add', '.')
    run('git', '-c', 'user.name=RelayTrial', '-c', 'user.email=trial@example.invalid',
        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=' + str(root / 'no-hooks'),
        'commit', '-qm', 'ASCII normalization baseline')
    (repo / 'HANDOFF.md').write_text(NOTE, encoding='utf-8')
    if mode == 'relay':
        relay('init')
        for alias, tool in (('source', 'claude'), ('receiver', provider)):
            relay('account', 'add', '--account', alias, '--provider', tool, '--plan', 'trial', '--capability', 'edit')

        def checkpoint():
            relay('handoff', 'prepare', '--workstream', 'tags', '--owner', 'source',
                  '--goal', 'Unicode caseless tag normalization; preserve order and duplicates',
                  '--next', 'Fix tags.py and run python check.py',
                  '--done', 'ASCII normalization works', '--remaining', 'Unicode regression',
                  '--failure', 'Using a set removed meaningful duplicates',
                  '--decision', 'Preserve duplicate tags and order',
                  '--accept', 'ASCII, blanks and Unicode regression pass')
        checkpoint()
        relay('board', 'check', '--workstream', 'tags', '--', sys.executable, 'check.py')
        (repo / 'check.py').write_text(CHECK, encoding='utf-8')
        checkpoint()
        ticket = json.loads(relay('board', 'release', '--workstream', 'tags', '--owner', 'source',
                                 '--source-stopped', '--json'))['ticket']
        prompt = json.loads(relay('board', 'claim', '--workstream', 'tags', '--to', 'receiver',
                                 '--ticket', ticket, '--json'))['prompt']
        assert 'Executed verification: stale' in prompt
        prompt = prompt.replace('usagectl ', 'python "' + str(CLI) + '" ')
    else:
        run(sys.executable, 'check.py')
        (repo / 'check.py').write_text(CHECK, encoding='utf-8')
        prompt = NOTE
    prompt += ('\nRead HANDOFF.md. This is a bounded benchmark in this temporary repository. '
               'Modify only tags.py; do not change check.py, Git history or handoff files. '
               'Use local tools only, no network or delegation. Finish the task now and report '
               'whether the old check applies and what you verified. Missing INDEX.md and '
               'DECISIONS.md are intentional in this fixture. Do not create them.')
    (root / 'prompt.txt').write_text(prompt, encoding='utf-8')
    return root, repo, env, prompt


def evaluate(repo):
    try:
        result = subprocess.run([sys.executable, '-B', '-c', CHECK], cwd=repo,
                                capture_output=True, timeout=2)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def stop_process(process):
    if os.name == 'nt':
        if process.poll() is not None:
            return
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=10, check=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def live(root, repo, env, prompt, provider, limit, codex_cli=None):
    if provider == 'claude':
        command = [shutil.which('claude') or 'claude', '-p', '--no-session-persistence',
                   '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits',
                   '--allowedTools', 'Read,Edit,Write,Bash(python *),Bash(git diff*),Bash(git status*)']
    else:
        command = [codex_cli or shutil.which('codex.cmd') or shutil.which('codex') or 'codex', 'exec',
                   '--ephemeral', '--sandbox', 'workspace-write', '--json', '-']
        if (root / 'state').exists():
            command[2:2] = ['--add-dir', str(root / 'state')]
    started = time.monotonic()
    first_correct = None
    first_edit_passed = None
    first_edit_seconds = None
    baseline = (repo / 'tags.py').read_bytes()
    last_source = baseline
    timed_out = False
    error = None
    process = None
    passed = False
    unchanged_check = False
    (root / 'prompt.txt').write_text(prompt, encoding='utf-8')

    def observe():
        nonlocal last_source, first_correct, first_edit_passed, first_edit_seconds
        try:
            source = (repo / 'tags.py').read_bytes()
        except FileNotFoundError:
            return  # Some editors replace a file using remove/rename.
        if source == last_source:
            return
        last_source = source
        at = round(time.monotonic() - started, 2)
        correct = evaluate(repo)
        if source != baseline and first_edit_seconds is None:
            first_edit_seconds, first_edit_passed = at, correct
        if correct and first_correct is None:
            first_correct = at

    # Raw output stays outside the task repo and is never committed automatically.
    try:
        with (root / 'events.jsonl').open('w', encoding='utf-8') as output, \
                (root / 'prompt.txt').open(encoding='utf-8') as input_file:
            process = subprocess.Popen(command, cwd=repo, env=env, stdin=input_file,
                                       stdout=output, stderr=subprocess.STDOUT, text=True,
                                       start_new_session=os.name != 'nt')
            try:
                while process.poll() is None:
                    if time.monotonic() - started >= limit:
                        timed_out = True
                        break
                    observe()
                    time.sleep(0.25)
            finally:
                stop_process(process)
            observe()  # Catch edits immediately before the process exited.
            passed = evaluate(repo)
            unchanged_check = (repo / 'check.py').read_text(encoding='utf-8') == CHECK
    except Exception as exc:
        error = '%s: %s' % (type(exc).__name__, exc)
    result = {'provider': provider, 'elapsed_seconds': round(time.monotonic() - started, 2),
              'time_limit_seconds': limit, 'timed_out': timed_out,
              'exit_code': process.returncode if process else None, 'harness_error': error,
              'first_correct_change_seconds': first_correct,
              'first_observed_edit_seconds': first_edit_seconds, 'first_observed_edit_passed': first_edit_passed,
              'final_check_passed': passed and unchanged_check,
              'acceptance_test_unchanged': unchanged_check,
              'stale_evidence_acknowledged': 'manual review required',
              'repeated_investigation': 'manual review required'}
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('note', 'relay'), required=True)
    parser.add_argument('--provider', choices=('claude', 'codex'), required=True)
    parser.add_argument('--live', action='store_true', help='Consumes signed-in account allowance; explicit opt-in')
    parser.add_argument('--codex-cli', help='Optional path to a compatible Codex executable')
    parser.add_argument('--timeout', type=int, default=90, choices=range(10, 111), metavar='10..110')
    args = parser.parse_args()
    root, repo, env, prompt = prepare(args.mode, args.provider)
    print('Trial artifacts: ' + str(root), flush=True)
    if args.live:
        result = live(root, repo, env, prompt, args.provider, args.timeout, args.codex_cli)
        result['mode'] = args.mode
        (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    else:
        print('Prepared only; no model call. Add --live only with allowance authorization.')
