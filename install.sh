#!/usr/bin/env bash
# Installs the Claude / Codex setup.
#   install.sh [--tool claude|codex|both] [--dry-run] [--skip-self-test] <project-folder>   (use . for the current folder)
# Default tool is claude. Options may come before or after the folder.
# Claude: Part 1 puts agents, skills, scripts, status line and hooks in ~/.claude (user level).
#         Part 2 sets up the project: permissions, CLAUDE.md block, handoffs/.
# Codex:  skills go to ~/.agents/skills, rules to ${CODEX_HOME:-~/.codex}/rules/claude-setup.rules, an AGENTS.md block in the
#         project, and the usage coordinator (usagectl) to ${CLAUDE_SETUP_HOME:-~/.claude-setup}. Hooks are not installed for Codex.
# Works in Git Bash on Windows, and on macOS/Linux. Backups go to ~/.claude/backups/claude-setup/.
# Everything is validated before anything is written (a failed check changes nothing); --dry-run prints the plan only.
# Part 1 also registers a Bash guard hook (blocks git push, aws, destructive gh).
# Run on the kit folder itself, it leaves the kit's CLAUDE.md and AGENTS.md unchanged.
# Part 1 also registers a SessionStart "session brief" hook (prints handoffs/INDEX.md and DECISIONS.md); Part 2 creates DECISIONS.md.
# Safe to run again. Exit codes: 0 ok, 1 failed preflight or self-test, 2 bad options.
set -euo pipefail

usage() { echo "Usage: install.sh [--tool claude|codex|both] [--dry-run] [--skip-self-test] <project-folder>   (use . for the current folder)"; }

# ---------- Parse ----------
TOOL=claude; DRY=0; SKIPT=0; TARGET=""; NOMOREOPTS=0
[ $# -gt 0 ] || { usage; exit 1; }
while [ $# -gt 0 ]; do
  if [ "$NOMOREOPTS" = 0 ]; then
    case "$1" in
      -h|--help) usage; exit 1 ;;
      --tool) [ $# -ge 2 ] || { echo "--tool needs a value: claude, codex or both"; exit 2; }; TOOL=$2; shift 2; continue ;;
      --tool=*) TOOL=${1#--tool=}; shift; continue ;;
      --dry-run) DRY=1; shift; continue ;;
      --skip-self-test) SKIPT=1; shift; continue ;;
      --) NOMOREOPTS=1; shift; continue ;;
      -*) echo "Unknown option: $1"; usage; exit 2 ;;
    esac
  fi
  [ -z "$TARGET" ] || { echo "Only one project folder is allowed (got '$TARGET' and '$1')"; usage; exit 2; }
  TARGET=$1; shift
done
case "$TOOL" in
  claude) WANT_CLAUDE=1; WANT_CODEX=0 ;;
  codex)  WANT_CLAUDE=0; WANT_CODEX=1 ;;
  both)   WANT_CLAUDE=1; WANT_CODEX=1 ;;
  *) echo "Bad --tool value '$TOOL': use claude, codex or both"; exit 2 ;;
esac
[ -n "$TARGET" ] || { usage; exit 1; }
[ -d "$TARGET" ] || { echo "No such folder: $TARGET"; exit 1; }

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$TARGET" && pwd)
SELF=0
[ "$ROOT" = "$HERE" ] && SELF=1
SRC="$HERE/claude-files"
USER_DIR="$HOME/.claude"
DEST="$ROOT/.claude"
MD="$ROOT/CLAUDE.md"
AMD="$ROOT/AGENTS.md"

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN=0 ;; esac
PS=powershell
winpath() { if [ "$WIN" = 1 ]; then cygpath -m "$1" 2>/dev/null || (cd "$1" && pwd -W); else printf '%s' "$1"; fi; }
unixpath() { if [ "$WIN" = 1 ]; then cygpath -u "$1" 2>/dev/null || printf '%s' "$1"; else printf '%s' "$1"; fi; }
if [ "$WIN" = 1 ] && command -v pwsh >/dev/null 2>&1; then PS=pwsh; fi
ROOTP=$(winpath "$ROOT")
HEREP=$(winpath "$HERE")

