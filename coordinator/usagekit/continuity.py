"""Local workstream views and cooperative, checkpoint-bound ownership transfers."""

import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile

from . import checkpoint_lock, config, handoff, history, live_usage, routing, store, usage
from .errors import CtlError, EXIT_CONFLICT
from .timeutil import fmt_utc, now


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def repo_key(root):
    return os.path.normcase(os.path.realpath(root))


@contextlib.contextmanager
def database(paths):
    config.ensure_writable(paths)
    os.makedirs(paths.state, exist_ok=True)
    db = sqlite3.connect(os.path.join(paths.state, 'continuity.sqlite3'), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('CREATE TABLE IF NOT EXISTS releases (repo TEXT, slug TEXT, ticket TEXT, '
                   'checkpoint TEXT, owner TEXT, at TEXT, consumed INTEGER DEFAULT 0, PRIMARY KEY(repo, slug))')
        db.execute('CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY, repo TEXT, slug TEXT, '
                   'record TEXT)')
        db.commit()
        yield db
    finally:
        db.close()


def checkpoint(root, slug):
    handoff.check_slug(slug)
    path = handoff.checkpoint_path(root, slug)
    if os.path.realpath(path) != os.path.abspath(path):
        raise CtlError('symlinked checkpoint paths are not supported')
    data = handoff.load_checkpoint(path)
    handoff.check_name_matches(data, slug)
    return path, data


def require_match(root, data):
    mismatches = handoff.compare(root, data)
    if mismatches:
        raise CtlError('; '.join(mismatches) + '\n' + handoff.recovery_hint(data), EXIT_CONFLICT)


def managed(paths, root, slug):
    if not os.path.exists(os.path.join(paths.state, 'continuity.sqlite3')):
        return False
    with database(paths) as db:
        return db.execute('SELECT 1 FROM releases WHERE repo=? AND slug=?', (repo_key(root), slug)).fetchone() is not None


@checkpoint_lock.operation
def release(paths, root, slug, owner, stopped):
    if stopped is not True:
        raise CtlError('Stop the source writer, then explicitly confirm --source-stopped', EXIT_CONFLICT)
    with database(paths) as db:
        db.execute('BEGIN IMMEDIATE')
        _path, data = checkpoint(root, slug)
        if data['owner'] != owner:
            raise CtlError('owner changed; refresh before releasing', EXIT_CONFLICT)
        require_match(root, data)
        ticket = secrets.token_urlsafe(24)
        db.execute('INSERT OR REPLACE INTO releases VALUES (?, ?, ?, ?, ?, ?, 0)',
                   (repo_key(root), slug, ticket, digest(data), owner, fmt_utc(now())))
        db.commit()
    return {'ticket': ticket, 'owner': owner, 'workstream': slug, 'status': 'released'}


@checkpoint_lock.operation
def claim(paths, root, slug, target, ticket):
    cfg = config.load(paths)
    account = cfg['accounts'].get(target)
    if account is None or 'edit' not in account['capabilities']:
        raise CtlError('destination must be a configured account with edit capability')
    with database(paths) as db:
        db.execute('BEGIN IMMEDIATE')
        path, data = checkpoint(root, slug)
        row = db.execute('SELECT * FROM releases WHERE repo=? AND slug=?', (repo_key(root), slug)).fetchone()
        if not row or row['consumed'] or not secrets.compare_digest(row['ticket'], str(ticket)):
            raise CtlError('no matching unconsumed release; inspect the checkpoint owner first. '
                           'If the destination already owns it, use handoff resume instead of retrying a consumed ticket. '
                           + handoff.recovery_hint(data), EXIT_CONFLICT)
        if row['checkpoint'] != digest(data):
            raise CtlError('checkpoint changed after release; prepare and release again. '
                           + handoff.recovery_hint(data), EXIT_CONFLICT)
        require_match(root, data)
        previous = data['owner']
        # Hold the writer lock through the Markdown update. If a crash interrupts commit,
        # a changed checkpoint invalidates the old ticket on the next attempt.
        db.execute('UPDATE releases SET consumed=1 WHERE repo=? AND slug=?', (repo_key(root), slug))
        data['owner'] = target
        handoff.write_checkpoint(path, data)
        db.commit()
    warning = None
    try:
        store.append_jsonl(paths, paths.tasks, [{'event': 'owner-change', 'workstream': slug,
                           'from': previous, 'to': target, 'at': fmt_utc(now())}])
    except (OSError, CtlError):
        warning = 'Ownership changed, but routing history could not be updated. Switching cooldown may be unavailable.'
    prompt = handoff.resume_prompt(account['provider'], data, 'handoffs/%s.checkpoint.md' % slug, target,
                                  latest_verification(paths, root, slug))
    prompt = '\n'.join(line for line in prompt.splitlines() if not line.startswith('Then take ownership:'))
    prompt += '\nOwnership was already claimed through Agent Relay. Do not claim it again.'
    result = {'status': 'claimed', 'owner': target, 'workstream': slug, 'prompt': prompt}
    if warning:
        result['warning'] = warning
    return result


def run_check(paths, root, slug, command, timeout=60):
    checkpoint(root, slug)
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise CtlError('supply a check after -- (an executable and its arguments)')
    if not 1 <= timeout <= 120:
        raise CtlError('check timeout must be between 1 and 120 seconds')
    before = digest(handoff.current_state(root))
    record = {'command': command, 'started_at': fmt_utc(now()), 'before': before}
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=timeout, shell=False)
            record['exit_code'] = result.returncode
            record['status'] = 'passed' if result.returncode == 0 else 'failed'
        except subprocess.TimeoutExpired:
            record.update(status='timed-out', exit_code=None)
        except OSError as exc:
            raise CtlError('cannot run check: %s' % exc)
        size = output.tell()
        output.seek(max(0, size - 8192))
        record['output_tail'] = output.read().decode('utf-8', errors='replace')
    record.update(after=digest(handoff.current_state(root)), finished_at=fmt_utc(now()))
    if record['before'] != record['after']:
        record['status'] = 'changed-during-check'
    with database(paths) as db:
        db.execute('INSERT INTO checks (repo, slug, record) VALUES (?, ?, ?)',
                   (repo_key(root), slug, json.dumps(record)))
        db.commit()
    return record


