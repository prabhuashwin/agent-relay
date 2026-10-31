#!/usr/bin/env bash
# Installs the Claude setup.
#   install.sh <project-folder>     (use . for the current folder)
# Part 1 puts agents, skills, scripts, status line and hooks in ~/.claude (user level).
# Part 2 sets up the project: permissions, CLAUDE.md block, handoffs/.
# Works in Git Bash on Windows, and on macOS/Linux. Backups go to ~/.claude/backups/claude-setup/.
# Part 1 also registers a Bash guard hook (blocks git push, aws, destructive gh).
# Run on the kit folder itself, it leaves the kit's CLAUDE.md unchanged.
# Part 1 also registers a SessionStart "session brief" hook (prints handoffs/INDEX.md and DECISIONS.md); Part 2 creates DECISIONS.md.
# Safe to run again.
set -euo pipefail

case "${1:-}" in ""|-h|--help) echo "Usage: install.sh <project-folder>   (use . for the current folder)"; exit 1 ;; esac
TARGET=$1
[ -d "$TARGET" ] || { echo "No such folder: $TARGET"; exit 1; }

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$TARGET" && pwd)
SELF=0
[ "$ROOT" = "$HERE" ] && SELF=1
SRC="$HERE/claude-files"
USER_DIR="$HOME/.claude"
DEST="$ROOT/.claude"
MD="$ROOT/CLAUDE.md"

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN=0 ;; esac
PS=powershell
winpath() { if [ "$WIN" = 1 ]; then cygpath -m "$1" 2>/dev/null || (cd "$1" && pwd -W); else printf '%s' "$1"; fi; }
if [ "$WIN" = 1 ] && command -v pwsh >/dev/null 2>&1; then PS=pwsh; fi
ROOTP=$(winpath "$ROOT")
HEREP=$(winpath "$HERE")

PY=""
for p in python3 python py; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys, json; sys.exit(sys.version_info < (3,))' >/dev/null 2>&1; then PY=$p; break; fi
done
[ -n "$PY" ] || { echo "Python 3 is required for install.sh"; exit 1; }

mkdir -p "$USER_DIR"
USERP=$(winpath "$HOME")   # forward slashes on Windows
STAMP=$(date +%Y%m%d-%H%M%S)
BK_ROOT="$USER_DIR/backups/claude-setup"
newbackup() {  # $1 = label; prints a fresh folder, never reusing a name
  local b="$BK_ROOT/$1-$STAMP" b0 n=2
  b0=$b
  while [ -e "$b" ]; do b="$b0-$n"; n=$((n + 1)); done
  mkdir -p "$b"; printf '%s' "$b"
}

# ---------- Part 1: user level ----------
BK_USER=$(newbackup user)
[ -f "$USER_DIR/settings.json" ] && cp "$USER_DIR/settings.json" "$BK_USER/"

mkdir -p "$USER_DIR/agents" "$USER_DIR/skills" "$USER_DIR/scripts"
cp "$SRC"/agents/* "$USER_DIR/agents/"
for d in "$SRC"/skills/*/; do
  name=$(basename "$d")
  mkdir -p "$USER_DIR/skills/$name"
  cp "$d/SKILL.md" "$USER_DIR/skills/$name/SKILL.md"
