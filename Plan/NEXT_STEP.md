# Next: Step 02 — Money and chart of accounts

Status: ready. Step 01 created the foundation; no application behavior has been implemented.

## Copy this prompt

> Build Step 02: exact money handling and the service-business chart of accounts. Follow Plan/NEXT_STEP.md, test valid and invalid inputs, demonstrate the result, then commit and push to GitHub. Stop after this step.

## The small thing to build

Create a local Python package with an exact USD Money value and an account catalog. A CLI demonstration prints the fictional service-business accounts and proves that $0.10 plus $0.20 is exactly $0.30. This step establishes the types that journal validation will use in Step 03.

No journal posting, database, provider SDK, agent runtime, web UI, bank connection, or real financial data is required for this step.

## Proposed files

```text
accounting_harness/
  __init__.py
  __main__.py
  domain/
    __init__.py
    money.py
    accounts.py
tests/
  test_money.py
  test_accounts.py
scripts/
  run_tests.py
```

Use standard-library `dataclasses`, exact integers, and `unittest`; add no third-party runtime dependencies. Keep direct construction as strict as parsing, so callers cannot bypass validation. Import the fixture account list through a validated loader; the JSON fixture must not become an unchecked source of live accounts.

## Money contract

- Represent a nonnegative USD amount in integer cents. An entry's side will determine direction in Step 03.
- Parse unsigned strings with exactly two fractional digits, for example `"0.00"`, `"0.10"`, `"1200.00"`. Reject whitespace, signs, commas, exponent notation and extra precision.
- Reject float inputs, boolean-as-integer values, NaN/infinity, negative cents and unsupported currencies. Zero is valid Money; Step 03 will reject zero journal lines.
- Addition preserves currency and returns a validated Money value. Formatting always has two fractional digits.
- Signed balances/reports are a later ledger concern; do not implement a whole arithmetic library now.

## Account contract

- Each account has a stable nonblank code, nonblank name, one of five classifications (`asset`, `liability`, `equity`, `revenue`, `expense`), an explicit normal side (`debit` or `credit`), and a boolean active flag.
- The catalog belongs to a specific entity and currency. Reject duplicate codes and unknown/inactive account lookups for posting use; allow a separate listing operation to display inactive accounts.
- Normal balances are explicit metadata: accumulated depreciation is a credit-normal asset, and owner drawings are debit-normal equity. Drawings are not expenses. Never infer all normal sides solely from classification.
- Use the 13 fictional accounts in [the reference month](../data/fixtures/service-business-month.json), including two zero-balance asset accounts reserved for later depreciation examples.

## Acceptance criteria

| Check | Expected result |
| --- | --- |
| Parse `"1200.00"` | 120000 cents; renders `1200.00` |
| Add `"0.10"` and `"0.20"` | Exactly 30 cents; renders `0.30` |
| Parse `"0.00"` | Accepted Money value |
| Parse float `0.1`, boolean `true`, `"1.005"`, `"-1.00"`, `"NaN"`, `"1e2"`, or `" 1.00"` | Clear validation error; no silent conversion |
| Construct with invalid type or unsupported currency | Same validation boundary as parsing |
| Load fictional catalog | 13 unique accounts for the sample entity |
| Look up Cash / Accounts Payable | Debit-normal asset / credit-normal liability |
| Look up accumulated depreciation / owner drawings | Credit-normal asset / debit-normal equity |
| Duplicate code, blank name, invalid classification/side, nonboolean active flag | Clear validation error |
| Look up missing/inactive account for posting | Refused |
| Test runner finds no tests | Nonzero exit; cannot silently pass |

## Verify and upload

Keep `python3 scripts/verify_foundation.py` passing. Add `python3 scripts/run_tests.py` for discovered `unittest` application tests, with an explicit zero-tests guard. Add a runnable `python3 -m accounting_harness demo-accounts` command. These commands are proposed and must exist before they are advertised as working.

Run the tests and demonstration locally, update CI and the README to run the same checks, and record observed results. Update `Plan/roadmap.json` and `Plan/STATUS.md` to mark Step 02 complete and Step 03 ready. Replace this file and the root README's next prompt with the Step 03 journal-validation specification. Commit, push, verify the exact remote commit and CI run, then stop.

Source basis: Volume 1 §2.2 (classifications), §3.2 (chart of accounts), §3.5 (debits and credits), §11.3 (accumulated depreciation), §14.4 (equity forms). Integer cents and API validation are engineering decisions.
