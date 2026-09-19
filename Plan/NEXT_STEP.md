# Next: Step 06 — Linked reversals

Status: ready. Steps 01–05 provide exact Money/accounts, journal validation, immutable ledger snapshots, and atomic SQLite persistence with safe retries.

## Copy this prompt

> Build Step 06: linked reversals. Follow Plan/NEXT_STEP.md, preserve original posted entries, add linked reversing journals with safe retries, test and demonstrate reversal behavior, then commit and push to GitHub. Stop after this step.

## The small thing to build

Add a correction operation to the synthetic local SQLite ledger. Given an existing journal ID, a new reversal ID, effective date, correction reason/evidence, local actor and explicit idempotency key, create a balanced journal with the original lines' debit/credit sides exchanged and the same exact amounts. Store a durable, queryable link to the original. Keep original entries, events and retry results unchanged. This step supports a full reversal, not arbitrary partial corrections or automatic replacement entries.

Revalidate reversal inputs and current account/source/period context inside the write transaction. A date outside the configured period is rejected; do not backdate around future locked-period rules. Preserve integer storage limits, schema/version handling, recorded UTC timestamps and reproducible report snapshots. If schema changes are required, provide a tested non-destructive versioned migration from Step 05 and reject unsupported versions; do not silently recreate databases.

Define reversal retry scope and payload canonicalization explicitly. The same key/action returns its original result; changed parameters fail without mutation. A different key must not reverse the same original twice. Reject missing original IDs and reversal-of-reversal requests for this first correction API. Atomically persist the reversal, lines, evidence, original link, event and retry result.

## Required evidence

- Reverse a fictional erroneous expense; show original and reversing journals with their link. A report including both nets their account effect to zero.
- Compare original journal/receipt before and after reversal and after reopen; originals remain unchanged.
- Retain a pre-reversal snapshot and reproduce its original report. A cutoff before the reversal excludes it; the reversal date is included.
- Test unchanged retry, changed-payload retry, duplicate reversal IDs, repeated reversal under another key and concurrent reversal requests; one original gets at most one full reversal.
- Reject missing originals, reversal-of-reversal, invalid evidence, wrong entity, inactive/unknown accounts and out-of-period dates without changing existing balances or records.
- Inject a mid-write failure and prove a fresh connection sees no partial reversal/link/event/retry record; a later retry succeeds once.
- Exercise any new database constraints and any schema migration using synthetic temporary databases. Preserve Step 05's immutability, restart and retry tests.

## Demonstration and delivery

Add `python3 -m accounting_harness demo-reversal` using a cleaned-up temporary synthetic database. Run the foundation check, guarded application test suite and all existing demos; add the new demo to CI. Record observed evidence and correction/rollback limits. Update README, phase/status/roadmap, mark Step 06 complete and Step 07 ready, and replace this brief with source registration. Commit, push, verify the exact commit and Actions run, then stop.

Source basis: journal/ledger principles from Volume 1 §§3.5–3.6. Reversal linkage, idempotency, concurrency and migrations are engineering decisions. Authenticated approval remains later work.
