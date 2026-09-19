# Step 05: Atomic persistence and retry

Implemented 2026-09-19. Synthetic local SQLite persistence; authenticated approval and real-data use remain later steps.

## API and storage contract

`accounting_harness.persistence.SQLiteLedger(path, catalog, period_start, period_end, known_source_ids=...)` is a context manager owning one connection. Call `admit(proposal, idempotency_key="...", actor_id="...")` to receive a frozen `PostingReceipt(entry, actor_id, recorded_at)`. `snapshot`, `trial_balance(as_of)` and `counts()` read committed records. `close()` closes the connection. Use a separate instance/connection per thread.

The proposal shape is unchanged from [Step 04](STEP_04_VERIFICATION.md). Admission reuses the existing validation and immutable-entry construction inside `BEGIN IMMEDIATE`. It inserts the journal header, ordered source references, ordered lines, one posting event, and one idempotency result in one transaction. Effective dates remain accounting dates; the service assigns a separate timezone-aware UTC recording timestamp. The actor is a supplied local operator reference, not authenticated identity or approval.

Schema version **1** is recorded with `PRAGMA user_version`. Creation, schema version and frozen context are transactional. Unsupported versions and nonempty unversioned files are refused without adoption/migration. Reopening requires the same entity, currency, complete account metadata, period, known-source set and report policy. Catalog order and source-set order do not affect context identity. No context modification or migration API exists.

Each line stores **1 through 9223372036854775807 cents** (maximum **92233720368547758.07 USD**). Larger lines are rejected before any posting write. Money never uses REAL storage or float arithmetic; totals are calculated in Python integers and may exceed SQLite's per-line range. SQLite 3.37+ is required for [STRICT tables](https://www.sqlite.org/stricttables.html). Direct SQL may losslessly coerce inputs to INTEGER; the application additionally refuses float/bool money inputs.

## Retry and concurrency semantics

The retry scope is `(entity_id, operation="post-v1", key)`. Keys and actor references must be nonblank strings without surrounding whitespace. SHA-256 covers deterministic JSON containing the validated entry, operator, operation and frozen context. Stored results reference the original journal/event; retries retain the original recording timestamp.

- Amount strings (including leading zeros) and equivalent Money values normalize to integer cents.
- ISO date strings and equivalent `date` values normalize to ISO dates. Datetimes and noncanonical date strings remain invalid.
- Object key order is irrelevant. List/tuple representations are equivalent. Source and line sequence order, including duplicate sources, is preserved and significant. An explicit matching line currency is equivalent to omission.
- An unchanged retry returns the original receipt without extra records. A changed valid payload or actor under the same scoped key raises `ValueError`. An invalid proposal is rejected by validation first. Either failure leaves the ledger unchanged.
- The same journal ID under a different key is rejected. Different IDs and keys with identical amounts produce distinct postings.

`BEGIN IMMEDIATE` serializes admission across connections. SQLite's [native busy timeout](https://www.sqlite.org/c3ref/busy_timeout.html) provides bounded lock retries: default 2000 ms, configurable integer 0–60000 ms per lock acquisition. Exhaustion raises `PersistenceBusy` and rolls back. This is not an unbounded retry loop or a whole-operation deadline; a caller retries with the same key. A commit that succeeded before a response was lost is recovered by that retry.

## Enforcement boundaries

SQL uses STRICT, WITHOUT ROWID tables, primary/unique keys, foreign keys and field checks. Connection foreign keys are enabled by the service. Checks constrain currency, line side, positive integer cents, positions, basic date shape, nonblank key/actor fields, operation and digest shape. Updates and deletes are blocked by triggers; posting an event seals its lines and sources against additions. Insert conflict guards prevent replacement of existing journals/events/retry identities. Frozen context tables reject later inserts. WITHOUT ROWID removes alternate row identities that could otherwise bypass those guards. SQLite documents why [REPLACE needs separate protection](https://www.sqlite.org/lang_conflict.html).

The application enforces aggregate balancing, at least two lines, required known evidence, active accounts, full calendar validity, period bounds and full text rules. SQL alone does **not** enforce all those cross-record accounting invariants. Direct arbitrary database administration, disabled constraints or changed schema are outside this local service's trust boundary. Raw SQL is not an alternative posting API.

Reports load immutable entries within one read transaction and retain the account catalog, period, entry values, cutoff and `unadjusted-zero-opening-v1` report policy. Retaining a snapshot reproduces that report after later postings. Snapshot report entries are the existing domain records; audit actor/time are available in posting receipts/events.

## Observed verification

Local environment: Python 3.13.1, SQLite 3.45.3.

- `python3 scripts/run_tests.py`: **90 tests pass**, including 21 persistence tests and the new CLI test. Existing discovery-zero/failure guards remain covered.
- `python3 scripts/verify_foundation.py`: plan links, ordered roadmap and reference accounting identities pass.
- All existing demos pass. `python3 -m accounting_harness demo-persistence` prints unchanged counts at persist, reopen and retry: **9 journals, 18 lines, 9 events, 9 retry records**. Both totals are **13300.00 USD**; Cash is **9400.00 USD**. Receipts are unchanged and its temporary database is removed.
- Tests compare every ordinary reference trial-balance row after reopen; unchanged and canonical-equivalent retry; changed payload/actor; duplicate IDs; distinct equal-value transactions; simultaneous same-key requests on two connections; explicit busy exhaustion and successful retry after unlock.
- Injected SQL failures occur after the first line and after the posting event. Fresh connections observe zero journals, lines, source links, events and retry results. Removing the injected trigger allows a single successful posting/retry.
- Invalid proposals (including storage overflow) preserve existing reports. Tests cover unsupported schema versions, incompatible context, unversioned unrelated databases, inclusive cutoffs, retained snapshots and values at the maximum stored cents.
- Direct SQL tests exercise malformed rows before sealing to avoid masking type/CHECK/FK failures. Separate tests cover updates, deletes, replacement, appended children and row-ID replacement attempts. Review found the replacement paths; regression tests failed before the fixes and passed afterward.

CI runs both verification commands and all four demonstrations. Delivery evidence is the exact pushed commit and matching Actions run linked in the completion response; this document does not infer an upload or CI result from local tests.

## Rollback and limits

No real financial data or database files are committed. Database files and SQLite sidecars are ignored. Use a new revert commit for software rollback; preserve database history. Do not delete or rewrite posted journals to undo code. Linked accounting reversals are Step 06. There are no automatic migrations; back up before any future migration. Older code lacking persistence will not understand these files.

The failure tests exercise transactional exceptions, connection reopen and thread contention. They do not simulate power loss, filesystem corruption, backup restoration or a multi-process operational deployment. Default SQLite durability with `synchronous=FULL` is used. All entries are loaded for local reports; bounded/paged reporting can be introduced when fixture-scale operation is insufficient.
