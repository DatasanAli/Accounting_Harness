# Step 14b: recorded partial settlement of vendor bills

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Implement after verified delivery of Step 14a.

**Goal:** Record a separately evidenced 100.00 payment against a posted 300.00 vendor bill, leaving 200.00 payable without recognizing the expense twice.

**Architecture:** Extend the existing immutable payables subledger with payment effects in the approved journal transaction. Bind the target bill and full cash movement into a versioned review intent and recheck remaining outstanding at posting time.

**Tech Stack:** Python standard library, SQLite, integer cents, existing localhost HTML/JS.

**Spec:** [Step 14 contract](STEP_14_PLAN.md), especially its payment branches and 14b acceptance tests. Reuse delivered Step 14a interfaces after inspecting the current implementation.

## Global constraints

- Exact USD integer cents; external amounts use the existing strict two-decimal string parser. Reject floats and booleans.
- Synthetic evidence remains inert; registering payment evidence never sends money or changes a bank account.
- Human approval binds the exact revision, intent, evidence, policy and action. Approval does not reserve unpaid balance.
- Posted journals, bill principal and allocation history are immutable. Managed bill/payment reversal remains explicitly unsupported until linked correction effects exist.
- Preserve old receipt, cash and bill hashes, approvals, retry receipts and provider run context.
- One whole cash movement allocates to one bill. Partial settlement refers to paying part of the bill; splitting one movement among bills is outside this increment.
- Use the shared entity/event/cash_movement claim across policies. Bill evidence is reusable across distinct valid payments; cash movement is not.
- Payment date must be on/after bill recognition and within January 2026. Existing frozen entity/catalog/currency continue.

## Task 1: partial vendor settlement with atomic allocation

**Contract:** Read `Plan/05-service-bookkeeping/STEP_14_PLAN.md` and the delivered 14a report; implement only the 14b branches.

**Files:** `accounting_harness/payables.py`, `review.py`, `approval.py`, `persistence.py`, `workspace.py`, `web.py`, `__main__.py`, static UI and focused payables/HTTP/CLI tests. Parent owns documentation/CI/delivery.

**Interfaces:** Consume Step 14a intent storage, PayablesService, snapshot/report, AP posting guard and source enrollment. Add `bill-payment-v1`, immutable vendor_bill_payments, `.propose_payment`, explicit atomic payment effect handling, and `demo-bill-payment`. The detailed contract defines exact field sets and accounting mappings. Delivered review schema v2 seals only bill-v1 intents; add an atomic, explicitly versioned migration for the bill-payment-v1 seal guard, preserving existing rows and failure rollback.

- [ ] Write failing tests: 300.00 principal minus 100.00 payment leaves 200.00 AP/control total and expense remains 300.00; another 50.00 leaves 150.00; full payment closes a fresh bill.
- [ ] Cover duplicate cash/event, wrong vendor/date/target, over-allocation, unsupported split, forged intent/journal and exact retry/restart. Two approved 200.00 payments racing against 300.00 outstanding allow one only, leaving 100.00; failed attempts leave no orphan effect/journal/retry.
- [ ] Add atomic payables schema migration and replace AP sealing guard to recognize bill and payment effects. Insert effect before posting event with deferred FK; journal/effect/review/retry roll back together on faults.
- [ ] Revalidate outstanding and claims inside the posting write transaction. Historical posted drafts validate against their own effects, so later settlements do not make audit history unreadable.
- [ ] Extend immutable captured reports with payments/cutoffs. A captured pre-payment report remains byte-identical after later payments; AP control equals vendor totals and exposes historical unassigned residuals honestly.
- [ ] Add local payment-evidence/proposal forms and payable balance display. Bill selection and exact amount come from evidence/intent; show evidence and journal before separate human confirmation.
- [ ] Add `demo-bill-payment`, then run relevant tests, guarded suite, foundation, every documented demo and JS/diff checks. Parent verifies the real browser flow, reviews, commits, pushes and checks exact-SHA CI before Step 15a.
