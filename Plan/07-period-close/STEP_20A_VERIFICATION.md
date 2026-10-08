# Step 20a verification: supported prepaid insurance consumption

Observed on 2026-10-08 with synthetic USD records.

## Behavior and browser demonstration

A fresh workspace contained a registered/enrolled insurance source and one posted
1,200.00 prepaid purchase, created through the existing trusted ledger fixture
primitive. This slice does not claim a purchase-entry UI; that path is planned
separately in Step 31a.

In the native Prepaid insurance form, the operator registered January 1–December 31
coverage, referencing the original purchase journal/source and full principal.
Preparing January consumption left the original journal and complete trial-balance
JSON unchanged. The prepared policy showed 1,200.00 supported remaining asset and
zero unassigned residual; it reserved no consumption.

The review screen showed both original and coverage evidence, exact allocation
intent, January 31 effective date, Insurance Expense 5200 debit 100.00 and Prepaid
Insurance 1200 credit 100.00. Only the separate checkbox and Approve & post action
created the consumption. Final state: two journals, unchanged original purchase,
Cash credit 1,200.00 unchanged, Insurance Expense 100.00, Prepaid 1,100.00 and zero
control residual. The actual 500px viewport had no horizontal document overflow.

The final implementation added catalog/full-ledger inputs to its snapshot digest
while the development server still ran its earlier candidate. Only digest fields
changed on loading final code; no balances or accounting history changed. A further
restart of frozen final code preserved the complete report, journals and trial
balance JSON exactly: consumed 100.00, remaining 1,100.00, residual 0.00.

## Checks and review

- `python3 scripts/run_tests.py`: **508 tests passed** in 32.359 seconds on final
  frozen code, including 23 focused prepaid tests. Zero-discovery guard retained.
- All **26 documented demonstrations** passed; `demo-prepaid-consumption` proves
  100.00 expense, 1,100.00 remaining, duplicate coverage refusal and restart retries.
- `python3 scripts/verify_foundation.py`: passed; final parent document check
  observed 102 Markdown files/349 links before this verification record was added.
- `node --check accounting_harness/static/app.js` and `git diff --check`: passed.
- Independent review approved spec compliance and task quality with no findings.
  Delivered as [ab557e4](https://github.com/DatasanAli/Accounting_Harness/commit/ab557e4581a705a776d613a4790e384eb71b038b); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37823178380). Remote main matched the local commit.

Focused coverage includes quotient/remainder cents, leap/full-month boundaries,
zero allocations, immutable first coverage, current month claims, shared original
evidence, final-seal supersession, typed-source bypass prevention, reversal before/
after consumption, old connections/direct reversal insertion, cumulative cap,
concurrent prepare/post retries, atomic initialization/write rollback and large
exact HTTP/trace amounts. Historical migration assertions were updated only for
the new current review version; old approval/context/retry byte checks remain.

## Persistence and scope

Ledger schema stays 4; review migrates 8→9; prepaid schema 1 is additive. No new account
is needed. Coverage/effect/review/post/retry writes are atomic inside the ledger;
source registration/enrollment remains separately recoverable as before. Unknown
schema versions fail closed, and initialization failure rolls back shared upgrades.

Supported allocation uses 1–120 complete calendar months and quotient/remainder
cents, with extras assigned to earliest months. Zero allocation fixes its coverage
identity but creates no draft, month claim, effect or journal. The workspace posts
only inside its configured January period. Captured reports distinguish supported
policy consumption from unrelated generic 1200 movements through an explicit signed
unassigned residual; that residual cannot authorize additional consumption.

Generic reversal of a consumed purchase or managed consumption is refused until a
linked correction policy exists. No daily allocation, scheduler, inferred estimate,
live connection or real-policy choice was introduced. Revert software through a
new commit while preserving posted history and supported dependency records.
