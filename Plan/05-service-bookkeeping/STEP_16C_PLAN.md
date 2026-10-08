# Step 16c: preserve current approval at the payable journal seal

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 16b, before Phase 05 acceptance.

**Goal:** Bring the existing payable SQL seal up to the current approval boundary
already verified for receivables and advances, without changing valid accounting
results or historical receipts.

**Evidence for this bounded follow-up:** Step 15a review reproduced an older
approval becoming stale between effect insertion and journal sealing. That AR gap
was fixed and regression-tested. Inspection of `payables.py` shows the older AP
seal still checks journal shape but checks latest approval only at effect insert.
Step 14b also left a recorded minor finding: its migration transforms stored
trigger SQL with unchecked string replacement. Resolve these concrete boundaries
before moving beyond service operations; this is not a whole-repository audit.

## Global constraints

- Preserve exact money, evidence/intent binding, immutable bill/payment history,
  current balances, original context, approvals, retry bytes and captured reports.
- No new accounting operation, UI permission, live connection or managed reversal.
  Valid bill recognition and partial settlement retain their existing behavior.
- Existing published payables schema 2 requires an explicit atomic migration;
  changing only fresh-database SQL does not protect existing workspaces.
- No broad workflow framework or unrelated refactor. Reuse concrete current-
  approval predicates only where effect insertion and seal actually share them.

## Task 1: reproduce the AP ordering gap and migrate its guard

**Files:** `accounting_harness/payables.py` and focused payable/payment migration,
approval-ordering and rollback tests. Parent owns docs/CI/delivery. Existing bill
and payment demos remain the user-facing demonstrations; no new UI is required.

- [ ] First reproduce, with real guards enabled: approved bill/payment effect
  inserted, then a newer rejected or pending draft revision, then journal seal.
  A stale approval must fail and roll back the entire write unit. Reuse the
  delivered AR regression method; do not weaken guards to fabricate a failure.
- [ ] Install explicit versioned AP trigger SQL that rechecks current pending
  revision, approval digest, exact bound operation and journal identity at final
  sealing as well as effect insertion. Retain exact lines/date/source checks.
- [ ] At the payment boundary, verify the required remaining-principal check
  against the final transaction state as well as the service precheck, including
  approved competing effects; no negative outstanding or orphan can commit.
- [ ] Replace the unchecked SQL-fragment transformation with an explicit known
  definition or validated versioned construction. Do not infer migration success
  from a `.replace` call that might have matched nothing.
- [ ] Prove atomic schema migration rollback, unchanged historical row bytes,
  old open connection enforcement, posted exact retries, pending old approvals,
  normal bill/payment posting and the original two-approved-payment race.
- [ ] Run focused payable/payment coverage, then guarded suite/foundation/all
  existing demos and diff checks. Freeze a concise report for independent review,
  commit/push and exact-SHA CI. Record the two prior review observations as resolved
  only after their regressions and migration checks pass.

If a focused reproduction disproves a suspected gap, report the exact evidence
and preserve the working guard; do not introduce changes just to satisfy a guess.
