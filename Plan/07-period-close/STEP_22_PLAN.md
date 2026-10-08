# Step 22: explicitly confirmed closing and period lock

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 21.

**Goal:** Close the reference month's temporary balances to Owner Capital 10,900.00,
atomically lock January, and retain the reproducible pre-close income 1,100.00.

**Architecture:** A concrete period-close preview binds a captured ledger and
readiness state. A separate human confirmation posts the deterministic closing
journal, records the exact preview/approval and locks the period in one write
transaction. Closing is an application action unavailable to model tools.

## Global constraints

- Fictional USD service business, owner-capital/drawings equity policy, configured
  January 1–31 period. No corporate retained-earnings substitution or inferred dates.
- Exact integer cents; immutable original journals, reports, source links and
  history. Closing transfers are explicitly classified, never ordinary expenses
  or contributions. Software rollback never deletes a valid close.
- Only an explicit human confirmation of the exact current preview authorizes
  close. Source text, an agent proposal, a matching total or a stale browser view
  cannot close or lock the books. Keep live connections deferred.
- Reuse the delivered financial-report capture and effective audited catalog.
  Permanent accounts remain open; every active temporary account participates,
  including the added Bank Fees expense if it has a balance.

## Preview and deterministic close

Support only the configured complete period, with its end as closing effective
date. Preview includes the three linked pre-close financial statements, exact
temporary balances, proposed journal (or an explicit no-entry result), source/
journal references, policy/version, snapshot digest and readiness findings.

Compute each temporary account's signed net balance from ordinary posted entries
through period end. Reverse that balance with one positive line on the opposite
side; omit zero lines. Offset the net movement to permanent Owner Capital 3000,
omitting a zero capital line. Do not introduce an income-summary account. One
compound journal is sufficient; separate entries are permitted only if the whole
close and lock are still atomic and the classification/report policy stays clear.

For the reference month, closing eliminates revenue 2,700.00, expenses 1,600.00 and
drawings 200.00 and increases capital by 900.00, from 10,000.00 to 10,900.00. Assets and
liabilities remain unchanged. Negative income, opposite-side temporary balances,
fee expense, and an exact zero capital transfer must be handled correctly.
An all-zero temporary balance needs an audited close/lock but no fabricated
zero-value or unbalanced journal.

Bind ledger inputs and relevant readiness state into the confirmation digest.
Activated subsidiary controls must reconcile. If a bank statement covering the
configured period exists, require the delivered recorded reconciliation to be
complete/current; show unresolved or stale reconciliation as a blocking finding.
Do not fabricate completion or a balancing plug. Do not require a bank statement
for an otherwise supported synthetic ledger with no imported bank data.

The human previews exactly what will close and confirms the digest through a
separate action. Use the existing approval boundary where it fits; an explicit
close-specific approval record is acceptable for the no-journal case. In either
case persist actor, timestamp, exact preview/policy/digest and references, and
enforce the action in application code. No endpoint accepts a client-provided
closing journal or a client-supplied privileged actor.

Use an immutable generated close-calculation evidence artifact to link the
closing journal to its captured input journals/sources and policy. It is a
calculation record, not external recognition evidence and not posting permission.
Bind the artifact digest to the exact preview and confirmation. Do not reuse
typed bank-fee/prepaid source IDs as direct closing journal sources: those
sources require their own recognition effects. The calculation artifact retains
the full trace to them without claiming their economic events again. A no-entry
close can retain its capture/approval without inventing a zero-amount source.
Keep registration/enrollment recovery explicit if that artifact spans the
separate source database; only the final journal/close/lock unit is atomic in the
ledger database. Preparing an artifact must not close or lock the period.

## Atomic persistence and locks

Recompute the preview/readiness binding inside the write transaction before any
close writes. Changed journal, account catalog or relevant bank reconciliation
state invalidates a pending confirmation. Concurrent attempts for the same period
produce one close. Scoped exact retry returns its original recorded result even
after the period is locked; changed payload/actor/key reuse conflicts.

Persist immutable close capture, human approval, closing classification and lock
with the closing journal/event and retry as one unit. Use one concrete versioned
schema; a separate mutable period-status cache is unnecessary. Preserve the
pre-close report capture rather than reconstructing it from a future live store.
Faults at any write or migration point restore the old state completely.

Enforce the date lock at the durable journal seal for every admission path,
including old open connections, direct ledger admission and linked reversal.
Only the exact closing journal being atomically recorded can cross its own lock
boundary. Refuse later postings whose effective dates lie within the closed interval; recorded time
cannot bypass it. Preserve original journals and existing exact posting retries.
New pending drafts do not obtain permission to post merely by predating the lock.

Integrate closing classifications into new Step 21 financial captures. Those three
pre-close statements exclude closing transfers consistently, including capital
and drawings; otherwise income would be counted twice in equity. The separate
post-close trial balance includes the closing entries. Old captures and their
digests remain unchanged; fresh post-close captures still show pre-close income
1,100.00 and ending equity 10,900.00 under the explicit statement policy.

Reopening and prior-period corrections remain unavailable without a later audited
policy. Explain that scope beside the confirmation, while retaining read access
to the closed period, statements and complete approval/journal trace.

## Task 1: close preview, exact confirmation and durable date refusal

**Files:** Concrete closing module/tests; persistence seal and financial-capture
integration; workspace/HTTP/CLI/static. Parent owns docs/CI/browser/delivery.

- [ ] RED: reference close clears every temporary account, capital 10,900.00,
  unchanged assets/liabilities/Cash 9,400.00, post-close columns 11,500.00 each;
  pre-close income 1,100.00 remains reproducible and fresh statements agree.
- [ ] Cover no activity, loss, opposite-side temporary balances, new fee expense,
  zero capital transfer, unsupported period/equity policy and failed readiness.
- [ ] Refuse stale preview after new posting/catalog/reconciliation changes,
  forged journal/actor, absent confirmation and duplicate/conflicting close.
- [ ] Test concurrent exact retry/competing close, every write fault, migration
  rollback, immutable records and original approval/retry/report preservation.
- [ ] Refuse backdated normal posting and reversal through old/direct/service/HTTP
  paths after close, while returning old exact retries without another journal.
- [ ] Add a readable close preview with statement/temporary/source details and a
  distinct Close and lock confirmation. Display the resulting lock and trace.
- [ ] Add `demo-close`; run focused then guarded suite/foundation/all demos/JS/diff,
  parent browser, independent review, commit/push/exact CI before Step 23 exports.
