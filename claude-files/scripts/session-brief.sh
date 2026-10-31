#!/usr/bin/env bash
# SessionStart hook (matchers: startup|resume|clear): prints open workstreams and latest decisions into context.
# Anything printed here is added to Claude's context.
input=$(cat)
field() { printf '%s' "$input" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | sed "s/^\"$1\":\"//; s/\"\$//"; }
cwd=$(field cwd | sed 's#\\#/#g')
{ [ -n "$cwd" ] && [ -d "$cwd" ]; } || cwd=.
if [ -f "$cwd/handoffs/INDEX.md" ]; then
  echo "[Session brief] Open workstreams (handoffs/INDEX.md):"
  head -n 40 "$cwd/handoffs/INDEX.md"
fi
if [ -f "$cwd/DECISIONS.md" ]; then
  echo "[Session brief] Latest decisions (DECISIONS.md, last 10 lines):"
  tail -n 10 "$cwd/DECISIONS.md"
fi
exit 0
