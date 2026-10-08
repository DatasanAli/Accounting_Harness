# Step 32: approved offline journal-export contract

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 31.

**Goal:** Demonstrate exactly one simulated remote journal from an explicitly
approved posted local journal, even if the response is lost and the app restarts.

**Architecture:** Reuse Step 30's scoped QuickBooks sandbox mapping and exact
parser. A durable outbox binds separate human export authorization to immutable
request bytes and a stable request ID. The same local simulator provides create
and readback behavior; no real network write or credentials are introduced.

**Tech stack:** Python standard library, SQLite and authenticated review UI.
**Spec:** [Phase 09](README.md), [QBO read contract](STEP_30_PLAN.md).

## Global constraints

- **Offline contract simulation** only. Local ledger remains authoritative; the
  mirror is a reconciliation aid. A simulated receipt is never remote delivery.
- Ordinary local posting approval is not export permission. Require a separate
  authenticated reviewer/owner action for this exact destination and payload.
- No agent export-authorize or send-money tool. Exporting an accounting journal
  is not permission to transfer money or rewrite either ledger.
- Preserve original journal/approval/evidence/report bytes. Drift creates an
  exception, never an automatic edit, balancing plug or deletion.

## Bounded export policy

Support one ordinary, reviewed, posted, unreversed USD cash expense journal using
non-control accounts Cash 1000 and Rent 5000 or Software Expense 5100. Reject
unposted drafts, closing entries, reversals, AP/AR/advance/accrual control entries,
and other shapes explicitly. Reference expense is 125.00. This narrow export
contract need not pretend it can serialize every subsidiary workflow correctly.

The operator previews local journal/evidence/approval references, exact remote
account mapping, sandbox realm, effective date and complete request bytes. Bind
those plus connector/mapping version to a digest and explicit human authorization.
Recheck posted state, current user grant and unreversed eligibility before the
first send. A changed mapping/destination or altered preview requires new explicit
approval; old authorized bytes are never silently rebuilt from current settings.

Construct POST `/v3/company/{realm}/journalentry?requestid={request_id}` for the
sandbox base only. A UUID-sized request ID is persisted before attempting send,
unique within the realm and no more than 50 characters. One local journal may
have only one export identity per destination; changing the local retry key must
not create another remote journal. Serialize QBO amount JSON as exact decimal
numbers without any binary-float intermediate, and parse readback equally exactly.

Intuit documents request-ID replay of the original response for identical retries
in its [basic field definitions](https://developer.intuit.com/app/developer/qbo/docs/learn/learn-basic-field-definitions#request-id),
checked in the rendered official page on 2026-10-08. Keep the exact request ID and
body on every retry. Do not infer unlimited server retention or guaranteed live
behavior from this synthetic simulation; the actual sandbox gate remains deferred.

Outbox states distinguish prepared/authorized, attempted, uncertain, confirmed
and exception. A timeout after sending is uncertain, not failed-with-no-effect.
Retry only the same authorized request ID/body under the documented contract;
never generate a fresh ID to resolve uncertainty. Crash after simulated creation
but before local receipt must recover the same remote ID. The simulator persists
its request receipt independently so this case survives reopening both sides.

Persist each attempt/status and authorized actor/time. Retries are bounded and
rate-limited with next-attempt times rather than sleeps. A definitive schema/
authorization rejection is an exception. If the outcome cannot be safely resolved,
retain uncertainty for explicit reconciliation; do not claim delivery or retry
non-idempotently. Permission revocation blocks new sends/retries, while history
remains inspectable by authorized readers.

After a returned remote ID, read it through Step 30's parser and reconcile realm,
ID, mapped accounts/sides, effective date, currency and exact totals to authorized
bytes. Mark confirmed only after that readback. A success status with wrong data
or a later changed/deleted remote record produces drift/exception with both
observations preserved. Later local reversal is also shown as divergence; no
implicit remote reversing entry. All local journals/balances remain unchanged.

## Task 1: durable authorization, uncertain outcome and readback

**Files:** Focused export/outbox module/tests, reuse concrete QBO parser/simulator,
workspace/HTTP/CLI/static. Root owns docs/CI/browser and delivery.

- [ ] RED: separately authorize a reviewed 125.00 expense, simulate create plus
  lost response, restart and retry; remote journal count stays one and readback
  reconciles 125.00 debit/credit to the same immutable local journal.
- [ ] Persist exact request/destination/mapping/approval binding before send;
  reject changed approvals, unsupported journals and a second identity/key for
  the same journal/destination. Verify native decimal JSON preserves large cents.
- [ ] Cover crashes before send, after send and before local receipt; 429 and
  transport timeout; bounded retries; uncertain state without a fabricated ID.
- [ ] Reject malformed/wrong-realm/unbalanced/wrong-amount readback, record later
  remote drift and local reversal, and preserve old confirmed receipt bytes.
- [ ] Exercise preparer/agent denial, grant revocation before retry, cross-entity
  requests, concurrent same export, rollback and immutable outbox audit.
- [ ] Add explicit preview/checkbox export simulation and status/readback UI;
  `demo-sandbox-export` prints one simulated remote journal and exact totals.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; browser,
  independent review, commit/push/exact CI. Real sandbox export stays deferred.
