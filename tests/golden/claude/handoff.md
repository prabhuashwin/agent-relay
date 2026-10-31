---
name: handoff
description: Write a compact handoff note for the current workstream so it can continue in a fresh session. Use on /handoff, "wrap up", "save progress", or before clearing a session with unfinished work.
---

# Handoff

Handoffs live in `handoffs/`, one file per workstream, listed in `handoffs/INDEX.md`.

1. **Pick the topic.**
   - If this session started from a file in `handoffs/`, reuse that file.
   - Otherwise read `handoffs/INDEX.md`. If an existing row is clearly the same workstream, reuse it; if not, make a new short kebab-case slug (2-3 words, e.g. `search-indexing`). If unsure which, ask the user in one line.
2. **Write `handoffs/<slug>.md`** (overwrite it), starting with `# Handoff: <Topic> - <one-line state>`, then:
   - **Goal** - 1-2 lines
   - **Done so far** - bullets, with file paths and commit ids
   - **Decisions and why** - bullets
   - **Open issues / gotchas**
   - **Next steps** - numbered, concrete
   - **Read first** - at most 5 files (with line ranges if useful)
   Keep it under 60 lines. No code dumps; point to paths and line numbers.
3. **Append new decisions to `DECISIONS.md`.** The handoff file keeps the full detail; `DECISIONS.md` is the one-line index. For each bullet under *Decisions and why* that was made this session and is not already in `DECISIONS.md` (grep a distinctive phrase), append one row `| YYYY-MM-DD | decision | why | <slug>.md |`, cells short, no `|` inside cells. Create the file with its standard header first if missing (same header as the `decide` skill). Older decisions already logged: leave alone.
4. **Update `handoffs/INDEX.md`**: add or update the row for this topic (Topic, File, today's date, one-line Status, Resume with). Create the file with the table header if missing. Mark finished workstreams `Done` rather than deleting rows.
5. **Tell the user exactly:**
   "Handoff saved to handoffs/<slug>.md. Run /clear, then start the new session with:
   `<Topic>: continue from handoffs/<slug>.md`"
   The topic name goes first so the new session's title says which workstream it is.
