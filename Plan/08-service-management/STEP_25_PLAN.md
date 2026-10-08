# Step 25: exact service project costing

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 24b.

**Goal:** Explain a project cost of700.00 and modeled margin of300.00 from600
recorded minutes, explicit labor/overhead rates,100.00 direct actual cost and
1,000.00 attributed actual revenue.

**Architecture:** A versioned human-entered costing scenario binds captured
project/time/actuals inputs and explicit rate assumptions. A pure cost-sheet
function calculates the model; it neither duplicates ledger costs nor posts an
allocation. Keep recorded actuals visible beside modeled labor and overhead.

**Spec:** [Phase 08](README.md) and delivered dimension/time capture contracts.

## Global constraints

- Exact integer cents and minutes. Rates are strict two-decimal USD per hour,
  converted to integer cents; no float arithmetic or silent input rounding.
- Distinguish actual attributed ledger amounts, recorded operational minutes and
  costing assumptions. A costing rate is not evidence of payroll paid or accrued.
- No financial journal, approval, tax, wage compliance or live connection occurs.
  Actor/project/entity scope comes from application code and validated records.
- Every cost sheet identifies scenario version, actual/time capture digests,
  project, dates, rate/rounding policy and source/journal/time references.
  Pure rendering never consults a later live store.

## Cost-sheet policy

Version `service-cost-v1` takes active captured project minutes and an explicit
nonnegative labor rate and overhead rate per hour. Compute each modeled component
as minutes times rate_cents divided by60, rounding half-up once per total component
for the selected project/period. Retain numerator/denominator and rounding delta
in the calculation trace. Do not round each time row independently or convert to
binary fractional hours. Zero rate/minutes produces zero, not an invented line.

The reference is600 minutes at40.00/hour =400.00 modeled direct labor, plus100.00
of explicitly selected direct nonlabor actual expense allocations, plus600 minutes
at20.00/hour =200.00 modeled overhead. Total modeled cost700.00; captured attributed
revenue1,000.00 less700.00 gives modeled project margin300.00. The report clearly
labels this as management costing, distinct from financial net income.

Actual direct-cost inputs reference unique allocation revisions and journal-line
portions already validated in24a. Require those portions to be direct, nonlabor
cost under an explicit category policy; do not accept arbitrary caller-entered
actual totals or count a portion twice. Negative credits/reversals reduce actual
cost faithfully. Missing/unclassified cost facts remain visible findings.

The selected policy uses modeled labor and overhead. Actual labor and indirect
expense allocations, if present, stay visible in an accompanying actuals bridge
but are not added again to the model's direct nonlabor component. Show exactly
which actual amounts are included/excluded and why. Do not silently discard an
actual amount or call model-to-ledger differences accounting errors. The captured
actuals view must still reconcile allocated plus unallocated to the ledger.

Store immutable scenario versions with original actor/time, explicit name, rates,
selected project/cutoff/input capture and optional explanation. Creating a new
rate or input selection requires a new version with a prior-version reference and
reason; old versions and reports remain unchanged. A refresh from new time or
actuals is also a new version, never a mutation of the original cost sheet.
Scoped exact retry returns its original version after newer versions exist;
conflicting/stale changes fail and concurrent edits cannot overwrite history.

## Task 1: reproducible modeled labor, direct costs and overhead

**Files:** Focused costing service/report/schema tests and workspace/HTTP/CLI/static
integration. Reuse concrete management storage/captures; parent owns docs/CI/
browser/delivery. No generic pricing, payroll or allocation engine.

- [ ] RED:600 minutes*40.00/hour +100.00 direct actual +600*20.00/hour =700.00;
  revenue1,000.00 gives margin300.00, with every fact/assumption traced separately.
- [ ] Verify integer half-up calculation for fractional-hour intervals, zero
  rates/time, large values, negative actual adjustments and loss-making projects.
- [ ] Reject wrong project/entity, stale/missing actual/time capture, duplicate
  direct-cost portions, malformed rates and inconsistent dimension selections.
- [ ] Prove actual labor/indirect amounts are displayed but not counted again in
  the model, and ledger/report actuals are unchanged by every scenario action.
- [ ] Test scenario version/reason/exact retry/concurrency, immutable records and
  migration/write rollback; old cost-sheet bytes survive later rate/time/ledger
  changes. New input capture produces a distinct explicit scenario version.
- [ ] Add a cost sheet showing actuals, minutes, assumptions, calculations and
  model-to-actual bridge. Add `demo-project-cost` with700.00 cost/300.00 margin.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, parent browser,
  independent review, commit/push and exact CI before operating/cash budgets.
