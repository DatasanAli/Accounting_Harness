# Step 16b: earn customer advances from completion evidence

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 16a.

**Goal:** Earn 200.00 of a 600.00 advance, leaving 400.00 unearned and unchanged cash.

**Spec:** [Step 16 contract](STEP_16_PLAN.md), 16b branches.

## Global constraints

All Step 16 constraints apply. Full completion value allocates to one posted
advance for the same customer/contract, within January and on/after receipt.
Share service_revenue_recognition claims across workflows. Approval reserves no
balance; posting rechecks remaining. Preserve old history/bytes; no live connection.

## Task 1: reviewed earning with atomic allocation and reports

**Files:** Extend advances/evidence/review/approval/workspace/HTTP/CLI/static and
focused tests. Parent owns docs/CI/browser/delivery.

- [ ] Write failing 200.00 earning / 400.00 remaining tests and competing approved
  400.00 allocations against 600.00; exactly one may post.
- [ ] Add typed advance_completion and exact advance-earning-v1 intent, independent
  reconstruction and shared service claims. Reject wrong contract/date and reuse.
- [ ] Add versioned immutable earning effects and mandatory matching 2100 guard;
  post remaining checks, allocation/journal/review/retry in one transaction.
- [ ] Cover migration/legacy preservation, stale intent, concurrent retries,
  every write fault, historical reads, full earning, cutoff and frozen reports.
- [ ] Add completion/earning UI, exact preview and explicit human confirmation;
  retain principal/earned/remaining and control reconciliation in captured report.
- [ ] Add demo-advance-earning; verify required checks/all demos and freeze for
  parent browser/review/commit/push/exact-CI verification before Step 16c payable-seal hardening and then Step 17.
