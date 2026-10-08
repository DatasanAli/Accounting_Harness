# Step 24a: traceable project attribution of recorded actuals

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 23b.

**Goal:** Split one recorded expense across two projects and show that project
amounts plus explicitly unallocated amounts exactly reproduce ledger actuals.

**Architecture:** A concrete management-dimensions service stores immutable project
identities and whole-assignment revisions for existing journal lines. Capture the
current revisions with the financial ledger; render reconciliation from that
capture only. This metadata does not modify the ledger or financial statements.

**Spec:** [Step 24 contract](STEP_24_PLAN.md).

## Global constraints

- Exact cents, existing synthetic entity/USD/January, immutable journals/evidence.
  Only ordinary revenue/expense lines participate in this initial actuals view.
- Each allocation names a validated project, optional customer identity, explicit
  cost category, behavior (fixed/variable/unclassified) and traceability
  (direct/indirect/unclassified). Never infer classifications from descriptions.
- Captures identify ledger snapshot, attribution revision IDs, policy and digest.
  Later metadata corrections create a new report, leaving every old capture intact.
- Local operator actions remain application-owned. No model/account activation,
  live connection, payroll calculation or financial approval is introduced here.

## Project and assignment contract

Create a bounded immutable project ID/name/entity and optional customer ID through
an explicit operator action. A same-ID exact retry retains original audit; changed
metadata conflicts. Do not introduce editable project lifecycle or external CRM
sync. Customer identity is a management reference, not a new invoice/customer
master or permission to modify issued documents. Refuse cross-entity references.

An assignment targets exact journal ID plus line position and captured immutable
line/journal digest. Accept a complete replacement allocation set, with explicit
positive unsigned-cent portions whose sum does not exceed the source line cents.
Project totals inherit the financial sign: revenue credit is positive revenue,
expense debit is positive cost; reversals/opposite-side lines contribute negatively.
Never turn a credit adjustment into a positive expense by using absolute values.

Unallocated residual is source signed cents less assigned signed cents and remains
visible, including zero and negative results. Categories/behavior/traceability
partition the same allocation rows; do not add the same allocation once per
classification axis. A partly unclassified row stays in the actuals reconciliation.
Close transfers never become project costs or service revenue.

Use one append-only assignment revision per journal-line target. A correction
requires the current prior revision and reason, then writes a new whole set.
It does not edit old rows or journal data. Zero allocations may clear a prior
assignment explicitly, leaving the whole line unallocated. Exact retry returns
its original revision even if a newer revision now exists; stale updates fail.
Concurrent updates must not silently overwrite each other. Protect project,
revision/allocation and retry records from update/delete/replace.

Linked reversal journals remain separate immutable financial lines. Show their
original journal link in the attribution view; do not blindly retain a net-zero
project cost when the original and reversal have different explicit attribution.
Initially leave an unassigned reversal visibly unallocated unless the operator
assigns its own line. The full source-actual reconciliation must still be exact.

Capture all current assignments and their source financial entries/catalog under
one database read transaction. The pure report can group by project/customer/
category and show source journal/line/evidence drilldown. For each supported account
and overall revenue/expense totals, allocated plus unallocated must equal the
same captured financial report totals. No double counting between two projects.

## Task 1: immutable assignments and project-to-ledger reconciliation

**Files:** Concrete management/dimensions module and tests, versioned additive
schema, workspace/HTTP/CLI/static. Parent owns docs/CI/browser/delivery.

- [ ] RED: recorded expense300.00, ProjectA120.00 and ProjectB100.00 allocations
  leave80.00 unallocated; each classification axis and ledger total reconcile.
- [ ] Validate exact amounts, existing posted line/digest, supported account/entry
  type, project/customer/entity, enums and bounds; refuse over-allocation and
  unposted/cross-entity/closing lines. Descriptions never grant classification.
- [ ] Test changed whole-set revision/reason, stale/conflicting/concurrent changes,
  original retry after a correction, immutable history and atomic write/migration
  faults without ledger/source/review mutation.
- [ ] Verify credits/reversals, unallocated and unclassified rows, zero/no activity,
  large cents, cutoff and old captured reports after later assignment/activity.
- [ ] Add project creation and explicit allocation review in the localhost view,
  exact reconciliation and source drilldown. Add `demo-project-dimensions`.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; parent browser,
  independent review and exact commit/CI before time facts.