done
if [ "$WIN" = 1 ]; then cp "$SRC"/scripts/*.ps1 "$USER_DIR/scripts/"
else cp "$SRC"/scripts/*.sh "$USER_DIR/scripts/"; chmod +x "$USER_DIR"/scripts/*.sh; fi

if [ "$WIN" = 1 ]; then
  STATUS_CMD="$PS -NoProfile -ExecutionPolicy Bypass -File \"$USERP/.claude/scripts/statusline.ps1\""
  HOOK_CMD="$PS -NoProfile -ExecutionPolicy Bypass -File \"$USERP/.claude/scripts/context-check.ps1\""
  GUARD_CMD="$PS -NoProfile -ExecutionPolicy Bypass -File \"$USERP/.claude/scripts/bash-guard.ps1\""
  BRIEF_CMD="$PS -NoProfile -ExecutionPolicy Bypass -File \"$USERP/.claude/scripts/session-brief.ps1\""
else
  STATUS_CMD="bash \"$HOME/.claude/scripts/statusline.sh\""
  HOOK_CMD="bash \"$HOME/.claude/scripts/context-check.sh\""
  GUARD_CMD="bash \"$HOME/.claude/scripts/bash-guard.sh\""
  BRIEF_CMD="bash \"$HOME/.claude/scripts/session-brief.sh\""
fi
COMPACT_CMD='echo "[Context check] The conversation was just compacted. If this workstream has progress or decisions not yet saved under handoffs/, end your reply with one line offering to run /handoff."'
USER_SETTINGS="$USERP/.claude/settings.json"

"$PY" - "$USER_SETTINGS" "$STATUS_CMD" "$HOOK_CMD" "$COMPACT_CMD" "$GUARD_CMD" "$BRIEF_CMD" <<'PYEOF'
import json, os, sys
p, sc, hc, cc, gc, bc = sys.argv[1:7]
s = {}
if os.path.exists(p):
    t = open(p, encoding="utf-8-sig").read().strip()
    if t:
        try:
            s = json.loads(t)
        except ValueError as e:
            sys.exit("%s is not valid JSON (%s). Fix it and re-run; nothing was changed." % (p, e))

def drop(groups, needle):
    out = []
    for g in groups:
        if isinstance(g, dict) and isinstance(g.get("hooks"), list):
            k = [x for x in g["hooks"] if needle not in json.dumps(x)]
            if k != g["hooks"]:
                if not k:
                    continue
                g = dict(g, hooks=k)
        elif needle in json.dumps(g):
            continue
        out.append(g)
    return out

old = s.get("statusLine")
if isinstance(old, dict) and "statusline." not in str(old.get("command", "")):
    print("Note: replacing your existing statusLine (%r); the old value is in the backup." % old.get("command"))
s["statusLine"] = {"type": "command", "command": sc, "padding": 0}
h = s.setdefault("hooks", {})
ups = drop(h.get("UserPromptSubmit", []), "context-check")
ups.append({"hooks": [{"type": "command", "command": hc}]})
h["UserPromptSubmit"] = ups
ss = drop(h.get("SessionStart", []), "just compacted")
ss.append({"matcher": "compact", "hooks": [{"type": "command", "command": cc}]})
ss = drop(ss, "session-brief")
ss.append({"matcher": "startup|resume|clear", "hooks": [{"type": "command", "command": bc}]})
h["SessionStart"] = ss
pt = drop(h.get("PreToolUse", []), "bash-guard")
pt.append({"matcher": "Bash", "hooks": [{"type": "command", "command": gc}]})
h["PreToolUse"] = pt
with open(p, "w", encoding="utf-8") as f:
    f.write(json.dumps(s, indent=2) + "\n")
PYEOF

# ---------- Part 2: project level ----------
BK_PROJ=$(newbackup "$(basename "$ROOT")")
[ -d "$DEST" ] && cp -R "$DEST" "$BK_PROJ/dot-claude"
[ -f "$MD" ] && cp "$MD" "$BK_PROJ/"

# Keep only the 10 newest backups
pruned=0
while IFS= read -r old; do
  [ -n "$old" ] && { rm -rf "$old" || true; pruned=$((pruned + 1)); }
done < <(ls -1dt "$BK_ROOT"/*/ 2>/dev/null | tail -n +11 || true)
[ "$pruned" -eq 0 ] || echo "Pruned $pruned old backup(s)."

mkdir -p "$DEST"
PROJ_SETTINGS="$ROOTP/.claude/settings.json"
"$PY" - "$PROJ_SETTINGS" "$SRC/project-settings.json" <<'PYEOF'
import json, os, sys
p, tpl = sys.argv[1:3]
s = {}
if os.path.exists(p):
    t = open(p, encoding="utf-8-sig").read().strip()
    if t:
        try:
            s = json.loads(t)
        except ValueError as e:
            sys.exit("%s is not valid JSON (%s). Fix it and re-run; nothing was changed." % (p, e))
sl = s.get("statusLine")
if isinstance(sl, dict) and "statusline." in str(sl.get("command", "")):
    del s["statusLine"]
h = s.get("hooks")
if isinstance(h, dict) and "UserPromptSubmit" in h:
    out = []
    for g in h["UserPromptSubmit"]:
        if isinstance(g, dict) and isinstance(g.get("hooks"), list):
            k = [x for x in g["hooks"] if "context-check" not in json.dumps(x)]
            if k != g["hooks"]:
                if not k:
                    continue
                g = dict(g, hooks=k)
        elif "context-check" in json.dumps(g):
            continue
        out.append(g)
    if out: h["UserPromptSubmit"] = out
    else: del h["UserPromptSubmit"]
    if not h: del s["hooks"]
tp = json.load(open(tpl, encoding="utf-8-sig")).get("permissions", {})
perms = s.setdefault("permissions", {})
for key in ("deny", "allow"):
    cur = list(perms.get(key, []))
    for item in tp.get(key, []):
        if item not in cur:
            cur.append(item)
    perms[key] = cur
with open(p, "w", encoding="utf-8") as f:
    f.write(json.dumps(s, indent=2) + "\n")
PYEOF

# Remove per-project copies installed by the previous kit version
for f in agents/scout.md agents/worker.md agents/reviewer.md statusline.ps1 statusline.sh \
         context-check.ps1 context-check.sh context-check.log; do
  rm -f "$DEST/$f"
done
for d in crew handoff recap; do rm -rf "$DEST/skills/$d"; done
rmdir "$DEST/agents" "$DEST/skills" 2>/dev/null || true

# CLAUDE.md: add or refresh our block, keep the project's own notes
if [ "$SELF" = 1 ]; then
  echo "CLAUDE.md: this is the kit itself; left unchanged."
