# Step 17: immutable synthetic bank CSV import

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 16c.

**Goal:** Import a documented fictional statement twice with one unchanged audit
receipt, list exact rows and prove no journal or account balance changed.

**Architecture:** A small bank module parses one CSV format and persists immutable
statements/transactions in the workspace ledger database under its own versioned
schema. Import creates bank records only. Matching and book adjustments follow in
Steps 18 and 19; no generic import framework or live bank adapter.

**Stack:** Python `csv`, SQLite, strict strings/integer cents, existing local UI.

## Global constraints

- Existing synthetic entity, USD and January 2026 workspace. Bank rows are inert
  data; descriptions/reference fields cannot grant permissions or execute code.
- Signed money is integer cents. Parse optional minus followed by the existing
  strict unsigned two-decimal amount string; reject plus signs, whitespace,
  exponent notation, float/bool inputs and negative zero. Movement rows cannot
  be zero; opening/closing balances may be zero or negative.
- Bank identity and ledger identity remain separate. Import never posts, enrolls
  evidence, proposes, approves or changes an existing journal.
- Preserve immutable ledger/review/provider context and prior retry bytes. Bank
  schema initialization and each import are transactional and fail closed.
- No real financial documents, databases or real bank CSV are committed. Committed
  CSV fixtures are explicitly fictional. No new network dependency or external account connection.

## Format and identity

The UI/CLI submits statement metadata separately from CSV rows: `statement_id`,
`bank_account_id`, `period_start`, `period_end`, `opening_balance`,
`closing_balance`, `currency` and `csv_content`. Entity and synthetic scope derive
from the workspace. Map the one selected bank account to existing Cash 1000;
the immutable mapping cannot change after records exist. Do not infer an account
from a bank description. Dates are strict ISO dates within the workspace period,
with start <= end and each booking date included in the statement range.

CSV has exactly these ordered headers:

```csv
bank_account_id,transaction_id,booking_date,amount,currency,reference,description
```

Use the standard CSV parser for quoted commas/newlines. Reject duplicate/unknown
headers, missing/extra cells, invalid UTF-8, unsupported currency, wrong account,
duplicate transaction IDs inside a file, empty IDs and malformed dates/amounts.
Bound request/file bytes, row count and field lengths before persistence. Empty
reference/description are permitted; empty statement rows are valid only when
opening equals closing. Document the chosen finite bounds and useful row errors.

Positive amount increases bank cash; negative decreases it. Require opening plus
all movement cents equals closing exactly. A mismatch returns its exact residual
and creates no bank records or ledger changes.

Statement identity is entity/account/statement ID. Transaction identity is
entity/account/bank transaction ID, independent of statement or import row number.
Preserve canonical metadata/row content, original row order, source digest and
recorded actor/time. Repeated identity/content returns the original receipt;
changed content under either identity conflicts. The same unchanged transaction
may be associated with overlapping statements without creating another bank
transaction. Equal amounts/content with genuinely different transaction IDs stay
distinct. Canonical hashing must include references/descriptions, not money alone.

## Persistence and local workflow

Provide explicit `BankStatementService.import_statement(...)`, statement listing
and detail through the existing workspace/HTTP boundary. Use versioned bank
schema, immutable account mapping, statement headers, transaction rows, ordered
statement membership and audit receipt. Insert the complete import in one write
transaction; a bad last row or injected write failure leaves no partial statement.
Guard UPDATE/DELETE/REPLACE; unique constraints and transactions handle concurrent
imports and content conflicts. No broad dynamic plugin or database registry.

The Bank statements view accepts metadata and CSV text/file content, clearly
labels the fictional format and shows row validation, opening/movements/closing,
stable transaction IDs and import audit. Return decimal strings and canonical
server trace text so large cents remain exact in the browser. Import controls
are distinct from any later match/adjustment actions. Existing request origin,
CSRF and bounded JSON protections continue to apply.

## Task 1: strict parser, durable import and localhost view

**Files:** New `accounting_harness/bank.py`; workspace/HTTP/CLI/static integration;
focused parser, persistence, concurrency and HTTP tests plus a tiny original
synthetic CSV fixture. Parent owns documentation/CI/browser/delivery.

- [ ] RED: import opening 1000.00, +200.00 and -150.00, closing 1050.00; repeat
  unchanged with two transactions/one statement and identical audit receipt.
- [ ] Reject malformed fields/headers, unbalanced statement, wrong account/date,
  same-ID changed content and partial failures without any persisted import.
- [ ] Cover quoted fields, exact negative/large amounts, empty statement, equal
  amount distinct IDs, overlapping statement membership, restart and concurrent
  exact retry/conflict. Verify immutable rows and schema rollback.
- [ ] Assert ledger snapshot/journal count and existing approval/retry bindings
  remain byte-identical across successful, repeated and failed imports.
- [ ] Add native import/list/detail UI and `demo-bank-import`; demonstrate two
  rows, no ledger movement and exact reopening/retry.
- [ ] Run targeted checks then guarded suite/foundation/all demos/JS/diff checks,
  self-review and freeze report for parent browser/review/commit/exact CI.

Next: Step 18 adds explicit human-confirmed one-to-one cash-journal matching and
audited unmatch; ambiguous amount/date/reference candidates remain unresolved.
