# Next: finish Step 12 — bounded live provider evaluation

Status: adapter, offline tests and synthetic demonstration implemented. The live
release gate is pending because `OPENAI_API_KEY` is not configured locally.
Steps 01–11 remain the completed roadmap; Step 13 is not ready for implementation.

## Copy this prompt

> Finish Step 12: run the bounded live synthetic provider evaluation with a locally configured OPENAI_API_KEY, record the results and any regressions, verify all checks, then commit and push to GitHub. Keep Step 13 gated until Step 12 passes. Stop after this step.

## Remaining work

Read the [Step 12 contract](04-agent-harness/STEP_12_PLAN.md) and
[verification](04-agent-harness/STEP_12_VERIFICATION.md). Configure credentials in
the local environment; never paste or commit them. Confirm the existing budget
before any billable call: pinned `gpt-4.1-mini-2025-04-14`, prompt `expense-v1`,
20 frozen cases plus four repeat samples, at most 24 requests, 300 seconds and
$0.25 conservative cost reservation. No automatic network retries.

Run `python3 -m accounting_harness eval-provider --live`. Record the sanitized
result: category numerators/denominators, exact supported proposals, required
review routing, evidence, unauthorized postings, balance, model/prompt/corpus,
request count, latency, usage-derived cost, unknown billing, failures and repeat
nondeterminism. A fake score cannot satisfy this gate. Address regressions with
new labeled cases and a versioned corpus; do not weaken the existing labels.

Re-run foundation, guarded suite and all eleven demos. Update the roadmap to
complete Step 12 only after its live gate passes; then make Step 13 ready using
the [prepared brief](05-service-bookkeeping/STEP_13_PLAN.md). Commit/push and
verify the exact GitHub SHA and Actions run. Stop without implementing Step 13.
