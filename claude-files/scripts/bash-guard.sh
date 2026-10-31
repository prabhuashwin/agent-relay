#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash): blocks commands the user must run themselves.
# Exit 2 = block; stderr is shown to Claude.
input=$(cat)
raw=$(printf '%s' "$input" | grep -oE '"command":"([^"\]|[\].)*"' | head -n 1 | sed 's/^"command":"//; s/"$//')
[ -n "$raw" ] || exit 0
# Unescape the JSON string so multi-line and quoted commands match the regexes.
cmd=$(printf '%s' "$raw" | sed -e 's/\\[ntr]/ /g' -e 's/\\"/"/g' -e 's/\\\\/\\/g')
reason=""
if printf '%s' "$cmd" | grep -Eiq "\bgit(\s+-{1,2}[A-Za-z0-9_-]+(=\S+|\s+(\"[^\"]*\"|'[^']*'|[^[:space:]-][^[:space:]]*))?)*\s+push\b"; then
  reason="git push"
elif printf '%s' "$cmd" | grep -Eiq '(^|[[:space:];&|(])aws([[:space:]]|$)'; then
  reason="aws cli"
elif printf '%s' "$cmd" | grep -Eiq '\bgh\s+(pr\s+merge|repo\s+delete|release\s+(create|delete)|api(\s+.*(-X|--method)[=\s]*(POST|PUT|PATCH|DELETE)\b|(\s.*)?\s(-f|-F|--field|--raw-field)\s))'; then
  reason="gh write command"
fi
if [ -n "$reason" ]; then
  echo "[Guard] Blocked ($reason): run it yourself in a terminal. Command: $cmd" >&2
  exit 2
fi
exit 0
