"""Read-only git helpers. Never runs anything that modifies a repository."""

import os
import shutil
import subprocess

from .errors import CtlError

# The self-test sets this so its throwaway state dir is not checked against git.
SKIP_HOME_CHECK = False


# Only these git subcommands may ever run. Nothing here can change a repository, the index or the work tree.
READ_ONLY_VERBS = frozenset(["rev-parse", "check-ignore", "symbolic-ref", "config", "diff", "ls-files",
                             "merge-base", "rev-list"])


def _verb(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c") else 1
    return args[i] if i < len(args) else ""


def _run(args, cwd=None, raw=False):
    """Run one read-only git command. raw=True returns bytes on stdout. None when git cannot be started."""
    verb = _verb(args)
    if verb not in READ_ONLY_VERBS or (verb == "config" and "--get" not in args):
        raise CtlError("internal error: refusing to run git %s (read-only commands only)" % verb, 1)
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    kw = {} if raw else {"text": True, "encoding": "utf-8", "errors": "replace"}
    try:
        return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, timeout=20, env=env, **kw)
    except (OSError, subprocess.SubprocessError):
        return None


def git(args, cwd, raw=False):
    """Like _run but a missing git is an error (exit 2)."""
    r = _run(args, cwd=cwd, raw=raw)
    if r is None:
        raise CtlError("git could not be run; handoff commands need git on PATH")
    return r


def git_available():
    return shutil.which("git") is not None


def git_root(cwd=None):
    if not git_available():
        return None
    r = _run(["rev-parse", "--show-toplevel"], cwd=cwd or os.getcwd())
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip() or None


def home_in_unignored_repo(home):
    """True when home sits inside a git work tree and is not ignored there."""
    if SKIP_HOME_CHECK or not git_available():
        return False
    ancestor = os.path.abspath(home)
    while not os.path.isdir(ancestor):
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            return False
        ancestor = parent
    r = _run(["-C", ancestor, "rev-parse", "--is-inside-work-tree"])
    if r is None or r.returncode != 0 or r.stdout.strip() != "true":
        return False
    probe = os.path.join(os.path.abspath(home), "config.json")
    r = _run(["-C", ancestor, "check-ignore", "-q", probe])
    return r is None or r.returncode != 0


def ensure_home_safe(home):
    if home_in_unignored_repo(home):
        raise CtlError("refusing to write: %s is inside a git work tree and is not ignored; "
                       "set CLAUDE_SETUP_HOME to a folder outside any repo" % home)
