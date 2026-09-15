# Step 03: journal validation and verification

Date: 2026-09-15. Implemented scope: pure proposal validation and a local `demo-journal` command. No balances, database, approval, posting, or agent calls are implemented.

## Reproduce

From the repository root, using Python 3.12+ and only its standard library:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-accounts
python3 -m accounting_harness demo-journal
```

## Observed local results

All 50 application tests passed on Python 3.13.1, including 20 new journal/CLI tests. The existing test runner's empty-discovery and failing-test guards remain tested. The foundation check and both CLI demonstrations passed. The journal output was:

```text
ACCEPTED: debits 1000.00 / credits 1000.00 USD
Difference: 0.00 USD
REJECTED: debits 1000.00 / credits 999.00 USD
Difference: 1.00 USD
  unbalanced at lines: total debits must equal total credits
Validation only; known source IDs do not establish correct accounting or approval.
```

Tests cover simple and compound entries, line-order independence, exact cents beyond float precision, both signs of imbalance, missing/malformed fields, unknown fields, dual debit/credit fields, zero/negative/float amounts, inactive/unknown accounts, entity/currency mismatches, calendar-date validation, absent/unknown sources, repeated validation, unchanged inputs, and immutable results. Later invalid lines remain rejected even after a balanced prefix; malformed amounts never yield misleading partial totals. Account/metadata findings can coexist with complete arithmetic totals.

A separate semantic example deliberately puts owner capital in Service Revenue: it passes arithmetic validation. This documents the validator's limit; recognition, classification, completeness, approval, idempotency and closed-period policy remain later work.

## API and input contract

```python
from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.journal import validate_journal
from accounting_harness.domain.money import Money

catalog = load_account_catalog('data/fixtures/service-business-month.json')
proposal = {
    'id': 'draft-1',
    'entity_id': catalog.entity_id,
    'currency': 'USD',
    'effective_date': '2026-01-01',
    'description': 'Synthetic owner contribution example',
    'source_ids': ['source-T01'],
    'lines': [
        {'account': '1000', 'side': 'debit', 'amount': Money(100000)},
        {'account': '3000', 'side': 'credit', 'amount': '1000.00'},
    ],
}
result = validate_journal(proposal, catalog, known_source_ids={'source-T01'})
assert result.accepted
assert result.total_debits == result.total_credits == Money(100000)
```

The validator accepts a dict and never mutates it, its nested values, the catalog or the known source set. Entries require exactly the documented fields. Lines require `account`, `side`, and `amount`, with optional `currency` defaulting to the entry currency. Amounts accept existing validated `Money` values or strings through `Money.parse`; there is no rounding or numeric coercion. Unknown fields, including separate debit/credit fields, are rejected. Sources/lines accept lists or tuples, and source IDs are checked against the caller's explicit set/frozenset. Caller context errors raise `TypeError`/`ValueError`; malformed proposals return findings.

Text identities and descriptions must be nonblank and unpadded. Effective dates accept a Python `date` (excluding `datetime`) or strict `YYYY-MM-DD` calendar strings. Compact dates, week dates, timestamps and impossible dates fail. Entry entity/currency must match the catalog; line currency and Money currency must match the entry. Account lookup uses `get_for_posting` without restricting an account to its normal side.

`ValidationResult` and `Finding` are frozen values. `accepted` is true exactly when `findings` is empty. Each finding has a stable `code`, a field/line `path` (zero-based indices), and a descriptive `message`. Consumers should branch on codes/paths, not message text.

| Code | Meaning |
| --- | --- |
| `entry_type`, `line_type`, `lines_type` | Unsupported object/container shape |
| `unknown_fields` | Extra entry or line fields; no silent dropping |
| `invalid_text`, `invalid_date` | Invalid required metadata |
| `entity_mismatch`, `currency_mismatch`, `unsupported_currency` | Scope/currency mismatch |
| `sources_required`, `invalid_source`, `unknown_source` | Missing, malformed or unrecognized source ID |
| `too_few_lines` | Fewer than two lines |
| `invalid_account`, `invalid_side` | Invalid/inactive/unknown account, or invalid debit/credit side |
| `invalid_amount`, `nonpositive_amount` | Malformed amount or zero line amount |
| `unbalanced` | Complete debit/credit totals differ |

`total_debits` and `total_credits` are exact Money values when every line's arithmetic is computable. Both are `None` for malformed lines, unknown line fields, invalid sides/amounts or incompatible currencies. Zero amounts remain computable but rejected. `difference_cents` is signed debits minus credits, or `None` when totals are unavailable. Totals alone never establish acceptance. No normalized entry is returned as a posting authorization token; later application boundaries must revalidate the actual proposal.

The demo reads known IDs from the existing synthetic fixture. Its $1,000 example is a validation illustration, not a claim that the fixture's $10,000 source document supports that amount. Source registration, evidence-content verification and interpretation remain later work. No fixture or source book was changed.

## Delivery and rollback

CI runs the foundation check, all application tests, and both demos. The completion response records the delivered commit SHA and the Actions run for that exact SHA after checking GitHub; this local record does not predeclare remote success. See the [verification workflow](https://github.com/DatasanAli/Accounting_Harness/actions/workflows/verify.yml).

Rollback uses a new revert commit. There is no persisted ledger or schema to migrate. Next: [Step 04 — ledger and trial balance](../NEXT_STEP.md). Stop after this delivery until the next user request.
