#!/usr/bin/env bash
# UserPromptSubmit hook: tells Claude when the conversation is getting large.
# Anything printed here is added to Claude's context for this turn.
input=$(cat)
field() { printf '%s' "$input" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | sed "s/^\"$1\":\"//; s/\"\$//"; }
path=$(field transcript_path | sed 's#\\\\#/#g')
sid=$(field session_id)
tokens=0
if [ -n "$path" ] && [ -f "$path" ]; then
  pick() { grep '"type":"assistant"' | grep '"usage"' | grep -v '"isSidechain":true' | tail -n 1; }
  line=$(tail -n 300 "$path" | pick)
  [ -n "$line" ] || line=$(pick < "$path")
  num() { printf '%s' "$line" | grep -o "\"$1\":[0-9]*" | head -n 1 | sed 's/.*://'; }
  a=$(num input_tokens); b=$(num cache_read_input_tokens); c=$(num cache_creation_input_tokens)
  tokens=$(( ${a:-0} + ${b:-0} + ${c:-0} ))
fi
k=$(( (tokens + 500) / 1000 ))

# Log every run so you can confirm the check is firing.
dir=$(cd "$(dirname "$0")" && pwd)
printf '%s  %sk  %s\n' "$(date '+%Y-%m-%d %H:%M')" "$k" "$sid" >> "$dir/context-check.log"

if [ "$tokens" -ge 150000 ]; then
  echo "[Context check] This conversation is at about ${k}k tokens, which makes every turn expensive. Start your reply with one line telling the user this, and recommend they run /handoff and then /clear before continuing. Then answer their message normally."
elif [ "$tokens" -ge 100000 ]; then
  echo "[Context check] This conversation is at about ${k}k tokens. At the end of your reply, add one line suggesting /compact (with a short focus note) or /handoff if the current task is nearly done."
fi
exit 0
