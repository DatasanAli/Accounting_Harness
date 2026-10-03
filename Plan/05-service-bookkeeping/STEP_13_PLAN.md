# Step 13 brief: cash receipts and expenses

Status: planned, gated on completion of Step 12's live provider evaluation.
This brief does not authorize implementation before the user requests Step 13.

## Copyable prompt after the gate passes

> Build Step 13: Cash receipts and expenses. Follow Plan/05-service-bookkeeping/STEP_13_PLAN.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Scope

Add deterministic reviewed templates for incurred cash expenses and immediately
earned service receipts. Reuse registered evidence, immutable draft revisions,
exact cents, separate human approval and atomic posting. A source's cash amount
alone cannot establish revenue or expense recognition. Do not add vendor bills,
receivables, bank execution, authentication or provider capabilities here.

Tests must prove that owner contributions, transfers and customer advances are
not misclassified as earned revenue, that unsupported evidence routes to review,
and that duplicate receipts and retries cannot create another posting. Preserve
all existing accounting, agent and zero-test-discovery checks.

Demonstrate rent 1200.00 USD and a separately evidenced earned cash receipt;
inspect debit/credit classifications, evidence/actor links and the resulting
trial balance. Update CLI documentation, CI, status, roadmap and the Step 14
brief. Run checks and demonstrations, commit/push and inspect the exact GitHub
SHA and Actions result, then stop.