CODEX_DIR=$(unixpath "${CODEX_HOME:-$HOME/.codex}")
CS_HOME=$(unixpath "${CLAUDE_SETUP_HOME:-$HOME/.claude-setup}")
AGENTS_SK="$HOME/.agents/skills"
RULES_SRC="$HERE/codex-files/rules/claude-setup.rules"
RULES_DEST="$CODEX_DIR/rules/claude-setup.rules"
MARKER=".claude-setup"

PY=""
for p in python3 python py; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys, json; sys.exit(sys.version_info < (3,))' >/dev/null 2>&1; then PY=$p; break; fi
done
[ -n "$PY" ] || { echo "Python 3 is required for install.sh"; exit 1; }

USERP=$(winpath "$HOME")   # forward slashes on Windows
STAMP=$(date +%Y%m%d-%H%M%S)
BK_ROOT="$USER_DIR/backups/claude-setup"
newbackup() {  # $1 = label; prints a fresh folder, never reusing a name
  local b="$BK_ROOT/$1-$STAMP" b0 n=2
  b0=$b
  while [ -e "$b" ]; do b="$b0-$n"; n=$((n + 1)); done
  mkdir -p "$b"; printf '%s' "$b"
}

START='<!-- claude-setup:start -->'
END='<!-- claude-setup:end -->'
marks_of() {  # $1 = file; prints none, ok or bad. Every line mentioning a marker must be exactly a marker, alternating start/end
  awk -v s="$START" -v e="$END" '
    { sub(/\r$/, "") }
    index($0, s) || index($0, e) { n++; if ($0 != (n % 2 ? s : e)) bad = 1 }
    END { print (n == 0 ? "none" : (bad || n % 2 ? "bad" : "ok")) }' "$1"
}

USER_SETTINGS="$USERP/.claude/settings.json"
PROJ_SETTINGS="$ROOTP/.claude/settings.json"

SK_CLAUDE="handoff,decide,recap"; [ "$WANT_CODEX" = 1 ] && SK_CLAUDE="$SK_CLAUDE,checkpoint"
SK_CODEX="handoff,decide,recap,checkpoint"

# ---------- Preflight: validate everything before any write ----------
PF=0
pf() { echo "  - $*"; PF=$((PF + 1)); }
echo "Preflight (tool: $TOOL)..."

need() { [ -e "$1" ] || pf "kit file missing: $1"; }
need "$SRC/DECISIONS.md"; need "$HERE/shared/render_skills.py"; need "$HERE/shared/tool-vars.json"
for n in handoff decide recap checkpoint; do need "$HERE/shared/skills/$n.tmpl.md"; done
if [ "$WANT_CLAUDE" = 1 ]; then
  need "$SRC/agents"; need "$SRC/skills/crew/SKILL.md"; need "$SRC/project-settings.json"
  for s in bash-guard context-check session-brief statusline; do
    if [ "$WIN" = 1 ]; then need "$SRC/scripts/$s.ps1"; else need "$SRC/scripts/$s.sh"; fi
  done
  [ "$SELF" = 1 ] || need "$HERE/CLAUDE.md"
  if [ "$SKIPT" = 0 ]; then need "$SRC/test-transcript.jsonl"; need "$SRC/test-transcript-compacted.jsonl"; fi
fi
if [ "$WANT_CODEX" = 1 ]; then
  need "$HERE/AGENTS.md"; need "$RULES_SRC"; need "$HERE/coordinator/usagectl.py"
fi

