"""Fresh local observations and explicit, bounded Codex quota refreshes."""
import os
import threading
import time
import datetime as dt

from . import collectors, config, usage, usage_history
from .errors import CtlError
from .timeutil import fmt_utc, now


class ProviderPoller:
    """Account-level reads independent of browser or local model activity."""
    def __init__(self, paths, alias, lock, interval=60, provider='codex'):
        cfg = config.load(paths)
        collectors.require_provider(cfg, alias, provider)
        self.provider = provider
        if interval < 60:
            raise CtlError('Provider polling interval must be at least 60 seconds')
        self.paths, self.alias, self.lock = paths, alias, lock
        self.interval, self.due, self.failures = interval, 0, 0
        self.stopped = threading.Event()
        self.thread = None
        self._status = {'account': alias, 'state': 'waiting', 'interval_seconds': interval,
                        'last_success': None, 'last_attempt': None, 'next_attempt': None,
                        'failures': 0, 'error_kind': None, 'error': None}

    def status(self):
        return dict(self._status)

    def record_success(self):
        self.failures = 0
        self.due = time.monotonic() + self.interval
        self._status = dict(self._status, state='connected', last_success=fmt_utc(now()),
            last_attempt=fmt_utc(now()), next_attempt=fmt_utc(now() + dt.timedelta(seconds=self.interval)),
            failures=0, error_kind=None, error=None)

    def record_failure(self, exc, clock=None):
        self.failures += 1
        delay = min(900, self.interval * 2 ** min(self.failures - 1, 4))
        self.due = (time.monotonic() if clock is None else clock) + delay
        kind = getattr(exc, 'kind', 'unavailable')
        messages = {'sign_in': 'Open Claude Code and sign in again, then refresh usage.',
                    'rate_limited': 'Provider rate limit reached. Automatic retry is scheduled.',
                    'connection': 'Provider could not be reached. Check your connection; retry is scheduled.'}
        self._status = dict(self._status, state='error', failures=self.failures,
            last_attempt=fmt_utc(now()), next_attempt=fmt_utc(now() + dt.timedelta(seconds=delay)),
            error_kind=kind if kind in messages else 'unavailable',
            error=messages.get(kind, 'Usage sync failed. Check the provider CLI login and compatibility; retry is scheduled.'))

    def tick(self, clock=None):
        supplied_clock = clock is not None
        clock = time.monotonic() if clock is None else clock
        if clock < self.due or not self.lock.acquire(blocking=False):
            return
        try:
            (refresh_claude if self.provider == 'claude' else refresh_codex)(self.paths, self.alias)
            self.record_success()
        except Exception as exc:
            # Never expose provider exceptions or authentication material to the UI.
            self.record_failure(exc, clock)
        finally:
            delay = min(900, self.interval * 2 ** min(max(0, self.failures - 1), 4))
            self.due = (clock if supplied_clock else time.monotonic()) + delay
            self.lock.release()

    def start(self):
        def run():
            while not self.stopped.is_set():
                self.tick()
                self.stopped.wait(1)
        self.thread = threading.Thread(target=run, name='relay-provider-poll', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=30)


def annotate(accounts, cfg, index, clock=None):
    """Add collection metadata to the same observation snapshot used for routing."""
    clock = clock or now()
    for alias, account in accounts.items():
        account['capture_enabled'] = cfg.get('claude_capture_account') == alias
        account['can_refresh'] = account['provider'] == 'codex'
        for window in account['windows']:
            observation = usage.latest(index.get((alias, window['window']), []))
            window['source'] = observation.get('source') if observation else None
            usage_history.annotate(window, index.get((alias, window['window']), []), cfg, clock)
    return accounts


def snapshot(paths):
    cfg = config.load(paths) if os.path.exists(paths.config) else config.default_config()
    clock = now()
    index, bad = usage.load_index(paths)
    accounts = annotate(usage.status(cfg, index, clock, config.zone_of(cfg)), cfg, index, clock)
    return {'accounts': accounts, 'checked_at': fmt_utc(clock),
            'warnings': ['Some usage observations could not be read.'] if bad else []}


def refresh_codex(paths, alias):
    cfg = config.load(paths)
    if not isinstance(alias, str) or alias not in cfg['accounts']:
        raise CtlError('Choose a configured Codex account alias matching the current CLI login.')
    if cfg['accounts'][alias]['provider'] != 'codex':
        raise CtlError('Claude usage arrives through terminal capture; it cannot be fetched on demand.')
    collectors.fetch_codex(paths, cfg, config.zone_of(cfg), now(), alias, timeout=20)
    return snapshot(paths)


def refresh_claude(paths, alias):
    from .claude_quota import fetch_claude
    cfg = config.load(paths)
    fetch_claude(paths, cfg, config.zone_of(cfg), now(), alias)
    return snapshot(paths)
