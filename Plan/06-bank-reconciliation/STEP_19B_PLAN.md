# Step 19b: reviewed bank-fee adjustment

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 19a.

**Goal:** Record one evidenced 10.00 bank fee through exact human review, reducing
book Cash from 1000.00 to 990.00. The fee can then match its imported bank row.

**Architecture:** Derive a typed immutable evidence anchor from one imported bank
transaction and an explicit operator fee classification. Use a concrete reviewed
operation and atomic bank-row consumption effect, not description classification
or a generic balancing entry. Reconciliation completion follows in Step 19c.

## Global constraints

- Synthetic entity/USD/January; exact cents and strict decimal strings. Account
  5300 Bank Fees Expense must exist through audited 19a enrollment; Cash is 1000.
- Bank text is data. An operator explicitly proposes fee treatment and reviews
  the bank row plus journal. Import/matching alone grants no posting authority.
- Only the whole negative bank transaction can become this fee. No arbitrary
  amount, split, tax/FX, refund or plug. Positive/zero rows fail explicitly.
- Preserve old contexts, hashes, approvals, retries, snapshots and match history.
  No external connection or money transmission. Cash and expense posting requires
  the existing separately bound human confirmation.

## Evidence and operation

Use a deterministic source identity based on entity/bank account/transaction ID.
The new strict typed bank-fee evidence retains those IDs, booking date, exact
amount/currency, original reference/description and bank canonical content digest.
Reconstruct it from the immutable bank import during review validation; a caller
cannot fabricate an imported bank row by supplying a typed document. Statement
membership is a trace reference, not the bank transaction's economic identity;
overlapping statements cannot create a second fee source or consumption.

The operator's classification/reason is recorded in the proposed operation and
shown separately from original bank text. Do not alter the bank record. Reuse
the source registration/enrollment recovery behavior when the source registry
and ledger write are separate files; do not claim cross-file atomic registration.

Use explicit `bank-fee-v1` with a strict versioned intent binding the stable bank
account/transaction identity, bank content digest, full positive fee cents, USD,
booking/effective date and exact evidence roles. Derive the draft from bank
transaction identity and the journal from entity/draft. Derive debit5300/credit1000;
independent review validation reconstructs all fields and mapping. Old receipt
policies cannot post typed bank evidence. Unknown policy/intent fields fail closed.

A currently matched row cannot create a fee. Also refuse fee preparation when
eligible existing cash-journal candidates could already represent the bank row;
leave the exception for explicit resolution instead of duplicating cash. Recheck
this state at posting under the write transaction. Claim a deterministic shared
cash-event identity and bank-row consumption; a new document or statement ID
cannot evade the claim. Rejection retains claim ownership for same-draft revision.

## Atomicity and SQL boundary

Add an immutable bank-fee effect with unique bank transaction, source, approval
and journal references, plus deferred linkage to the posting event. Known approved
posting inserts effect before journal, then review/retry in the same transaction.
The final journal seal rechecks the current approved revision/intent after effect
insertion and exactly matching amount/date/two account lines/evidence. A journal
using the derived bank-fee evidence cannot omit its effect. Do not apply a blanket
guard to every future 5300 line: closing expense later uses separately evidenced
closing policy, not a second bank fee.

Exact retry precedes fresh mutation checks. Concurrent duplicate proposals/posts
produce one fee and one cash movement. All effect/journal/review/retry failures
roll back together; an orphan effect cannot commit. Managed fee reversal is
unsupported until it also restores bank consumption/matching through linked effects.

After fee posting, ordinary explicit bank matching can link the new cash journal
to its bank transaction. Matching is a separate recoverable action: its failure
does not justify reposting the fee. No automatic matching or second approval is
silently invented. The UI shows posted-but-unmatched state and exact retry recovery.

## Task 1: imported fee evidence, review, atomic posting and UI

**Files:** Concrete bank/fee service, evidence/review/approval/persistence integration,
workspace/HTTP/CLI/static and focused tests. Parent owns docs/CI/browser/delivery.

- [ ] RED: book1000 plus reviewed fee10 gives Cash990/Bank Fees Expense10, one
  additional journal; no change before human confirmation.
- [ ] Reject forged/missing import, wrong account/currency/sign/date, changed digest,
  unsupported allocation, matched/candidate-existing row and stale approval.
- [ ] Prove bank-row identity across overlapping statements, shared cash claim,
  exact concurrent retry, new same-draft approval after correction and no duplicates.
- [ ] Cover versioned migration/legacy bytes, effect/journal/review/retry rollback,
  final-seal supersession, immutable/orphan effects and unsupported reversal.
- [ ] Add explicit fee proposal/review, evidence trace and post-to-match handoff;
  `demo-bank-fee` shows1000→990 with expense10 and no timing-difference entries.
- [ ] Verify focused/full checks/all demos and browser; reviewed commit/push/exact
  CI before Step 19c. No reconciliation-complete claim in this slice.
