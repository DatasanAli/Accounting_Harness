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

## Source-registration fixture

[source-receipt.json](source-receipt.json) is an original fictional 125.00 USD receipt for Step 07. It uses a separate document identity and is not an extra posting in the reference month. The source demo and application tests register it in temporary SQLite storage. It contains no real business records.

## Offline tool-contract corpus

[agent-tool-cases.json](agent-tool-cases.json) contains 24 original synthetic scripts with explicit expected outcomes, proposed account/amount labels, findings and retained revision counts. Corpus v1 covers eight categories. `python3 -m accounting_harness demo-tools` runs them offline in isolated temporary databases. It verifies deterministic capabilities and denied calls, not model inference accuracy. Hostile text is intentional test data and grants no permissions.

## Provider-proposal corpus

[provider-proposal-cases.json](provider-proposal-cases.json) freezes 20 original
synthetic cases (`expense-cases-v1`): clean 8, ambiguity 2, missing facts 2,
conflicting facts 2, duplicates 2, unsupported 2, and hostile instructions 2.
Expected accounting labels are separate from handwritten synthetic response
decisions. Live evaluation ignores those synthetic responses and sends only
registered evidence, account results and prior-source-use context. Neither
labels nor category names are included in the prompt. Four clean cases are
repeated to report nondeterminism. Any regression gets a new corpus version;
these offline results do not establish live model accuracy.

## Fictional bank statement

[fictional-bank-january.csv](fictional-bank-january.csv) contains two original
fictional bank movements: a 200.00 deposit and a -150.00 payment. Supply statement
metadata separately: account `fictional-bank`, a statement ID, January 1–31 2026,
USD, opening balance `1000.00` and closing balance `1050.00`. Importing this fixture
creates bank records only; it does not create journals or alter the reference
month's books.

The exact ordered headers are:

```csv
bank_account_id,transaction_id,booking_date,amount,currency,reference,description
```

A positive amount increases bank cash; a minus decreases it. Amount strings have
exactly two decimal places, without a plus sign, whitespace or exponent notation.
Zero movement and negative zero are rejected. Opening/closing balances may be
zero or negative. All row dates must lie within the supplied January statement
range, and opening plus movements must equal closing exactly.

Limits are 8,192 UTF-8 bytes of CSV, 100 movement rows, 512 characters per field,
80 characters per identity, 22 characters per money string, and signed cent magnitude at most 2^63−1. Identities
cannot contain control characters or surrounding whitespace. The whole HTTP JSON
request remains limited to 16,384 bytes, including escaping and metadata; the
browser checks the serialized request size too. Quoted commas/newlines in CSV
fields use the standard CSV format. Reference and description may be empty.

Retry the same statement ID with the same metadata and exact CSV bytes to receive
its original import receipt. Reformatting quotes or line endings changes the
statement's source digest and conflicts under that ID. An unchanged canonical
bank transaction can appear in another overlapping statement; different bank
transaction IDs remain distinct even when their amounts and descriptions match.
