# Step 05 implementation plan

Implement the approved atomic persistence/retry brief for the synthetic local ledger. One numbered delivery; linked reversals remain Step 06.

Architecture: a standard-library `SQLiteLedger` in `accounting_harness/persistence.py` reuses `InMemoryLedger.admit` to produce validated immutable entries inside a SQLite write transaction. Store journal headers, ordered sources/lines, one posting event and one scoped retry result together. Use schema version 1, immutable context, append-only records, and a bounded SQLite busy timeout. Return a frozen posting receipt with the entry, operator reference and recorded UTC time. Read snapshots in one transaction and reuse the existing trial-balance policy.

- [x] Add behavioral tests in `tests/test_persistence.py` and observe the missing persistence boundary fail. Cover every reference row after reopen, retry conflicts and canonical equivalence, injected rollback, two-connection concurrency, busy exhaustion, invalid proposals, integer limits, schema constraints, incompatible reopen, and historical snapshots.
- [x] Implement `SQLiteLedger(path, catalog, period_start, period_end, known_source_ids=...)`, `admit(proposal, idempotency_key=..., actor_id=...)`, `snapshot`, `trial_balance(as_of)`, `counts()`, and connection lifecycle. Require positive signed-64-bit line cents; sum in Python integers. Canonical amounts use cents, dates ISO, and arrays preserve order/duplicates; catalog and known-source sets are sorted for context comparison.
- [x] Run `python3 -m unittest discover -s tests -p 'test_persistence.py' -v` and resolve failures. Add a failing CLI test, implement `demo-persistence` with a cleaned-up temporary database, and add it to `.github/workflows/verify.yml`.
- [x] Review the implementation against the brief, update README, testing strategy, phase/status/roadmap and the Step 06 brief; record observed verification and SQL/application enforcement limits in `STEP_05_VERIFICATION.md`.
- [x] Run foundation verification, guarded application tests and all four demos. All 90 tests and demonstrations passed; independent review findings were fixed and rechecked.

Delivery procedure: inspect/stage only intended changes, commit, push to `origin main`, compare remote SHA, and inspect the Actions run for that exact commit. The completion response records the observed delivery result.

No new dependencies, authenticated posting, real financial data, automatic migrations, or reversal implementation. SQL constraints cover types, keys, references and basic field validity; the application validates aggregate balancing, full date/text rules, active accounts and period eligibility. A SQLite transaction provides rollback for exceptions; tests do not simulate power loss or establish operational backup readiness.
