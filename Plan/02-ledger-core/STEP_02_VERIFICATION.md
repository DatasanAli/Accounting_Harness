# Step 02: verification and usage

Date: 2026-09-10. Implemented scope: exact USD Money, validated account/catalog types, a JSON catalog loader, and a local demonstration. No journal validation or posting, persistence, provider, or bank integration is implemented.

## Reproduce

From the repository root with Python 3.12+:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-accounts
```

The implementation uses only Python's standard library. These same commands run in GitHub Actions. The fixture and application require no PDFs, API keys, external network calls, or package installation.

## Observed local results

The application suite passed all 30 tests on Python 3.13.1. Subtests cover multiple values within each input-validation test. The CLI displayed all 13 expected accounts and these results:

```text
13 validated accounts.
Exact addition: 0.10 + 0.20 = 0.30 USD (30 cents)
Rejected excess precision '1.005': amount must be unsigned with exactly two decimal places
```

| Boundary | Verified result |
| --- | --- |
| Money parsing and formatting | Exact cents, zero, carry to next dollar, normalized leading zeros, amounts beyond binary floating-point integer precision |
| Money rejection | Floats, booleans, decimal objects, negative values, non-finite values, signs, exponent notation, whitespace, commas and excess fractional precision rejected |
| Direct construction | Cents must be a nonnegative integer; currency must be USD; frozen fields prevent ordinary mutation |
| Chart of accounts | All 13 account codes, names, classifications, normal sides and temporary flags match independent expected metadata |
| Catalog boundaries | Nonblank entity; USD; duplicate codes rejected; input list snapshotted; accounts immutable; codes local to the catalog |
| Inactive accounts | Included in listing; refused by `get_for_posting` |
| JSON loader | Required fields, field types, unknown account fields, duplicate JSON keys and duplicate account codes checked |
| CLI | Expected catalog/arithmetic/error example displayed; unsupported command exits nonzero |
| Test runner | Empty discovery exits 1; intentional failing test exits 1; passing test imports the package from a different working directory |

The foundation verification is retained independently of the application tests. The pre-existing fixture amounts and textbook source files were not changed.

## Domain API examples

```python
from accounting_harness.domain.money import Money
from accounting_harness.domain.accounts import load_account_catalog

fee = Money.parse("1200.00")
print(fee.cents)  # 120000
print(Money(10) + Money(20))  # 0.30

catalog = load_account_catalog("data/fixtures/service-business-month.json")
cash = catalog.get_for_posting("1000")
print(cash.classification, cash.normal_side)  # asset debit
```

`Money.parse` accepts unsigned strings with exactly two fractional digits. `Money(cents, currency="USD")` validates integer cents directly. Wrong input types raise `TypeError`; unsupported values/formats raise `ValueError`. Addition accepts another Money value; it performs no float conversion. Signed balances and additional currencies remain outside this step.

`Account` requires code, name, classification and normal side; `active=True` and `temporary=False` are constructor defaults. JSON requires an explicit active flag and preserves the fixture's temporary flag when provided. Codes/names/entity IDs cannot be blank or padded with surrounding whitespace. Account classification and normal side are separate fields; the loader never infers a normal balance from classification alone.

`AccountCatalog(entity_id, currency, accounts)` accepts a list or tuple of validated accounts and stores a tuple snapshot. Empty catalogs are valid. `list_accounts()` returns all accounts sorted by code, including inactive ones. `get_for_posting(code)` resolves only a known active account; it does not post anything. Catalog scope is domain organization, not a production authorization system.

`load_account_catalog(path)` validates the JSON entity/accounts portion and ignores the reference fixture's other top-level data. It does not validate journals or evidence; those belong to later steps.

## Delivery and rollback

The completion response identifies the exact commit and its successful [GitHub Actions run](https://github.com/DatasanAli/Accounting_Harness/actions/workflows/verify.yml). Use a new revert commit to undo Step 02; there is no persisted ledger or migration to roll back. Keep Step 01's original fixture and source references intact.

Next: [Step 03 — journal validation](../NEXT_STEP.md). Stop after delivering Step 02 until the user requests it.
