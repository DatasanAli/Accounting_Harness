# Step20c verification: evidenced unbilled service revenue

Observed on2026-10-08 with a separate synthetic250.00 completed service.

## Native browser demonstration

The fresh workspace had13 baseline accounts, zero journals and no1150 account.
Its empty combined accrual report already identified schema2; the old expense
report retained schema1. Native registration recorded a January28 service
completion and separate January31 unbilled/uncollected basis for the same customer,
event and full250.00. It added two sources, with no account activation or journal;
the entire trial balance stayed identical.

Explicit preparation activated fixed1150 Accrued Service Revenue at zero. All13
prior balances stayed identical and journal count remained zero. The review screen
showed both original facts, customer, event, policy and exact January31 entry:
1150 debit250.00 / Service Revenue4000 credit250.00. Confirmation was unchecked
and posting disabled until the separate human action.

After checkbox confirmation and Approve & post, one journal existed. Cash and
Accounts Receivable remained0.00; accrued service assets and Service Revenue were
250.00. The report showed supported principal250.00, control250.00, residual0.00,
original customer name and source/approval/journal trace. Unsupported collection,
invoice conversion, estimate and managed correction policies were visible. The
actual500px viewport had no horizontal document overflow.

A fresh process running the frozen final code reopened the revenue workspace.
Full journal, trial balance, expense, revenue and combined accrual report JSON
matched exactly, with one journal. A separate server then reopened the actual
prior20b workspace: its complete v1 expense report, journals and trial balance
matched the retained browser baseline byte-for-byte. The new combined report
identified v2 and its revenue component correctly remained0.00.

## Automated verification

- 38 focused expense/revenue accrual tests passed, including18 new revenue tests.
- Guarded full suite:546 tests passed in36.817 seconds.
- All28 demonstrations passed; foundation, JavaScript syntax and diff checks passed.
- Earlier expected current-version assertions and the legacy workspace fixture
  setup were updated without weakening historical bytes/rollback assertions.
- Independent review approved spec compliance and task quality; no Critical or
  Important findings. One Minor label issue is queued for final whole-work review:
  some shared revenue-validation refusals still say "expense accrual". The refusal
  remains effective; no accounting or historical-data issue was found.
- Exact commit/remote/CI checks follow local acceptance.

## Commands

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_revenue_accrual.py -v
python3 -m accounting_harness demo-revenue-accrual
node --check accounting_harness/static/app.js
```

## Scope

The strict policy recognizes one whole supported January service amount from
separate completion and cutoff facts. Shared cash/invoice/advance service claims
prevent double recognition. It creates no customer invoice or cash receipt.
Collection, invoice conversion, estimates and automatic reversal remain explicit
future policies. Posted managed accruals cannot be silently edited or deleted.

No live model, external accounting connection or real-data policy is introduced.
Original reference-month expectations and existing expense-accrual report formats
remain authoritative for their respective snapshots. Preserve history during a
software rollback; use a new revert commit rather than rewriting published work.
