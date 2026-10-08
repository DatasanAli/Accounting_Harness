# Step 19c verification: captured reconciliation and human completion

Observed on 2026-10-08 with synthetic January records.

## Behavior and browser demonstration

The browser fixture had four separately reviewed journals: owner funding 950.00,
service deposit 200.00, expense payment 150.00 and bank fee 10.00. Its statement opened
at 0.00, included funding 950.00 and fee-10.00, and closed at 940.00. Funding and fee
were explicitly matched. This accounts for the starting funds without inventing
an opening balance or omitting a book movement.

The operator supplied reasons for the outstanding 150.00 payment and 200.00 deposit
in transit. The UI then showed book 1,000.00 less reviewed fee 10.00 =990.00 and bank
940.00 +200.00 -150.00 =990.00. Timing classifications and explicit completion
created no journals. Source, fee approval, match and timing references remained
inspectable, and the book starting amount was labeled as a derived bridge.

After the first completion, the operator deliberately unmatched the fee. The
numeric difference remained 0.00, but the unmatched bank exception blocked another
completion. The UI marked current-state drift while preserving the first recorded
completion exactly. Rematching and explicitly completing again created a second
immutable completion: the first remained historical/stale and the second current.

At every stage, all four journals and the complete trial-balance JSON were
identical to their pre-reconciliation values. The actual 500px viewport had no
horizontal overflow. Restarting final code preserved byte-identical reconciliation,
completion/history/drift and ledger results: both balances 990.00, residual 0.00,
two completion records and four original journals.

## Verification and delivery

The guarded suite passed **485 tests** in 30.737 seconds. All **25 demonstrations**,
foundation, JavaScript syntax and diff checks passed. A subsequent test-only
strengthening asserted literal zero residual for an ambiguous-bank case; all
**15 focused reconciliation tests** then passed in 1.778 seconds. No application
code changed after the broad verification.

Independent review approved spec compliance and quality with no findings. Delivered as [c4edae4](https://github.com/DatasanAli/Accounting_Harness/commit/c4edae4bc77151bad6dd796a89d5200158f1aa8c); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37820570127). Remote main matched the local commit.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_reconciliation.py
python3 -m accounting_harness demo-reconciliation
node --check accounting_harness/static/app.js
```

Coverage includes exact reference bridges, strict timing roles, zero-residual
exceptions, later clearing at an earlier cutoff, unchanged captured reports,
a real concurrent WAL writer during capture, completion retry/drift, immutable
history, initialization/write rollback, exact large amounts and HTTP/restart.
The new additive reconciliation schema does not change prior schema versions.

## Scope and rollback

The report uses the fictional USD/January, one-Cash-account and zero-ledger-opening
policy. Capture includes later account activity conservatively, so a later entry
can mark an earlier completion drifted even if cutoff amounts stay equal. Historical
completion never changes. Unresolved bank errors and multiple-Cash-line journals
remain explicit exceptions. No live bank/model connection, new timing journal or
balancing plug is introduced. Correct timing through audited withdrawal/review;
revert software through a new commit while preserving all captured history.
