# Step 32 verification: separately authorized offline journal export

Local implementation, verification, native browser rehearsal and independent re-review passed. Upload and exact-commit CI are pending.

## Delivered behavior under verification

One ordinary reviewed, posted, unreversed USD cash expense can be mirrored into a persistent synthetic QuickBooks simulator. Supported lines are Cash 1000 credit and Rent 5000 or Software 5100 debit. AP/AR, advances, accruals, closing, reversals, unposted and unreviewed journals are refused.

A persisted preview binds the journal, evidence and local approval references, sandbox realm, account-map/connector policy, effective date, exact request body and digest. Reviewer/owner explicitly authorizes that preview separately from posting. Preparers and agent runs cannot authorize or send. One immutable journal/realm identity supplies a UUID request ID on every attempt.

The separate outbox and simulator files preserve uncertain outcomes across restart. Attempts are capped at three and record next-attempt times rather than sleeping. Timeout does not fabricate a remote ID. Exact parsed readback checks realm, ID, date, currency, mapped accounts, sides and cents. Drift, deletion and later local reversal remain exceptions; old confirmed observations are retained. The local journal and balances do not change.

These are offline contract simulations. There is no OAuth, credential, live network transport or verified Intuit retention/compatibility claim. A real sandbox gate remains deferred.

## Checks

- Final guarded application suite: **879 tests passed** in 121.527s after all fixes.
- All **46** CI demonstration commands passed locally.
- Foundation documentation/roadmap/reference checks passed; rerun after delivery-document updates.
- Native JavaScript syntax and diff whitespace checks passed.
- Focused export tests cover exact large cents, changed preview/mapping, unsupported shapes/policies, permissions, revocation, concurrency, authorization rollback, crash points, rate limiting/caps, malformed readback and preserved history.

`demo-sandbox-export` creates one separately authorized 125.00 expense, simulates a lost creation response, reopens both stores and retries the same request. It confirms **one simulated remote journal**, exact 125.00 per side, with one unchanged local journal.

## Actual browser rehearsal

Used a new ignored synthetic group with alpha/beta entities and owner/preparer/reviewer identities. The rent evidence was registered by an authenticated preparer and posted by a separate authenticated reviewer.

- Keyboard-only login, expansion of the Operations navigation group, Integrations, and Preview journal export.
- Exact payload preview showed 125.00 debit/credit, sandbox realm, mapped account IDs, local approval/evidence references and a digest. Authorization started disabled until its separate checkbox was selected.
- Native authorization, send and readback controls produced confirmed status, one simulated remote ID and unchanged local books.
- A direct authenticated preparer send request returned HTTP 403.
- At an actual 390px viewport, the document width equaled its 375px content width; wide tables scrolled inside their containers.
- Stopped the server process, started a fresh process against the same files and loaded history through the UI. All five prior event records remained byte-for-byte identical; simulator count stayed one and local journal count stayed one.
- Inspection found that the detailed audit view could round large integer cents through JavaScript. Fixed by serving canonical audit JSON as a string and rendering it directly. A native regression asserts `9007199254740993` verbatim, and a full large-journal roundtrip checks `90071992547409.93` with unchanged pre-existing stores.

## Independent review and delivery

Independent review found one Important defect: a drift exception followed by a read timeout and then matching data could return to confirmed without reconciliation. The fix derives unresolved exception state from the entire immutable event history. Two regression sequences first failed, then passed, covering both prior confirmation and initially invalid readback, repeated timeouts, reopen and repeated matching observations. All 19 focused export tests pass (5.389s). Scoped independent re-review approved the fix and ran three targeted tests successfully. No Important or Critical findings remain. The final guarded suite passed all 879 tests in 121.527s.

Commit, remote SHA and exact CI will be recorded after verification. The autonomous campaign proceeds to Step 33a after delivery.

## Rollback and boundaries

Use a new software revert commit if needed. Keep posted journals and immutable outbox/receipt history. Do not delete an uncertain export or issue a fresh request ID to assume it failed. Reconciliation of unresolved/exception outcomes requires an explicit later supported action; no automatic remote reversal is implemented.
