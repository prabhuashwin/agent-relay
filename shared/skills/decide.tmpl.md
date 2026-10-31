---
name: decide
description: Append one decision to the project's DECISIONS.md log. Use on {{decide_cmd}}, "log this decision", "note that we decided".
---

# Decide

`DECISIONS.md` at the project root is an append-only table, one row per decision.

1. **Parse the argument.** Text before ` -- ` is the decision, text after it is the why. If no why was given, take it from the conversation if obvious, otherwise ask in one line.
2. **Handoff column.** If this session started from `handoffs/<slug>.md`, use `<slug>.md`. Otherwise use the row in `handoffs/INDEX.md` that clearly matches the current work. Otherwise `-`.
3. **Create `DECISIONS.md` if missing**, with exactly this content:
   ```
   # Decisions

   Append-only, one line per decision, newest last. Add a row with `/decide <decision> -- <why>`; `/handoff` also adds the session's new decisions. Detail lives in the handoff file named in the last column.

   | Date | Decision | Why | Handoff |
   |---|---|---|---|
   ```
4. **Append exactly one row**: `| YYYY-MM-DD | <decision> | <why> | <slug>.md |` (today's date). Cells short (about 15 words max), no line breaks, any `|` in the text replaced by `/`. {{append_note}}
5. **Reply with only the appended row**, nothing else.