if [ "$WANT_CLAUDE" = 1 ]; then
  if ! jout=$("$PY" - "$USER_SETTINGS" "$PROJ_SETTINGS" <<'PYEOF'
import json, os, sys
bad = 0
# (file, hook events that the installer edits, whether permissions are merged)
checks = [(sys.argv[1], ("UserPromptSubmit", "SessionStart", "PreToolUse"), False),
          (sys.argv[2], ("UserPromptSubmit",), True)]
for p, events, perms in checks:
    if not os.path.exists(p):
        continue
    try:
        t = open(p, encoding="utf-8-sig").read().strip()
        s = json.loads(t) if t else {}
    except (ValueError, OSError) as e:
        print("%s is not valid JSON (%s)" % (p, e)); bad = 1; continue
    if not isinstance(s, dict):
        print("%s must contain a JSON object" % p); bad = 1; continue
    if "hooks" in s:
        h = s["hooks"]
        if not isinstance(h, dict):
            print("%s: \"hooks\" must be an object" % p); bad = 1
        else:
            for ev in events:
                if ev in h and not isinstance(h[ev], list):
                    print("%s: hooks.%s must be a list" % (p, ev)); bad = 1
    if perms and "permissions" in s:
        pm = s["permissions"]
        if not isinstance(pm, dict):
            print("%s: \"permissions\" must be an object" % p); bad = 1
        else:
            for k in ("deny", "allow"):
                if k in pm and not isinstance(pm[k], list):
                    print("%s: permissions.%s must be a list" % (p, k)); bad = 1
sys.exit(bad)
PYEOF
  ); then
    while IFS= read -r l; do [ -z "$l" ] || pf "$l"; done <<< "$jout"
  fi
  if [ "$SELF" = 0 ] && [ -f "$MD" ] && [ "$(marks_of "$MD")" = bad ]; then
    pf "CLAUDE.md: claude-setup markers are damaged (missing, out of order or not on their own line). Fix them and re-run."
  fi
fi
if [ "$WANT_CODEX" = 1 ] && [ "$SELF" = 0 ] && [ -f "$AMD" ] && [ "$(marks_of "$AMD")" = bad ]; then
  pf "AGENTS.md: claude-setup markers are damaged (missing, out of order or not on their own line). Fix them and re-run."
fi

