# Step 20c: separately evidenced unbilled service revenue

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 20b.

**Goal:** Recognize 250.00 of completed, unbilled and uncollected service at
January cutoff, with no cash receipt or fabricated customer invoice.

**Spec:** [Step 20 adjustment contract](STEP_20_PLAN.md).

**Architecture:** Extend the concrete accrual boundary from Step 20b with a
distinct revenue policy and effect. Reuse shared validation only where the two
implemented accrual policies require identical behavior; no generic workflow
engine or speculative settlement/estimate support.

## Global constraints

- Exact cents, existing fictional USD/January entity and separate human approval.
  The 250.00 accrual example is separate from the original reference month.
- Audited fixed account `1150`, `Accrued Service Revenue`, asset classification,
  debit normal, active and non-temporary. Use the delivered account-extension
  boundary, preserving frozen baseline context and all historical account data.
- Existing AR 1100, AP 2000, advance 2100 and expense-accrual 2050 controls remain
  enforced. An unbilled right to consideration is not an issued invoice.
- Share the existing `service_revenue_recognition` event claim with cash,
  invoices and advance earning, including claims retained after rejection.
- No live connection, automatic approval, unsupported estimate, tax or FX policy.

## Evidence, approval and effects

Pair an existing strict `service_completion` document with a distinct new
schema-v2 `revenue_accrual_basis` source. Besides standard source fields, the
basis has exactly four additional strings: `event_id`, `counterparty_id`,
`cutoff_date`, `status`. Status is exactly `unbilled_uncollected`. This is an
explicit synthetic operator-provided fact; absent files alone do not prove it.

Both sources agree on entity, customer, service event, currency and full amount.
Completion date equals its document date and lies within January on/before
cutoff. Basis date and cutoff equal the configured January 31 period end. Reject
conflicting facts, uncompleted/future service, copied roles, partial amounts and
unsupported currencies. Descriptions remain data and cannot alter this policy.

`revenue-accrual-v1` independently rebuilds the exact cutoff journal: 1150 debit
and Service Revenue 4000 credit for the full supported amount. Strict intent binds
schema/kind, customer/event, currency, principal cents, cutoff and evidence roles
(`completion`, `basis`). Derive one draft from entity/event independent of source
IDs; changed input requires a new revision and fresh exact approval. A second
policy cannot evade the original shared service claim by using a new document.

Persist an immutable effect linking customer/event/evidence, principal/cutoff,
exact approval and deferred posting reference. The effect, journal, review link
and retry commit atomically. Reconstruct and revalidate before approval/posting;
the final seal checks the latest pending revision, approval digest, exact intent,
line/date/source shape and journal identity after effect insertion.

Account 1150 activates with zero unexplained balance, then every 1150 movement
requires its matching approved effect. Preserve old-connection/direct-admission
guards. Atomically migrate any shared review, account and accrual schema changes;
failure restores prior schema definitions and historical rows. No silent repair
or rewriting of prior expense accruals is permitted.

A pure captured report distinguishes expense obligations from accrued service
assets, retains original verified party names and source/approval/journal trace,
and reconciles each category to its own control account. Extend the report format
explicitly without rewriting older captured report shape/digests. New captures
identify the report version even when they contain no revenue accruals.

This delivery does not collect, convert to an issued invoice, reverse automatically
or estimate revenue. Generic reversal of a managed accrual stays unavailable
until a linked correction policy exists. A later invoice/completion using the
same service event must fail the shared claim rather than duplicate revenue.

## Task 1: supported completed service at cutoff

**Files:** Existing accrual module and focused tests; concrete account/source/
review/approval hooks; workspace/HTTP/CLI/static. Parent owns documentation, CI,
browser and delivery. Inspect the final delivered 20b interfaces before coding.

- [ ] RED: completion 250.00 on January 28 plus an unbilled/uncollected January 31
  basis prepares a draft with no journal. Exact human confirmation posts 1150
  debit 250.00 / Service Revenue credit 250.00; Cash/AR unchanged, residual 0.00.
- [ ] Refuse conflicting event/customer/amount/date/status, absent completion,
  wrong accounts, unanchored sources, forged intent/lines and stale approvals.
  Exercise rejected/new-pending revision between effect and final sealing.
- [ ] Test cash/invoice/advance/accrual service-claim collisions in both directions,
  including rejection, new document IDs and exact concurrent retry/restart.
- [ ] Verify fixed-account activation and explicit schema migration preserve
  original context, expense-accrual/history/approvals/retries and old reports.
  Cover migration/write faults, direct guards and managed reversal refusal.
- [ ] Capture independent expected balances, cutoff and unchanged prior report
  bytes after later activity; retain exact large-value server/browser strings.
- [ ] Add native fact/proposal and accrued-revenue view with the existing separate
  confirmation. Add `demo-revenue-accrual` for the 250.00 result and duplicate
  recognition refusal. Do not alter original reference-month expectations.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff and parent
  browser exercise; freeze for independent review, commit/push/exact CI.

Before Step21, deliver the separate [Step20d operational fixture](STEP_20D_PLAN.md).
The original T03 Jan3 purchase conflicts with the delivered Jan1 coverage-start
policy, so that new fixture explicitly uses a Jan1 purchase and distinct identity;
original fixture bytes and all month-end expected amounts remain unchanged.
