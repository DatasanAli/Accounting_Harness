# Step 04: ledger and trial-balance verification

Date: 2026-09-16. Scope: a single-threaded, in-memory ledger for synthetic proposals, immutable snapshots, and exact as-of-date trial balances. Persistence, authenticated approval, posting audit events and hosted deployment remain future work.

## Reproduce

From the repository root with Python 3.12+ and its standard library:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-accounts
python3 -m accounting_harness demo-journal
python3 -m accounting_harness demo-ledger
```

## Observed local results

All **68 application tests passed** on Python 3.13.1, including 17 ledger tests and one new CLI test. The foundation check and all three demonstrations passed. The ledger demo explicitly adapts only ordinary T01–T09; it prints entity, currency, period, cutoff, policy, included IDs and all 13 accounts.

| Account | Debit USD | Credit USD |
| --- | ---: | ---: |
| 1000 Cash | 9400.00 | 0.00 |
| 1100 Accounts Receivable | 1000.00 | 0.00 |
| 1200 Prepaid Insurance | 1200.00 | 0.00 |
| 1500 Equipment | 0.00 | 0.00 |
| 1590 Accumulated Depreciation | 0.00 | 0.00 |
| 2000 Accounts Payable | 0.00 | 200.00 |
| 2100 Unearned Service Revenue | 0.00 | 600.00 |
| 3000 Owner Capital | 0.00 | 10000.00 |
| 3100 Owner Drawings | 200.00 | 0.00 |
| 4000 Service Revenue | 0.00 | 2500.00 |
| 5000 Rent Expense | 1200.00 | 0.00 |
| 5100 Software Expense | 300.00 | 0.00 |
| 5200 Insurance Expense | 0.00 | 0.00 |
| **Total** | **13300.00** | **13300.00** |

Each row is compared against the original fixture's independent unadjusted expectations; the fixture was not changed. Cutoff tests show Cash 7600.00 / Receivables 2500.00 on January 14 and Cash 9100.00 / Receivables 1000.00 on January 15, when collection T05 becomes included. Invalid/duplicate/out-of-period entries preserve the exact prior snapshot and report. Changed proposals cannot reuse an earlier validation result to bypass admission checks.

Additional coverage: zero activity, empty catalogs, inactive accounts, equal amounts with distinct IDs, source-set isolation, nested caller mutation, immutable results, old-snapshot report reproduction after later admission, invalid date/timestamp inputs, boundary dates, compound entries/repeated accounts, cents beyond float precision, out-of-order admissions, and credit/cleared Cash balances. Existing money, catalog, journal and test-runner guard tests remain passing.

## API

```python
from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.ledger import InMemoryLedger, trial_balance

catalog = load_account_catalog('data/fixtures/service-business-month.json')
ledger = InMemoryLedger(catalog, '2026-01-01', '2026-01-31',
                        known_source_ids={'source-T01'})
entry = ledger.admit({
    'id': 'example-1', 'entity_id': catalog.entity_id, 'currency': 'USD',
    'effective_date': '2026-01-01', 'description': 'Synthetic contribution',
    'source_ids': ['source-T01'],
    'lines': [
        {'account': '1000', 'side': 'debit', 'amount': '1000.00'},
        {'account': '3000', 'side': 'credit', 'amount': '1000.00'},
    ],
})
report = ledger.trial_balance('2026-01-31')
assert str(report.total_debits) == str(report.total_credits) == '1000.00'
assert trial_balance(report.snapshot, report.as_of) == report
```

`admit` privately copies and revalidates each draft using Step 03's validator, then checks entry-ID uniqueness and the inclusive ledger period. It constructs frozen entry/line records and replaces the snapshot only after all checks succeed. Sources and lines become tuples; amounts become validated Money values. There is no batch API. Rejections raise `EntryRejected` with structured `.findings`: existing journal codes plus `duplicate_entry_id` and `date_out_of_range`. Invalid ledger context/report dates raise `TypeError` or `ValueError`.

`ledger.snapshot` is a read-only property returning a frozen `LedgerSnapshot` with catalog, period and retained entry records. Keep that object to reproduce reports after new admissions. `trial_balance(snapshot, as_of)` derives all balances from those records; no independent balance cache is maintained. Shared `accounting_date` parsing preserves the journal's strict date rules and excludes timestamps.

Reports retain the full snapshot, inclusive cutoff, sorted included IDs (effective date then ID), all catalog rows in code order, entity/currency and policy `unadjusted-zero-opening-v1`. This policy starts every account at zero at the period start and assumes the caller supplied ordinary entries. The fixture adapter selects ordinary entries explicitly; the general ledger does not infer accounting meaning from descriptions. Debit/credit display follows actual net signs, including opposite-normal balances; zero shows in both columns. Integer cents supply all arithmetic.

These record dataclasses are output containers for ledger-produced snapshots, not alternate validated admission APIs. Private Python fields and data constructors are not an authorization system. This prototype is single-threaded, has no durable history, and loses data on process exit. Known source IDs and balanced arithmetic do not establish correct classification or evidence content. Actor/audit and approval controls will accompany their planned later steps before operational use.

## Delivery and rollback

Delivery currently means committing to the configured GitHub repository and verifying its Actions workflow; there is no hosted runtime configured. CI runs the foundation check, all application tests, and all three demos. The completion response supplies the exact pushed commit and its checked CI run; this local record does not predeclare remote success. See the [verification workflow](https://github.com/DatasanAli/Accounting_Harness/actions/workflows/verify.yml).

Undo published code with a new revert commit. No database or migration exists yet, and the demonstration only holds synthetic records in memory. Next: [Step 05 — atomic persistence and retry](../NEXT_STEP.md). Stop after delivering Step 04 until requested to continue.
