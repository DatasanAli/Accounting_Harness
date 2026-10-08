# Step 19a verification: audited bank-fee account activation

Observed on 2026-10-08 using the preserved synthetic bank-matching workspace.

## Browser demonstration

The Bank statements view displayed a fixed activation action for 5300 Bank Fees
Expense. Confirming it displayed the immutable original actor/time/metadata audit.
The account is an active debit-normal temporary expense, ready for separately
reviewed fees. Activation created no financial journal or fee proposal.

All three preexisting journals remained identical. Every original account balance
was unchanged, and a new 5300 row showed debit 0.00/credit 0.00. The new report
snapshot identity changed to include the activated catalog. Saved historical
ledger/context/posting/retry/import/matching table rows were byte-identical before
and after activation. The actual 500px browser viewport had no horizontal overflow.

Restarting final code preserved the exact activation audit, three journals, all
13 original balances and match/unmatch/rematch history. The new captured catalog
contained 14 accounts and exactly one zero-balance 5300 row.

## Verification and delivery

The guarded suite passed **454 tests** in 27.326 seconds, including **14 focused
account-extension tests**. Foundation, all **23 demos**, JavaScript syntax and
diff checks passed. Initial broad checks caught an extra legacy unknown-account
finding; the policy guard was narrowed to activated extension codes, and the
final suite plus 24/24 tool cases passed with existing finding shapes preserved.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_account_extensions.py
python3 -m accounting_harness demo-bank-fee-account
node --check accounting_harness/static/app.js
```

The new demo shows 14 current accounts, the original 13-account context, unchanged
activation audit on restart/retry and zero added journals. Tests preserve pending
receipt/invoice/payment approvals, provider run scopes/checkpoints and old reports;
new AP/AR/advance captures include their effective catalog in report identities.

Independent review approved spec compliance and quality with one minor consistency
finding: direct Python validation accepts tuple-shaped lines while the new receipt
account restriction checks lists. Saving normalizes tuples and posting stays
protected. Track that validation consistency fix for the final whole-work review.
Delivered as [361459d](https://github.com/DatasanAli/Accounting_Harness/commit/361459d215050cc4bc05ebcb98180a83360d6258); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37815799255). Remote main matched the local commit.

## Scope and recovery

This is one fixed account activation, not an editable chart of accounts or a
posting authorization. Historical captured catalogs and baseline context remain
preserved. Reviewed fee posting follows in Step 19b.

A copy to a different workspace path failed the existing run-log path binding;
the browser check therefore used the original preserved workspace. This limitation
is recorded for Step 33 recovery and is not a successful restore claim. No provider
or bank connection was made. Preserve history when reverting software through a
new commit; do not delete the activated account or its audit.
