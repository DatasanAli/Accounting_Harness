# Step 20: evidenced month-end adjustments

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 19c, one independently delivered template at a time.

**Goal:** Add the reference insurance consumption of 100.00, reuse the supported
200.00 advance earning, and support separately evidenced unbilled expense/revenue
accruals without duplicate recognition.

**Architecture:** Concrete versioned adjustment policies use the existing evidence,
review, exact approval and atomic posting boundaries. Each adjustment is an
ordinary journal with immutable supporting effects. A month-end label alone does
not authorize recognition or bypass a managed control account.

## Global constraints

- Exact integer cents, synthetic USD/January scope, immutable journal/evidence
  history, source/actor/effective-date references and separate human confirmation.
- No live connection or real policy selection. No estimates inferred from a
  description. Explicit structured support controls each supported calculation.
- Shared economic-event claims survive rejection. Existing recorded recognition
  cannot be repeated under another template, source ID or month-end label.
- Existing AP 2000, AR 1100 and advance 2100 guards stay active. Unbilled accruals
  cannot masquerade as issued bills/invoices or unexplained subsidiary balances.
- Preserve old context, reports, approvals and exact retry behavior. Additive
  account/schema activation is audited and atomic; never rewrite the baseline.

## Independently verifiable slices

1. [20a prepaid insurance consumption](STEP_20A_PLAN.md): original posted asset,
   explicit coverage policy and one supported period allocation; 1,200.00 annual
   principal produces 100.00 January consumption and 1,100.00 remaining.
2. [20b accrued expense](STEP_20B_PLAN.md): a separately evidenced incurred, unbilled and unpaid
   expense credits a fixed Accrued Expenses liability, not AP. Plan its exact
   fact/intent/account activation contract before implementation.
3. 20c accrued revenue: separately evidenced completed, unbilled and uncollected
   service debits a fixed Accrued Service Revenue asset, not AR. Plan its exact
   fact/intent/account activation contract before implementation.

The latter two use the audited account-extension mechanism delivered in Step 19a
for concrete trusted definitions, not a general account editor. Their event
claims share expense_recognition/service_revenue_recognition with earlier
workflows. One whole supported amount accrues once; settlement, conversion into
a later bill/invoice, estimates and automatic reversing accruals require separate
policies and remain unavailable until explicitly implemented.

Reuse Step 16b for earned advances. A second month-end action against the same
completion must return its existing result or refuse the claimed event; do not
introduce another earning policy or table. Reference acceptance combines the
verified ordinary month, insurance 100.00 and advance earning 200.00. Additional
unbilled-accrual examples are separate fixtures and do not change those reference
month expectations. Step 21 consumes the resulting captured adjusted ledger.

Detailed task briefs must keep each slice independently testable and delivered
with the shared suite/demos, localhost demonstration, independent review, commit
and exact-SHA CI. Do not implement all three templates under a single opaque step.
