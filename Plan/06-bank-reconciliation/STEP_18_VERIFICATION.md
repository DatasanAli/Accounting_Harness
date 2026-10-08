# Step 18 verification: human-confirmed bank matching

Observed on 2026-10-08 using synthetic January 2026 transactions.

## Behavior

The versioned `bank-match-v1` policy compares exact signed cents, currency and
booking/effective dates within three calendar days. Exact journal/source references
can narrow candidates; descriptions cannot. Confirmation requires uniqueness in
both directions and a current captured-view binding, recomputed under the write
transaction. Journals with multiple Cash lines stay unsupported and inspectable.

Immutable match/unmatch events preserve actor, time, compared evidence and policy.
Unmatch needs a human reason and the current match event. Historical retries return
their original receipt even after unmatch; a fresh rematch creates a new event.
Overlapping statements share transaction identity and cannot add match capacity.
Schema1-to-2 migration preserves original imports and rolls back atomically.

## Browser demonstration

The existing fictional statement had a +200.00 deposit and -150.00 payment. Three
separately approved synthetic cash journals supplied one matching receipt and two
payment candidates. The exact-reference deposit displayed one confirmable pair;
the payment remained ambiguous with two candidates and no confirmation action.

The operator confirmed the deposit, supplied a reason for unmatch, then confirmed
a fresh match. History retained `match`, `unmatch`, `match`; the original event and
reason stayed visible. After every action and an application restart, complete
import detail/audit and ledger/trial-balance JSON were identical to their values
before matching. All three original journals remained; no accounting entry was
created by matching. The actual 500px viewport had no horizontal page overflow.

## Verification and delivery

The guarded suite passed **440 tests** in 26.230 seconds, including **42 focused
bank tests**. Foundation, all **22 demos**, JavaScript syntax and diff checks
passed. Independent review approved spec compliance and quality with no findings.
Commit/upload and exact-SHA CI verification are pending; no delivery result is
inferred from local tests.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p 'test_bank*.py'
python3 -m accounting_harness demo-bank-match
node --check accounting_harness/static/app.js
```

The new demo confirms a +200.00 receipt, leaves equal -150.00 alternatives
ambiguous, reopens/retries and unmatches without changing journals or balances.
Tests additionally cover concurrent claims/retries, stale candidates, opposite
signs/date boundaries, immutable events, migration and injected write rollback.

## Limits and rollback

Matching remains a local operator action, not production authentication or a
journal approval. No fee adjustment, reconciliation completion or live connection
is included. Captured account-view changes may conservatively require refresh.
Unmatch is the supported audited correction; never erase historical events.
Revert software through a new commit while preserving the whole workspace.
