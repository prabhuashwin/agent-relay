#!/usr/bin/env bash
# UserPromptSubmit hook: tells Claude when the conversation is getting large.
# Anything printed here is added to Claude's context for this turn.
input=$(cat)
field() { printf '%s' "$input" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | sed "s/^\"$1\":\"//; s/\"\$//"; }
path=$(field transcript_path | sed 's#\\\\#/#g')
sid=$(field session_id)
tokens=0
if [ -n "$path" ] && [ -f "$path" ]; then
  # Last assistant usage line after the last compaction marker; prints COMPACTED if a compaction came last.
  pick() { awk '
    index($0,"\"isCompactSummary\":true") { last=""; c=1; next }
    index($0,"\"type\":\"assistant\"") && index($0,"\"usage\"") && !index($0,"\"isSidechain\":true") { last=$0 }
    END { if (last != "") print last; else if (c) print "COMPACTED" }'; }
  line=$(tail -n 300 "$path" | pick)
  [ -n "$line" ] || line=$(pick < "$path")
  [ "$line" = COMPACTED ] && line=""
  num() { printf '%s' "$line" | grep -o "\"$1\":[0-9]*" | head -n 1 | sed 's/.*://'; }
  a=$(num input_tokens); b=$(num cache_read_input_tokens); c=$(num cache_creation_input_tokens)
  tokens=$(( ${a:-0} + ${b:-0} + ${c:-0} ))
fi
k=$(( (tokens + 500) / 1000 ))
prompt_raw=$(field prompt)
p=$(printf '%s' "$prompt_raw" | sed -e 's/\\[ntr]/ /g' -e 's/^[[:space:]]*//')
case "$p" in /*) slash=1 ;; *) slash=0 ;; esac

# Log every run so you can confirm the check is firing.
dir=$(cd "$(dirname "$0")" && pwd)
log="$dir/context-check.log"
printf '%s  %sk  %s\n' "$(date '+%Y-%m-%d %H:%M')" "$k" "$sid" >> "$log"
if [ "$(wc -l < "$log" 2>/dev/null || echo 0)" -gt 1000 ]; then
  { tail -n 500 "$log" > "$log.tmp" && mv "$log.tmp" "$log"; } 2>/dev/null || true
fi

if [ "$tokens" -ge 150000 ]; then
  [ "$slash" = 1 ] && exit 0
  echo "[Context check] This conversation is at about ${k}k tokens, so this prompt was blocked to save usage. Run /handoff (saves progress to handoffs/), then /clear, and resend your message in the new session. If you must keep going here, run /compact first." >&2
  exit 2
elif [ "$tokens" -ge 100000 ]; then
  echo "[Context check] This conversation is at about ${k}k tokens. At the end of your reply, add one line telling the user this, and that at 150k their prompts will be blocked until they run /handoff then /clear (or /compact). Suggest doing it now if the current task is nearly done."
fi
exit 0
