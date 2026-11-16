# Relay resume workflow implementation plan

**Goal:** Complete the four approved follow-ups: useful resume prompts, actionable
recovery, an honest comparison trial, and a Herdr companion workflow.

**Design:** Reuse checkpoint fields and the latest local executed-check record.
Keep reported checks distinct. Do not copy check output into prompts. Preserve
existing conflict exit codes, ownership rules and checkpoint schema. Recovery
must preserve edits and require review before refreshing state. Keep the comparison
fixture offline; live agent trials require explicit allowance authorization.

**Execution:** Inline on feat/relay-resume-workflow; no parallel writers.

- [x] Add failing regression tests for context, fresh/stale/missing evidence and
  recovery advice; implement shared evidence lookup and prompt enrichment.
- [x] Validate prompt behavior through CLI resume and board claim, including
  managed workstreams and stale evidence after checkpoint refresh.
- [x] Create a repeatable plain-note versus Relay trial fixture and scoring protocol.
  Run offline safeguard trials; record live measurements only if actually performed.
- [x] Document and smoke-test Herdr with a temporary portable binary and fictional
  task. Keep real account credentials and running services untouched.
- [x] Run relevant Python and dashboard tests, check documentation links and diff,
  and save the verified results and workstream handoff.
