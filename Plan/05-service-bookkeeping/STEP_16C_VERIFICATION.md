# Step 16c verification: payable approval and balance seals

Observed on 2026-10-08 using synthetic bills and recorded payments.

## Reproduced boundary

Five regression cases failed against the delivered payables schema2 with all
actual guards enabled: bill and payment effects could be followed by a newer
rejected or pending revision before journal sealing, and two approved 200.00
payment effects could be inserted before either was sealed against a 300.00 bill.
The latter path bypassed the service-level precheck and committed excess use.
The tests exercise the real immutable row envelopes within one ledger transaction;
no guard is removed to manufacture the failure.

The requested fix installs explicit versioned trigger definitions for existing
workspaces, rechecks the current approved revision/intent at final sealing, and
checks total allocated principal including effects not yet sealed in the same
transaction. No accounting operation or UI permission is added.

A separate fault-injection regression also reproduced shared review initialization
committing before the AP upgrade: an AP2/review3 workspace was left at review7
when the AP version update failed. Payables initialization now owns one outer
transaction, using the delivered review/approval transaction-joining behavior.
No shared application module change was needed.

## Browser migration smoke

The preserved Step 14b browser workspace reopened successfully with payables3 and
review7. It retained two journals, the original vendor bill300.00, recorded
payment100.00 and outstanding/AP control200.00, with zero residual. Cash remained
credit100.00 and Software Expense debit300.00. Original bill/payment references
and the unrelated pending large draft remained visible. This read-only browser
exercise created no journal.

## Verification and delivery

The guarded suite passed **398 tests** in 20.758 seconds; **44 focused payable
tests** passed, including 11 new regressions. Foundation, all **20 demos** and
diff validation passed. Independent review approved spec compliance and task
quality with no findings. Delivered as [0cc3e5f](https://github.com/DatasanAli/Accounting_Harness/commit/0cc3e5f9fc4f66d0412d45d31f9559ba22e2cea6); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37809290761). The remote main SHA matched the local commit.
Required checks remain the guarded suite, foundation, all 20 existing demos and
diff validation. The bill 300.00/payment 100.00 demonstration must still leave 200.00
payable without another expense. No new UI or demonstration command is required.

Migration acceptance includes original history/context/approval/retry/report
preservation, pending old approvals, already-open connection enforcement, direct
seal denial, whole-unit rollback and atomic schema initialization. Independent review confirmed that the explicit
migration and passing regressions resolve both the prior unchecked SQL-fragment
replacement observation and the AP final-approval ordering gap.

## Limits and rollback

The existing local fictional operator and supported bill/payment policies remain.
No payment is sent and no external account/provider is connected. Preserve ledger
history and workspace databases; use a new revert commit for software rollback,
never deletion or silent editing of a posted bill/payment.
