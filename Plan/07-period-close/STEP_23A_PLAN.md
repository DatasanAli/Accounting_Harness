# Step 23a: captured direct cash-flow statement

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 22.

**Goal:** Reconcile reference operating cash -400.00, investing 0.00 and financing
9,800.00 to ending Cash 9,400.00 using existing posted journals.

**Architecture:** Extend the financial-report presentation with a pure direct
cash-flow function over an explicit immutable capture. Reuse the delivered
financial snapshot and closing classification; capture any extra operational
trace in the same read transaction. Do not query current stores while rendering.

**Spec:** [Step 23 contract](STEP_23_PLAN.md).

## Global constraints

- Exact signed integer cents and server-produced decimal strings; browser code
  does not calculate money with Number. Synthetic USD/January/zero opening ledger.
- Every row traces its journal, effective date, cash amount, counterpart accounts
  and sources; category totals plus unresolved cash equal the ledger cash change.
- No posting, reclassification of actual journals or description-based inference.
  Management policy is explicit and separately versioned from journal facts.
- Ordinary and linked reversal entries retain their cash effect. Closing entries
  are excluded from performance flows; a closing entry containing Cash is a
  blocking integrity finding rather than a hidden adjustment.
- Preserve old statement captures and policy/digests; use a new cash-flow report
  type or explicitly version an extended capture, including empty captures.

## Supported classification policy

Start with one nonzero Cash1000 line per journal and exactly one non-Cash
counterpart line. Classify that exact signed cash amount by explicit account
identity: Owner Capital3000 and Drawings3100 are financing; Equipment1500 is
investing; service revenue4000, prepaid insurance1200, supported expense accounts
5000/5100/5200/5300, receivables1100 and advances2100 are operating under this
bounded service-business policy. Positive and negative flows are retained, so a
linked reversal reverses the same category rather than being relabeled income.

For payable settlement, use the captured approved payment/bill trace to establish
its underlying supported expense classification. An untraced legacy AP movement
or a payable for an unsupported capital purchase must remain unresolved; do not
assume all liabilities imply operating cash. The delivered vendor-bill policies
currently support rent/software expense only. Capture that fact, not a future
live service lookup. No cash movement arises from invoice recognition, prepaid
consumption, accrual recognition or earned-advance release themselves.

Compound/multiple-cash-line journals, unknown counterpart codes, contradictory
operational evidence and unsupported transfers remain visible unresolved flows.
Do not silently net them, force a category or allocate cash across accrual lines.
Show the exact cash change for every unresolved journal, including a zero-net
unsupported multiple-Cash journal. The full cash bridge still reconciles, but
report status cannot say classification is complete while any exception exists.
A future explicit allocation policy may expand supported forms separately.

Reference receipts are collections1,500.00 plus advances600.00; operating payments
are rent1,200.00, software100.00 and prepaid insurance1,200.00. Thus net operating
cash is -400.00. Owner contributions10,000.00 less drawings200.00 produce financing
9,800.00. No investing cash occurs; opening0.00 plus9,400.00 equals closing9,400.00.
Use the delivered adjusted operational reference builder without bypassing guards.

For an earlier inclusive January cutoff, include only effective entries through
that date. A display period still starts January1; do not invent nonzero opening
balances or comparative periods. Read the captured ledger Cash directly for the
bridge, independently of the classification total, and show a signed residual.

## Task 1: traceable cash categories and complete cash bridge

**Files:** Focused financial/cash-flow module and tests, workspace/HTTP/CLI/static.
Parent owns docs/CI/browser/delivery. Inspect delivered Step21/22 interfaces first.

- [ ] RED: independent reference receipts/payments/category totals above, net
  change9,400.00, opening0.00/ending9,400.00, residual0.00; all trace rows sum.
- [ ] Cover no activity, loss without cash, invoice/accrual/earning noncash entries,
  bank fee, supported equipment cash acquisition, owner withdrawals/contributions,
  linked reversals, cutoffs and large exact amounts.
- [ ] Verify unsupported/compound/multiple-Cash/untraced payable cases remain
  visible and block complete classification even if unresolved signed amounts net
  to zero. Nothing creates a journal or changes prior classifications.
- [ ] Preserve old capture/report bytes after later posts, enrollment and close;
  fresh post-close cash flow agrees with ordinary pre-close cash flow.
- [ ] Add cash-flow view beside linked statements, explicit exceptions and source
  drilldown. Add `demo-cash-flow` with the reference bridge and snapshot identity.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; parent browser,
  independent review and exact commit/CI before the portable export slice.
