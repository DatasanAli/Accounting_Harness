# Original bookkeeping reference month

[service-business-month.json](service-business-month.json) is fictional acceptance data for one USD service business. It is not a copy of a textbook exercise and is not an implemented ledger.

January 2026 begins with zero balances. The sample uses accrual bookkeeping, owner capital/drawings, and a stated full-month insurance allocation. It has 13 accounts: 11 used during the month and two zero-balance asset accounts reserved for later equipment/depreciation work.

## Events and accounting expectations

| ID | Event | Debit | Credit |
| --- | --- | --- | --- |
| T01 | Owner funds business | Cash 10,000.00 | Owner Capital 10,000.00 |
| T02 | January rent paid and incurred | Rent Expense 1,200.00 | Cash 1,200.00 |
| T03 | Pay 12 months' insurance starting January | Prepaid Insurance 1,200.00 | Cash 1,200.00 |
| T04 | Invoice for completed services | Accounts Receivable 2,500.00 | Service Revenue 2,500.00 |
| T05 | Partial receipt against T04 | Cash 1,500.00 | Accounts Receivable 1,500.00 |
| T06 | Bill for January software consumed | Software Expense 300.00 | Accounts Payable 300.00 |
| T07 | Partial recorded payment against T06 | Accounts Payable 100.00 | Cash 100.00 |
| T08 | Customer pays before service | Cash 600.00 | Unearned Service Revenue 600.00 |
| T09 | Owner withdraws funds | Owner Drawings 200.00 | Cash 200.00 |
| A01 | One month of insurance consumed | Insurance Expense 100.00 | Prepaid Insurance 100.00 |
| A02 | Deliver 200.00 of prepaid service | Unearned Service Revenue 200.00 | Service Revenue 200.00 |

T01–T09 form the unadjusted stage. A01–A02 form the adjustment stage. Workflow operations introduced earlier may already post an equivalent recognition event; the eventual application must not apply that event again during close.

## Independent expected results

- Cash: 10,000 − 1,200 − 1,200 + 1,500 − 100 + 600 − 200 = **9,400.00**.
- Receivables: 2,500 − 1,500 = **1,000.00**; prepaid insurance: 1,200 − 100 = **1,100.00**.
- Payables: 300 − 100 = **200.00**; unearned revenue: 600 − 200 = **400.00**.
- Revenue: 2,500 + 200 = **2,700.00**. Expenses: 1,200 + 300 + 100 = **1,600.00**. Net income: **1,100.00**.
- Ending equity: 0 + 10,000 + 1,100 − 200 = **10,900.00**.
- Assets: 9,400 + 1,000 + 1,100 = **11,500.00** = liabilities **600.00** + equity **10,900.00**.
- Operating cash flow: 1,500 + 600 − 1,200 − 1,200 − 100 = **−400.00**. Investing: **0.00**. Financing: 10,000 − 200 = **9,800.00**. Ending cash: **9,400.00**.
- Unadjusted and adjusted trial balances each total **13,300.00** on both sides. Closing revenue, expenses and drawings directly to owner capital produces **11,500.00** on each side of the post-close trial balance.

The three closing entries are original examples using direct closure to owner capital. They preserve permanent asset/liability balances and zero the temporary accounts. This is an explicit sample policy; the corporate income-summary/retained-earnings examples in the book use different equity accounts.

## Verification limits

Run `python3 scripts/verify_foundation.py` from the repository root. The checker recomputes these identities using exact cents and compares the full expected account balances at each checkpoint. It also verifies fixture references and local plan links. It does not demonstrate persistent posting, human approval, agent accuracy, report cutoff logic or real-world accounting correctness; those receive application tests in their numbered steps.
