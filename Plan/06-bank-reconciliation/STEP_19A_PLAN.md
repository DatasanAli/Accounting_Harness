# Step 19a: add the bank-fee expense account without rewriting history

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 18, if the account extension is still required.

**Goal:** Make a clearly classified bank-fee expense account available for the next
reviewed adjustment, preserving all old context, approvals, retries and snapshots.

**Reason for this slice:** The original 13-account catalog contains rent, software
and insurance expense but no bank fees. A fee must not be mislabeled as one of
those expenses. Extending the frozen baseline catalog in-place would change
ledger context and invalidate historical bindings.

**Architecture:** Mirror the delivered additive source-enrollment boundary for
one concrete, immutable account extension. Keep the original catalog in
`ledger_context.canonical`; derive the current catalog from baseline plus audited
extensions. No editable chart-of-accounts UI or general catalog framework.

## Global constraints

- Exact synthetic entity and USD; retain the original January period and source
  context. Existing `_context`, source bytes, approval bindings, idempotency
  envelopes and provider/run scopes remain byte-identical.
- New account is `5300`, `Bank Fees Expense`, expense classification, debit normal,
  active, temporary and entity-scoped. In the existing Account metadata set
  `temporary=True`, matching the other expense accounts so later closing includes
  bank fees. Reuse the existing Account validation and metadata
  names rather than inventing another account model.
- Never change, deactivate, relabel, replace or delete an existing account.
  Historical snapshot catalogs remain immutable; no financial journal is created
  by account activation. Existing 13-account fixture remains its historical fixture.
- Only the trusted application selects this fixed account definition. Source text,
  browser fields and agents cannot create arbitrary accounts or permissions.
- Versioned atomic migration and audited enrollment; no live connections.

## Required behavior

Add an immutable account-extension audit containing account code/entity, exact
canonical metadata/digest, actor, recorded timestamp and versioned operation.
The new FK-target account row and extension anchor commit together. Existing
account rows stay unchanged; direct replacement/unaudited insertion fail. Preserve
original account immutability triggers and add extension UPDATE/DELETE/REPLACE
protection. Failed migration/enrollment rolls back schema/version/rows/guards.

Expose a small trusted `ensure_bank_fee_account(actor_id=...)` operation and a
current-catalog read on SQLiteLedger. A repeated request returns original audit
identity/time without extra rows. Conflicting metadata fails. Already-open
connections observe committed enrollment on their next transaction; avoid stale
in-memory catalog caches.

Use the current catalog for new entry/review validation and newly captured ledger
snapshots/reports. Identify concrete call sites that currently use the frozen
baseline catalog; update those that need active account resolution without
changing historical context hashing or old captured objects. Future bank-fee
review chooses 5300 explicitly; receipt/model expense policies retain their
existing bounded account choices. Account availability grants no posting approval.

The localhost bank view can show a separate explained setup action or let the
trusted next-step fee workflow initialize this fixed account visibly. Do not add
a free-form account editor. Show account name/code and original activation audit.

## Task 1: additive fixed account enrollment and preservation

**Files:** Ledger persistence/domain catalog integration, concrete review/report
call sites, workspace/CLI/minimal UI and focused migration/enrollment tests.
Parent owns docs/CI/browser/delivery.

- [x] RED: 5300 unavailable before activation, available afterward with exact
  metadata, unchanged journal count/balances and original baseline context.
- [x] Preserve an existing posted retry, pending approved receipt, invoice/payment
  approval and provider run through activation/reopen; bytes and results unchanged.
- [x] Old captured snapshot/catalog/report remains identical. New captured catalog
  includes 5300; balanced fee proposal passes generic journal account validation,
  while unsupported old recognition policies continue to refuse fee posting.
- [x] Test exact concurrent retry, already-open connection visibility, wrong entity,
  conflicting metadata, direct unaudited/replace attempts, immutable rows and
  faults at migration/anchor/account insertion boundaries.
- [x] Add `demo-bank-fee-account` showing account activation with zero additional
  journals. Run focused then guarded full checks/all demos/JS/diff; freeze for
  parent review/browser/commit/exact CI before reconciliation/fee posting.

Step 19b will use the account for a separately reviewed 10.00 bank-fee journal.
Its reference reconciliation is book1000 - fee10 = 990 and bank940 + deposit200
- outstanding150 = 990. It must never post timing differences or a balancing plug.
