# Step 15a: reviewed customer invoice recognition

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Deliver this slice before collection/aging.

**Goal:** Recognize an evidenced 2500.00 service invoice with an immutable customer receivable and zero AR control residual.

**Architecture:** Explicit invoice-v1 intent and shared service-recognition claims feed the existing human approval/post boundary; the invoice effect and AR journal commit together. Preserve existing payable workflows.

**Tech Stack:** Python standard library, SQLite, integer cents, native localhost forms.

**Spec:** `Plan/05-service-bookkeeping/STEP_15_PLAN.md`, 15a branches only. Collection descriptions establish the next delivery's boundary; do not implement collection tables, routes, policy or aging yet.

## Global constraints

Follow all constraints in `Plan/05-service-bookkeeping/STEP_15_PLAN.md`: exact USD integer cents/decimal strings, January 2026 current catalog, synthetic evidence only, separate human approval, immutable history, preserved legacy digest/retry/context bytes, semantic claims shared across policies, mandatory AR control effects and reproducible captured reports. No live connections, tax, FX, credit notes, split cash allocation or managed operational reversals. Browser money uses exact decimal strings or server-produced trace text, including integers beyond 2^53.

## Task 1: invoice recognition, control reconciliation and local UI

**Contract:** Read `Plan/05-service-bookkeeping/STEP_15_PLAN.md` for exact schema/identity/intent/mapping and acceptance values. Inspect delivered Step 14 interfaces before coding.

**Files:** New `accounting_harness/receivables.py`; extend sources/review/approval/persistence/workspace/web/CLI/static; add focused receivables, HTTP and CLI tests. Reuse concrete shared primitives where genuinely repeated; no generic workflow framework. Parent owns Plan/README/AGENTS/CI and delivery.

**Interfaces:** Typed customer_invoice plus service_completion; explicit invoice-v1; ReceivablesService.ensure_enabled/propose_invoice/snapshot; pure receivables_report; required concrete approved-post effect; demo-invoice.

- [ ] Write failing tests for AR debit 250000/revenue credit 250000, zero pre-approval effects, customer outstanding/control250000 and zero residual, exact retry/restart and independent cutoff/snapshot results.
- [ ] Add strict evidence and intent reconstruction; identity and shared service_revenue_recognition claims reject duplicate invoice/service recognition across earned-cash and invoice paths. Preserve legacy weak-policy denial for typed facts.
- [ ] Add atomic review migration for the known invoice intent policy, zero-unassigned-opening AR activation and immutable invoice effects. SQL sealing requires matching approved effect, journal/date/two source identities and exact AR/revenue lines, including direct/old-connection attempts.
- [ ] Test old receipt/cash/bill/payment bytes and approvals, missing/forged/stale intent/evidence, migration faults, every new atomic write boundary, immutable rows, historical residuals and unsupported managed reversals. Existing AP remains independent and reconciled.
- [ ] Capture original customer names verified against approved evidence, including baseline known sources; retain immutable detail in reports. Later registrations/names must not rewrite frozen reports.
- [ ] Add localhost registration/proposal/review and Customer invoices view with exact evidence/due date/amount/control residual and trace links. Actor/policy/mapping derive server-side; approval remains explicit.
- [ ] Add demo-invoice, run relevant tests then guarded suite/foundation/all demos/JS/diff checks, report red/green/results/limits and freeze for parent browser/review/delivery. Continue 15b only after exact-SHA CI success.
