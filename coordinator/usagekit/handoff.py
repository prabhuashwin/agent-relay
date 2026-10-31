"""Checkpoint handoffs: build, render, parse and verify. Git is only ever read (see gitutil.READ_ONLY_VERBS)."""

import hashlib
import json
import os
import re
import tempfile

from . import gitutil
from .config import ALIAS_RE, SLUG_RE
from .errors import CtlError, EXIT_CONFLICT

SCHEMA = 1
CKPT_PATH_RE = re.compile(r"^handoffs/[^/]+\.checkpoint\.md$")
EXCLUDE_SPEC = ":(exclude,glob)handoffs/*.checkpoint.md"
BASE_CANDIDATES = ("origin/main", "origin/master", "main", "master")
LIST_FIELDS = ("acceptance", "changed_files", "done", "remaining", "failures", "decisions")
FIELDS = ("schema", "workstream", "owner", "goal", "acceptance", "repo", "branch", "base_commit", "head_commit",
          "changed_files", "uncommitted", "done", "remaining", "verification", "failures", "decisions",
          "next_action", "prepared_at")
NEVER_DISCARD = ("Never discard, stash, commit, or overwrite uncommitted changes or other people's work; "
                 "if something conflicts, stop and ask the user.")


# ---------- helpers ----------

def check_slug(slug, what="workstream"):
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise CtlError("invalid %s slug %r (lowercase letters, digits and -, up to 64 characters)" % (what, slug))
    return slug


def strip_credentials(url):
    """Remove user:password@ and query/fragment from scheme URLs so no token reaches a checkpoint."""
    if not url:
        return None
    url = url.strip()
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/?#]*@)?(.*)$", url)
    if m:
        rest = re.split(r"[?#]", m.group(3), maxsplit=1)[0]
        return m.group(1) + rest
    if re.match(r"^[A-Za-z]:[\\/]", url) or url.startswith((".", "/", "~")):
        return _basename(url)
    m = re.match(r"^(?:[^/@\s:]+@)?([A-Za-z0-9][A-Za-z0-9.-]*):(.*)$", url)
    if m:   # scp-style host:path; drop the user part
        return m.group(1) + ":" + re.split(r"[?#]", m.group(2), maxsplit=1)[0]
    if "/" in url or "\\" in url:
        return _basename(url)
    return url or None


def _basename(path):
    parts = [p for p in re.split(r"[\\/]", path) if p]
    return parts[-1] if parts else None


def _one_line(text):
    return " ".join(str(text).split())


def require_root():
    if not gitutil.git_available():
        raise CtlError("git is not installed or not on PATH; handoff commands need it")
    root = gitutil.git_root()
    if root is None:
        raise CtlError("not inside a git work tree; run from the project's repository")
    return root


def checkpoint_path(root, slug):
    return os.path.join(root, "handoffs", "%s.checkpoint.md" % slug)


# ---------- git facts (read-only) ----------

def _text(r):
    return r.stdout.strip() if r.returncode == 0 else None


def head_commit(root):
    return _text(gitutil.git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], root))


def branch_name(root):
    return _text(gitutil.git(["symbolic-ref", "-q", "--short", "HEAD"], root))


def repo_identity(root):
    remote = _text(gitutil.git(["config", "--get", "remote.origin.url"], root))
    return {"name": os.path.basename(os.path.normpath(root)), "remote": strip_credentials(remote)}


def _split_z(raw):
    return [os.fsdecode(p) for p in raw.split(b"\0") if p]


def resolve_commit(root, ref):
    return _text(gitutil.git(["rev-parse", "--verify", "-q", ref + "^{commit}"], root))


def resolve_base(root, head, ref):
    if ref:
        commit = resolve_commit(root, ref)
        if commit is None:
            raise CtlError("--base %r is not a commit in this repository" % ref)
        return commit
    if head is None:
        return None
    for cand in BASE_CANDIDATES:
        if resolve_commit(root, cand):
            mb = _text(gitutil.git(["merge-base", head, cand], root))
            if mb:
                return mb
    return head


