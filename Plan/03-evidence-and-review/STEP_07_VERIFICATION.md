# Step 07 — Source registration

Observed locally on 2026-09-22. GitHub delivery is reported with the exact commit and Actions run in the completion response; this record does not predict CI success.

## Contract and API

The [source contract and implementation plan](STEP_07_PLAN.md) defines required fields, supported kind, canonicalization, persistence and posting boundaries. The only supported document kind is a structured synthetic `receipt`; source schema version is integer `1`. Unknown/missing fields fail. Required identity and metadata text is exact and nonblank without surrounding whitespace; dates use strict YYYY-MM-DD; currency is USD and amount is a positive decimal string with exactly two fractional digits. Source amounts use exact Money arithmetic and are stored in canonical JSON as strings, so ledger SQL line-integer limits do not truncate evidence.

```python
from accounting_harness.sources import SQLiteSourceRegistry, load_source_document

receipt = load_source_document("data/fixtures/source-receipt.json")
with SQLiteSourceRegistry("synthetic-sources.sqlite3", "demo-service-001") as registry:
    imported = registry.register(receipt, actor_id="synthetic-local-operator")
    stored = registry.get(receipt["document_id"])
    assert stored == imported.record
```

Use a separate registry path, not a ledger path. Caller-selected files survive close/reopen. The demo uses a temporary directory and deletes it on exit. `SourceRecord` and `ImportResult` are frozen values. `counts()` returns document and registration-event counts in one SQLite snapshot. The JSON loader rejects duplicate keys and non-object roots; registration validates the full document. File/JSON/type/validation errors propagate without creating source records.

Identity is `(entity_id, document_id)`. Its unchanged retry returns the original record, actor and recorded UTC time, with `repeated=True` and no new event. The actor is a caller-supplied prototype reference, not authentication. A different valid importing actor can retrieve the original repeat result. Changed content under an existing identity raises `ValueError` without replacing evidence. Canonical strings themselves are compared, avoiding reliance on digest collision resistance for identity-conflict handling.

The SHA-256 content digest covers normalized structured content, excluding entity/document identity and import actor/time. Sorted keys, compact JSON separators and ASCII escapes define the exact UTF-8 bytes. Amount formatting normalizes leading zeros. All other field text is retained exactly, including case and Unicode representation; raw JSON layout is not retained. The stored source schema version fixes this rule for v1. Equal digests across distinct identities never merge records. A digest is not a business-duplicate detector or evidence of authenticity.

## Storage, audit and ledger boundary

The registry has its own application ID and schema v1 with `registry_context`, `source_documents` and `registration_events`. Each source has a durable `register-source-v1` event recording its first actor and UTC time. Each new registration runs under `BEGIN IMMEDIATE`; document and event commit or roll back together. A native bounded busy timeout defaults to 2000 ms (allowed 0–60000); lock exhaustion raises `PersistenceBusy`, and the same identity/content may be retried. Initialization DDL and version markers are atomic. No existing schema migration is needed; mismatched application IDs, unsupported versions and nonempty unversioned files are rejected without adoption.

SQL enforces identity uniqueness, entity/event references on application connections, basic types and digest shape, and append-only rows with update/delete/REPLACE refusal. The application enforces complete metadata/date/currency/amount validation and digest computation. Direct database administration is not an authenticated API or tamper-proof boundary. Rejected imports and harmless repeats do not create new audit events.

The ledger remains schema v2 with the same frozen known-source set. Registration does not change it or its context-bound posting retry digests. A source description that asks to approve/post remains stored data. Drafts are Step 08; evidence-bound human approval and posting integration are Step 09 and must explicitly preserve prior journals, retry results and report snapshots. No PDF extraction, provider, approval role or source-to-posting adapter is introduced here.

## Observed verification

- Initial source tests failed because the registry module was absent; the new CLI test failed because `demo-source` was absent. Both passed after implementation.
- Source coverage comprises 18 tests: full required-field/malformed-input cases, duplicate JSON keys, canonical expected bytes and digest, exact large amounts, immutable input/output snapshots, original actor/time across reopen/retry, identity conflicts, distinct identities with equal amounts/content, entity isolation, two-connection repeat/conflict races, bounded busy failure/retry, schema rejection, initialization rollback, event-insert failure rollback, SQL immutability and unchanged ledger behavior.
- An injected event-write failure preserved the existing source/event, left no second source, and allowed a later retry exactly once. An injected initialization failure left no schema objects and reset both version markers, allowing clean retry.
- Concurrent identical imports produced one new result and one repeat with the same original receipt; conflicting concurrent imports produced one winner and one rejection.
- A registry open against a ledger file was refused. Registering instruction-like document text left that ledger file byte-identical, and reopen preserved its snapshot and posting retry receipt.
- Independent code review found no significant issues. The reviewer also checked commit-lock failure rollback/retry and preservation of distinct Unicode representations in temporary storage.
- Full guarded application suite: **128 tests passed**, including all prior ledger, reversal, migration and zero-discovery tests.
- All six CLI demonstrations exited successfully. Existing reference totals remained **13300.00 USD** debit/credit and **9400.00 USD Cash**. Reversal demo retained its original receipt and canceled the **125.00 USD** expense to zero.
- `demo-source`: initial import had **1 source / 1 event**; reopen/repeat retained **1 unchanged source**; another identity produced **2 sources / 2 events** with equal digests; changed amount under the first identity was rejected with original evidence intact.
- Fixture digest: `89df1e7075bd319bbc4abb6ef9b4c4bd600f243be9376969f04dd8a274bd9ecb`.

Foundation verification passed: 30 Markdown files, 136 local links, 34 ordered steps, source references and all reference-month accounting identities. These checks are separate from the application behaviors. CI runs that check, the guarded suite and all six demos.

## Rollback and limits

Revert software with a new commit while preserving registry files and evidence. Existing ledger files need no migration and remain compatible with Step 06. Older code does not use the separate registry; never reset its version marker or remove evidence to accommodate rollback. Source corrections cannot overwrite registered evidence; a future reviewed supersession policy is outside Step 07. Tests establish exception/lock rollback, not power-loss recovery, operational backups, real-document authenticity or production access control. Only synthetic fixtures, code and documentation are committed.