def _verification(db, root, slug, current):
    row = db.execute('SELECT record FROM checks WHERE repo=? AND slug=? ORDER BY id DESC LIMIT 1',
                     (repo_key(root), slug)).fetchone()
    if not row:
        return {'status': 'not-run'}
    try:
        record = json.loads(row['record'])
    except (ValueError, TypeError):
        return {'status': 'unavailable'}
    if (not isinstance(record, dict) or
            record.get('status') not in ('passed', 'failed', 'timed-out', 'changed-during-check') or
            not isinstance(record.get('after'), str) or
            not isinstance(record.get('command'), list) or
            not all(isinstance(arg, str) for arg in record['command'])):
        return {'status': 'unavailable'}
    if row and record['after'] != current:
        record['original_status'] = record['status']
        record['status'] = 'stale'
    return record


def latest_verification(paths, root, slug):
    if not os.path.exists(os.path.join(paths.state, 'continuity.sqlite3')):
        return {'status': 'not-run'}
    try:
        with database(paths) as db:
            return _verification(db, root, slug, digest(handoff.current_state(root)))
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, CtlError):
        # Evidence is advisory; never make a completed ownership change look failed.
        return {'status': 'unavailable'}


def snapshot(paths, root, task_type='feature', scope='small', risk='medium'):
    cfg = config.load(paths) if os.path.exists(paths.config) else config.default_config()
    zone, clock = config.zone_of(cfg), now()
    index, bad = usage.load_index(paths)
    tasks, events = history.load_tasks(paths)
    state = handoff.current_state(root)
    current = digest(state)
    result = {'repo': root, 'branch': state['branch'], 'observed_at': fmt_utc(clock),
              'accounts': live_usage.annotate(usage.status(cfg, index, clock, zone), cfg, index, clock), 'workstreams': [], 'errors': [],
              'routing_inputs': {'type': task_type, 'scope': scope, 'risk': risk},
              'setup_needed': not bool(cfg['accounts'])}
    if bad:
        result['errors'].append('Some usage observations could not be read; inspect usage status.')
    with database(paths) as db:
        for path in sorted(Path(root, 'handoffs').glob('*.checkpoint.md')):
            slug = path.name[:-len('.checkpoint.md')]
            try:
                _path, data = checkpoint(root, slug)
                mismatches = handoff.compare(root, data, state)
                row = db.execute('SELECT * FROM releases WHERE repo=? AND slug=?',
                                 (repo_key(root), slug)).fetchone()
                released = bool(row and not row['consumed'] and row['checkpoint'] == digest(data) and not mismatches)
                verification = _verification(db, root, slug, current)
                req = routing.Request(task_type, scope, risk, need=['edit'], owner=data['owner'],
                                      checkpoint=slug if not mismatches else None, workstream=slug)
                if data['owner'] in cfg['accounts']:
                    recommendation = routing.recommend(cfg, zone, clock, index, tasks, events, req)
                    if recommendation['action'] == 'switch':
                        recommendation['next_step'] = (
                            'Claim with the destination account in Transfer ownership below.' if released else
                            'Stop the source writer, prepare a matching checkpoint, then release and claim in Transfer ownership below.')
                else:
                    recommendation = {'action': 'blocked', 'recommended': None, 'confidence': 'low',
                                      'reasons': ['Checkpoint owner %s is not configured locally.' % data['owner']],
                                      'next_step': 'Configure the owner account or explicitly transfer to a configured account.',
                                      'uncertainty': 'An account alias is not a login.'}
                result['workstreams'].append({
                    'slug': slug, 'goal': data['goal'], 'owner': data['owner'], 'next_action': data['next_action'],
                    'acceptance': data['acceptance'], 'done': data['done'], 'remaining': data['remaining'],
                    'failures': data['failures'], 'checkpoint_matches': not mismatches, 'mismatches': mismatches,
                    'prepared_at': data['prepared_at'], 'status': 'released' if released else 'owned',
                    'release_ticket': row['ticket'] if released else None,
                    'reported_verification': data['verification'], 'verification': verification,
                    'recommendation': recommendation})
            except CtlError as exc:
                result['errors'].append('%s: %s' % (slug, exc.message))
    return result
