# Step 21: reproducible core financial statements

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 20.

**Goal:** Report the reference month's 1,100.00 income and 11,500.00 assets from
one captured ledger, with linked owner equity and account/journal drilldown.

**Architecture:** One immutable financial-report capture and pure rendering
functions. Reuse the ledger snapshot, exact account balances and catalog; reports
neither post nor reclassify transactions. Keep report policy and presentation
separate from the recorded facts.

**Tech stack:** Python standard library, existing SQLite workspace and localhost UI.

## Global constraints

- Synthetic USD service business, owner capital/drawings and the existing January
  period. Unsupported legal forms, currency conversions and reporting bases are
  explicit errors, never inferred from account labels or document text.
- Exact integer cents throughout; output decimal strings for the browser. Retain
  negative results and contra balances rather than forcing normal-side amounts.
- Every report identifies entity, inclusive cutoff, period start, captured catalog,
  included journal IDs, policy/version and deterministic snapshot/report digests.
- Render only from the captured object. Later postings, account extensions,
  registry changes and eventual closing must not change an existing report.
- No external connection, posting permission, account modification or unsupported
  estimate is introduced. Parent owns docs/CI/browser/commit and remote checks.

## Report contract

Create a small `financial_reports.py` with an immutable capture and pure linked
income statement, owner's equity statement and balance sheet. Capture all inputs
in one ledger read transaction. Bound the requested cutoff to the configured
period; do not silently reinterpret a date outside the supported period.

The income statement presents revenue as credit minus debit, expenses as debit
minus credit, and income as revenue minus expenses. Include opposite balances and
linked reversals faithfully. Each account row carries its exact net contribution
and contributing journal/source references so its drilldown sums to its total.

For this initial period with zero opening equity, owner's equity is opening
capital plus net contributions plus current-period income minus net drawings.
Read contribution/drawings movement from their explicit accounts and retained
journal classification. Never infer it from descriptions. Label net withdrawals
or reversed contributions faithfully. Exclude closing transfers from ordinary
contribution/performance movement when closing is added in Step 22.

Balance-sheet assets use debit-minus-credit, including accumulated depreciation
as a negative asset. Liabilities use credit-minus-debit. Owner equity comes from
the linked equity statement. Show the signed accounting-equation residual and
refuse to call an inconsistent report reconciled. Do not add income again to a
capital figure that already contains closing transfers.

Make the initial capture contract ready for the explicit distinction between
ordinary and closing journals: capture immutable classification data, initially
all ordinary, and bind it into the report policy/digest. Step 22 must extend the
capture at its storage boundary; pure reports must never query a current close
table. Pre-close financial statements exclude closing transfers consistently
across all three statements. The separate post-close trial balance includes them.

Preserve historical snapshot formats when extending an existing capture. A new
financial capture type is preferable to silently changing delivered ledger or
subsidiary report shapes. The active catalog includes audited account extensions,
while a captured catalog keeps its original labels and account set.

## Task 1: captured statements and traceable localhost reports

**Files:** New focused financial report module/tests, workspace/HTTP/CLI/static
integration and a shared synthetic reference builder only if existing helpers
cannot supply the posted month. Do not redesign operational services.

- [ ] RED: independently asserted reference revenue2,700.00, expenses1,600.00,
  income1,100.00; opening capital0.00, contributions10,000.00, drawings200.00,
  ending equity10,900.00; assets11,500.00 and liabilities600.00; residual0.00.
- [ ] Use the verified Step 20 adjusted reference month. Operational fixture
  setup must obey active AP/AR/advance guards and approval paths; do not disable
  triggers or fabricate subsidiary effects to make report totals pass.
- [ ] Implement the three linked pure statements with account/journal/source
  drilldown and exact captured metadata. Test every reference account against
  independent expectations, not a second call to the same report calculation.
- [ ] Cover no activity, loss/negative balances, contra assets, linked reversal,
  inclusive cutoff, invalid/outside dates, newly enrolled accounts, very large
  cents and a later ledger mutation leaving old report bytes unchanged.
- [ ] Assert every drilldown adds to its line and each statement cross-links to
  the same snapshot/policy. No floats or browser reconstruction of cent totals.
- [ ] Add Reports navigation and a clear cutoff/statement/account drilldown view.
  Add `demo-statements` printing the reference values and common capture digest.
- [ ] Run focused report/HTTP tests, guarded full suite/foundation/all demos,
  JavaScript/diff checks and parent browser exercise. Freeze for independent
  review, commit/push and exact-SHA CI before Step 22 closing and date locks.

Tax statements, depreciation estimation, allowance estimation, comparative
periods and multi-currency consolidation remain explicit later policies.
