# Step 20a: supported prepaid insurance consumption

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 19c.

**Goal:** Recognize January insurance expense 100.00 from an evidenced annual
prepaid principal 1,200.00, leaving 1,100.00 without another cash movement.

**Spec:** [Step 20 adjustment contract](STEP_20_PLAN.md).

**Architecture:** Bind one immutable coverage policy to an existing posted
prepaid purchase. A concrete reviewed allocation creates a consumption effect and
the fixed Insurance Expense 5200 debit / Prepaid Insurance 1200 credit journal.
No general allocation engine or automatic posting scheduler.

## Global constraints

All Step 20 constraints apply. The original purchase must already be posted and
unreversed; a draft, source amount alone or description is insufficient. A policy
and a pending approval reserve no consumption. Posting checks cumulative use and
original validity inside the journal transaction. Cash remains unchanged.

## Evidence and allocation contract

Add a strict synthetic `prepaid_coverage` document. Besides standard source fields,
it has exactly these additional string fields: `original_journal_id`,
`original_source_id`, `coverage_start`, `coverage_end` and `allocation_policy`.
The latter is the fixed `equal-months-cents-v1` policy. Its amount is the full
original principal. The original journal must belong to this entity/currency,
contain exactly one 1200 debit and one 1000 credit of that principal, and retain the
named source. That source's canonical identity/content must be registered and
anchored. Validate all references from storage, not caller-supplied journal data.

Coverage starts on the first day of a calendar month and ends on the last day of
a calendar month, one through 120 full months later inclusively. The original
purchase must be effective on or before coverage starts. Coverage metadata can
extend beyond January, but this delivery posts only an allocation inside the
configured ledger period. Partial-month or daily allocation is explicitly
unsupported. Source descriptions are inert, including apparent instructions.

For N covered months and integer principal P, use quotient/remainder: each month
receives P//N cents, with one extra cent in each of the earliest P%N months. The
total is exactly P; no float or silent rounding. An allocation of zero is shown
as no journal required and cannot create a zero-value line. The requested month
must be covered and its journal effective date is that month's last day.

The first successfully prepared policy fixes one coverage identity/content for
the original purchase journal. Reusing it is allowed; changing coverage or using
a second source to redefine the same purchase fails clearly. A unique semantic
claim by entity/original purchase/month prevents duplicate consumption under
another document ID, policy label or draft. Correction uses a new revision of
that deterministic draft and a new approval, preserving the claim.

`prepaid-consumption-v1` approval binds the original journal/source/content,
coverage policy/digest, allocation month, exact integer amount and evidence roles.
Independently reconstruct the expected proposal at save, approval and post; do
not trust an amount supplied by the browser. Require exact two-line account/date
mapping, and the shared strict integer-intent validation used by other policies.

## Persistence and accounting boundary

Persist immutable coverage anchors and consumption effects with versioned atomic
initialization. Effects link to the exact current approval and eventual posting
event. Evidence registration/enrollment is separate and already complete; its
anchored references are bound into approval. The effect, journal, review link and
retry commit together.
Validate the current approved revision again at final journal sealing. Reject
orphan effects, forged intent, changed shape and cumulative use above principal.

New entries that cite an anchored coverage source must have its matching approved
effect. Preserve the existing generic ledger's documented semantic boundary;
this is not a claim that arbitrary source-free account movements can be assigned
to a specific insurance policy. Report policy principal minus supported
consumption beside the 1200 control balance and its unassigned residual. An
unexplained reduction cannot authorize further consumption or be hidden in the
report. Tests must cover an unrelated direct 1200 movement and honest residual
handling rather than silently counting it as a supported policy allocation.

Once a consumption is posted, refuse reversal of its original purchase and refuse
generic reversal of that managed consumption until a linked correction policy
exists. Enforce this dependency durably for already-open connections and linked
reversal insertion, not only through a new UI check. If the purchase is reversed
before consumption, a pending approval becomes invalid and cannot post.

Captured reports include policy/original references, principal, allocations by
effective date, consumed/remaining amounts, 1200 control/residual and explicit
policy/version/digests. Render purely from a captured ledger/effect/policy state.
Later allocations or registry changes do not rewrite an earlier captured report.

## Task 1: reviewed monthly consumption and traceable remaining asset

**Files:** New focused prepaid adjustment module/tests; strict source/review/
approval hooks, ledger reversal dependency guard, workspace/HTTP/CLI/static.
Parent owns docs/CI/browser/delivery. Use the existing posted-purchase primitive;
do not build an unrelated procurement feature in this slice.

- [ ] RED: post a synthetic 1,200.00 purchase using the supported ledger primitive,
  bind January 1–December 31 coverage, prepare 100.00 January consumption, and prove no
  additional journal before exact human confirmation. After posting: expense 100.00,
  prepaid 1,100.00, cash unchanged and no control residual.
- [ ] Independently check quotient/remainder allocation including uneven cents,
  leap-year month boundaries, invalid partial coverage and zero allocations.
- [ ] Refuse missing/unposted/reversed/wrong-account/changed-amount originals,
  unsupported dates, conflicting coverage, repeated month under another identity,
  stale revisions, forged lines/intent, excess use and intervening reversal.
- [ ] Verify exact concurrent retries, competing same-month proposals, write faults,
  final-seal supersession, dependency reversal refusal, immutable records and
  atomic initialization with historical AP/AR/advance approval bytes unchanged.
- [ ] Test current control/residual honestly and frozen prior capture/digest after
  later activity. Return exact server decimal/canonical trace strings to the UI.
- [ ] Add coverage/consumption preparation and remaining-asset UI with the existing
  separate review/confirmation. Add `demo-prepaid-consumption` with the 100.00/1,100.00
  example, duplicate refusal and preserved original cash movement.
- [ ] Run focused then guarded full checks/all demos/JS/diff; freeze for parent
  browser and independent review, then commit/push/exact CI before Step 20b.
