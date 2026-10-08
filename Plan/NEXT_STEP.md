# Active delivery: Step 12a, then Step 13a

The user has authorized both the working localhost app and the wider accounting
roadmap in this request. Continue through individually verified commits without
asking for the next step. Live model/API and external-account connections stay
deferred. See [the working plan](LOCALHOST_APP_PLAN.md).

Step 12a is in progress: persistent localhost UI, offline fixture proposals,
Ollama/OpenAI choices disabled by default, explicit human review/posting, audit,
run history and trial balance. Verify browser behavior, full suite/demos and the
exact uploaded commit's CI before advancing.

## Exact next implementation prompt

> Build Step 13a: Additive synthetic evidence enrollment and a receipt input form in the localhost workspace. Preserve immutable ledger context, old approval bindings and snapshots; test import retry/conflict/restart and posting boundaries. Keep live API/model connections deferred. Verify, commit, push and check exact CI, then continue with Step 13b cash receipts/expenses under the expanded roadmap authorization.

The original Step 12 live gate remains available later via
`python3 -m accounting_harness eval-provider --live`; it has not passed and is
not required to continue independent offline work. Its original bounded budget
and measurement criteria remain in the [Step 12 contract](04-agent-harness/STEP_12_PLAN.md).
