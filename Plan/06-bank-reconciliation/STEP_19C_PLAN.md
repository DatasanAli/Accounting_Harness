# Step 19c: captured bank-to-book reconciliation

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 19b.

**Goal:** Explain book1000 - fee10 = 990 and bank940 + deposit200 - outstanding150
= 990, with only the fee posted and unexplained differences blocking completion.

**Architecture:** A pure report over a captured statement, ledger and matching
state, followed by an immutable explicitly confirmed reconciliation record.
Timing differences reference existing book entries; they never create journals.

## Global constraints

- Exact integer cents and synthetic USD/January scope. State the bank account,
  statement period/cutoff, ledger snapshot and versioned report policy.
- Source descriptions and a balanced total are not proof of reconciliation.
  Every reconciling item has a stable bank/book identity and explicit role.
- Preserve ledger, imports, matches, approvals and completed historical reports.
  No ledger edits, automatic adjustments, money movement or external connection.
- Human confirmation binds the exact report/state; changed books or matches make
  a pending completion stale. Completed reports remain immutable historical facts,
  with current-state drift visible rather than rewriting completion history.

## Captured report and completion

Capture the selected statement, immutable imported rows, ledger entries/catalog,
active matching history and timing classifications in one ledger read transaction.
Effective journal dates and bank booking dates determine inclusion at the statement
cutoff. A match to a later bank booking must not clear a book timing difference at
an earlier cutoff. Report generation is pure after capture, including names/labels.

Bank closing is the imported validated statement balance. Book Cash is ledger
Cash at the same cutoff. Deposits in transit are positive book cash movements not
on the bank side at cutoff; outstanding payments are negative book movements not
cleared there. Each item references one specific eligible journal and its amount,
never a free-form amount. Prevent duplicate classification, already-cleared use,
wrong sign/account, future entries and self-canceling invented items.

Unmatched bank rows remain exceptions until matched to an existing/approved book
adjustment or supported by a separately audited bank-error resolution. This
bounded delivery need not implement bank-error adjustments; unresolved bank-side
errors block completion and stay visible. Ambiguous matches also block completion.
An unexplained numeric difference cannot be classified as a plug.

Show original book balance, linked reviewed book adjustments, current adjusted
book balance, bank closing, each timing item, adjusted bank balance and signed
unexplained difference. Avoid double-subtracting a fee already included in the
captured ledger: the display bridge references the before-adjustment snapshot or
derives its labeled starting amount from the exact linked adjustments, while the
final book total comes directly from the final ledger snapshot.

Completion requires zero numeric residual, complete classification of applicable
cash/book/bank exceptions, one-to-one matches and unchanged bound state. Recheck
inside the write transaction. Persist an immutable report/capture/policy/digest,
actor/time and references with scoped exact retry. Repeating the same completion
returns its original record; changed payload conflicts. New later activity can
require a new reconciliation revision, never an edit to the old record.

## Reference fixture funding

For the full-January end-to-end example, record a supported owner funding journal
950.00 on January 1 and include its matching +950.00 bank row. The full statement
therefore opens at 0.00, includes funding +950.00 and the fee -10.00, and closes at
940.00. The phrase starting bank/book950 describes cash before the later deposit,
payment and fee; do not mislabel the January 1 journal as a pre-period opening
balance or silently ignore it as an unmatched book movement. Match the funding
row as well as the posted fee. The later +200.00 deposit and -150.00 payment are
the two reviewed timing items. This preserves the stated 990.00 reconciliation
without inventing an opening balance or suppressing a cash exception.

## Task 1: timing evidence, report and explicit completion

**Files:** Bank reconciliation module/service, workspace/HTTP/CLI/static and focused
snapshot/concurrency/report tests. Parent owns docs/CI/browser/delivery.

- [x] RED: synthetic opening bank/book950, book deposit200 and payment150 gives
  book1000; imported bank fee10 gives bank940. Reviewed fee produces book990;
  bank940 + deposit200 - outstanding150 =990. Only fee adds a journal.
- [x] Show every source/match/adjustment/timing reference and exact report digest.
  Explicit completion succeeds only after fee posting/matching and timing review.
- [x] Refuse unexplained difference, zero difference with unmatched/ambiguous rows,
  duplicate/wrong-sign/future/cleared timing items, stale state and arbitrary plugs.
- [x] Cover cutoff with later clearing, frozen prior report, later ledger/match drift,
  concurrent exact completion retry, changed payload, immutable rows and write faults.
- [x] Add clear bank-to-book UI with separate timing review and completion action;
  `demo-reconciliation` proves both990 balances and only10 fee posting.
- [x] Verify focused/full checks/all demos/browser, independent review, commit/push
  and exact-SHA CI before period-end adjustment work.
