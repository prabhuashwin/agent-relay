"""Standalone hidden Windows launcher; never imports or stores credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def retry_delay(failures):
    return min(60, 5 * 2 ** (failures - 1)) if failures <= 5 else None


def supervise(config_path):
    import msvcrt
    try:
        from .windows_job import own_tree, close_tree, resume_child
    except ImportError:  # Launched as a standalone script by pythonw.
        from windows_job import own_tree, close_tree, resume_child
    path = Path(config_path)
    lock = path.with_suffix('.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return
    status_path = path.with_suffix('.status.json')
    def status(state, **extra):
        temporary = status_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(state=state, supervisor_pid=os.getpid(),
            updated_at=time.time(), **extra)), encoding='utf-8')
        temporary.replace(status_path)
    def enabled():
        try:
            return json.loads(path.read_text(encoding='utf-8')).get('enabled') is True
        except (OSError, ValueError):
            return False
    child, job = None, None
    try:
        cfg = json.loads(path.read_text(encoding='utf-8'))
        failures = 0
        while enabled():
            started = time.monotonic()
            try:
                child = subprocess.Popen(cfg['command'], cwd=cfg['cwd'],
                    env=dict(os.environ, **cfg['env']), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW | 0x4)  # CREATE_SUSPENDED
                job = own_tree(child)
                resume_child(child)
            except OSError:
                status('launch_failed')
                return
            status('running', child_pid=child.pid, port=cfg['port'])
            while child.poll() is None and enabled():
                time.sleep(2)
            if not enabled():
                break
            close_tree(job)
            job = None
            failures = 1 if time.monotonic() - started >= 300 else failures + 1
            delay = retry_delay(failures)
            if delay is None:
                status('stopped_after_failures', failures=failures,
                       action='Check the configured port, repository path and Python installation; disable then enable startup.')
                return
            status('restarting', failures=failures, retry_in_seconds=delay)
            until = time.monotonic() + delay
            while enabled() and time.monotonic() < until:
                time.sleep(1)
        status('disabled')
    finally:
        close_tree(job)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        lock.close()


if __name__ == '__main__':
    supervise(sys.argv[1])
