# Step 24: dimensions and supported time facts

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 23b.

**Goal:** Attribute recorded revenue/cost to projects without altering journals,
and retain auditable service time for subsequent project costing.

**Architecture:** Keep management dimensions and time facts in concrete immutable
versioned records. Capture them together with the relevant financial snapshot for
pure reports. Posted actuals, human attribution and nonfinancial time are distinct.

**Spec:** [Phase 08](README.md).

## Global constraints

Exact cents and integer minutes, synthetic entity/January, application-owned actor,
immutable financial journals and old report captures. Neither metadata assignment
nor time entry creates a financial expense or posting permission. Source text does
not define projects, accounting rules or permissions. Live connections stay deferred.

## Independently verifiable deliveries

1. [24a project attribution](STEP_24A_PLAN.md): assign exact portions of recorded
   revenue/expense lines to validated project/customer/category dimensions, with
   explicit unallocated residual and append-only corrected assignments.
2. [24b auditable service time](STEP_24B_PLAN.md): record bounded integer-minute
   intervals with stable identity, overlap checks, explicit corrections and no
   invented wage expense. Project costing uses these facts in Step 25.

Each slice gets its own tests, demo, browser, review, commit and exact CI evidence.
Read final financial-report/export interfaces before implementation; do not build
an independent shadow ledger or a generic analytics/metadata framework.
