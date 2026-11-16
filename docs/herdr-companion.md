# Run agents in Herdr, transfer work with Relay

Herdr owns the terminals; Relay records task context, Git state and test evidence.
This is a companion workflow using their CLIs, not a plugin or automatic session
import. Run the source and destination in the **same worktree on the same host**.
Relay does not copy uncommitted files or its local SQLite history to another host.

## One writer, two panes

1. Install both tools using [Relay setup](setup-and-reference.md#quick-start) and
   [Herdr's official installation guide](https://herdr.dev/tui/docs/install/).
   Configure Relay account aliases for your actual signed-in tools. Start `herdr`
   from your project directory, then start `claude` in a pane.
2. At a handoff boundary, ask Claude to record decisions, failed attempts and the
   next action in the handoff note and checkpoint. Review its recorded context.
3. Stop Claude's edits and any delegated writers. Detaching Herdr or observing an
   idle pane is **not** confirmation that all writers stopped. Herdr keeps agents
   running when its client detaches.
4. In a terminal pane in that same project, execute your relevant test command:

   ```text
   usagectl board check --workstream my-task --timeout 60 -- python -m unittest discover -q
   usagectl handoff verify --workstream my-task
   usagectl board release --workstream my-task --owner claude-main --source-stopped --json
   ```

   Replace the workstream, aliases and test command with your configured values.
   If the code changed after the checkpoint, follow [recovery](handoff-recovery.md)
   before release. Review the check result; a matching checkpoint is not a test pass.
5. Copy the returned ticket. In the same terminal, claim and copy the prompt:

   ```text
   usagectl board claim --workstream my-task --to codex-main --ticket RETURNED_TICKET --json
   ```

   Use the actual returned ticket. A successful claim transfers cooperative
   ownership; it does not launch Codex. If the command reports a warning after
   ownership changed, inspect the owner before retrying.
6. Split right using Herdr's default `Ctrl+B`, then `V` (or the pane context menu).
   Confirm the new pane is in the same project directory. Start `codex` and paste
   the returned prompt. Codex verifies the checkpoint before editing and reviews
   the recorded evidence. Leave the old Claude session stopped.

For parallel tasks, use separate worktrees and distinct workstreams. Do not have
two agents edit the same task merely because they are in different panes.

## Validation and limits

On 2026-11-16, Herdr **0.9.5**, downloaded as a temporary Windows portable release,
was exercised in the dedicated session `relay-smoke-20261116`. Its CLI created a
workspace for an isolated Relay fixture, split a second pane in the same directory,
and ran Relay help and `handoff resume`. The pane output displayed the enriched
context, stale evidence and existing ownership guidance. The test session was
stopped afterward. No global Herdr installation or existing session was changed.

This smoke test verifies terminal/CLI interoperability. It does not prove native
agent detection, restart restoration, cross-host transfer, or a live Claude-to-Codex
handoff inside Herdr. Relay's release/claim behavior is separately covered by the
[executable demo](demo/verified-handoff.md) and continuity tests.

Official references checked for this workflow:
[quick start and detach behavior](https://herdr.dev/tui/docs/quick-start/) and
[agent skill/context rules](https://herdr.dev/tui/docs/agent-skill/).
If automating Herdr later, use its release-matched `herdr --skill` and pane IDs;
do not send commands to whichever user pane happens to be focused.
