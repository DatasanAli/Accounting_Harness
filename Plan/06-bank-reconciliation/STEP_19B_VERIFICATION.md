# Step 19b verification: reviewed imported bank fee

Observed on 2026-10-08 with synthetic January evidence and an imported bank row.

## Browser demonstration

A fresh workspace contained one separately approved service receipt journal:
Cash debit 1,000.00 and Service Revenue credit 1,000.00. The fixed fee account was
active. An imported statement had a negative 10.00 fee row dated January 31,
opening 1,000.00 and closing 990.00. No existing cash journal matched that amount.

The operator selected explicit Bank fee classification and supplied a reason.
Preparing the proposal showed the original imported row, derived typed evidence,
bound intent and exact 5300 debit 10.00/Cash credit 10.00 journal. There was still
one journal and Cash 1,000.00 before separate confirmation.

Selecting the review checkbox and Approve & post produced exactly one additional
journal: Cash 990.00, Bank Fees Expense 10.00 and unchanged Service Revenue 1,000.00.
The bank view explicitly displayed that fee posting and matching are separate.
Confirming the unique match then marked the bank row matched, with one matching
event and an identical ledger/trial-balance JSON result. No third journal appeared.
The actual 500px viewport had no horizontal page overflow.

Restarting the final application retained exactly two journals, Cash 990.00,
Expense 10.00 and byte-identical ledger/trial-balance and matching JSON results.

## Verification and delivery

The guarded suite passed **470 tests** in 28.940 seconds, including 16 new fee tests.
Foundation, all **24 demos**, JavaScript syntax and diff checks passed. The new
`demo-bank-fee` shows 1000.00→990.00 only after exact human approval, original evidence
and reason, restart/retry without duplicate fee, and separate explicit matching.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_bank_fees.py
python3 -m accounting_harness demo-bank-fee
node --check accounting_harness/static/app.js
```

Tests include imported identity/sign/digest, existing and late cash candidates,
concurrent exact retries, overlapping statement identities, rejected-draft revision,
shared cash claims, separate-file evidence enrollment recovery, final approval
supersession/shape/orphan effects, rollback/immutability and HTTP/restart boundaries.
Review schema 7→8 plus fee-schema initialization is atomic; the ledger remains
schema 4 and old contexts/approval/retry/report bytes remain unchanged.

Independent review approved spec compliance and quality with no new findings.
Exact commit/remote CI checks are pending; no delivery result is inferred locally.

## Limits and rollback

The complete reconciliation workflow follows in Step 19c; this fee posting alone
does not establish reconciliation completion. Source registration and ledger
enrollment use separate files with explicit recovery, not a cross-file transaction.
A managed fee reversal remains unavailable until linked bank-consumption/matching
corrections exist. Preserve immutable evidence, fee effect and journal history;
revert software through a new commit. No live connection or money transmission
occurred.
