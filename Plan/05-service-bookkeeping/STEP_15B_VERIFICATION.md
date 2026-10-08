# Step 15b verification: recorded collection and aging

Observed on 2026-10-08 with synthetic January 2026 data. This records a receipt
that already occurred; it does not move money or contact a customer.

## Behavior

One incoming settlement cash fact allocates its entire amount to one posted
invoice for the same customer/currency. Receipt date cannot precede recognition.
The exact `invoice-collection-v1` intent binds the target, receipt event, amount,
date and evidence into the human-approved revision. Collection debits Cash and
credits Accounts Receivable, with no second revenue recognition.

Posting rechecks unpaid principal and shared cash-event ownership inside the
write transaction. Approval reserves no balance. Immutable collection effects,
journals, review posting and retry receipts commit together. AR sealing rechecks
the current approval/revision and intent after effect insertion. Prior invoice
and AP/payment workflows remain supported; managed collection reversals require
a future linked correction workflow and are currently refused.

Captured reports filter invoices/collections by cutoff, retain original customer
names and trace identities, and reconcile customer outstanding to AR. Aging uses
due dates: current/due today, 1–30, 31–60, 61–90 and 91+ days. Customer and total
buckets sum to outstanding; later receipts cannot change a captured earlier report.

## Browser result

The server reopened the final Step 15a workspace containing I-15A-001: 2500.00,
recognized January 10, due January 25. Through the forms, the operator registered
a 1500.00 recorded incoming receipt dated January 20 and selected that invoice.
Review showed invoice and cash evidence, exact intent, Cash debit 1500.00 and AR
credit 1500.00. Before confirmation, one journal and AR 2500.00 remained.

After the separate checkbox and Approve & post action:

| Result | USD |
| --- | ---: |
| Cash debit | 1500.00 |
| AR/customer outstanding | 1000.00 |
| Invoice paid | 1500.00 |
| Revenue credit, unchanged | 2500.00 |
| Unassigned AR residual | 0.00 |

There were two journals. At January 31, the invoice was six days past due:
1000.00 appeared in the 1–30 day bucket and all other buckets were zero. The
customer name, original principal, due date and collection trace remained visible.
The actual 500px browser viewport had no horizontal page overflow. No browser
fixes were required in this walkthrough.

## Verification and delivery

The guarded suite passed **345 tests** in 17.856 seconds; all **18 demos**, foundation, JavaScript syntax and diff checks passed. There are 17 new collection tests; the focused invoice/collection/AP/payment run passed 77 tests. After a demo-only wording/date correction, its affected CLI test and demo passed again. Independent review approved spec compliance and code quality with no findings. Commands include:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-collection
node --check accounting_harness/static/app.js
```

All earlier demos remain required. Checks cover competing approvals, exact retries,
over-collection, reused cash, wrong target/customer/date, forged split allocation,
stale approval at final seal, migration/write rollback, cutoff aging, original
invoice history, server-derived HTTP fields and exact large-cent display.

Delivered as [f29ac94](https://github.com/DatasanAli/Accounting_Harness/commit/f29ac946ae743c630100feae42ebc1d3c458136a). Local HEAD and remote main matched. [GitHub Actions run 37802605944](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37802605944) completed successfully for that exact SHA, including the full suite and all 18 demos.

## Limits and rollback

Only whole cash movements allocated to one invoice are supported. Split receipts,
credit notes, refunds, tax/FX and operational reversal effects remain outside this
slice. January's bounded dates can leave older aging buckets empty. The existing
fictional local operator is not production authentication. Live connections stay
deferred and provider proposals retain their bounded expense scope.

Preserve workspace databases together. Revert published software with a new
commit; do not delete invoice/collection/journal history as an accounting correction.
