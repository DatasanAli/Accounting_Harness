# Step 07 implementation plan and source contract

Implement the source-registration brief in the existing one-step delivery workflow. Standard-library Python and SQLite only; synthetic inputs only.

## Contract

`SQLiteSourceRegistry(path, entity_id, busy_timeout_ms=2000)` owns a separate, single-entity database. `register(document, actor_id=...)` accepts a decoded JSON object and returns an immutable `ImportResult(record, repeated)`; `get(document_id)` and `counts()` read durable results. `load_source_document(path)` rejects duplicate JSON keys. Caller-supplied operator IDs are prototype audit references, not authentication.

Required fields, with no unknown fields: `schema_version` (integer 1), `synthetic` (boolean true), `entity_id`, `document_id`, `kind` (only `receipt` in this step), `document_date` (strict YYYY-MM-DD), `currency` (USD), `amount` (positive unsigned decimal string with two fractional digits), `counterparty`, and `description`. Text must be nonblank with no surrounding whitespace. Amounts use the existing exact Money parser. Metadata is evidence, not an accounting classification or permission.

Identity is `(entity_id, document_id)`, chosen by the importer and compared exactly. The content digest is SHA-256 of UTF-8 canonical JSON: sorted keys, compact separators, ASCII escapes; include all required fields except entity/document identity and normalize amount through Money formatting. The schema version versions this canonicalization. Preserve other text exactly, including case and Unicode representation. JSON layout/key order and leading amount zeros do not affect the digest. Store canonical content, digest, identity, original actor and UTC recorded time. Keep actor/time outside the content digest; any valid operator repeating an identical import gets the original receipt without a new event. Reusing identity with different content fails, retaining all prior evidence. Distinct identities with identical content remain distinct, with equal digests; digest equality is neither proof of business duplication nor an authorization decision. Raw JSON byte layout is not retained.

## Storage and posting boundary

The existing ledger freezes known sources in its context and binds that context into posting retry digests. Do not extend its source set or change its schema. Registry storage uses its own application ID and schema v1, refusing mismatched, unsupported, or nonempty unversioned databases. No existing file migration is needed. Source and registration-event rows commit together under BEGIN IMMEDIATE, with a bounded busy timeout and append-only SQL triggers (including REPLACE protection). Failures roll back; identity is the retry key. Persisted UTC time is assigned once. SQL enforces keys, references, basic types and immutability; complete input validation and digest computation belong to the application.

Registration cannot post or approve anything and does not add sources to an existing ledger. Step 09 must explicitly design and test evidence binding for application posting without invalidating old context/retries/snapshots. Step 08 can read registry evidence to construct drafts. Document text, including apparent commands, stays inert.

## Implementation and verification

- [x] Write `tests/test_sources.py` against this API; observe missing implementation failure. Cover strict validation, digest reproducibility, identity conflicts, original audit receipt after reopen, same-content separate documents, entity isolation, concurrency, busy timeout, event-write rollback, SQL immutability, schema rejection and unchanged existing ledger.
- [x] Implement `accounting_harness/sources.py` and `data/fixtures/source-receipt.json`. Run targeted tests.
- [x] Add a failing CLI test; implement `demo-source` in `__main__.py` using temporary synthetic storage, and add its command to CI.
- [x] Review the diff and update README, working commands, testing strategy, phase/status/roadmap, verification record and Step 08 brief.
- [x] Run foundation verification, the guarded full suite, and all six demos. Observed: 128 tests and all demos passed; independent review found no significant issues.

Delivery procedure: commit intended changes, push main, compare GitHub SHA and inspect the exact Actions run. The completion response records the observed delivery result.

Rollback: revert software with a new commit; retain registry files and evidence. Old ledger code can still open its unchanged ledger database. Older software does not consume the separate registry; never downgrade its version marker or delete history to make rollback work.
