# Recover a handoff without losing work

Read the error first. Keep all edits; do not reset, stash or overwrite the working
tree to make verification pass. Inspect `git status`, `git diff` and the checkpoint
owner before deciding which state is correct.

| Problem | Meaning | Recovery |
|---|---|---|
| Repository or branch differs | You may be in the wrong checkout | Return to the intended worktree; do not refresh a checkpoint against unrelated work |
| Head or uncommitted files differ | The checkpoint describes another state | Have its current owner review the changes, update the handoff and prepare a new checkpoint |
| Executed verification is stale | The recorded command ran against another repository fingerprint | Review and rerun the relevant command with `board check`; preparing alone does not rerun it |
| Checkpoint changed after release | The ticket no longer describes this checkpoint | Reconcile context, stop the source writer, release again and use the new ticket |
| No matching unconsumed release | Ticket missing, wrong or already used | Inspect ownership first; if already transferred, resume as that owner instead of retrying claim |
| Executed verification unavailable | Local evidence could not be read | Inspect `board status`; resolve local storage access and rerun the check. Do not infer failure of a completed ownership change |
| Destination lacks edit capability | Alias missing or not configured to edit | Inspect `usagectl config show`; configure the intended account rather than choosing an unrelated alias |

## Example recovery

Assume `search-index` is still owned by `claude-main` and you have reviewed the
changes in the correct worktree. Substitute the actual goal, next action,
completed/remaining work, decisions and failed attempts when preparing. Preparation
replaces the recorded context; do not accidentally erase useful fields.

```text
usagectl handoff verify --workstream search-index
git status --short
git diff
usagectl handoff prepare --workstream search-index --owner claude-main --goal "Finish the indexer" --next "Review empty-input handling" --done "Added parser" --remaining "Review empty-input handling" --accept "Indexer tests pass" --decision "Preserve whitespace" --failure "Regex approach dropped whitespace"
usagectl board check --workstream search-index --timeout 60 -- python -m unittest discover -q
usagectl handoff verify --workstream search-index
usagectl board release --workstream search-index --owner claude-main --source-stopped --json
```

Stop on unexpected failures. Only attest `--source-stopped` after the source and
its helpers stop editing. Then claim with the newly returned ticket:

```text
usagectl board claim --workstream search-index --to codex-main --ticket NEW_RETURNED_TICKET --json
```

If ownership already changed to `codex-main`, obtain its prompt instead:

```text
usagectl handoff resume --workstream search-index --to codex-main
```

Ownership is cooperative. Relay cannot stop an editor or prove that a task is
complete. See [verification boundaries](continuity-dashboard.md#verification).
