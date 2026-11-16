# Handoff pilot results — 2026-11-16

**This pilot does not show that Relay is faster than a good handoff note.** Both
conditions produced correct task code. Relay made verification freshness explicit
and, with the sandbox configured correctly, recorded fresh before/after checks.

## Observed runs

Windows; Python 3.12; fresh temporary repositories; a 90-second cap per invocation.
Claude Code 2.1.284 reported `claude-fable-5-1`. Codex used the configured
`gpt-6-astra` without a model override. The task and scoring are described in the
[protocol](handoff-comparison.md). All trials, including failures, are listed below.

| Run, in launch order | First observed passing edit | Total elapsed | Outcome |
|---|---:|---:|---|
| Claude, note | 56.80 s | 86.20 s | Completed; acceptance passed |
| Codex 0.134.0, Relay | — | 9.88 s | Setup failure: CLI too old for configured model; no task work |
| Claude, Relay | 69.30 s | 90.42 s | Timed out after a correct edit and passing check; no final response |
| Codex 0.169.0, Relay | 48.98 s | 56.56 s | Completed; acceptance passed; Relay state write blocked, agent tested directly |
| Codex 0.169.0, note | 25.14 s | 36.00 s | Completed; acceptance passed |
| Codex 0.169.0, Relay, state access corrected | 31.92 s | 42.03 s | Completed; acceptance passed; fresh checks recorded through Relay |

The last run granted Codex write access only to its own temporary Relay state
directory via `--add-dir`. A current Codex CLI was installed in a temporary prefix;
the user's installed CLI and configured model were not replaced. Every task run
left its acceptance-test file unchanged. Setup time is excluded from timings.

## Trace review

- **Claude, note:** reproduced the Unicode failure, fixed it and reran the check.
  Its final answer ambiguously said the old check still applied while explaining
  that only the earlier ASCII case passed. Score freshness acknowledgement as
  **ambiguous**, not as a clean failure or success. Three initial file reads used
  wrong paths and were retried; shell/RTK availability also caused retries.
- **Claude, Relay:** explicitly stated the old pass predates the new assertion and
  does not apply. It verified the checkpoint, read each task/context file once,
  reproduced the failure and fixed it. Shell permission retries and extra Relay
  inspection occurred; the run hit the cap before its final response.
- **Codex, note:** explicitly rejected the old pass as evidence for the current
  acceptance criteria. Read the task files once, reproduced the failure, fixed it,
  and ran additional whitespace/order/duplicate checks. Four initial RTK commands
  failed before it used available tools.
- **Codex, Relay, first compatible run:** explicitly identified stale evidence and
  fixed the task. Its attempt to write evidence failed with `FileExistsError` under
  workspace-only sandboxing; it reported that limitation and ran the test directly.
  Two initial RTK commands also failed.
- **Codex, Relay, corrected state access:** explicitly identified stale evidence,
  verified the checkpoint, reproduced failure through `board check`, then recorded
  a passing `board check` after the fix. Three initial RTK commands failed before
  native commands succeeded. No repeated successful task-file reads were observed.

No clear reduction in repeated investigation was demonstrated. Tool/path retries
are reported separately from necessary inspection and before/after test runs.

## Limits and resulting fixes

This is one small task, with one note run per provider, personal skills/settings,
uncontrolled network latency and other local work running during parts of the
pilot. It is not a statistically meaningful ranking. The plain note was deliberately
honest about stale tests; an advantage against a misleading note would not establish
an advantage against careful handoff practice. No live source agent produced the
fixture. Herdr was not involved in these timings.

The pilot exposed setup friction worth addressing: incompatible Codex versions,
the need to permit temporary state writes, and irrelevant RTK guidance inherited
from the local environment. Do not silently drop these costs from future trials.

Review also hardened the harness: monitor errors now stop the CLI and retain an
outcome; POSIX cleanup targets the dedicated process group; acceptance uses the
harness's own test code. First-edit success is now a separate metric from time to
first passing edit. A Windows CRLF baseline error invalidated the first-edit metric
in the last pilot run, so **no first-edit-success scores are published here**. The
baseline comparison is fixed and regression-tested for future runs. First-passing
times and final acceptance above are unaffected by that baseline-scoring bug.

Raw CLI logs and result files remain in local temporary directories, referenced in
the workstream handoff. They are not published because they contain local context.
Repeat the protocol with pinned settings, several tasks and counterbalanced runs
before making speed or efficiency claims.
