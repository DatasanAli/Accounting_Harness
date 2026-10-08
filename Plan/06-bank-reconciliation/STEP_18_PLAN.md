# Step 18: bank matching and unresolved exceptions

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 17.

**Goal:** Propose a unique bank-to-book cash match, require explicit human
confirmation, preserve ambiguous/unmatched rows, and undo a match through an
audited action without changing accounting balances.

**Architecture:** Extend the concrete bank service with immutable matching events
and deterministic candidates from a captured bank/ledger view. Import, matching
and journal recognition remain separate actions. No model classifier or live
bank connection is needed.

## Global constraints

- Exact signed USD integer cents, existing fictional entity and January period.
  Browser amounts are exact decimal strings; descriptions/references remain data.
- Match only an imported transaction for the selected bank account and one posted
  journal with exactly one nonzero Cash-1000 line. Debit is positive bank cash;
  credit is negative. Multiple Cash lines are an explicit unsupported candidate,
  not silently netted. Account mapping comes from immutable bank configuration.
- Matching never creates, edits, reverses or reclassifies a journal. A transfer or
  owner contribution stays classified as its existing posted journal; it cannot
  become income by being matched.
- One active bank transaction ↔ one journal match. Overlapping statements refer
  to the same bank transaction identity and do not create new match capacity.
- Human confirmation binds the exact current candidate and source identities.
  Recompute eligibility inside the write transaction; stale views cannot consume
  a row already matched elsewhere. Explicit audited unmatch preserves history.
- Preserve prior contexts, approvals, retry receipts, snapshots, bank imports and
  ledger balances. No external connections or production-authentication claims.

## Candidate policy

Version `bank-match-v1` requires same entity/account/currency, exact signed amount
and booking/effective dates within three calendar days. Return deterministic
candidate order and explain the compared date, amount and reference fields.
Reference comparison is exact against journal ID or its source IDs, never a
substring of descriptive text. If a bank reference exactly identifies one of the
amount/date candidates, narrow to those exact-reference candidates. Otherwise
retain amount/date candidates with the unmatched-reference fact visible.

Zero eligible candidates stays unmatched; two or more stays ambiguous. Only a
unique eligible pair can be confirmed in this bounded workflow: the bank row has one candidate and that journal has no other eligible unresolved bank row. Check both directions, including equal bank amounts competing for one book entry. Do not pick
the first equal-amount item or silently invent a journal. Unsupported multiple
Cash-line entries and incomplete references remain inspectable exceptions.

Exclude already actively matched bank transactions and journals from new
candidate consumption. Candidate output includes the immutable bank content
digest, canonical journal digest, policy and a deterministic binding token for
the current match state. Confirmation accepts IDs/binding, not caller-supplied
money, account, actor or policy. Recompute uniqueness and binding under the ledger
write transaction, including newly posted competing candidates.

## Audited persistence

Add an atomic versioned bank migration for append-only match/unmatch history and
scoped retry receipts. Store entity/account, stable bank transaction ID, journal,
binding/policy, actor, recorded timestamp and operation. Unmatch references the
active match event and requires a nonempty human reason. Derive current active
matches from immutable history; a mutable derived index is unnecessary at this
fixture scale. Enforce one-to-one changes under `BEGIN IMMEDIATE` and reject
missing/wrong-entity references. Protect historical rows from UPDATE/DELETE/REPLACE.

Exact operation/key/payload repetition returns the original receipt; changed
payload conflicts. A retry of an old match after unmatch returns that historical
receipt without reactivating it. A new deliberate rematch creates a new event.
Unmatch binds the current active match, so a stale request cannot undo a different
later match. Failed writes leave no partial event/retry and no ledger change.

## Localhost flow and acceptance

The bank view shows each imported row as unmatched, ambiguous or matched, plus
candidate journal/evidence/date/amount. Present the exact pair before a separate
Confirm match action. Ambiguous rows have no automatic confirmation action.
Matched rows show the original audit and a separate Unmatch action with reason.
Keep all state after restart. No adjustment or accounting approval is implied by
confirming a bank match.

## Task 1: candidates, human match, audited unmatch and UI

**Files:** Existing bank module/schema, workspace/HTTP/CLI/static UI, focused bank
matching tests. Parent owns documentation/CI/browser/delivery.

- [x] RED: unique +200.00 bank receipt and posted Cash debit200.00 propose one pair;
  explicit confirmation creates one match and no journal or balance change.
- [x] Two -150.00 bank candidates/journals remain ambiguous without exact reference;
  distinct equal amounts retain distinct identities. An exact reference can narrow
  candidates; opposite signs, currency, date-window and account mismatch fail.
- [x] Confirming a preexisting transfer/owner-contribution journal leaves its
  original counterpart classification and revenue unchanged.
- [x] Race two confirmations for one bank row or journal: at most one active pair. Two equal bank rows competing for one book entry remain ambiguous before confirmation.
  Exact concurrent retries return one receipt. Recompute uniqueness after a new
  same-amount journal arrives; refuse stale bindings.
- [x] Verify restart, overlapping statements, changed-key payload, unmatch reason,
  stale unmatch, rematch, historical retry behavior, immutable events and injected
  event/retry/schema rollback. Assert unchanged bank/ledger source records.
- [x] Add browser candidate/confirm/exception/unmatch flow and `demo-bank-match`.
  Demo confirms one unique receipt and leaves two ambiguous alternatives unresolved.
- [x] Run focused tests, guarded suite/foundation/all demos/JS/diff checks; freeze
  report for parent browser/review/commit/push/exact-SHA CI before Step 19.
