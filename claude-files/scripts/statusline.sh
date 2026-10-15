#!/usr/bin/env bash
# Claude Code status line (terminal only): model + current context size.
input=$(cat)
field() { printf '%s' "$input" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | sed "s/^\"$1\":\"//; s/\"\$//"; }
model=$(field display_name)
path=$(field transcript_path | sed 's#\\\\#/#g')
tokens=0
cu=$(printf '%s' "$input" | grep -o '"current_usage":{[^}]*}' | head -n 1)
if [ -n "$cu" ]; then
  num() { printf '%s' "$cu" | grep -o "\"$1\":[0-9]*" | head -n 1 | sed 's/.*://'; }
  a=$(num input_tokens); b=$(num cache_read_input_tokens); c=$(num cache_creation_input_tokens)
  tokens=$(( ${a:-0} + ${b:-0} + ${c:-0} ))
elif [ -n "$path" ] && [ -f "$path" ]; then
  pick() { grep '"type":"assistant"' | grep '"usage"' | grep -v '"isSidechain":true' | tail -n 1; }
  line=$(tail -n 300 "$path" | pick)
  [ -n "$line" ] || line=$(pick < "$path")
  num() { printf '%s' "$line" | grep -o "\"$1\":[0-9]*" | head -n 1 | sed 's/.*://'; }
  a=$(num input_tokens); b=$(num cache_read_input_tokens); c=$(num cache_creation_input_tokens)
  tokens=$(( ${a:-0} + ${b:-0} + ${c:-0} ))
fi
k=$(( (tokens + 500) / 1000 ))
if   [ "$tokens" -ge 150000 ]; then c='\033[31m'; tip=' - /handoff then /clear'
elif [ "$tokens" -ge 100000 ]; then c='\033[33m'; tip=' - /compact soon'
else c='\033[32m'; tip=''; fi
printf "%s | ${c}ctx %sk%s\033[0m\n" "$model" "$k" "$tip"
