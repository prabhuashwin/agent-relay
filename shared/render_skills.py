#!/usr/bin/env python3
"""Render shared/skills/*.tmpl.md for one tool.

  render_skills.py --tool claude|codex --out DIR [--skills a,b,c]

Writes DIR/<name>/SKILL.md (LF line endings). {{token}} values come from
shared/tool-vars.json. An unknown token, tool or skill makes the render fail
(exit 1) and nothing is written.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
SUFFIX = ".tmpl.md"


def render_text(text, values, label="template"):
    missing = []

    def sub(m):
        k = m.group(1)
        if k not in values:
            missing.append(k)
            return m.group(0)
        return values[k]

    out = TOKEN.sub(sub, text)
    if missing:
        raise ValueError("%s: unknown token(s): %s" % (label, ", ".join(sorted(set(missing)))))
    return out


def available(skills_dir):
    return sorted(f[: -len(SUFFIX)] for f in os.listdir(skills_dir) if f.endswith(SUFFIX))


def render(tool, out_dir, names=None, shared_dir=HERE):
    with open(os.path.join(shared_dir, "tool-vars.json"), encoding="utf-8") as f:
        allvars = json.load(f)
    if tool not in allvars:
        raise ValueError("no variables for tool %r in tool-vars.json" % tool)
    skills_dir = os.path.join(shared_dir, "skills")
    have = available(skills_dir)
    names = names or have
    unknown = [n for n in names if n not in have]
    if unknown:
        raise ValueError("no template for skill(s): %s" % ", ".join(unknown))
    rendered = {}
    for n in names:
        with open(os.path.join(skills_dir, n + SUFFIX), encoding="utf-8", newline="") as f:
            rendered[n] = render_text(f.read(), allvars[tool], n + SUFFIX)
    for n, text in rendered.items():  # write only after every template rendered
        d = os.path.join(out_dir, n)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return sorted(rendered)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tool", required=True, choices=["claude", "codex"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--skills", default="", help="comma-separated names (default: all)")
    a = ap.parse_args(argv)
    names = [n for n in a.skills.split(",") if n]
    try:
        done = render(a.tool, a.out, names or None)
    except (ValueError, OSError) as e:
        print("render_skills: %s" % e, file=sys.stderr)
        return 1
    print("rendered %s for %s: %s" % (len(done), a.tool, ", ".join(done)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
