# Phase 02: Exact money and ledger core

Status: in progress. Steps 02–03 are implemented and verified locally; Step 04 is ready. Steps 04–06 remain unimplemented. See the [Step 02 verification record](STEP_02_VERIFICATION.md) and [Step 03 verification record](STEP_03_VERIFICATION.md); delivery evidence is reported for the exact commit in the completion response.

**Depends on:** Step 01. Keep all examples local and fictional; no operational posting claims.

**Outcome:** A deterministic local journal and ledger that preserve balanced entries and survive restart.

**Source basis:** Volume 1 §§2.2, 3.2–3.6; §14.4 for entity-specific equity distinctions. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Implement the pure domain first. Account codes stay stable. Use integer cents for posted amounts. Add database constraints and explicit transactions only at Step 05. All future operations call this same posting core; they must not maintain independent balances.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 02: Money and chart of accounts

Completed: `Money`, `Account`, `AccountCatalog`, validated JSON loading, the `demo-accounts` CLI, and 30 passing application tests. Step 03 is also complete; Steps 04–06 describe future work.

- **Build:** Add exact USD Money values and a validated service-business account catalog; expose one list-accounts demonstration.
- **Test:** Reject invalid amount formats, floats, booleans, unsupported currency and duplicate/invalid accounts; 0.10 + 0.20 equals 0.30 exactly.
- **Verify manually:** Print the account catalog and exact cents arithmetic; do not post entries.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 02: Money and chart of accounts. Follow Plan/02-ledger-core/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 03: Journal validation

Completed: pure dict proposal validation, immutable structured findings, exact totals, and `demo-journal`. All 50 application tests pass, including 20 added journal/CLI tests.

- **Build:** Add dated, evidenced draft entries with account/side/amount lines and a pure validation result.
- **Test:** Accept simple and compound balanced entries; reject imbalance, zero/negative lines, unknown/inactive accounts, invalid date and currency mismatch.
- **Verify manually:** Validate a $1,000 owner contribution and reject a $999 credit against a $1,000 debit.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 03: Journal validation. Follow Plan/02-ledger-core/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 04: Ledger and trial balance

- **Build:** Apply valid entries to an in-memory ledger and generate an as-of-date trial balance.
- **Test:** Ordinary reference entries yield $13,300.00 debit and credit trial-balance totals; compare every account; reject duplicate entry IDs and out-of-range dates.
- **Verify manually:** Print the unadjusted reference trial balance, including Cash $9,400.00.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 04: Ledger and trial balance. Follow Plan/02-ledger-core/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 05: Atomic persistence and retry

- **Build:** Persist journals in SQLite with schema versioning, atomic posting and scoped idempotency keys.
- **Test:** Reopen database; inject failure after a line write; exercise same-key retries and changed payloads; concurrent same-key requests result in one posting.
- **Verify manually:** Post, restart, retry, and show one unchanged journal and balance.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 05: Atomic persistence and retry. Follow Plan/02-ledger-core/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 06: Linked reversals

- **Build:** Add corrections using an original-entry reference and a balanced reversing journal.
- **Test:** Original remains unchanged; reversal nets to zero; repeated reversal request does not double-reverse; reject missing original.
- **Verify manually:** Reverse a fictional erroneous expense and show both records.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 06: Linked reversals. Follow Plan/02-ledger-core/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Before persistence, rerun fictional fixtures. After persistence, back up before migrations; roll back code separately from correcting posted journals.
