# Step 24b: auditable project time facts

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 24a.

**Goal:** Retain exactly ten supported service hours for project costing, detect
repeated/overlapping entries and correct time without rewriting its history.

**Architecture:** Extend the concrete management service with immutable time
records and explicit void events. Stable source identity and nonoverlapping
same-worker intervals prevent duplicate counting; pure reports derive active
minutes from captured history. No wage rate or financial posting is implied.

**Spec:** [Step 24 contract](STEP_24_PLAN.md).

## Global constraints

- Integer minutes only; no floating-point hours or implicit rounding. Synthetic
  January dates, validated entity/project, bounded worker/event identifiers.
- A time fact is nonfinancial evidence. It does not prove paid wages, create an
  expense or duplicate an existing ledger allocation. Rates/estimates follow25.
- Source text and client-supplied actor fields cannot authorize corrections.
  Preserve prior time captures and journals, with live connections deferred.

## Supported time policy

Version `service-time-v1` records project, worker, work date, start minute and end
minute within that day, and a stable time-event ID. Use integers0..1439 for start,
1..1440 for end, with end greater than start; duration=end-start. Overnight work
must be explicitly entered as separate daily intervals. Presentation may show
hours as an exact minutes/60 ratio or hours+minutes; never round the stored fact.

The scoped event identity is entity plus worker plus time-event ID, independent of
project/document labels. Exact repetition returns original actor/time; changed
content under the same identity conflicts. For a worker/date, any overlap with an
active recorded interval fails even under a different event/project ID. Adjacent
intervals are allowed. This is an explicit bounded service-time policy; it does
not claim to model simultaneous multi-project work or jurisdictional timesheets.

A correction explicitly voids a specific currently active record with a reason
and audit, then records a new event ID through the normal checks. No mutation or
reactivation of old facts. Historical retry after void returns the original fact
and its current voided status, without re-adding active minutes. If a single
correct-and-replace UI action is offered, both writes must commit atomically;
otherwise show the two explicit recoverable operations honestly.

Keep time events, void events and scoped retry receipts immutable, with SQL
reference checks and application transaction serialization for overlap. Concurrent
same/overlapping entries produce one active interval at most. Failed writes leave
no partial receipt/void. Existing project/journal/history survives migration.

A captured time report states project/worker/date, active intervals, total integer
minutes, void/replacement audit and policy/digest. Capture against the immutable
project definitions; later corrections do not alter old reports. Ten hours means
600 minutes exactly. Reports label time as an operational fact separate from
recorded financial costs and assumed costing rates.

## Task 1: time identity, overlap and audited correction

**Files:** Concrete management service/schema/report tests and workspace/HTTP/
CLI/static integration. Parent owns docs/CI/browser/delivery.

- [ ] RED: two supported five-hour daily intervals give600 minutes; repeat of
  either exact event leaves600 and original audit, with no financial journal.
- [ ] Reject invalid/bool/fractional minutes, zero/negative/overnight interval,
  out-of-period date, absent/cross-entity project, changed event and overlapping
  interval under different IDs/project. Accept adjacent/nonoverlapping intervals.
- [ ] Exercise concurrent duplicate/overlap, explicit void/reason, historical retry
  after void, corrected new event, immutable rows and migration/write rollback.
- [ ] Verify captured totals remain unchanged after later correction and all
  time rows reconcile to active minutes; preserve project/ledger/report history.
- [ ] Add native time-entry, history/void controls and exact minutes/hours display;
  `demo-project-time` prints600 minutes and duplicate rejection without new costs.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, parent browser,
  independent review, commit/push and exact CI before project costing.