else
  START='<!-- claude-setup:start -->'
  END='<!-- claude-setup:end -->'
  BLOCK=$(mktemp)
  { echo "$START"; cat "$HERE/CLAUDE.md"; [ -z "$(tail -c 1 "$HERE/CLAUDE.md")" ] || echo; echo "$END"; } > "$BLOCK"
  if [ -f "$MD" ]; then
    # Every line mentioning a marker must be exactly a marker, alternating start/end
    marks=$(awk -v s="$START" -v e="$END" '
      { sub(/\r$/, "") }
      index($0, s) || index($0, e) { n++; if ($0 != (n % 2 ? s : e)) bad = 1 }
      END { print (n == 0 ? "none" : (bad || n % 2 ? "bad" : "ok")) }' "$MD")
    if [ "$marks" = ok ]; then
      awk -v s="$START" -v e="$END" -v bf="$BLOCK" '
        { sub(/\r$/, "") }
        $0 == s { if (!done) { while ((getline l < bf) > 0) print l; done = 1 } skip = 1; next }
        $0 == e { skip = 0; next }
        !skip   { print }' "$MD" > "$MD.tmp"
    elif [ "$marks" = bad ]; then
      echo "CLAUDE.md: claude-setup markers are damaged (missing, out of order or not on their own line); left unchanged. Fix them and re-run."
      cp "$MD" "$MD.tmp"
    else
      { cat "$MD"; printf '\n\n'; cat "$BLOCK"; } > "$MD.tmp"
    fi
  else
    { printf '# Project notes\n\n(Ask Claude to fill this in: build/test commands, layout, off-limits areas.)\n\n'; cat "$BLOCK"; } > "$MD.tmp"
  fi
  mv "$MD.tmp" "$MD"
  rm -f "$BLOCK"
fi

mkdir -p "$ROOT/handoffs"
[ -f "$ROOT/DECISIONS.md" ] || cp "$SRC/DECISIONS.md" "$ROOT/DECISIONS.md"

echo "Installed into $ROOTP"
echo "User backup:    $BK_USER"
echo "Project backup: $BK_PROJ"

# ---------- Part 3: self-test ----------
TEST_IN="{\"transcript_path\":\"$HEREP/claude-files/test-transcript.jsonl\",\"session_id\":\"install-test\"}"
if [ "$WIN" = 1 ]; then
  out=$(printf '%s' "$TEST_IN" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/context-check.ps1" 2>&1 || true)
else
  out=$(printf '%s' "$TEST_IN" | bash "$USER_DIR/scripts/context-check.sh" 2>&1 || true)
fi
case "$out" in *"Context check"*) echo "Context check self-test: OK" ;; *) echo "Context check self-test: FAILED - paste this output to Claude" ;; esac

TEST_IN2="{\"transcript_path\":\"$HEREP/claude-files/test-transcript-compacted.jsonl\",\"session_id\":\"install-test\",\"prompt\":\"hello\"}"
rc2=0
if [ "$WIN" = 1 ]; then
  out2=$(printf '%s' "$TEST_IN2" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/context-check.ps1" 2>&1) || rc2=$?
else
  out2=$(printf '%s' "$TEST_IN2" | bash "$USER_DIR/scripts/context-check.sh" 2>&1) || rc2=$?
fi
if [ "$rc2" = 0 ] && [ -z "$out2" ]; then echo "Context check (post-compact) self-test: OK"; else echo "Context check (post-compact) self-test: FAILED - paste this output to Claude"; fi

gtest() {  # $1 = command; runs the guard, prints its exit code
  local j="{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$1\"}}" rc=0
  if [ "$WIN" = 1 ]; then printf '%s' "$j" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/bash-guard.ps1" >/dev/null 2>&1 || rc=$?
  else printf '%s' "$j" | bash "$USER_DIR/scripts/bash-guard.sh" >/dev/null 2>&1 || rc=$?; fi
  echo "$rc"
}
g1=$(gtest "git push origin main"); g2=$(gtest "git status")
if [ "$g1" != 0 ] && [ "$g2" = 0 ]; then echo "Bash guard self-test: OK"; else echo "Bash guard self-test: FAILED - paste this output to Claude (push exit=$g1, status exit=$g2)"; fi
g3=$(gtest 'echo hi\ngit push')
if [ "$g3" != 0 ]; then echo "Bash guard multi-line self-test: OK"; else echo "Bash guard multi-line self-test: FAILED - paste this output to Claude (exit=$g3)"; fi

TEST_IN3="{\"cwd\":\"$HEREP\",\"hook_event_name\":\"SessionStart\",\"source\":\"startup\"}"
if [ "$WIN" = 1 ]; then out3=$(printf '%s' "$TEST_IN3" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/session-brief.ps1" 2>&1 || true)
else out3=$(printf '%s' "$TEST_IN3" | bash "$USER_DIR/scripts/session-brief.sh" 2>&1 || true); fi
case "$out3" in *"[Session brief] Open workstreams"*) echo "Session brief self-test: OK" ;; *) echo "Session brief self-test: FAILED - paste this output to Claude" ;; esac

chk() { "$PY" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$2" && echo "$1 settings.json: OK" || echo "$1 settings.json: INVALID - paste this output to Claude"; }
chk user "$USER_SETTINGS"
chk project "$PROJ_SETTINGS"