# Every destination that must be a folder: a file in the way would make mkdir abort part-way through
dircheck() {  # $1 = path that must be (or become) a folder
  local p=$1
  while [ ! -e "$p" ] && [ ! -L "$p" ] && [ "$p" != "/" ] && [ "$p" != "." ]; do p=$(dirname "$p"); done
  [ -d "$p" ] || pf "$1 must be a folder, but $p is a file"
}
dircheck "$ROOT/handoffs"; dircheck "$BK_ROOT"
if [ "$WANT_CLAUDE" = 1 ]; then
  dircheck "$DEST"
  for d in agents scripts skills; do dircheck "$USER_DIR/$d"; done
  for n in crew ${SK_CLAUDE//,/ }; do dircheck "$USER_DIR/skills/$n"; done
fi
if [ "$WANT_CODEX" = 1 ]; then
  dircheck "$AGENTS_SK"; dircheck "$(dirname "$RULES_DEST")"; dircheck "$CS_HOME/bin"; dircheck "$CS_HOME/coordinator.new"
fi

# Render the skills into a temp folder (an unknown {{token}} fails here, before any write)
RENDER_TMP=$(mktemp -d)
trap 'rm -rf "$RENDER_TMP"' EXIT
RTP=$(winpath "$RENDER_TMP")
if [ -f "$HERE/shared/render_skills.py" ]; then
  if [ "$WANT_CLAUDE" = 1 ]; then
    "$PY" "$HEREP/shared/render_skills.py" --tool claude --out "$RTP/claude" --skills "$SK_CLAUDE" >/dev/null 2>"$RENDER_TMP/err" || pf "skill render failed (claude): $(cat "$RENDER_TMP/err")"
  fi
  if [ "$WANT_CODEX" = 1 ]; then
    "$PY" "$HEREP/shared/render_skills.py" --tool codex --out "$RTP/codex" --skills "$SK_CODEX" >/dev/null 2>"$RENDER_TMP/err" || pf "skill render failed (codex): $(cat "$RENDER_TMP/err")"
  fi
fi

if [ "$PF" -gt 0 ]; then echo "Preflight failed ($PF problem(s)); nothing was changed."; exit 1; fi
echo "Preflight: OK"

foreign() { [ -e "$1" ] && [ ! -f "$1/$MARKER" ]; }   # an existing skill folder that is not ours
# Only the checkpoint skill (new with Codex support) is protected this way; crew, handoff, decide and recap behave as before
cforeign() { [ "$1" = checkpoint ] && foreign "$USER_DIR/skills/checkpoint"; }

rtk_report() {
  local r=""
  if command -v rtk >/dev/null 2>&1; then r=$(command -v rtk)
  elif [ -x "$HOME/.headroom/bin/rtk" ]; then r="$HOME/.headroom/bin/rtk"
  elif [ -x "$HOME/.headroom/bin/rtk.exe" ]; then r="$HOME/.headroom/bin/rtk.exe"; fi
  if [ -n "$r" ]; then echo "RTK: found at $r"; else echo "RTK: not found; plain commands work, filter output with grep/tail"; fi
}

# ---------- Dry run: print the plan, change nothing ----------
if [ "$DRY" = 1 ]; then
  echo "Dry run (tool: $TOOL): nothing will be changed. Plan:"
  echo "would back up overwritten files to $BK_ROOT (user and project folders, one each)"
  if [ "$WANT_CLAUDE" = 1 ]; then
    echo "would copy agents to $USER_DIR/agents"
    echo "would install skills to $USER_DIR/skills: crew, $SK_CLAUDE"
    ! cforeign checkpoint || echo "would skip skill checkpoint: $USER_DIR/skills/checkpoint exists and is not ours (kept as is)"
    echo "would copy scripts to $USER_DIR/scripts"
    echo "would register status line and hooks in $USER_DIR/settings.json (other settings kept)"
    echo "would merge permissions into $DEST/settings.json (other settings kept)"
    if [ "$SELF" = 1 ]; then echo "CLAUDE.md: this is the kit itself; would leave unchanged."
    else echo "would add or refresh the claude-setup block in $MD (your own notes kept)"; fi
  fi
  if [ "$WANT_CODEX" = 1 ]; then
    IFS=, read -r -a names <<< "$SK_CODEX"
    for n in "${names[@]}"; do
      if foreign "$AGENTS_SK/$n"; then echo "would skip skill $n: $AGENTS_SK/$n exists and is not ours (kept as is)"
      else echo "would install skill $n to $AGENTS_SK/$n"; fi
    done
    echo "would write rules to $RULES_DEST (default.rules and config.toml untouched)"
    if [ "$SELF" = 1 ]; then echo "AGENTS.md: this is the kit itself; would leave unchanged."
    else echo "would add or refresh the claude-setup block in $AMD (your own notes kept)"; fi
    echo "would copy the coordinator to $CS_HOME/coordinator and launchers to $CS_HOME/bin (config.json and state/ untouched)"
  fi
  if [ "$WANT_CLAUDE" = 1 ]; then
    stale=""
    for f in agents/scout.md agents/worker.md agents/reviewer.md statusline.ps1 statusline.sh              context-check.ps1 context-check.sh context-check.log; do
      [ -e "$DEST/$f" ] && stale="$stale $f"
    done
    for d in crew handoff recap; do [ -e "$DEST/skills/$d" ] && stale="$stale skills/$d"; done
    [ -z "$stale" ] || echo "would remove stale per-project files from $DEST:$stale"
  fi
  nbk=$( { ls -1d "$BK_ROOT"/*/ 2>/dev/null || true; } | wc -l | tr -d "[:space:]")
  [ $((nbk + 2)) -le 10 ] || echo "would prune $((nbk + 2 - 10)) old backup(s) (the 10 newest are kept)"
  echo "would create $ROOT/handoffs and $ROOT/DECISIONS.md if missing"
  if [ "$SKIPT" = 1 ]; then echo "would skip self-tests"; else echo "would run self-tests"; fi
  rtk_report
  echo "Dry run complete: nothing was changed."
  exit 0
fi

# ---------- Backups (before anything is overwritten) ----------
mkdir -p "$USER_DIR"
BK_USER=$(newbackup user)
BK_PROJ=$(newbackup "$(basename "$ROOT")")
bk() {  # $1 = existing path, $2 = backup folder, $3 = name inside it
  [ -e "$1" ] || return 0
  local t="$2/$3"; mkdir -p "${t%/*}"; cp -R "$1" "$t"
}
if [ "$WANT_CLAUDE" = 1 ]; then
  bk "$USER_DIR/settings.json" "$BK_USER" settings.json
  for f in "$SRC"/agents/*; do n=${f##*/}; bk "$USER_DIR/agents/$n" "$BK_USER" "agents/$n"; done
  for d in "$SRC"/skills/*/ "$RENDER_TMP"/claude/*/; do n=${d%/}; n=${n##*/}; cforeign "$n" || bk "$USER_DIR/skills/$n" "$BK_USER" "skills/$n"; done
  for f in "$SRC"/scripts/*; do n=${f##*/}; bk "$USER_DIR/scripts/$n" "$BK_USER" "scripts/$n"; done
  [ -d "$DEST" ] && cp -R "$DEST" "$BK_PROJ/dot-claude"
  [ -f "$MD" ] && cp "$MD" "$BK_PROJ/"
fi
if [ "$WANT_CODEX" = 1 ]; then
  bk "$RULES_DEST" "$BK_USER" codex-rules/claude-setup.rules
  for d in "$RENDER_TMP"/codex/*/; do n=${d%/}; n=${n##*/}; foreign "$AGENTS_SK/$n" || bk "$AGENTS_SK/$n" "$BK_USER" "codex-skills/$n"; done
  bk "$CS_HOME/coordinator" "$BK_USER" coordinator/coordinator
  bk "$CS_HOME/bin" "$BK_USER" coordinator/bin
  find "$BK_USER/coordinator" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} + 2>/dev/null || true
  [ -f "$AMD" ] && cp "$AMD" "$BK_PROJ/"
