# Step 35b delivery in progress

The user confirmed provider evaluation controls as the next scope. Step 35a is
[delivered](09-integrations-and-pilot/STEP_35A_VERIFICATION.md). Step 35b now connects
the durable budgets and frozen cases to authenticated offline scoring; see the
[plan](09-integrations-and-pilot/STEP_35B_PLAN.md) and
[verification](09-integrations-and-pilot/STEP_35B_VERIFICATION.md). Focused tests and
independent re-review pass. All 967 tests and 51 demos pass locally; GitHub shipping
and exact-SHA CI are in progress.

This completes the planned provider-control implementation after verification,
not G0 or any live gate. [G0 decisions](09-integrations-and-pilot/G0_DECISIONS.md)
remain unselected for actual operators, provider/account/model, live budgets and
sandbox ownership. Public compatibility review and sandbox prerequisites remain
in [LIVE_VERIFICATION_GATES.md](09-integrations-and-pilot/LIVE_VERIFICATION_GATES.md).
Optional Phase 10 is still unselected.

Next prompt after delivery:

> Prepare the remaining G0 decision checklist and G1 compatibility review using current official public documentation. Check the existing provider/model and proposed sandbox contracts. Do not inspect credentials, enable live transports, make provider or sandbox account calls, or change financial records.
