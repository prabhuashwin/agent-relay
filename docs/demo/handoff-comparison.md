# Plain handoff note versus Relay: reproducible pilot

The question is whether Relay helps a receiving agent continue an unfinished task,
not whether it replaces a terminal manager. This trial does not benchmark Herdr.

## Task and fairness

`compare_handoffs.py` creates a fresh temporary repository per run. The task is to
finish Unicode caseless tag normalization while preserving order and duplicates.
ASCII handling already works. A check passed before a Unicode regression test was
added; the current code fails that new case.

Both modes receive the same source, acceptance test and honest `HANDOFF.md`,
including the failed set-based attempt and the fact that the old test predates the
new case. The Relay mode also prepares/claims a checkpoint and supplies its generated
resume prompt with stale executed evidence. The source is a deterministic fixture,
not a live source-agent conversation. This isolates the receiving step.

The harness evaluates the first observed correct edit and final result with its own
acceptance code. It also checks that the agent left `check.py` unchanged. Preparation
time is excluded, so this is not an end-to-end cost comparison.

## Run

From the Relay checkout, prepare a fixture without using model allowance:

```text
python docs/demo/compare_handoffs.py --mode relay --provider codex
```

Each invocation prints its temporary artifact directory. Read `prompt.txt` and the
fixture before enabling live execution. Live runs use the installed, signed-in CLI
and its default model/settings. They consume account allowance. Run each command
separately after explicitly authorizing that consumption:

```text
python docs/demo/compare_handoffs.py --mode note --provider claude --live
python docs/demo/compare_handoffs.py --mode relay --provider claude --live
python docs/demo/compare_handoffs.py --mode relay --provider codex --live
python docs/demo/compare_handoffs.py --mode note --provider codex --live
```

The default cap is 90 seconds per run. `--timeout` accepts 10 through 110 seconds.
On Windows the harness terminates the launched process tree at the cap. A timeout
is an outcome, not a reason to silently exclude a run. `--codex-cli` accepts a path
to a compatible portable Codex executable. Do not change models between paired
trials. Inherited API-key variables are removed; the CLIs use their account login.

## Score

`result.json` records completion, timeout, observed time to first passing edit,
whether the first observed edit passed, final acceptance and whether the test file
changed. It records harness errors and cleans up the launched CLI on monitor errors.
Codex gets explicit write access to this trial's temporary Relay state directory.
`events.jsonl` contains raw CLI
output for manual review; it stays outside the repository and may include private
local context. Do not publish raw traces without reviewing them.

For each run, manually record:

- **Stale evidence acknowledged:** agent explicitly recognizes that the earlier
  pass does not cover the current case, rather than merely quoting the prompt.
- **Repeated investigation:** repeated inspection of the same file or question
  before new evidence arrives. List the actual repeated reads or commands. Reading
  the provided files once is necessary verification, not wasted investigation.
- **First edit versus first passing edit:** score whether the first observed change
  passes separately from the time until any passing change. The observation is
  sampled about every 250 ms; startup and
  test execution add latency. If no passing edit is observed, keep it null.

A useful follow-up uses at least five fresh runs per condition, counterbalanced
order, a pinned CLI/model/settings combination, and several task types. Report all
failures, medians and ranges. Personal skills, hooks, caches, network conditions,
and model nondeterminism affect this small pilot. Do not claim Relay is faster
from one pair, or compare providers as if their environments were identical.

See [recorded pilot results](handoff-comparison-results.md) and the
[Herdr companion workflow](../herdr-companion.md).
