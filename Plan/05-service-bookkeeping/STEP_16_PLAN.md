# Step 16: customer advances and supported earning

**Goal:** Record 600.00 received before service as a liability, then recognize
200.00 from separately evidenced completion, leaving 400.00 unearned.

**Architecture:** Extend the existing typed evidence, immutable intent, shared
event claims and human posting boundary with explicit advance effects. Deliver
16a receipt and 16b earning separately. Reuse concrete common helpers where they
remove actual repetition; do not add a configurable workflow framework.

**Stack:** Python standard library, SQLite, exact integer cents, native localhost UI.

## Global constraints

- Existing fictional entity, USD catalog and January 2026 posting period.
  Strict decimal strings and integer cents; reject float/bool money. Browser
  amounts and intent/trace text must preserve cents beyond 2^53.
- Cash receipt alone does not establish earning. Evidence remains inert data;
  human approval binds exact revision, intent, evidence, policy and action.
- Preserve prior canonical source bytes, revision hashes, approval bindings,
  retry envelopes, provider scope and frozen ledger context. Migrations are
  additive, versioned and atomic; failed initialization restores prior state.
- Share `cash_movement` and `service_revenue_recognition` event claims with cash,
  invoices and settlements. Rejected drafts retain claims. Changing document
  identity cannot reuse the same economic event under another policy.
- Immutable journal-linked effects; no mutable balance columns. Every active
  2100 posting requires the matching approved advance effect. AP/AR guards remain
  independent. Managed advance/earning reversals remain unsupported until linked
  inverse effects are implemented.
- No live model/bank/account connection, refund, tax/FX, multi-currency, split
  movement/completion allocation or real-data acceptance claim.

## Evidence and identities

Add strict schema-v2 `customer_prepayment`, using existing base fields plus
`event_id`, `counterparty_id`, `contract_id`. It records one fully prepaid service
obligation; amount is principal and date is receipt date. Pair it with existing
`cash_movement` direction `in`, purpose `customer_advance`, with matching entity,
customer, event, currency, amount and date. Different display names do not replace
stable identity checks; retain the original recorded name for reporting.

Bounded 16a supports one advance per entity/customer/contract. A further deposit
against that contract requires a later explicit extension and fails here rather
than creating an unexplained second principal. Advance identity is `advance:`
plus digest of `[entity_id, customer_id, contract_id]`; draft is `draft:` plus
advance ID, and journal follows the existing entity/draft digest convention.

16b adds strict schema-v2 `advance_completion`, with existing base fields plus
`event_id`, `counterparty_id`, `contract_id`, `completion_date`. Base date equals
completion date. Its amount is the value earned by this completion, not total
contract principal. Completion must match the selected posted advance's customer,
contract and currency and occur on/after receipt within the posting period.
The full completion amount allocates to one advance. Its event consumes the same
`service_revenue_recognition` role used by ordinary service completion; document
kind never creates a separate recognition namespace.

## Exact intents and journals

Policy `advance-v1` binds exactly:

```json
{"schema_version":1,"kind":"customer_advance","advance_id":"advance:<derived>","customer_id":"customer-1","contract_id":"contract-1","cash_event_id":"advance-cash-1","currency":"USD","principal_cents":60000,"effective_date":"2026-01-22","evidence_roles":{"prepayment":"prepayment-source","cash":"cash-source"}}
```

Derive debit Cash 1000 and credit Unearned Revenue 2100 from the two facts. An
advance cannot pass the earned-cash policy, even if its description claims the
service is complete. Receipt registration and proposal create no liability or
journal before human approval.

Policy `advance-earning-v1` binds exactly:

```json
{"schema_version":1,"kind":"customer_advance_earning","advance_id":"advance:<derived>","customer_id":"customer-1","contract_id":"contract-1","completion_event_id":"completion-1","currency":"USD","earned_cents":20000,"effective_date":"2026-01-31","evidence_roles":{"prepayment":"prepayment-source","completion":"completion-source"}}
```

