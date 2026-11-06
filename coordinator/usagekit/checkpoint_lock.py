"""Cross-process lock shared by CLI and dashboard checkpoint writers."""
import contextlib
import functools
import os
import time

from . import gitutil
from .errors import CtlError, EXIT_CONFLICT


@contextlib.contextmanager
def repository(root):
    result = gitutil.git(['rev-parse', '--git-path', 'usagectl-handoff.lock'], root)
    if result.returncode:
        raise CtlError('cannot resolve checkpoint lock path')
    path = result.stdout.strip()
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    with open(path, 'a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 10
        while True:
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise CtlError('another checkpoint writer is active; retry after it finishes', EXIT_CONFLICT)
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def operation(function):
    @functools.wraps(function)
    def wrapped(paths, root, *args, **kwargs):
        with repository(root):
            return function(paths, root, *args, **kwargs)
    return wrapped


def command(function):
    @functools.wraps(function)
    def wrapped(args):
        from .handoff import require_root
        with repository(require_root()):
            return function(args)
    return wrapped
