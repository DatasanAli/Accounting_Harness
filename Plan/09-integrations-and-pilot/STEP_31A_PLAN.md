# Step 31a: reviewed owner and prepaid-purchase cash entries

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 30.

**Goal:** Enter the reference month's owner contribution, owner drawing and
prepaid insurance purchase through explicit evidence and human review in the UI.

**Architecture:** A concrete `nonoperating-cash-v1` policy pairs the existing typed
cash movement with a separate classification fact and reconstructs fixed account
mappings. Reuse shared economic claims, draft revision and approval/posting paths.
No arbitrary journal editor or procurement/subsidiary engine.

**Tech stack:** Existing Python/SQLite/source/review services and native forms.
**Spec:** [Step 31](STEP_31_PLAN.md), all global constraints apply.

## Evidence and mapping contract

Add strict schema-v2 `nonoperating_cash_basis` with exactly `event_id`,
`counterparty_id` and `classification` beyond the standard document fields.
Classification is one of `owner_contribution`, `owner_draw` or `prepaid_insurance`.
Reuse the existing `owner_contribution` and `owner_draw` cash purposes. Add the
explicit `prepaid_insurance` purpose to schema-v2 cash movements without changing
old documents or broadening the older expense/service policies.
Both registered/anchored facts must be distinct and match entity, currency,
economic event, counterparty, full amount and January effective date.

| Classification | Cash direction | Debit | Credit |
| --- | --- | --- | --- |
| owner_contribution | in | 1000 Cash | 3000 Owner Capital |
| owner_draw | out | 3100 Owner Drawings | 1000 Cash |
| prepaid_insurance | out | 1200 Prepaid Insurance | 1000 Cash |

Descriptions cannot select accounts. The basis explicitly records the operator's
classification; it is not inferred from a bank memo. Reconstruct the exact journal
and strict intent at save/review/post, bind both evidence roles, and use one
deterministic draft per entity/event. Share the existing `cash_movement` claim
and add a single basis-recognition claim for the same event so a renamed source
or changed template cannot duplicate it. Rejection retains claims; revision
requires the current prior revision and fresh exact approval.

Keep the purchase journal exactly one 1200 debit and one Cash credit of principal.
It must remain valid as the original purchase for Step 20a, including its retained
registered cash source. Coverage and consumption remain separate actions; this
purchase never implicitly starts a schedule or records expense. Preserve the
existing durable reversal dependency once a consumption exists. Owner capital
and drawings are neither revenue nor expense and must classify consistently in
statements, close and cash flow.

Reference UI fixture: owner contribution 10,000.00, drawing 200.00 and prepaid
purchase 1,200.00 produce three separately approved journals; Cash 8,600.00,
Capital 10,000.00 credit, Drawings 200.00 debit and Prepaid 1,200.00 debit. Preparing
all three before approval creates no journals. Then a separate supported January
consumption produces Expense 100.00/Prepaid1,100.00 with Cash unchanged.

## Task 1: complete ordinary reference-month entry paths

**Files:** Focused policy/source/review hooks/tests, workspace/HTTP/CLI/static.
Parent owns docs/CI/browser and delivery.

- [ ] RED: separately evidenced contribution/drawing/purchase produce exactly the
  table above after explicit approvals, with no prior journal side effects.
- [ ] Reject mismatched direction/purpose/classification/facts, unsupported control
  accounts, forged amount/intent, new-ID duplicates and cross-policy cash reuse.
- [ ] Preserve old source/review/run contracts, final seal and period lock guards;
  test rejected revisions, exact concurrent retry and posting rollback.
- [ ] Feed the reviewed purchase into existing coverage/consumption; assert 100.00
  expense/1,100.00 remaining, unchanged cash and reversal dependency refusal.
- [ ] Verify statement/closing/cash-flow classifications use delivered policies
  and captured history stays unchanged; no subsidiary guard is broadened.
- [ ] Add native evidence/proposal forms and `demo-owner-prepaid-cash`. Run focused
  then guarded suite/foundation/all demos/JS/diff; browser, independent review,
  commit/push/exact CI before operational agent tools.