fi

# Keep only the 10 newest backups
pruned=0
while IFS= read -r old; do
  [ -n "$old" ] && { rm -rf "$old" || true; pruned=$((pruned + 1)); }
done < <(ls -1dt "$BK_ROOT"/*/ 2>/dev/null | tail -n +11 || true)
[ "$pruned" -eq 0 ] || echo "Pruned $pruned old backup(s)."

# Adds or refreshes our block in a notes file, keeps the project's own notes.
update_notes() {  # $1 = file, $2 = source file, $3 = tool name for the new-file hint
  local f=$1 src=$2 BLOCK marks
  BLOCK=$(mktemp)
  { echo "$START"; cat "$src"; [ -z "$(tail -c 1 "$src")" ] || echo; echo "$END"; } > "$BLOCK"
  if [ -f "$f" ]; then
    marks=$(marks_of "$f")
    if [ "$marks" = ok ]; then
      awk -v s="$START" -v e="$END" -v bf="$BLOCK" '
        { sub(/\r$/, "") }
        $0 == s { if (!done) { while ((getline l < bf) > 0) print l; done = 1 } skip = 1; next }
        $0 == e { skip = 0; next }
        !skip   { print }' "$f" > "$f.tmp"
    elif [ "$marks" = bad ]; then
      echo "$(basename "$f"): claude-setup markers are damaged (missing, out of order or not on their own line); left unchanged. Fix them and re-run."
      cp "$f" "$f.tmp"
    else
      { cat "$f"; printf '\n\n'; cat "$BLOCK"; } > "$f.tmp"
    fi
  else
    { printf '# Project notes\n\n(Ask %s to fill this in: build/test commands, layout, off-limits areas.)\n\n' "$3"; cat "$BLOCK"; } > "$f.tmp"
  fi
  mv "$f.tmp" "$f"
  rm -f "$BLOCK"
}

# ---------- Part 1: user level (Claude) ----------
if [ "$WANT_CLAUDE" = 1 ]; then
  mkdir -p "$USER_DIR/agents" "$USER_DIR/skills" "$USER_DIR/scripts"
  cp "$SRC"/agents/* "$USER_DIR/agents/"
  for d in "$SRC"/skills/*/ "$RENDER_TMP"/claude/*/; do
    name=${d%/}; name=${name##*/}
    if cforeign "$name"; then
      echo "Warning: $USER_DIR/skills/$name exists and is not managed by claude-setup; skipped, left as is."
      continue
    fi
    mkdir -p "$USER_DIR/skills/$name"
    cp "$d/SKILL.md" "$USER_DIR/skills/$name/SKILL.md"
    [ "$name" != checkpoint ] || printf 'managed by claude-setup; remove this file to stop updates
' > "$USER_DIR/skills/$name/$MARKER"
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

  # ---------- Part 2: project level (Claude) ----------
  mkdir -p "$DEST"
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
    update_notes "$MD" "$HERE/CLAUDE.md" Claude
  fi
fi

