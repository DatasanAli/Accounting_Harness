# Step 08: versioned drafts implementation contract

Goal: preserve editable proposals as immutable revisions and expose a pending/rejected review queue. Standard-library Python/SQLite and synthetic receipts only. Implements the Step 08 brief in the phase plan; the user requested Steps 08–10 sequentially, each with its own verified commit/push.

## Storage and interfaces

`SQLiteReviewStore(ledger, registry, policy_version='review-v1')` uses the ledger connection for optional review tables with their own `review_schema` version. Initialization is atomic and additive; ledger schema v2, context, retry digests and snapshots remain unchanged. No source registry migration. A registry must match the ledger entity. Existing ledgers require sources provisioned in their original frozen context; new evidence outside that context remains a finding. Never silently extend the frozen source list.

`save(draft_id, proposal, evidence={source_id: digest}, expected_revision=0, actor_id, idempotency_key, reason)` appends a pending revision. JSON proposals are copied canonically; evidence is explicitly bound by identity and SHA-256. Metadata must be nonblank; revision numbers are integers. Creation expects 0, edits expect the current revision. Rejected drafts may be edited into pending revisions. `reject(draft_id, expected_revision, actor_id, idempotency_key, reason)` appends a rejected revision; rejecting an already rejected revision is invalid. There is no approval or posting API in this step.

Revision digest binds proposal, evidence and policy; immutable records also retain validation findings, state, reason, actor and UTC time. `history`, `get`, `queue` return immutable records with canonical JSON strings and tuple findings. Reads recheck evidence into separate current findings; original findings remain intact. Missing/conflicting evidence never disappears from review. A valid pending revision is reviewable, never approved. Receipt policy supports one receipt, checks the total against its amount; unsupported multiple receipts remain a finding rather than guessing allocations. Pure journal validation, period and SQLite integer limits also apply.

Each mutation stores a revision, event and scoped retry key in one BEGIN IMMEDIATE transaction. Retry identity is (entity implied by file, operation, key); digest includes expected revision, actor, reason, proposal/evidence/policy. Exact repeats return the historical result even after later edits; changed requests conflict. Stale edits fail. Append-only triggers block update/delete/replace. Application code enforces transitions and accounting semantics; SQL is not an authentication boundary.

## Execution checklist

- [x] Write failing `tests/test_review.py` for edit/reopen/history, unresolved evidence, rejection, stale/retry conflicts, entity isolation, SQL immutability, rollback, lock/concurrent edits and version rejection.
- [x] Implement `accounting_harness/review.py` with the above API, using existing validation and ledger transactions.
- [x] Add `demo-review` and a CLI assertion; run the guarded suite and all seven demos.
- [x] Update README, commands/CI, status, roadmap, Step 09 brief and observed verification. Inspect/stage intended paths, commit/push and inspect the matching Actions run before Step 09.

Rollback: revert software with a new commit; retain append-only review tables. Existing ledger v2 code ignores these optional tables. Never lower a schema marker, delete records or change posted journals to roll back code.
