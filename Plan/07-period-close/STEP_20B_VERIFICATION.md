# Step 20b verification: evidenced unbilled expense accrual

Observed on2026-10-08 with a separate synthetic150.00 software expense.

## Browser demonstration

A fresh workspace initially had13 baseline accounts and zero journals. Opening
Expense accruals and registering the paired incurrence/basis facts did not activate
2050 or create a journal. The facts recorded service consumed on January28 and a
separate January31 assertion that the full150.00 was unbilled and unpaid.

Explicit preparation activated fixed2050 Accrued Expenses with a zero balance;
all13 earlier account balances remained identical and journal count stayed zero.
The review screen showed both facts, vendor/event, full amount, policy and exact
January31 journal: Software Expense5100 debit150.00 / Accrued Expenses2050 credit
150.00. Its checkbox was initially unchecked and posting unavailable.

After a separate checkbox and Approve & post action, the workspace had one journal,
Software Expense150.00 and Accrued Expenses150.00. Cash and Accounts Payable remained
zero. The outstanding-obligation report showed150.00, control150.00 and residual
0.00, with the original vendor name and source/approval/journal references. Its
stated unsupported settlement/conversion/correction scope was visible. The actual
500px viewport had no horizontal document overflow.

A fresh process running the frozen final implementation reopened the same
workspace. Full journal, trial-balance and expense-accrual report JSON matched
the pre-restart values exactly. The journal count remained one.

## Verification results

- Focused accrual tests: 20 passed, including workspace migration rollback.
- All 27 documented demonstrations passed against the final application code;
  the accrual demonstration refused a later bill for the same event and preserved
  its result after restart.
- Foundation, JavaScript syntax and diff whitespace checks passed.
- Independent review found a shared-schema initialization gap in Workspace. The
  fix uses the accrual service transaction before generic review handles. A new
  regression covers six real entry paths, exact rollback and successful recovery.
  Scoped re-review approved the fix with no new findings.
- A subsequent full run found one historical bank-fee test using the now-modern
  workspace as its legacy fixture. Its setup now constructs ledger4 directly;
  the literal version, schema SQL, all original rows and old retries stay checked.
  Its 50 targeted tests passed; scoped review approved with no new findings.
- Final guarded full suite: **528 tests passed in34.708 seconds**. This run follows
  both fixes. All27 demonstrations and the final browser restart passed against
  the same final application code.

The earlier 527-test pass and subsequent 528-test run with one fixture failure
remain part of the development record; neither is presented as the final result.
Delivered as [d3511be23bfcdea6fb23629e91bb0f0f592932ec](https://github.com/DatasanAli/Accounting_Harness/commit/d3511be23bfcdea6fb23629e91bb0f0f592932ec). Remote main matched exactly;
[CI37826947400 passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37826947400) for that SHA.

## Commands

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_expense_accrual.py -v
python3 -m accounting_harness demo-expense-accrual
node --check accounting_harness/static/app.js
```

## Scope and rollback

The fixed2050 liability is active, credit-normal and non-temporary. It is separate
from issued vendor bills/AP2000. This policy recognizes one full evidenced January
incurrence at cutoff; it does not estimate, settle, convert a later bill or
reverse automatically. Shared expense-recognition claims prevent recognizing the
same event again under cash, vendor bill or renamed accrual evidence.

No live connection or real-data policy choice is introduced. Preserve historical
ledger/evidence/approval/report bytes. Correct posted managed accruals only through
a separately defined linked policy; a software rollback is a new revert commit,
not deletion of accounting history.

## Storage compatibility

The concrete initialization migrates ledger4 to5, shared review9 to10 and adds
expense-accrual schema1. It retains original context, extension audit, approval
and retry bytes. Account2050 is activated only by an explicit successful
preparation; opening a workspace, reporting or registering source facts creates
no activation. A failed preparation also leaves no activation or operation claim.