# ---------- Codex ----------
if [ "$WANT_CODEX" = 1 ]; then
  for d in "$RENDER_TMP"/codex/*/; do
    name=${d%/}; name=${name##*/}
    if foreign "$AGENTS_SK/$name"; then
      echo "Warning: $AGENTS_SK/$name exists and is not managed by claude-setup; skipped, left as is."
      continue
    fi
    mkdir -p "$AGENTS_SK/$name"
    cp "$d/SKILL.md" "$AGENTS_SK/$name/SKILL.md"
    printf 'managed by claude-setup; remove this file to stop updates\n' > "$AGENTS_SK/$name/$MARKER"
  done

  mkdir -p "$(dirname "$RULES_DEST")"
  cp "$RULES_SRC" "$RULES_DEST"

  if [ "$SELF" = 1 ]; then
    echo "AGENTS.md: this is the kit itself; left unchanged."
  else
    update_notes "$AMD" "$HERE/AGENTS.md" Codex
    asz=$(wc -c < "$AMD" | tr -d '[:space:]')
    [ "$asz" -le 32768 ] || echo "Warning: AGENTS.md is $asz bytes; Codex reads at most 32768 bytes of project instructions by default. Trim it."
  fi

  mkdir -p "$CS_HOME/bin"
  rm -rf "$CS_HOME/coordinator.new"
  cp -R "$HERE/coordinator" "$CS_HOME/coordinator.new"
  find "$CS_HOME/coordinator.new" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} + 2>/dev/null || true
  rm -rf "$CS_HOME/coordinator"
  mv "$CS_HOME/coordinator.new" "$CS_HOME/coordinator"
  cat > "$CS_HOME/bin/usagectl" <<'SHEOF'
#!/bin/sh
# usagectl launcher installed by claude-setup
here=$(cd "$(dirname "$0")" && pwd)
for p in python3 python py; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$p" "$here/../coordinator/usagectl.py" "$@"
  fi
done
echo "usagectl: Python 3.9 or newer not found" >&2
exit 1
SHEOF
  chmod +x "$CS_HOME/bin/usagectl"
  cat > "$CS_HOME/bin/usagectl.cmd" <<'CMDEOF'
@echo off
where python >nul 2>nul
if not errorlevel 1 goto usepython
py -3 "%~dp0..\coordinator\usagectl.py" %*
exit /b %errorlevel%
:usepython
python "%~dp0..\coordinator\usagectl.py" %*
exit /b %errorlevel%
CMDEOF
fi

# ---------- All modes ----------
mkdir -p "$ROOT/handoffs"
[ -f "$ROOT/DECISIONS.md" ] || cp "$SRC/DECISIONS.md" "$ROOT/DECISIONS.md"

echo "Installed into $ROOTP (tool: $TOOL)"
echo "User backup:    $BK_USER"
echo "Project backup: $BK_PROJ"
[ "$WANT_CODEX" = 0 ] || echo "usagectl: add $(winpath "$CS_HOME")/bin to your PATH to run it as 'usagectl' (your shell profile is not edited)."
rtk_report

[ "$SKIPT" = 0 ] || { echo "Self-tests skipped (--skip-self-test)."; exit 0; }

# ---------- Part 3: self-test ----------
FAILS=0
bad() { FAILS=$((FAILS + 1)); }