def changed_files(root, base, head):
    if not base or not head:
        return []
    r = gitutil.git(["diff", "--name-only", "-z", "--no-renames", base, head], root, raw=True)
    if r.returncode != 0:
        return []
    return sorted(p for p in _split_z(r.stdout) if not CKPT_PATH_RE.match(p))


def _read_untracked(root, rel):
    full = os.path.join(root, rel)
    try:
        if os.path.islink(full):
            return os.fsencode(os.readlink(full))
        if os.path.isfile(full):
            with open(full, "rb") as fh:
                return fh.read()
    except OSError:
        return b"<unreadable>"
    return b"<not a regular file>"


def _nested_digest(full):
    """Digest of a nested repository: its HEAD, its diff against HEAD and its untracked files."""
    if not os.path.isdir(full):
        return b"<missing>"
    h = hashlib.sha256()
    head = gitutil.git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], full)
    h.update(b"head\0" + (head.stdout.strip().encode() if head.returncode == 0 else b"none"))
    diff = gitutil.git(["diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD"], full, raw=True)
    h.update(b"\0diff\0" + (diff.stdout if diff.returncode == 0 else b"<unreadable>"))
    other = gitutil.git(["ls-files", "--others", "--exclude-standard", "-z"], full, raw=True)
    for rel in sorted(_split_z(other.stdout)) if other.returncode == 0 else []:
        data = b"<nested>" if rel.endswith("/") else _read_untracked(full, rel)
        h.update(b"\0untracked\0" + os.fsencode(rel) + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest().encode()


def uncommitted_state(root, head):
    """Paths with uncommitted changes (tracked changes vs HEAD plus untracked files) and a hash over the
    `git diff HEAD` text and the bytes of every untracked file. Checkpoint files themselves are excluded."""
    flags = ["--no-renames", "--no-ext-diff", "--no-textconv", "--no-color"]
    tail = ["--", ".", EXCLUDE_SPEC]
    # With no commits there is no HEAD: staged files come from the index (git treats an unborn HEAD as empty), the rest
    # from the work tree against the index.
    variants = [[head]] if head else [["--cached"], []]
    tracked_paths, diff_bytes = [], b""
    for extra in variants:
        names = gitutil.git(["diff", "--name-only", "-z"] + flags + extra + tail, root, raw=True)
        text = gitutil.git(["diff", "--binary"] + flags + extra + tail, root, raw=True)
        if names.returncode == 0:
            tracked_paths += [p for p in _split_z(names.stdout) if not CKPT_PATH_RE.match(p)]
        if text.returncode == 0:
            diff_bytes += text.stdout
    other = gitutil.git(["ls-files", "--others", "--exclude-standard", "-z"], root, raw=True)
    untracked = sorted(p for p in _split_z(other.stdout) if not CKPT_PATH_RE.match(p)) if other.returncode == 0 else []
    links = gitutil.git(["ls-files", "--stage", "-z"], root, raw=True)
    gitlinks = sorted(os.fsdecode(e.split(b"\t", 1)[1]) for e in links.stdout.split(b"\0")
                      if e.startswith(b"160000 ") and b"\t" in e) if links.returncode == 0 else []
    h = hashlib.sha256()
    h.update(b"diff\0" + diff_bytes)
    for rel in gitlinks:   # submodules: the diff shows only the recorded commit, so hash the real nested state
        h.update(b"\0submodule\0" + os.fsencode(rel) + b"\0" + _nested_digest(os.path.join(root, rel)))
    for rel in untracked:
        if rel.endswith("/") and os.path.exists(os.path.join(root, rel, ".git")):   # untracked nested repository
            h.update(b"\0nested\0" + os.fsencode(rel) + b"\0" + _nested_digest(os.path.join(root, rel)))
            continue
        data = _read_untracked(root, rel)
        h.update(b"\0untracked\0" + os.fsencode(rel) + b"\0" + str(len(data)).encode() + b"\0" + data)
    return {"paths": sorted(set(tracked_paths) | set(untracked)), "diff_sha256": h.hexdigest()}


def current_state(root):
    head = head_commit(root)
    return {"repo": repo_identity(root), "branch": branch_name(root), "head_commit": head,
            "uncommitted": uncommitted_state(root, head)}


# ---------- build / render / parse ----------

def build_checkpoint(root, workstream, owner, goal, next_action, now_iso, accept=(), done=(), remaining=(),
                     verify=(), failures=(), decisions=(), base_ref=None):
    state = current_state(root)
    head = state["head_commit"]
    base = resolve_base(root, head, base_ref)
    return {"schema": SCHEMA, "workstream": workstream, "owner": owner, "goal": goal,
            "acceptance": list(accept), "repo": state["repo"], "branch": state["branch"], "base_commit": base,
            "head_commit": head, "changed_files": changed_files(root, base, head),
            "uncommitted": state["uncommitted"], "done": list(done), "remaining": list(remaining),
            "verification": list(verify), "failures": list(failures), "decisions": list(decisions),
            "next_action": next_action, "prepared_at": now_iso}


def parse_verify_arg(text):
    parts = [p.strip() for p in text.split("=>")]
    if len(parts) != 3 or not parts[0] or parts[2] not in ("pass", "fail"):
        raise CtlError("--verify expects 'COMMAND=>RESULT=>pass|fail', got %r" % text)
    return {"command": parts[0], "result": parts[1], "status": parts[2]}


def render(data):
    def bullets(items):
        return "\n".join("- " + _one_line(i) for i in items) if items else "- none"
    repo = data["repo"]
    ver = ["- `%s`: %s (%s)" % (_one_line(v["command"]), _one_line(v["result"]), v["status"])
           for v in data["verification"]] or ["- none recorded"]
    unc = data["uncommitted"]
    parts = [
        "# Checkpoint: %s" % data["workstream"], "",
        "Owner: %s. Prepared: %s." % (data["owner"], data["prepared_at"]), "",
        "## Goal", _one_line(data["goal"]), "",
        "## Acceptance", bullets(data["acceptance"]), "",
        "## Repo state",
        "- repo: %s (%s)" % (repo["name"], repo["remote"] or "no remote"),
        "- branch: %s" % (data["branch"] or "(detached HEAD)"),
        "- base commit: %s" % (data["base_commit"] or "none"),
        "- head commit: %s" % (data["head_commit"] or "none (no commits yet)"),
        "- changed files since base: %d" % len(data["changed_files"]),
        "- uncommitted paths: %d" % len(unc["paths"]), "",
        "## Uncommitted files", bullets(unc["paths"]), "",
        "## Done", bullets(data["done"]), "",
        "## Remaining", bullets(data["remaining"]), "",
        "## Verification", "\n".join(ver), "",
        "## Failures", bullets(data["failures"]), "",
        "## Decisions", bullets(data["decisions"]), "",
        "## Next action", _one_line(data["next_action"]), "",
        "## Machine data (the only source the tools read)", "",
        "```json", json.dumps(data, indent=2, sort_keys=True), "```", ""]
    return "\n".join(parts)


def write_checkpoint(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".checkpoint-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(data))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _reject_constant(name):
    raise ValueError("non-finite number %s" % name)


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(i, str) for i in v)


def validate_data(data, label):
    def bad(msg):
        raise CtlError("checkpoint %s is malformed: %s" % (label, msg))
    if not isinstance(data, dict):
        bad("JSON block is not an object")
    if data.get("schema") != SCHEMA or isinstance(data.get("schema"), bool):
        bad("unsupported schema %r" % (data.get("schema"),))
    missing = [k for k in FIELDS if k not in data]
    extra = [k for k in data if k not in FIELDS]
    if missing or extra:
        bad("missing %s unknown %s" % (missing or "none", extra or "none"))
    if not isinstance(data["workstream"], str) or not SLUG_RE.match(data["workstream"]):
        bad("invalid workstream")
    if not isinstance(data["owner"], str) or not ALIAS_RE.match(data["owner"]):
        bad("invalid owner alias")
    for k in ("goal", "next_action", "prepared_at"):
        if not isinstance(data[k], str):
            bad("%s must be a string" % k)
    for k in LIST_FIELDS:
        if not _is_str_list(data[k]):
            bad("%s must be a list of strings" % k)
    repo = data["repo"]
    if not (isinstance(repo, dict) and set(repo) == {"name", "remote"} and isinstance(repo["name"], str)
            and (repo["remote"] is None or isinstance(repo["remote"], str))):
        bad("invalid repo")
    for k in ("branch", "base_commit", "head_commit"):
        if data[k] is not None and not isinstance(data[k], str):
            bad("%s must be a string or null" % k)
    unc = data["uncommitted"]
    if not (isinstance(unc, dict) and set(unc) == {"paths", "diff_sha256"} and _is_str_list(unc["paths"])
            and isinstance(unc["diff_sha256"], str)):
        bad("invalid uncommitted")
    ver = data["verification"]
    if not (isinstance(ver, list) and all(isinstance(v, dict) and set(v) == {"command", "result", "status"}
                                          and all(isinstance(x, str) for x in v.values()) for v in ver)):
        bad("invalid verification")
    return data


def parse_checkpoint(text, label="file"):
    marker = "\n```json\n"
    i = text.rfind(marker)
    if i < 0:
        raise CtlError("checkpoint %s is malformed: no json block" % label)
    body = text[i + len(marker):]
    j = body.rfind("\n```")
    if j < 0:
        raise CtlError("checkpoint %s is malformed: json block is not closed" % label)
    try:
        data = json.loads(body[:j], parse_constant=_reject_constant)
    except ValueError as exc:
        raise CtlError("checkpoint %s is malformed: invalid JSON (%s)" % (label, exc))
    return validate_data(data, label)


def load_checkpoint(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except FileNotFoundError:
        raise CtlError("no checkpoint at %s; run the checkpoint skill first" % path)
    except (OSError, UnicodeDecodeError) as exc:
        raise CtlError("cannot read checkpoint %s: %s" % (path, exc))
    return parse_checkpoint(text, path)


# ---------- verification ----------

def _ancestor(root, a, b):
    """0 a is an ancestor of b, 1 not, other: unknown commit."""
    return gitutil.git(["merge-base", "--is-ancestor", a, b], root).returncode


def _head_relation(root, old, new):
    if old == new:
        return "same", None
    if old is None:
        return "ahead", None
    if new is None:
        return "behind", None
    fwd = _ancestor(root, old, new)
    if fwd == 0:
        return "ahead", None
    back = _ancestor(root, new, old)
    if back == 0:
        return "behind", None
    if fwd not in (0, 1) and back not in (0, 1):
        return "diverged", "the checkpoint commit is not in this repository"
    return "diverged", None


def _short(c):
    return c[:10] if c else "none"


def _listing(paths, limit=8):
    shown = ", ".join(paths[:limit])
    return shown + (" (+%d more)" % (len(paths) - limit) if len(paths) > limit else "")


def _only_checkpoint_commits(root, old, new):
    """True when every change between old and new touches only handoffs/*.checkpoint.md."""
    r = gitutil.git(["diff", "--name-only", "-z", "--no-renames", old, new], root, raw=True)
    if r.returncode != 0:
        return False
    return all(CKPT_PATH_RE.match(p) for p in _split_z(r.stdout))


def compare(root, data, state=None):
    """List of mismatch lines between the checkpoint and the repository as it is now. Empty list means match."""
    now = state or current_state(root)
    out = []
    a, b = data["repo"], now["repo"]
    same_repo = (a["remote"] == b["remote"]) if (a["remote"] or b["remote"]) else (a["name"] == b["name"])
    if not same_repo:
        out.append("repo differs: checkpoint is for %s (%s), this is %s (%s); run it in the right repository"
                   % (a["name"], a["remote"] or "no remote", b["name"], b["remote"] or "no remote"))
    if data["branch"] != now["branch"]:
        out.append("branch differs: checkpoint is on %s, this is %s; use a separate worktree for parallel work, "
                   "or switch branch yourself"
                   % (data["branch"] or "(detached HEAD)", now["branch"] or "(detached HEAD)"))
    rel, why = _head_relation(root, data["head_commit"], now["head_commit"])
    if rel == "ahead" and data["head_commit"] and _only_checkpoint_commits(root, data["head_commit"],
                                                                          now["head_commit"]):
        rel = "same"   # committing the checkpoint file itself must not make it stale
    if rel != "same":
        detail = {"ahead": "this repo has commits the checkpoint does not know; the checkpoint is out of date",
                  "behind": "this repo lacks commits the checkpoint was made at; the work is missing here",
                  "diverged": why or "histories have split"}[rel]
        out.append("head %s: checkpoint at %s, this is %s; %s"
                   % (rel, _short(data["head_commit"]), _short(now["head_commit"]), detail))
    old_p, new_p = set(data["uncommitted"]["paths"]), set(now["uncommitted"]["paths"])
    if new_p - old_p:
        out.append("uncommitted added: %s (not in the checkpoint)" % _listing(sorted(new_p - old_p)))
    if old_p - new_p:
        out.append("uncommitted removed: %s (in the checkpoint, missing here: the uncommitted work is not in "
                   "this tree)" % _listing(sorted(old_p - new_p)))
    if old_p == new_p and data["uncommitted"]["diff_sha256"] != now["uncommitted"]["diff_sha256"]:
        out.append("uncommitted modified: same files but different content than the checkpoint")
    return out


def check_name_matches(data, slug):
    if data["workstream"] != slug:
        raise CtlError("checkpoint file %s.checkpoint.md is for workstream %r, not %r; it was renamed or edited"
                       % (slug, data["workstream"], slug), EXIT_CONFLICT)


def routing_checkpoint_status(root, slug, expected_workstream):
    """(True, None) when the checkpoint parses, names the expected workstream and matches the repo; else
    (False, reason). Never raises for a bad checkpoint: routing treats that as no checkpoint."""
    try:
        data = load_checkpoint(checkpoint_path(root, slug))
        if data["workstream"] != expected_workstream:
            return False, "checkpoint is for workstream %r, expected %r" % (data["workstream"], expected_workstream)
        mism = compare(root, data)
        if mism:
            return False, mism[0]
    except CtlError as exc:
        return False, exc.message
    return True, None


# ---------- resume prompt ----------

def resume_prompt(provider, data, rel_path, to):
    codex = provider == "codex"
    skills = "$handoff, $decide, $recap, $checkpoint" if codex else "/handoff, /decide, /recap"
    lines = [
        "You are resuming workstream '%s' as account '%s' (%s)." % (data["workstream"], to, provider),
        "Goal: %s" % _one_line(data["goal"]),
        "Checkpoint: %s (read it first; its JSON block is the source of truth)." % rel_path,
        "Branch: %s. Commit: %s." % (data["branch"] or "(detached HEAD)", data["head_commit"] or "none yet"),
        "Next action: %s" % _one_line(data["next_action"]),
        "Verify first: run `usagectl handoff verify --workstream %s`; it must report a match before you edit anything."
        % data["workstream"],
        "Then take ownership: `usagectl handoff claim --workstream %s --to %s`." % (data["workstream"], to),
        NEVER_DISCARD,
        "Read handoffs/INDEX.md and the last 10 lines of DECISIONS.md. Skills: %s. When you reach a boundary, "
        "run the checkpoint skill%s." % (skills, " (`$checkpoint`)" if codex else ""),
    ]
    if codex:
        lines.append("Keep command output small (grep/tail); do not run anything that needs approval you do not have.")
    else:
        lines.append("Keep context small; run /handoff when the task is done.")
    return "\n".join(lines)
