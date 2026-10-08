# Step 26: versioned operating and cash budgets

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 25.

**Goal:** Save a one-month operating budget and cash plan where opening1,000.00
plus collections1,500.00 less payments1,200.00 gives ending1,300.00, then retain a
separate delayed-collection scenario without altering actuals or the original plan.

**Architecture:** Immutable scenario revisions contain explicit operating
assumptions and dated cash receipts/payments. Pure calculations produce budget
income and a cash bridge from that version. Reuse the concrete management
version/audit conventions, not a forecasting engine or second ledger.

**Spec:** [Phase 08](README.md).

## Global constraints

- Exact integer cents and minutes; strict decimal rates/amounts. Synthetic USD
  and January plan month; scenario cash dates may extend into the next month to
  express deferral, but they cannot change the ledger's permitted posting period.
- Budgeted revenue, planned collection and recorded cash are different facts.
  Every view clearly identifies scenario/version, assumptions, policy and dates.
- Human-owned scenario editing creates new immutable versions with prior-version
  reference/reason. Old versions and reports stay reproducible after actuals change.
- No postings, payments, external calls, automatic borrowing or accounting approval.
  Scenario numbers and descriptions cannot grant permissions or claim actuals.

## Operating budget

Support one explicit activity driver: service minutes for the whole month. Store
nonnegative integer planned minutes and identify the unit policy as service hours
with60 minutes/hour. Each budget line targets one active captured revenue/expense
account and is either fixed amount cents or variable rate cents/hour. Require
unique line IDs; multiple lines per account may be aggregated but retain trace.
Unknown accounts, mixed currency and assets/liabilities/equity budget lines fail.

Fixed lines retain their amount; variable line amounts equal planned minutes
multiplied by rate cents divided by60, rounded half-up once per line. Bind rounding
policy and exact numerator/denominator. Total revenue minus expenses is planned
income, including a loss. A zero-activity plan preserves fixed costs and has zero
variable revenue/cost. Capture account metadata and rates; do not resolve labels
from a future mutable source when rendering an old version.

A small variance-ready example may use480 planned minutes (eight hours), revenue
rate125.00/hour, expense variable rate50.00/hour and fixed expense100.00: planned
revenue1,000.00 and expense500.00. This is a separate management scenario from the
cash-plan example and the original reference month's recorded accounting.

## Dated cash plan

Opening cash is an explicit scenario assumption, not inferred as true from a
budgeted balance. Planned cash rows carry stable row ID, direction, positive cents,
expected calendar date, category and optional budget/source reference. Require
explicit linkage where provided and distinguish unsupported external references
from verified actual source IDs. Equal amounts on different row IDs remain distinct;
a repeated row identity cannot be counted twice.

Only rows whose expected dates fall in the plan month contribute to its cash
bridge. Show out-of-month receipts/payments in a deferred schedule; do not count a
February collection as January cash. Operating income does not automatically
populate or reconcile to collections, because accrual and cash timing differ.

For the reference cash plan, opening1,000.00, January collections1,500.00 and
payments1,200.00 produce ending1,300.00. A new version moving the collection to
February gives January ending-200.00 and a1,500.00 deferred receipt. Show that
negative closing plan as a200.00 funding gap, without inserting borrowing, changing
payment dates or modifying actual journals to make the plan positive.

The scenario record and all lines, audit and retry commit atomically. Validate the
whole scenario before storing it. Exact retry after newer versions returns its
original result; changed payload/key or stale parent revision fails. Corrections
replace the whole scenario in a new version rather than mutating line histories.

## Task 1: explicit income assumptions and dated cash scenarios

**Files:** Concrete budget/scenario module and tests, immutable additive storage,
workspace/HTTP/CLI/static. Parent owns docs/CI/browser/delivery.

- [ ] RED: exact1,000+1,500-1,200=1,300 cash bridge; delayed collection new version
  yields-200 January/1,500 deferred, with the original report byte-identical.
- [ ] Verify fixed/variable operating lines, planned480 minutes/revenue1,000/
  expenses500, zero activity, fractional-hour rounding, losses and large values.
- [ ] Reject malformed/bool/floating amounts or minutes, wrong account/entity/
  currency, duplicate line IDs, invalid dates and conflicting/stale versions.
- [ ] Test concurrent exact/versioned saves, immutable rows, migration/write
  rollback and old scenario/report preservation after later ledger/time changes.
- [ ] Prove every action leaves journals, actual financial/project reports and
  approvals unchanged; report income and cash timing separately with full trace.
- [ ] Add clear scenario/version controls, operating assumptions, cash bridge and
  deferred schedule; `demo-budget` demonstrates1,300 and delayed-collection-200.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, parent browser,
  independent review, commit/push and exact CI before flexible variance reports.