Derive debit Unearned Revenue 2100 and credit Service Revenue 4000. Reconstruct
intent and journal independently during review validation, checking exact fields,
types, identity, evidence roles, amount, date, accounts and source digests.
Earning draft identity derives from entity/completion event, independent of target
advance. An unposted target correction is a new revision needing new approval.
Original prepayment evidence is reusable across distinct supported completions.

## Persistence and reports

Add explicit `advances_schema` and immutable `advances_context` with
`advances-zero-opening-v1`. Activation under the ledger write transaction requires
zero unassigned current account-2100 balance; retain actor/time/snapshot/entry IDs.
Do not manufacture obligations for historical direct liability entries. Report
historical unassigned control residuals honestly.

16a adds immutable `customer_advances`: customer/contract/cash event, both source
IDs, principal, effective date, approval and journal. Unique customer/contract,
cash event/source, prepayment source, approval and journal prevent duplicates.
16b adds immutable `customer_advance_earnings`: completion event/source, target,
earned cents/date, approval and journal. Effect-to-posting-event links are deferred
foreign keys, so an orphan cannot commit.

Extend the known review-intent policies through explicit versioned migration.
The trusted posting branch inserts the effect before sealing the journal within
the same transaction as review posting and retry storage. SQL guards check the
approved current intent and exactly matching two journal lines, date and sources;
old connections, generic admission and direct inserts cannot omit the effect.
Use explicit trigger definitions or checked replacements in migrations. Recheck the current approved revision and bound intent at the final posting-event seal as well as effect insertion; a later rejection/revision within the same transaction must prevent sealing and roll back the unit.

Earning posting rechecks remaining principal under `BEGIN IMMEDIATE`. Approval
reserves nothing. Positive earning cannot exceed principal minus prior posted
earnings. Two approved 400.00 completions against 600.00 allow one, leaving 200.00.
Exact retries return their historical result before fresh mutation checks.
Historical posted drafts validate against their own effects, remaining readable
after further earning. Every effect/journal/review/retry fault rolls back together.

Provide explicit `AdvancesService.ensure_enabled`, `.propose_advance`,
`.propose_earning` (16b), `.snapshot` and pure `advances_report(snapshot, as_of=...)`.
Capture ledger, principal/earnings, activation and original verified customer
names in one read transaction, including baseline known sources. Report principal,
earned, remaining, customer totals, account-2100 credit-minus-debit control,
signed residual, cutoff, policy, journal references and snapshot/report digests.
Captured earlier reports never query current registry/ledger state. Version any
report representation changes explicitly; preserve captured legacy representation.

## Localhost behavior and acceptance

16a adds paired prepayment/cash registration, reviewed advance proposal and a
Customer advances view. 16b adds completion registration and selection of a
posted advance, showing evidence, exact intent and journal before confirmation.
Backend derives actor/policy/mapping; browser cannot choose posting permissions.
Only recorded cash is represented; no money is transmitted.

16a: before approval, zero journal/liability effects. After approval, Cash debit
600.00, Unearned credit 600.00, revenue zero, principal/remaining 600.00, residual
zero. Test mismatched facts, duplicate contract/cash, shared claims, forged intent,
legacy bytes, initialization/transaction rollback, control bypasses, immutable
reports, exact restart/retry and managed reversal refusal. Add `demo-advance`.

16b: completion 200.00 leaves unearned/remaining 400.00, revenue 200.00 and Cash
unchanged 600.00. Further valid earning can close the advance. Test duplicate
recognition across cash/invoice/advance, wrong customer/contract/date, unsupported
split, over-earning, competing approvals, concurrent exact retry, stale/corrected
intent, historical readability, cutoff/frozen report and all write faults. Add
`demo-advance-earning`.

Each delivery runs meaningful focused tests, guarded suite, foundation, all demos,
JS/diff checks, real browser confirmation, independent review, commit/push and
exact-SHA CI. The parent owns documentation, CI, browser and delivery; application
implementation begins only after the preceding verified delivery.
