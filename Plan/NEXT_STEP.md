# Step 35a delivered; Step 35b next

The 2026-10-28 request starts the planned offline prerequisites for live verification.
[Step 35a](09-integrations-and-pilot/STEP_35A_VERIFICATION.md) adds durable evaluation
budgets, deadline/crash controls and a frozen semantic manifest. Independent
re-review passed. Commit [`ffed155`](https://github.com/DatasanAli/Accounting_Harness/commit/ffed1553da35bcff3bb763b960a097ba54d35acd)
was pushed and matched `origin/main`; [exact CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/40721400386)
passed **950 tests and all 50 demonstrations**.

[Step 35](09-integrations-and-pilot/STEP_35_PLAN.md) is split into independent
substeps. Step 35b remains unimplemented. G0 operator/account choices are explicit
in the [decision record](09-integrations-and-pilot/G0_DECISIONS.md); no live gate
has passed. Optional Phase 10 is still unselected.

Next prompt:

> Build Step 35b: connect the durable evaluation controls and frozen manifest to authenticated operational scoring. Use synthetic fixtures and injected transports, test and demonstrate the access, restart, usage and scoring boundaries, then commit, push and verify exact-SHA CI. Keep live providers, credentials and sandbox connections disabled.
