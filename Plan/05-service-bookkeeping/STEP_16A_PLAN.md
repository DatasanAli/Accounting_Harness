# Step 16a: reviewed customer advances

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 15b.

**Goal:** Evidence and approve a 600.00 advance as Cash debit / Unearned credit,
with no revenue and zero control residual.

**Spec:** [Step 16 contract](STEP_16_PLAN.md), 16a branches only.

## Global constraints

All Step 16 contract constraints bind this task: exact money, synthetic inert
evidence, immutable principal/journals, separate bound human approval, shared
cash-event claims, preserved legacy bytes, mandatory 2100 effects and captured
pure reports. No earning tables/policy/routes yet; no live connections.

## Task 1: advance receipt, liability control and local UI

**Files:** New `accounting_harness/advances.py`; existing evidence, review, approval,
ledger, workspace, HTTP, CLI, static UI and focused tests. Parent owns docs/CI.

- [ ] Write failing 600.00/no-revenue and negative evidence/duplicate tests.
- [ ] Add exact prepayment/cash facts, deterministic identity and advance-v1 intent.
- [ ] Add atomic intent/advance schemas, shared cash claims, mandatory approved
  2100 effect, zero-unassigned activation and reversal refusal.
- [ ] Verify legacy bytes, old connections/direct insert guards, failure rollback,
  immutable rows, retry/restart and captured original-name reports.
- [ ] Add registration/proposal/review and Customer advances view; exact server
  amounts and explicit human confirmation remain mandatory.
- [ ] Add demo-advance; run targeted then full required checks/all demos, self-review
  and freeze with report for parent browser/review/commit/exact-CI verification.
