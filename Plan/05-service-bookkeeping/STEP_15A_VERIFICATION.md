# Step 15a verification: customer invoice recognition

Observed on 2026-10-08 with synthetic January 2026 data. Collection and aging
follow in the separate Step 15b delivery; live connections remain deferred.

## Accounting behavior

A typed customer invoice and separate service-completion fact must agree on
customer, event, currency, full value and recognition date. The invoice alone
cannot establish earning. `invoice-v1` binds the exact receivable identity,
principal, due date, accounts and evidence into the human-approved revision.
Shared service-event claims prevent recognition through both invoice and earned
cash workflows. Registration/proposal create no invoice effect or journal.

Accounts Receivable activates only with zero unexplained opening balance. The
immutable invoice effect, journal, review posting and retry receipt commit in one
transaction. Mandatory AR guards require a matching approved effect, including
older connection and direct admission paths. Existing AP/payment guards remain
independent. Managed invoice reversal is refused until linked customer correction
effects exist.

Captured reports retain ledger context, invoice details, original verified customer
names, cutoff, journal references, policy and digests. AR debit-minus-credit
control reconciles to customer outstanding, with an explicit signed residual.
Current registry changes cannot rewrite captured names or balances.

## Browser demonstration

Through a fresh localhost workspace, the operator registered I-15A-001 for
2500.00 and separate design-service completion dated January 10, due January 25.
Preparing the draft left zero journals and zero customer items. Review showed both
facts, exact intent, AR debit 2500.00 and Service Revenue credit 2500.00.

After the separate confirmation checkbox and Approve & post action, the customer
view showed one journal, original customer name, principal/outstanding 2500.00,
paid 0.00, AR control 2500.00 and residual 0.00. Revenue was 2500.00; Cash and AP
remained zero. The actual 500px viewport had no horizontal page overflow.
A copied payable/vendor heading found during the walkthrough was corrected to
the shared operation/parties wording. Restarting with the final implementation preserved the same journal, original customer name and exact reconciled balance. A separate pending invoice for 90071992547409.93 rendered the exact amount and 9007199254740993-cent intent; the rounded 9007199254740992 value was absent. It remained unposted and did not change the 2500.00 ledger.

## Verification

The guarded suite passed **327 tests** in 16.440 seconds, including 26 invoice tests. All **17 demonstrations**, foundation, JavaScript syntax and diff checks passed. Existing 19 payable and 14 payment tests also passed. Review found a stale-approval ordering gap at the final SQL journal seal. The fix now rechecks current revision, approval digest and bound intent at sealing; a regression for both rejection and pending supersession proves full rollback. All **27 focused invoice tests** and `demo-invoice` passed after this isolated fix. Final scoped review approved spec compliance and code quality with no remaining findings. The final suite contains 328 tests; the 327-test broad run precedes this one added regression. A fresh final browser workspace repeated registration, exact review and explicit posting after the fix: one journal, AR/outstanding 2500.00 and residual 0.00. Commands include:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-invoice
node --check accounting_harness/static/app.js
```

All prior documented demonstrations remain required alongside the new invoice
demo. Observed test coverage includes invalid/forged facts and intents, shared claims,
legacy migration/approval bytes, atomic write faults, control bypasses, concurrent
exact retry, restart, original-name capture, frozen reports and exact browser
amount serialization.

## Limits and rollback

Whole-principal, immediately completed service invoices are supported. Tax/FX,
credit notes, split recognition and managed invoice corrections remain outside
this slice. Authenticated roles are a later step; the current operator is the
existing fictional local human. Provider runs retain their bounded expense scope.

Preserve workspace databases together. Revert published software with a new
commit; never delete an invoice or journal to undo an accounting transaction.

## Delivery evidence

Delivered as [0176f99](https://github.com/DatasanAli/Accounting_Harness/commit/0176f99c6bce416f2f38ab83c00221e8a1e9af09). Local HEAD and remote main matched. [GitHub Actions run 37800424176](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37800424176) completed successfully for this exact SHA, running the final 328-test suite and all 17 demos.
