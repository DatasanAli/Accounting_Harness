# Next: Step 05 — Atomic persistence and retry

Status: ready. Steps 01–04 provide exact Money/accounts, journal validation, and an in-memory ledger with reproducible trial balances.

## Copy this prompt

> Build Step 05: atomic persistence and retry. Follow Plan/NEXT_STEP.md, persist journals in SQLite with atomic writes and safe idempotent retries, test and demonstrate restart/retry behavior, then commit and push to GitHub. Stop after this step.

## The small thing to build

Add a standard-library SQLite repository for the local synthetic ledger. Preserve Step 04's validation, date range, immutable entry semantics, and snapshot/report policy. A persisted journal must retain ID, entity, currency, effective date, description, source references and lines, plus a local operator actor reference and a separate recorded UTC timestamp. This is a synthetic local persistence demonstration; authenticated approval and real-data operation remain later steps.

Define a schema version and reject unsupported versions without destructive changes. Preserve the entity/catalog/period context across reopen; reject incompatible reopen configuration. Document the supported cents range for SQLite storage and reject overflow before any write; never fall back to REAL money columns or float conversion.

Commit each journal, its lines, a posting event, and its idempotency record in one transaction. Revalidate inside the write transaction and enforce applicable database uniqueness, foreign keys and field constraints. Keep admission single-entry. Report snapshots must be loaded consistently from stored entries and carry the metadata needed to reproduce a trial balance.

## Retry contract

Require an explicit nonblank idempotency key scoped to the entity and operation. Canonicalize the validated entry payload deterministically, including source IDs, effective date and lines; document treatment of equivalent amount/date representations and collection ordering. Bind the actor/context needed for the recorded action. Store a digest with the result identity.

- Same scoped key and same canonical payload returns the original result, with no extra journal, lines or event.
- Same scoped key and changed payload fails without mutation.
- Same journal ID under another key is rejected, preserving Step 04's uniqueness rule.
- Different entry IDs and different keys with equal amounts remain distinct transactions.
- Concurrent attempts using separate SQLite connections with the same key/payload yield one committed journal and one event. Use a bounded busy/retry policy and report exhaustion clearly.

## Required evidence

- Persist ordinary T01–T09, close the connection, reopen it and reproduce every reference trial-balance row and both 13300.00 USD totals.
- Inject a failure after at least one line write but before commit. A fresh connection must find no partial journal, lines, event or idempotency result. Retrying after the failure must succeed once.
- Exercise unchanged retry, changed-payload retry, duplicate IDs under a different key, and concurrent same-key requests.
- Check unknown/inactive accounts, wrong entity/currency, invalid sources, unbalanced entries, out-of-period dates and storage overflow through the persistence service; failures leave existing reports unchanged.
- Test applicable schema constraints via direct SQL and verify a new database uses the expected schema version. Do not claim SQL constraints cover an invariant tested only through application code.
- Retain a report snapshot, persist later entries and reproduce the old report from that snapshot.

## Demonstration and delivery

Add `python3 -m accounting_harness demo-persistence`, using a temporary synthetic database that is cleaned up after the demo. Show persist → close/reopen → retry → unchanged journal/event counts and balances. Keep real databases and financial records out of GitHub.

Keep the foundation check, guarded application test runner and all three existing demos passing. Add the persistence demo to CI. Record observed checks, schema/retry semantics and rollback limits; update README, phase/status/roadmap; mark Step 05 complete and Step 06 ready; replace this document with the linked-reversal brief. Commit, push, verify the exact commit and CI run, then stop.

Source basis: journal/ledger principles from Volume 1 §§3.5–3.6. Transactions, idempotency, storage limits, schema versioning and concurrency are engineering decisions.
