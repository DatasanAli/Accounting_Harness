# Step 14a: reviewed vendor bill recognition

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Implement this bounded task before Step 14b.

**Goal:** A separately evidenced 300.00 software bill becomes a reviewed expense/AP journal and an immutable vendor payable with zero control-account residual.

**Architecture:** Extend existing review revisions with optional digest-bound operation intents. Insert the bill effect and approved journal in one ledger transaction, enforcing the AP control/subledger relationship after explicit zero-opening activation.

**Tech Stack:** Python standard library, SQLite, integer cents, existing localhost HTML/JS.

**Spec:** [Step 14 contract](STEP_14_PLAN.md), sections 1–12. Implement the 14a branches only. Payment descriptions define compatibility boundaries for the next delivery; no payment tables, policy, API or form belong to 14a.

## Global constraints

- Exact USD integer cents; external amounts use the existing strict two-decimal string parser. Reject floats and booleans.
- Synthetic documents only. Source text cannot grant permission; a proposal never approves or posts itself.
- Receiving a bill alone cannot establish expense incurrence. Require the separately typed incurrence fact.
- Preserve old journal snapshots, approval bindings, run context and idempotency digests; do not reconstruct their context from the growing registry.
- Posted entries and source histories remain immutable. Managed payable corrections are explicitly unavailable until a linked correction workflow exists.
- Keep provider runs on `review-v1` and their source-use guard. New operation policies are application-owned and selected from persisted draft policy.
- Remain within January 2026 and the existing 13-account catalog. Due dates may extend beyond the ledger period.
- Reuse Step 13b `operation_claims` and its economic roles. Bill recognition claims `expense_recognition` on the same event used by cash expenses; never scope that identity by policy name.

## Task 1: vendor bill recognition, review and local UI

**Contract:** Read `Plan/05-service-bookkeeping/STEP_14_PLAN.md` sections 1–12; implement only 14a. Global constraints above remain binding.

**Files:** `accounting_harness/payables.py` (new), `sources.py`, `review.py`, `approval.py`, `persistence.py`, `workspace.py`, `web.py`, `__main__.py`, static UI, `tests/test_payables.py` (new), affected source/review/HTTP/CLI tests. Parent owns Plan, README, AGENTS and CI edits.

**Interfaces:** Consume delivered source enrollment, typed incurred-expense evidence, semantic operation claims, stored-policy routing and existing atomic approval/post transaction. Produce explicit `bill-v1` intent validation; `PayablesService.ensure_enabled`, `.propose_bill`, `.snapshot`; `prepare_payable_post`; pure `payables_report`; and `demo-bill`. The full contract gives exact fields and transaction order.

- [ ] Write failing behavior tests for the independent 30000-cent expense/AP outcome, zero pre-approval effects, bill identity and cross-policy duplicate recognition, invalid evidence, intent binding, old digest compatibility, AP activation/bypass guards, atomic rollback, immutable history and unsupported managed reversals.
- [ ] Implement exact typed `vendor_bill` evidence and deterministic bill identity/journal/intent. Do not infer incurrence from text, due date or invoice amount.
- [ ] Add optional immutable operation intent side table and atomic review schema migration. Missing/unexpected/unbound intent blocks approval. Legacy hashes and retry envelopes remain byte-compatible; rejected bill revisions retain the intent.
- [ ] Add payables activation and immutable bill effect table, approved atomic posting hook and mandatory AP posting-event guard. An already-open ledger connection cannot bypass it. Existing unassigned AP blocks activation without inventing opening bills.
- [ ] Add single-snapshot payable report with cutoff, vendor/bill detail, control total, subledger total, signed unassigned residual and reproducible digest. Historical unmanaged residuals are shown honestly.
- [ ] Add native evidence/proposal forms and payables list through existing localhost HTTP controls. Derive actor, amount, accounts and policy server-side. Show both documents and exact proposal before separate human confirmation.
- [ ] Add `demo-bill`: 300.00 software expense/AP, outstanding 300.00, zero residual, traceable evidence and approval, no network.
- [ ] Run targeted tests, then foundation/guarded full suite/all demos; report commands/results, compatibility checks and limitations for parent review. Parent performs browser flow, final delivery and exact-SHA CI.

No actual payment is sent. Step 14b records payments that occurred; its separately verified implementation follows this delivery.
