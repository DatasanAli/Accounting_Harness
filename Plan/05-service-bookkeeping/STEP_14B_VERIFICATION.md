# Step 14b verification: recorded vendor settlement

Observed on 2026-10-08 with synthetic January 2026 data. This workflow records
cash movement that already occurred; it does not send money or connect a bank.

## Behavior and boundaries

A posted bill and one outgoing settlement cash fact determine the exact
`bill-payment-v1` intent. The entire movement applies to one bill for the same
vendor and currency, on/after recognition and within the posting period. Human
approval binds the selected bill, evidence, amount, date and journal. Approval
does not reserve remaining balance; posting rechecks it inside the write
transaction. Two approved 200.00 payments against 300.00 can post only one.

Review schema 3 seals the new intent policy; payables schema 2 adds immutable
payment effects and extends the mandatory AP guard. Payment effect, journal,
approval posting and retry receipt commit together. The shared cash-event claim
prevents reuse across bill payments and cash templates. Original bill evidence
is reusable across valid payments. Managed bill/payment reversal remains refused
until linked subledger correction is supported.

## Browser demonstration

The localhost server reopened the populated Step 14a workspace, preserving its
300.00 software bill and an unrelated pending large-amount draft. Through the
forms, the operator registered a 100.00 recorded payment dated January 20 and
prepared settlement against B-14A-001. Before confirmation there was still one
journal, AP/outstanding 300.00 and expense 300.00. Review showed the bill, cash
fact, canonical intent and AP debit 100.00 / Cash credit 100.00.

After the separate confirmation checkbox and Approve & post action, there were
two journals: AP/outstanding 200.00, paid 100.00, expense unchanged at 300.00,
Cash credit 100.00 and unassigned residual 0.00. The vendor view retained the
February 9 due date and displayed the payment trace. At the actual 500px browser
viewport, that view had no horizontal page overflow.

## Automated evidence

- Guarded suite: **301 tests passed** in 14.869 seconds, including 14 new payment
  tests and 19 existing payable tests.
- All **16 demonstrations passed**, including `demo-bill-payment`.
- Foundation, JavaScript syntax and diff checks passed.
- Payment checks cover partial/full settlement, competing approvals, concurrent
  exact retries, restart, shared cash claims, stale/corrected intent, forged
  allocation/journal, overpayment, wrong vendor/date, immutable rows, migration
  rollback and faults at effect/journal/review/retry boundaries.
- HTTP checks cover trusted actor/policy derivation and separate confirmation.
  Server text retains 9007199254740993 cents exactly and a 0.01 remainder without
  JavaScript number rounding. Captured reports retain their original balances
  after subsequent settlement.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-bill-payment
node --check accounting_harness/static/app.js
```

Independent review approved spec compliance and code quality with no blocking findings. One minor maintenance observation remains: schema migrations transform known trigger SQL by string replacement; future edits should verify the expected fragments or install explicit versioned SQL. Shipped migration behavior and rollback passed. The payment report shape grows across releases; captured snapshots remain stable within the implemented report contract.

## Limits and rollback

Whole movements apply to one bill; split allocations, vendor credits, tax/FX and
managed corrections are outside this slice. The original local fictional
operator model remains; authenticated roles are a later delivery. Source text
does not grant permission. Live providers and external accounts remain deferred.

Preserve workspace databases together. Revert published software with a new
commit; never delete payment/journal history to undo an accounting transaction.

## Delivery evidence

Local verification is complete. Commit, remote SHA and exact-SHA Actions result
will be recorded after review and upload; no GitHub success is claimed yet.
