# Step 20b: separately evidenced unbilled expense accrual

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 20a.

**Goal:** Recognize a supported 150.00 incurred but unbilled/unpaid software expense
at January cutoff, with no cash movement or fabricated vendor bill.

**Spec:** [Step 20 adjustment contract](STEP_20_PLAN.md).

**Architecture:** One concrete accrual policy and immutable effect use existing
evidence, shared recognition claims and exact human approval. A fixed audited
liability account keeps unbilled accruals separate from the managed AP subledger.

## Global constraints

- All Step 20 constraints apply. The fictional reference month's original totals
  remain unchanged; this 150.00 example is a separate fixture.
- Use the delivered additive account-extension boundary for fixed account `2050`,
  `Accrued Expenses`, liability classification, credit normal, active and
  non-temporary. Preserve baseline context and existing account metadata. No
  caller-defined chart entries and no journal from account activation.
- Do not bypass AP 2000, AR 1100, advance 2100 or prepaid evidence guards. Incurrence
  already recognized by a cash or vendor-bill policy cannot accrue again.
- Integer cents only. Explicit source/intent identities, effective date, current
  approval, immutable effects and final seal; no live connection or estimates.

## Evidence and policy

Pair an existing strict `incurred_expense` fact with a new schema-v2
`expense_accrual_basis` source. In addition to the standard source fields, the
basis has exactly `event_id`, `counterparty_id`, `cutoff_date` and `status`, all
strings. The only supported status is `unbilled_unpaid`. This is an explicit
synthetic operator-provided fact, not an inference from an absent invoice file.
Descriptions remain inert and cannot grant approval.

The two documents must be distinct and agree on entity, currency, event,
counterparty and full amount. Incurrence date equals its document date and lies
within the configured January period on/before cutoff. Basis document date and
cutoff both equal the configured period end, January 31. Only the existing
incurred-expense accounts 5000/5100 are supported; the new policy does not silently
broaden the old receipt/model account choices. Reject missing support, conflicting
facts, future service, partial/split amounts and unsupported account selections.

`expense-accrual-v1` reconstructs exactly two lines at cutoff: the evidenced expense
account debit and 2050 credit, both the full supported amount. Its strict intent
binds schema/kind, entity-scoped event, vendor, currency, principal cents, expense
account, effective date and evidence roles (`incurrence`, `basis`). Derive one draft
identity from entity/event, independent of document IDs. Revised input creates a
new revision and requires fresh exact approval; it does not transfer an existing
event claim to another draft.

Share `expense_recognition` with cash and vendor bills using the incurrence fact.
The basis document is not an additional independent economic event. Rejection
retains the claim. Posting revalidates anchored evidence, independently rebuilt
intent/journal and current approval within the ledger write transaction.

## Durable effect and captured report

Add a concrete immutable accrual effect with event/vendor, original evidence,
principal, expense account, cutoff, exact approval and journal references. Its
posting link is deferred until the same transaction creates the journal and
posting event. Review link/retry/effect/journal commit together. Recheck latest
pending revision, digest and intent at final journal sealing, including an
intervening rejected or pending revision after effect insertion.

The new 2050 control activates with zero unexplained opening balance and then
requires the matching approved accrual effect. Direct admission, an older open
connection or another review policy cannot create an unassigned 2050 posting.
Protect effect/context rows and schema version against silent replacement, updates
and deletion. Account enrollment and schema initialization must fail atomically;
do not commit a partially upgraded shared review schema before an accrual failure.

Capture recognized obligations and ledger together. A pure versioned report shows
each vendor/event/evidence, principal, cutoff, approval/journal, total accruals,
2050 control and residual, plus snapshot/report digests. Retain original verified
source names, exact server decimal values and canonical trace text. Previously
captured reports remain unchanged after later activity.

This slice does not settle, reverse automatically, convert into a received bill or
estimate an accrual. Generic reversal of a managed accrual is refused until a
linked correction policy exists. Those limits stay visible in the UI. A later
bill carrying the same incurrence event must fail the existing shared claim;
do not hide duplicate expense by clearing an obligation outside a defined policy.

## Task 1: reviewed incurred expense at cutoff

**Files:** Focused accrual module/tests; concrete account extension and source/
review/approval/storage hooks; workspace/HTTP/CLI/static. Parent owns docs/CI/
browser/delivery. Inspect delivered Step 19a and 20a interfaces before coding.

- [ ] RED: separately evidenced 150.00 software incurrence on January 28 and an
  unbilled/unpaid January 31 basis produce a pending draft with no journal. Explicit
  confirmation yields Software Expense 150.00 and Accrued Expenses 150.00, Cash/AP
  unchanged, one immutable effect and zero control residual.
- [ ] Reject conflicting vendor/event/amount/date/status, unsupported accounts,
  copied evidence roles, missing anchors, forged intent/lines and superseded
  approvals. Test effect→revision change→seal with whole-unit rollback.
- [ ] Cover cash/bill/accrual claim collisions in both directions, including
  rejection, same event under new document IDs and exact concurrent retry.
- [ ] Verify audited fixed-account activation, old context/approvals/retry bytes,
  atomic account/shared-review/accrual migration failure, effect/journal/retry
  write faults, old-connection/direct guards and unsupported managed reversal.
- [ ] Check independently expected totals, cutoff and pure frozen report bytes,
  including large exact cent display. Do not relabel accruals as issued bills.
- [ ] Add native accrual fact/proposal and outstanding-accrual views with separate
  human review. Add `demo-expense-accrual`, with the 150.00 result and duplicate
  recognition refusal. Leave the reference month fixture unchanged.
- [ ] Run focused then guarded full checks/all demos/JS/diff; freeze for parent
  browser and independent review, commit/push/exact CI before Step 20c revenue.
