# Step 15: customer invoices, collections and aging

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Deliver 15a and 15b separately after verified Step 14.

**Goal:** Recognize a separately evidenced 2500.00 service invoice and then a 1500.00 collection, leaving 1000.00 receivable with revenue recognized once.

**Architecture:** Reuse immutable review intents, semantic event claims and the trusted atomic posting boundary. Introduce explicit receivable tables/policies and an AR control guard, with snapshot-based customer reporting. Reuse concrete shared primitives where they prevent actual duplication; do not introduce a configurable workflow engine.

**Tech Stack:** Python standard library, SQLite, integer cents, existing localhost HTML/JS.

**Spec:** [Phase 05](README.md), [operations design](OPERATIONS_DESIGN.md), and the delivered [Step 14 contract](STEP_14_PLAN.md).

## Global constraints

- Exact USD cents and strict decimal amount strings. Reject booleans/floats as money. Browser amounts use decimal strings; bound intents and trace details use exact server-produced text, preserving cents beyond JavaScript's exact integer range.
- Synthetic evidence is data, never permission. Invoice alone does not establish earning; require separate service-completion evidence.
- Human approval binds exact revision, intent, evidence, policy and action. Neither an agent nor a template approves/posts.
- Preserve prior receipt/cash/bill/payment hashes, approval bindings, retry envelopes, source canonical bytes and run context. Use additive, versioned schema migrations with rollback.
- Keep the existing fictional entity, USD catalog and January 2026 posting period. Due dates may be later. No tax, FX, credit notes, split cash allocation or managed operational reversal in these slices.
- Recognition claims use the same entity/event/`service_revenue_recognition` key as earned cash. Collections use the shared `cash_movement` role; template names do not create new economic identities. Rejected drafts retain claims.
- Once AR is activated, every account-1100 posting must carry its matching approved receivable effect. Existing AP guards continue to work independently.
- A report captures immutable ledger/items/allocations/context together and remains pure after capture. Source display names are verified against original approved evidence and retained in the snapshot, including initial-context sources.

## Evidence, identity and intents

Add exact schema-v2 `customer_invoice` fields to the existing base document:
`event_id`, `counterparty_id`, `invoice_number`, `due_date`. Stable customer identity
is `counterparty_id`; `counterparty` is the recorded display name. Preserve invoice
number spelling. Require due date on/after issue date.

Recognition pairs the invoice with `service_completion`, matching entity, event,
customer identity, currency, full amount, issue date and completion date. In this
bounded immediate-invoicing policy, issue and completion dates are equal. Other
timing/partial-recognition cases fail explicitly.

Invoice ID: `invoice:` plus `digest([entity_id, customer_id, invoice_number])`.
Draft ID: `draft:` plus invoice ID. Journal ID: `journal:` plus
`digest([entity_id, draft_id])`. Different source IDs cannot evade invoice identity
or service-event recognition claims. Distinct customers may use the same number.

Policy `invoice-v1` binds exactly:

```json
{"schema_version":1,"kind":"customer_invoice","invoice_id":"invoice:<derived>","customer_id":"customer-1","invoice_number":"I-001","recognition_event_id":"service-1","currency":"USD","principal_cents":250000,"revenue_account":"4000","effective_date":"2026-01-10","due_date":"2026-01-25","evidence_roles":{"invoice":"invoice-source","completion":"completion-source"}}
```

The example placeholder is not accepted input; recompute IDs. Derive exact lines
from evidence: debit 1100 Accounts Receivable, credit 4000 Service Revenue.
Reconstruct the expected intent/journal during direct review validation, so a
caller cannot forge mapping, principal, date, identity or source roles. Exact key
sets and integer types remain mandatory. Keep old-policy typed-evidence denial.

For collection, use `cash_movement` with direction `in`, purpose `settlement`,
matching customer/currency, and a distinct cash event. Allocate its full amount
to one posted invoice selected by the operator. Receipt date is on/after invoice
recognition and in the ledger period. A partial collection pays part of invoice
principal; it does not split one receipt across invoices.

Policy `invoice-collection-v1` binds exactly:

```json
{"schema_version":1,"kind":"customer_invoice_collection","invoice_id":"invoice:<derived>","customer_id":"customer-1","receipt_event_id":"receipt-1","currency":"USD","allocated_cents":150000,"effective_date":"2026-01-20","evidence_roles":{"invoice":"invoice-source","cash":"receipt-source"}}
```

Collection draft identity derives from entity/receipt event, independent of target
invoice, allowing an explicit new revision to correct an unposted target. The
journal identity follows the same entity/draft digest convention. Exact source
IDs are the two role values; original invoice evidence is reusable across valid
collections, while a cash event is consumed once. Debit Cash 1000, credit AR 1100;
never credit revenue on collection.

## Persistence and posting

