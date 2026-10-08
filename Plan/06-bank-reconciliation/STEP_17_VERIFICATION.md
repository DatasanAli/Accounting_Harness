# Step 17 verification: immutable synthetic bank import

Observed on 2026-10-08 with original fictional January 2026 CSV data.

## Behavior and format

Bank statements, stable bank transaction identities, original row order and import
receipts are stored separately from journals in the ledger database. Import does
not enroll evidence, create a draft, approve or post. The first successful import
fixes one synthetic bank account's mapping to Cash 1000.

Signed amounts are strict two-decimal strings, calculated as integer cents. The
statement must satisfy opening plus movements equals closing. Exact same
statement identity/metadata/CSV bytes returns the original receipt. Changed source
bytes under that identity conflict. Overlapping statements can reference an
unchanged canonical bank transaction; equal amounts under distinct transaction
IDs remain distinct.

The [fictional CSV format and limits](../../data/fixtures/README.md#fictional-bank-statement)
include 8,192 CSV UTF-8 bytes, 100 rows, 512 characters per field, 80 per identity,
22 per money string, signed cent magnitude at most 2^63−1, and the existing
16,384-byte complete HTTP JSON request bound. File loading validates UTF-8 and
preserves original CRLF bytes separately from textarea normalization. The browser
checks the serialized request size including JSON escaping.

## Browser demonstration

A fresh local workspace imported the prefilled fictional January statement:

| Bank value | USD |
| --- | ---: |
| Opening balance | 1,000.00 |
| deposit-1, January 5 | +200.00 |
| payment-1, January 6 | -150.00 |
| Closing balance | 1,050.00 |

One statement and two rows were displayed in original order, with the import
actor, timestamp, content/source digests and receipt identity. Repeating the same
native import action returned an identical listing and full detail/audit record.
There were still zero journals, Cash 0.00 and the original five evidence records.

Changing closing balance to 1050.01 produced the exact signed residual -0.01 and
left the imported listing unchanged. The actual 500px viewport had no horizontal
page overflow. Restarting the final application retained an identical full
statement/detail/audit record, two rows and zero journals. No blocking browser
finding was observed.

## Verification and delivery

The guarded suite passed **420 tests** in 23.940 seconds, including 22 focused bank
checks. Foundation, all **21 demos**, JavaScript syntax and diff checks passed.
Independent review approved spec compliance and task quality with no findings.
Commit, remote comparison and exact-SHA GitHub CI are pending.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-bank-import
node --check accounting_harness/static/app.js
```

## Limits and rollback

Only the documented synthetic format, January 2026/USD and one fixed bank/Cash
mapping are supported. Bank import is not matching or reconciliation; it does not
assert that imported bank cash equals the ledger. Those workflows follow in
Steps 18–19. No live bank, accounting-system or model connection was made.

Preserve the complete workspace and immutable import history. Revert software
through a new commit; do not delete bank/ledger records to disguise a correction.