if [ "$WANT_CLAUDE" = 1 ]; then
  TEST_IN="{\"transcript_path\":\"$HEREP/claude-files/test-transcript.jsonl\",\"session_id\":\"install-test\"}"
  if [ "$WIN" = 1 ]; then
    out=$(printf '%s' "$TEST_IN" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/context-check.ps1" 2>&1 || true)
  else
    out=$(printf '%s' "$TEST_IN" | bash "$USER_DIR/scripts/context-check.sh" 2>&1 || true)
  fi
  case "$out" in *"Context check"*) echo "Context check self-test: OK" ;; *) echo "Context check self-test: FAILED - paste this output to Claude"; bad ;; esac

  TEST_IN2="{\"transcript_path\":\"$HEREP/claude-files/test-transcript-compacted.jsonl\",\"session_id\":\"install-test\",\"prompt\":\"hello\"}"
  rc2=0
  if [ "$WIN" = 1 ]; then
    out2=$(printf '%s' "$TEST_IN2" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/context-check.ps1" 2>&1) || rc2=$?
  else
    out2=$(printf '%s' "$TEST_IN2" | bash "$USER_DIR/scripts/context-check.sh" 2>&1) || rc2=$?
  fi
  if [ "$rc2" = 0 ] && [ -z "$out2" ]; then echo "Context check (post-compact) self-test: OK"; else echo "Context check (post-compact) self-test: FAILED - paste this output to Claude"; bad; fi

  gtest() {  # $1 = command; runs the guard, prints its exit code
    local j="{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$1\"}}" rc=0
    if [ "$WIN" = 1 ]; then printf '%s' "$j" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/bash-guard.ps1" >/dev/null 2>&1 || rc=$?
    else printf '%s' "$j" | bash "$USER_DIR/scripts/bash-guard.sh" >/dev/null 2>&1 || rc=$?; fi
    echo "$rc"
  }
  g1=$(gtest "git push origin main"); g2=$(gtest "git status")
  if [ "$g1" != 0 ] && [ "$g2" = 0 ]; then echo "Bash guard self-test: OK"; else echo "Bash guard self-test: FAILED - paste this output to Claude (push exit=$g1, status exit=$g2)"; bad; fi
  g3=$(gtest 'echo hi\ngit push')
  if [ "$g3" != 0 ]; then echo "Bash guard multi-line self-test: OK"; else echo "Bash guard multi-line self-test: FAILED - paste this output to Claude (exit=$g3)"; bad; fi

  TEST_IN3="{\"cwd\":\"$HEREP\",\"hook_event_name\":\"SessionStart\",\"source\":\"startup\"}"
  if [ "$WIN" = 1 ]; then out3=$(printf '%s' "$TEST_IN3" | $PS -NoProfile -ExecutionPolicy Bypass -File "$USERP/.claude/scripts/session-brief.ps1" 2>&1 || true)
  else out3=$(printf '%s' "$TEST_IN3" | bash "$USER_DIR/scripts/session-brief.sh" 2>&1 || true); fi
  case "$out3" in *"[Session brief] Open workstreams"*) echo "Session brief self-test: OK" ;; *) echo "Session brief self-test: FAILED - paste this output to Claude"; bad ;; esac

  chk() { "$PY" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$2" && echo "$1 settings.json: OK" || { echo "$1 settings.json: INVALID - paste this output to Claude"; bad; }; }
  chk user "$USER_SETTINGS"
  chk project "$PROJ_SETTINGS"
fi

if [ "$WANT_CODEX" = 1 ]; then
  if command -v codex >/dev/null 2>&1; then
    RP=$(winpath "$CODEX_DIR/rules")/claude-setup.rules
    c1=$(codex execpolicy check --rules "$RP" -- git push origin main 2>&1 || true)
    c2=$(codex execpolicy check --rules "$RP" -- git status 2>&1 || true)
    isforb() { printf '%s' "$1" | grep -Eq '"decision"[[:space:]]*:[[:space:]]*"forbidden"'; }
    if isforb "$c1" && ! isforb "$c2"; then echo "Codex rules self-test: OK"
    else echo "Codex rules self-test: FAILED - paste this output to Codex (push: $c1 / status: $c2)"; bad; fi
  else
    echo "Codex rules self-test: skipped: codex not on PATH"
  fi

  skok=1
  for d in "$RENDER_TMP"/codex/*/; do
    n=${d%/}; n=${n##*/}; f="$AGENTS_SK/$n/SKILL.md"
    foreign "$AGENTS_SK/$n" && continue
    if [ "$(head -n 1 "$f" 2>/dev/null)" != "---" ] || ! grep -q "^name: $n\$" "$f" || ! grep -q '^description: ' "$f"; then
      echo "  skill $n: frontmatter missing or wrong in $f"; skok=0
    fi
  done
  if [ "$skok" = 1 ]; then echo "Codex skills self-test: OK"; else echo "Codex skills self-test: FAILED - paste this output to Codex"; bad; fi

  cst=$(mktemp -d)
  if cout=$(CLAUDE_SETUP_HOME="$(winpath "$cst")" "$PY" "$(winpath "$CS_HOME")/coordinator/usagectl.py" selftest 2>&1); then echo "Coordinator self-test: OK"
  else echo "Coordinator self-test: FAILED - paste this output to Codex"; echo "$cout" | tail -n 5; bad; fi
  rm -rf "$cst"
fi

if [ "$FAILS" -gt 0 ]; then echo "$FAILS self-test(s) failed."; exit 1; fi
