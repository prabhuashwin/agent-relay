---
name: checkpoint
description: Prepare a verified checkpoint so this workstream can continue on another account or tool. Use on {{checkpoint_cmd}}, after {{handoff_cmd}} at a meaningful boundary, and before usage runs out.
---

# Checkpoint

A checkpoint is `handoffs/<slug>.checkpoint.md`: readable sections plus one JSON block with git facts that another session can verify before it continues. It complements the handoff note, it does not replace it.

1. **Write the handoff first** ({{handoff_cmd}}) if this session has progress not yet saved.
2. **Gather facts, do not guess.** Workstream slug (lowercase, digits, hyphens), your account alias as configured in usagectl (ask the user in one line if unknown), goal, acceptance checks, what is done, what remains, each verification command with its real result, failures, decisions, and the single next action.
3. **Prepare it** (read-only on git; it never adds, commits, stashes or resets):
   `{{usagectl}} handoff prepare --workstream <slug> --owner <alias> --goal "<goal>" --next "<next action>" --done "<item>" --remaining "<item>" --verify "<command>=><result>=>pass|fail"`
   Repeat `--done`, `--remaining`, `--verify`, `--accept`, `--failure`, `--decision` as needed. If it refuses because another owner holds the workstream, stop and ask the user before using `--take-over`.
4. **Report** the checkpoint path and how to resume on another account:
   `{{usagectl}} handoff resume --workstream <slug> --to <alias>`
   If `CLAUDE_SETUP_HOME` is set, the launcher is `$CLAUDE_SETUP_HOME/bin/usagectl` instead of the path above.
   Say which uncommitted files exist; never discard, stash, commit or overwrite the user's changes to make a checkpoint match.
