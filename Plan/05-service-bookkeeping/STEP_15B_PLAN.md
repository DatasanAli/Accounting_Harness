# Step 15b: recorded customer collections and aging

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Deliver after verified Step 15a.

**Goal:** Collect 1500.00 against a 2500.00 service invoice, leaving 1000.00 receivable and unchanged 2500.00 revenue, with reproducible aging.

**Architecture:** Bind one full cash receipt to one posted invoice, apply its immutable collection effect in the approved posting transaction, and derive aging from captured invoice/collection/ledger data at a defined cutoff.

**Tech Stack:** Python standard library, SQLite, integer cents, native localhost forms.

**Spec:** `Plan/05-service-bookkeeping/STEP_15_PLAN.md`, collection and aging branches. Reuse delivered 15a interfaces and existing partial payable settlement behavior.

## Global constraints

Follow all constraints in `Plan/05-service-bookkeeping/STEP_15_PLAN.md`: exact USD integer cents/decimal strings, January 2026 current catalog, synthetic evidence only, separate human approval, immutable history, preserved legacy digest/retry/context bytes, semantic claims shared across policies, mandatory AR control effects and reproducible captured reports. No live connections, tax, FX, credit notes, split cash allocation or managed operational reversals. Browser money uses exact decimal strings or server-produced trace text, including integers beyond 2^53.

## Task 1: collection allocation, customer aging and local UI

**Contract:** Read `Plan/05-service-bookkeeping/STEP_15_PLAN.md` for exact receipt/intent/mapping, temporal, concurrency and report requirements.

**Files:** Extend receivables/review/approval/persistence/workspace/web/CLI/static and focused collection/HTTP/CLI tests. Parent owns docs/CI/delivery.

**Interfaces:** invoice-collection-v1; ReceivablesService.propose_collection; immutable customer_invoice_collections; atomic reviewed collection posting; snapshot-based receivables_report with aging; demo-collection.

- [ ] Write failing independent tests for principal250000 minus collection150000 equals100000 AR/outstanding, cash150000, revenue still250000 and residual0; date Jan31/dueJan25 is six days past due.
- [ ] Implement exact full-receipt intent and shared cash event claims. Invoice evidence remains reusable. Require matching customer/currency, posted target, receipt date at/after invoice and amount no greater than remaining. Reject split allocation and overcollection.
- [ ] Add atomic review/receivables migrations and mandatory AR guard extension. Approval does not reserve funds: two approved150000 collections against250000 permit one only, leaving100000. Preserve exact concurrent retries and rollback across effect/journal/review/retry boundaries.
- [ ] Capture collections with the ledger/items in one read transaction. Posted audit history remains valid after later receipts; frozen pre-collection reports/digests never change. Aging current/1–30/31–60/61–90/91+ totals equal outstanding, with due-today and cutoff boundaries checked.
- [ ] Add explicit collection-evidence/proposal forms, collection history and customer aging in localhost UI, preserving exact strings/traces and separate confirmation. No money transfer or customer message occurs.
- [ ] Add demo-collection; verify meaningful invalid, duplicate, race, migration, immutable/reversal, snapshot and HTTP cases; guarded suite/foundation/all demos/JS/diff. Freeze/report for parent browser/review/commit/push/exact CI before Step 16a.
