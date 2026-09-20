# Step 06 — Linked reversals

Observed locally on 2026-09-20. GitHub delivery is reported with the exact commit and Actions run in the completion response; this record does not predict CI success.

## Contract and implementation

`SQLiteLedger.reverse(original_id, *, reversal_id, entity_id, effective_date, reason, source_ids, actor_id, idempotency_key)` returns an immutable `PostingReceipt`. Its `original_entry_id` identifies the original journal; ordinary posting receipts have `None`. `ledger.receipt(entry_id)` retrieves either receipt after restart. The reversing journal preserves line order, accounts and exact integer cents, exchanging every debit/credit side. Its description is the correction reason and its evidence references are the supplied known source IDs. The original journal and its evidence, event and posting retry result remain unchanged.

Validation and writes run inside `BEGIN IMMEDIATE`, sharing the existing admission validator and journal-writing code. Current entity, active account, evidence and inclusive period rules are rechecked. Dates outside the configured period fail. Missing originals, duplicate IDs, a second full reversal and reversal-of-reversal requests fail. No partial reversal, replacement entry, mutable context, authenticated approval or locked-period functionality is introduced. Future period locks must be enforced by this same transaction boundary.

The retry scope is `(entity_id, reverse-v1, key)`, independent of ordinary `(entity_id, post-v1, key)` retries. Its SHA-256 digest covers the immutable context, action, original ID, actor and complete validated reversing entry. Calendar dates normalize to ISO; source list/tuple representations are equivalent; evidence order and duplicates matter; reason text is retained verbatim. Same-key unchanged requests return the original receipt and UTC timestamp; changed payloads fail without mutation. Recorded time is excluded from the digest. Retry validation is repeated, consistent with posting; context remains frozen in this version.

## Schema v2 and correction storage

The additive v1→v2 migration creates `reversals` and its constraints/triggers in one transaction, then changes `user_version`. It preserves all v1 tables, rows and triggers. Existing context must match before migration. Unknown versions and nonempty unversioned databases remain rejected. New databases create the same base tables and the v2 addition atomically.

Each `reversals` row stores the original and reversing IDs, entity, `reverse-v1` action, retry key and digest. This single immutable row is both the durable link and the reversal retry result. Each reversing journal has a normal `post-v1` posting event with its local actor and recorded UTC time; ordinary posting retry records stay in `idempotency`. `counts()` includes `reversals` separately: total retry results are `idempotency + reversals`.

SQL enforces original/reversing event references, entity consistency, distinct IDs, unique original and reversal IDs, scoped retry keys, action/digest/key format, append-only rows, replacement refusal and no reversal chains. The application enforces exact inverse line contents, balance, active accounts, valid evidence and calendar/period rules. Direct SQL is not an authenticated posting API or a tamper-proof boundary against a database administrator.

## Observed verification

- `python3 scripts/run_tests.py`: **109 tests passed**, including the original 90 tests and 19 reversal/CLI cases. The zero-discovery guard is preserved.
- All five CLI demonstrations exited successfully. Existing reference totals remained **13300.00 USD debit/credit**, with **9400.00 USD Cash**.
- `demo-reversal` posted a fictional **125.00 USD** Software Expense debit / Cash credit. The linked reversal credits Software Expense and debits Cash by exactly **125.00 USD**.
- Cutoff **2026-01-09** retained **125.00 / 125.00** totals; inclusive reversal date **2026-01-10** produced **0.00 / 0.00**, with every account netting to zero. The pre-reversal snapshot reproduced **125.00 / 125.00** after correction.
- Original receipt and posting retry remained identical after reversal and reopen. Same-action retries returned the same reversal receipt; a post and reversal can independently use the same key. Changed actor, date, reason, evidence, original or reversal ID failed without writes.
- Same-key concurrent requests returned equal receipts. Different-key concurrent requests produced one reversal and one rejection, retaining two journals total.
- Mid-line and after-event injected failures left no partial journal, evidence, link or retry result visible to a fresh connection. A later retry committed exactly once.
- The maximum signed 64-bit line amount reversed exactly. Invalid source/entity/date requests and unknown/inactive current accounts preserved existing records and reports.
- The synthetic [Step 05 SQL export](../../tests/fixtures/step05-v1.sql), generated with the unchanged Step 05 implementation, migrated without changing old rows or retry digests. Original retry still succeeded. Wrong context prevented migration. A failure after all migration DDL rolled back schema and version; retry then succeeded. Direct constraints and append-only guards were exercised.

`python3 scripts/verify_foundation.py`: passed — 28 Markdown files, 127 local links, 34 ordered steps, source references and all reference-month accounting identities. Code review found no actionable issues.

## Migration and rollback limits

Before opening an existing caller-owned v1 file with this version, close writers and take a SQLite-consistent backup (for example, Python's `sqlite3.Connection.backup`). Opening a matching file migrates automatically. Failure rolls back; repair the cause and retry. No downgrade is provided: Step 05 code refuses v2, so a software rollback needs a forward-compatible fix or revert, not a schema-version reset. Preserve all journals posted since migration. Backups are for disaster recovery, not undoing valid activity. Full reversal corrects supported synthetic accounting activity without deleting history; a mistaken reversal requires a separately reviewed future correction workflow.

Both persistence demonstrations remove their temporary databases. Only synthetic SQL, code and documentation are committed.
