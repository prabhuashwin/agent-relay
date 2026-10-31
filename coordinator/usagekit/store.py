"""JSONL state files: append with LF, tolerant reads."""

import json
import os

from . import config
from .errors import CtlError


def _reject_constant(name):
    raise ValueError("non-finite number %s" % name)


def read_jsonl(path):
    """Return (records, bad_line_count). Missing file is empty. Bad lines are skipped, not fatal."""
    records, bad = [], 0
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line, parse_constant=_reject_constant)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
                else:
                    bad += 1
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise CtlError("cannot read %s: %s" % (path, exc))
    return records, bad


def append_jsonl(paths, path, records):
    """Append all records in one write (so a batch lands whole or not at all)."""
    if not records:
        return
    config.ensure_writable(paths)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(data)