Add explicit `receivables_schema` and immutable `receivables_context`, with
zero-unassigned-opening policy `receivables-zero-opening-v1`. Activate under the
ledger write transaction only when current AR control less receivable detail is
zero. Capture actor/time/snapshot/entry IDs. Existing unexplained AR blocks setup;
do not invent opening customer items. Historical earlier residuals remain visible.

15a adds immutable `customer_invoices`: invoice/customer/number/event, both source
IDs, principal, revenue account, effective/due dates, approval and posted journal.
Use unique customer/invoice number, recognition event, source identities, approval
and journal; effect-to-posting-event FK is deferred. No mutable balance/status
columns. 15b adds immutable `customer_invoice_collections`: receipt event, invoice,
cash source, allocated cents, effective date, approval and posted journal.

Use the delivered intent side table and digest envelopes. Add an explicit atomic
review-schema migration whenever the intent seal's known policy list grows.
Do not update old revision rows or append null fields to old hashes. Keep
rejections and exact retries compatible.

The trusted approval-post branch inserts the concrete effect before journal
sealing. The effect must match its approved intent/current revision and intended
journal. A mandatory posting-event guard checks exactly the expected AR/counterpart
lines, amount, date and evidence identities. It applies to ordinary ledger
admission, generic review posting, old connections and private insertion calls;
there is no caller bypass. Preserve existing post retry behavior before fresh
mutation checks. A failure at effect/journal/review/retry boundaries rolls back
the whole unit; an orphan effect cannot commit.

For new collection posting, recompute outstanding inside the write transaction:
principal minus already posted collections. Require positive full receipt amount
no greater than remaining. Approvals do not reserve funds. Historical posted
invoice/collection revisions validate against their own linked effects, remaining
readable after later activity. New attempts recheck claim ownership and current
AR reconciliation.

Explicitly reject managed invoice/collection reversal until a linked inverse
allocation workflow exists. Ordinary unrelated reversal and historical exact
retries remain valid. Direct inverse AR journals cannot bypass the active guard.

## Reports and local workflow

Provide `ReceivablesService` with the analogous explicit initialization,
`ensure_enabled`, `propose_invoice`, `propose_collection` (15b only) and `snapshot`
interfaces; pure `receivables_report(snapshot, as_of=...)`; and a required concrete
posting hook. Keep report capture in a single ledger read transaction.

Filter invoice and collection effects by their linked journals in the captured
snapshot and cutoff. AR control is debit minus credit in account 1100. Outstanding
is principal minus included collections. Customer detail totals must equal AR;
report signed unassigned residual rather than hiding it. Retain policy, cutoff,
included journal IDs and snapshot/report digests. A frozen earlier report must
remain byte-identical after later collections or source registrations.

15b adds aging of outstanding balances by due date: current (not yet past due,
including due today), 1–30 days, 31–60, 61–90 and 91+ past due. A January 25 due
date at January 31 is six days past due. Buckets and customer totals sum exactly
to outstanding; later collections cannot alter a captured earlier aging report.
Older buckets may remain zero in the bounded January workspace.

Add native invoice/completion registration and proposal forms, then collection
cash-evidence/proposal forms in 15b. Select policies from stored drafts. Browser
inputs cannot override derived actor, principal, accounts, intent or policy.
Display exact evidence, intent, journal and due date before separate confirmation.
Show invoices/customer totals/AR residual and, in 15b, collection history/aging.
Persisted source/approval/journal references remain inspectable. Preparation and
recording a collection never send money or customer messages.

## Independent acceptance and delivery

15a: pending proposal has zero journals/items; approval creates AR debit 2500.00
and revenue credit 2500.00, principal/outstanding 2500.00, zero paid and zero
residual. Refuse missing completion, wrong customer/event/amount/date, duplicate
invoice/service event (including earned-cash use), forged intent/journal, unbound
source and unsupported current policy. Verify migration/legacy bytes, activation
residual, old-connection/generic/direct-SQL bypass denial, atomic rollback,
immutable history/snapshot and managed reversal refusal. Add `demo-invoice`.

15b: 1500.00 collection leaves AR/outstanding 1000.00, cash debit 1500.00, revenue
still 2500.00, zero residual. January 31 aging places the remainder six days past
due. Refuse over-allocation, wrong customer, early receipt, reused cash event,
partial receipt allocation and unposted target. Two approved 1500.00 collections
against 2500.00 allow only one under concurrency, leaving 1000.00. Verify exact
concurrent retry, restart, source/intent/approval binding, every atomic write fault,
pre-collection cutoff and frozen report preservation. Add `demo-collection`.

Each slice gets targeted meaningful tests, guarded full suite, foundation, all
prior demos plus its new demo, JS/diff checks, actual localhost browser review,
independent code review, commit/push and exact-SHA GitHub CI verification. These
are planned acceptance checks until recorded in the slice's verification file.
