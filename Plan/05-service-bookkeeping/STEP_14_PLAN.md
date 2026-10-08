# Step 14 Vendor Bills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Implement the independently verifiable substeps in order; each receives review and delivery checks.

**Goal:** Record an evidenced 300.00 vendor expense bill, then record a 100.00 cash settlement that leaves 200.00 payable, through the existing explicit human approval flow.

**Architecture:** Two explicit policies, `bill-v1` and `bill-payment-v1`, bind a small immutable operation intent into each new revision digest. Posted bill/payment rows share the journal transaction and are mandatory for new AP postings after payables activation. Retain existing receipt/cash policies and all their historical bytes.

**Tech Stack:** Existing Python, integer cents, SQLite and localhost forms. No dependency, bank connection, model call, or general workflow framework.

**Spec:** `Plan/05-service-bookkeeping/README.md`, `Plan/05-service-bookkeeping/STEP_13B_PLAN.md`, [the daily operations design](OPERATIONS_DESIGN.md).

## 1. Bound the deliveries

Step 14a includes bill evidence, intent binding, immutable vendor bill records, AP activation/enforcement, reconciliation and the bill UI. Step 14b adds recorded payment evidence, one payment allocated in full to one bill, and its UI. A partial settlement means paying part of the bill: a 100.00 payment against 300.00 principal. Splitting one payment across bills, vendor credits, taxes, currency conversion, bill amendments after posting and operational reversals are excluded.

The frozen January 2026 ledger, existing chart and synthetic-only rules continue. Due dates may be later than January; recognition/payment effective dates must fall within the ledger period. New account or period support is not part of this slice. Future 15/16 can reuse immutable revision intents and transaction ordering, but should introduce their own explicitly named tables/policies rather than a polymorphic open-item framework now.

Read current source at implementation time. Step 13a delivered ledger schema v3 and additive evidence enrollment; Step 13b provides typed evidence, explicit cash policy routing and shared economic-event claims. Reuse those APIs. This step adds a separate review schema migration and payables schema; it must not rebuild historical ledger context.

## 2. Files and responsibilities

- `accounting_harness/payables.py` (new): bill/payment schema, strict intent validation, deterministic journal builders, draft submission, transaction-internal effect insertion, immutable report projection.
- `accounting_harness/review.py`: optional intent persistence/digest binding; explicit payables policy dispatch; ordinary revision/rejection/retry lifecycle stays shared.
- `accounting_harness/approval.py`: a required branch for the two known payables policies inside `post`; existing approval and post retry envelopes stay unchanged.
- `accounting_harness/persistence.py`: a clear public reversal denial for managed payables, preserving legacy exact retries. The DB trigger additionally blocks ledger admission from bypassing payables.
- `accounting_harness/sources.py`: exact synthetic `vendor_bill` v2 fields. Existing incurrence and cash schemas from 13b remain authoritative.
- `accounting_harness/operations.py`: share 13b's economic-event usage claim with bill recognition/payment if it exists; do not duplicate an incompatible claim namespace.
- `accounting_harness/workspace.py`, `web.py`, `__main__.py`: stored-policy routing, bill/payment forms, payables snapshot view and deterministic demos.
- `tests/test_payables.py` (new), existing review/approval/reversal/web tests: accounting outcomes, boundary failures, restart/retry, direct-service bypass and concurrent allocation.
- Phase plans, verification records, status/next prompt, test strategy and CI: one observed delivery record per 14a and 14b.

## 3. Typed evidence and identities

Add `vendor_bill` using the existing v2 base document fields plus exactly `event_id`, `counterparty_id`, `bill_number` and `due_date`. `amount` is the principal; `document_date` is the bill issue date. Retain vendor display name in the existing `counterparty` field; stable identity is `counterparty_id`. A vendor table is unnecessary: group immutable bills by vendor ID and show their recorded display names. Preserve bill numbers exactly after existing nonempty/trim checks; do not apply undocumented case or punctuation normalization.

Recognition requires both a `vendor_bill` and an `incurred_expense`: same event ID, vendor ID, currency and amount. Use the incurrence date as effective date; in this bounded workflow require bill issue date equal incurrence date and due date on/after issue date. Reject later invoicing/backdated recognition as unsupported timing, rather than silently adopt the cash policy or an arbitrary date. Only expense accounts 5000/5100 are supported. Cash evidence cannot establish this expense.

Derive internal bill ID as `bill:` plus `digest([entity_id, vendor_id, bill_number])`. Reusing a different source ID for the same bill number/vendor cannot introduce a second bill. Reusing the same incurrence event with a different bill number also cannot recognize another expense. Distinct vendors may reuse a bill number.

Payment uses a v2 `cash_movement` with `direction='out'`, `purpose='settlement'`, matching vendor/currency, and amount equal this allocation. Its event ID is the payment event; it is deliberately different from the bill's recognition event. The target bill is selected explicitly by the operator and bound into the intent. A bill is reusable evidence for several distinct payments; a cash movement is fully consumed by one payment here. Payment date cannot precede the bill recognition date. Do not compare payment amount to original bill principal for equality.

## 4. Exact operation-intent shapes

Use strictly validated JSON objects; reject missing/extra keys, booleans for cents, noninteger cents, values outside `1..MAX_CENTS`, unknown kinds and arbitrary policy names. IDs/dates use existing validators. No arbitrary `metadata` field.

Recognition intent (policy `bill-v1`):

```json
{
  "schema_version": 1,
  "kind": "vendor_bill",
  "bill_id": "bill:<derived-sha256>",
  "vendor_id": "vendor-synthetic-1",
  "bill_number": "B-001",
  "recognition_event_id": "incurrence-001",
  "currency": "USD",
  "principal_cents": 30000,
  "expense_account": "5100",
  "effective_date": "2026-01-10",
  "due_date": "2026-02-09",
  "evidence_roles": {"bill": "source-bill-001", "incurrence": "source-incurrence-001"}
}
```

Payment intent (policy `bill-payment-v1`):

```json
{
  "schema_version": 1,
  "kind": "vendor_bill_payment",
  "bill_id": "bill:<derived-sha256>",
  "vendor_id": "vendor-synthetic-1",
  "payment_event_id": "cash-out-001",
  "currency": "USD",
  "allocated_cents": 10000,
  "effective_date": "2026-01-15",
  "evidence_roles": {"bill": "source-bill-001", "cash": "source-payment-001"}
}
```

The literal example ID is explanatory, not accepted input: the application recomputes the hash. Proposal source IDs must be exactly the unique role values; its evidence map binds every value to its registry digest. Journal ID is deterministic per draft: `journal:` plus `digest([entity_id, draft_id])`. Bill draft identity derives from bill ID; payment draft identity derives from entity/payment event. Direct `save()` must enforce these identities for the two policies, not merely trust the template helper.

A different bill target for the same payment can be corrected only with a new revision of that payment draft before posting; the payment event remains reserved to the same draft. Every amount, date, source-role or target change changes its content digest and requires fresh approval. After posting, edit/reject remains prohibited.

## 5. Intent persistence and compatibility

Add one append-only side table, without altering old `draft_revisions` rows:

```sql
CREATE TABLE draft_operation_intents (
    draft_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    intent_json TEXT NOT NULL,
    PRIMARY KEY(draft_id, revision),
    FOREIGN KEY(draft_id, revision) REFERENCES draft_revisions(draft_id, revision)
) STRICT, WITHOUT ROWID;
```

Protect UPDATE/DELETE/REPLACE. A BEFORE INSERT trigger rejects attaching an intent when that revision already has a `review_events` row. During save, write revision, then intent, then event, then retry record, in the existing transaction. The event is the seal: its INSERT trigger requires exactly one valid intent row for known payables policies and no intent for legacy receipt/cash policies. This prevents attaching previously unbound metadata after approval. Actual JSON shape/content remains application validation, as in current evidence validation.

Bump `review_schema` from 1 to 2 atomically, temporarily replacing only its version-row protection inside the migration. Preserve all old revision/event/retry rows and their bytes. The migration creates the new table and guards in the same transaction; any failure leaves version 1 unchanged. Unknown schema versions fail. Do not change ledger `_context`, registry canonical bytes, approval schema or provider run context to introduce intents.

Extend `save(..., operation_intent=None)` and append `operation_intent_json: str | None = None` at the end of `DraftRevision` if the typed return needs it. Existing agent tool schemas do not accept the new parameter, and old provider run receipt recovery stays unchanged. Copy the prior intent on rejection; never drop it or generate an empty intent. Implement `_get` with explicit columns or explicit reconstruction so adding the optional field cannot shift positional fields.

Hash construction must preserve the old branches exactly:

```python
base_content = [proposal, evidence, policy_version]
content_digest = digest(base_content if intent is None else
                        base_content + [{'operation_intent_v1': intent}])

base_request = [operation, draft_id, expected, actor, reason,
                proposal, evidence, policy_version]
if require_unused_evidence:
    base_request += [True]  # Existing receipt behavior and exact ordering.
if intent is not None and operation == 'save':
    base_request += [{'operation_intent_v1': intent}]
request_digest = digest(base_request)
```

Rejection request identity retains its existing envelope (operation/draft/expected/actor/reason); it deterministically copies the immutable previous revision, including intent. Do not append a derived intent to old rejection retry envelopes. Its *new revision content* binds the copied intent.

At read/approve/post, recompute the stored revision content hash from proposal, evidence, saved policy and side-table intent; an absent mandatory intent, an unexpected intent, or mismatch yields a finding and cannot approve/post. `_binding` need not change: it already includes `revision_digest`, all evidence digests, policy and ledger context. Approval and post request digest formats also need no new fields; the approved content hash now transitively binds intent. Legacy hash verification uses precisely the old three-element list.

Keep the explicit stored-policy routing introduced by 13b. A `bill-v1` store cannot change a receipt policy approval into bill authority. Unknown policy or kind never takes a generic posting branch.

## 6. Payables schema and activation

Introduce `payables_schema(version)` and a singleton immutable `payables_context` with entity ID, activation actor/time, activation ledger snapshot digest, included journal IDs and policy `payables-zero-opening-v1`. Its existence activates the AP posting guard. Tables and guards may initialize without activation so the UI can report a blocked onboarding residual.

`ensure_enabled(actor_id)` acquires the ledger write transaction and computes current AP from posted journal lines, using Python integer summation. Require current unassigned AP balance exactly zero. If nonzero, fail with that residual and no activation row: do not silently create vendor opening items. Store activation evidence atomically. Retrying an already enabled workspace returns its original activation record. No separate confirmation flow is needed for this authorized fictional workflow; creating the first bill can invoke it explicitly in application code.

14a adds:

```sql
CREATE TABLE vendor_bills (
    bill_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    bill_number TEXT NOT NULL,
    recognition_event_id TEXT NOT NULL UNIQUE,
    bill_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
    incurrence_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
    principal_cents INTEGER NOT NULL CHECK(principal_cents > 0),
    expense_account TEXT NOT NULL REFERENCES accounts(code),
    effective_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
    journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id)
        DEFERRABLE INITIALLY DEFERRED,
    UNIQUE(vendor_id, bill_number)
) STRICT, WITHOUT ROWID;
```

One ledger file is already entity-scoped and USD-only. Actor/time and exact intent/evidence are reachable through the approval and journal links; avoid duplicating mutable status/balance columns. Add the usual nonempty text/date constraints and SQL immutability protections from existing modules.

Both effect tables also reject INSERT when their journal already has a posting event. Effects are necessarily inserted before the journal is sealed; a later insert cannot retroactively assign a historical journal or add a second effect to a previously checked event.

14b adds the following under payables schema v2, leaving v1 rows intact:

```sql
CREATE TABLE vendor_bill_payments (
    payment_event_id TEXT PRIMARY KEY,
    bill_id TEXT NOT NULL REFERENCES vendor_bills(bill_id),
    cash_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
    allocated_cents INTEGER NOT NULL CHECK(allocated_cents > 0),
    effective_date TEXT NOT NULL,
    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
    journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id)
        DEFERRABLE INITIALLY DEFERRED
) STRICT, WITHOUT ROWID;
```

For 14a, the AP guard references only `vendor_bills`; its 14b migration atomically replaces that guard with the version recognizing both tables. Do not reference an absent payments table or scaffold unused 14b behavior in 14a.

## 7. Posting cannot omit the subledger effect

Add explicit code in the existing `ReviewApplication.post` transaction after approval/current-revision/binding validation:

```python
entry = self.ledger._validate_entry(json.loads(current.proposal_json))
if current.policy_version in ('bill-v1', 'bill-payment-v1'):
    # Concrete implementation imported locally to avoid module import cycles.
    # No transaction entry/commit inside this function.
    prepare_payable_post(self.store, approval, current, entry)
receipt = self.ledger._store_entry(entry, actor_id)
# Existing review_postings and approved_post_requests writes follow.
```

`prepare_payable_post` is an explicit `if kind == vendor_bill / elif vendor_bill_payment` function, not a caller-supplied callback or plugin registry. It requires `db.in_transaction`, revalidates the exact operation, ownership of event claims, AP readiness and all evidence, then inserts the bill/payment row. Its posting-event FK is deferred, so that row can precede `_store_entry`. Any missing journal at commit fails. Existing `review_postings` and post retry record commit in the same transaction. Faults at any point roll everything back, including the effect row.

For a bill, recheck absence of bill identity/event and emit exactly expense debit/principal + AP credit/principal. For payment, load the posted bill and calculate `principal_cents - sum(existing payment cents)` using Python integers. Require positive allocation no greater than remaining, matching vendor/evidence and no repeated cash event. Emit exactly AP debit/allocated + Cash credit/allocated. A state change after approval may invalidate payment posting; approval is not a reservation of outstanding balance.

Separate immutable evidence/intent validation from mutable posting readiness. Pending payment drafts may receive current over-allocation findings, but reading an already posted draft must validate its own linked effect instead of treating its own consumed payment as a duplicate or subtracting it twice. Likewise reading a posted bill must accept its own linked bill row. `prepare_payable_post` is only for a new post and rejects any already posted effect; the existing exact-post retry path returns first. This preserves readable historical review traces after settlement.

Install a `BEFORE INSERT ON posting_events` trigger, conditional on activated payables and an account-2000 line, that requires exactly one matching `vendor_bills` or `vendor_bill_payments` row for `NEW.journal_id`. Validate the expected AP side/amount and counterpart side/account/amount against that row, with exactly two journal lines. The preinserted row must reference an existing approval; the application verifies its exact current revision and intent. Add the inverse invariant: inserting a payable effect requires its future journal to be the approved operation journal, checked in application and at posting-event sealing. All relevant rows remain immutable afterward.

This ordering means ordinary `SQLiteLedger.admit`, `ReviewApplication.post` under `review-v1`, an old already-open ledger connection, and a direct `_store_entry` call cannot omit the allocation and still commit an AP posting in an enabled ledger. There is no `skip_payables`, caller-provided boolean or special actor bypass. Existing `admit` and approval-post retries return their prior receipt before a fresh posting attempt; they remain valid even if their historic journal predates activation.

Raw database ownership still permits dropping triggers or forging whole rows; this is not authentication. State the existing SQL/application enforcement boundary accurately. The guard specifically prevents missing/mismatched accounting effects through normal service/direct SQL insertion, not hostile database administrators.

## 8. Duplicate evidence and event claims

Do not use blanket `require_unused_evidence=True` for payment: a bill source must be reusable. Also do not replace it with a UI-only precheck or disable all duplicate checks.

Use an immutable event claim with semantic key `(purpose, event_id)` and owner draft ID. Minimal purposes are `expense_recognition` and `cash_movement`. If 13b already owns this claim table, extend that exact primitive; otherwise put a small `economic_event_claims(purpose, event_id, draft_id, revision)` table next to review revisions, with a composite FK to the first claiming revision. Its primary key is `(purpose,event_id)` and claim mutation/replacement is prohibited. Claim and first revision are inserted within the existing save transaction after exact retry lookup. Same draft may reuse its own claim in later revisions; another draft cannot. Rejected drafts retain the claim, requiring correction of that draft rather than a new identity.

Cash expense and vendor bill recognition use the *same* expense-recognition purpose. Every cash template and bill payment uses the *same* cash-movement purpose. Scoping claims by policy name would permit recording the same expense as both a cash expense and a bill, or consuming a payment as both a cash expense and AP settlement. Shared event IDs are already typed evidence in 13b. Verify 13b has implemented this before claiming cross-workflow duplicate protection.

Bill ID and deterministic draft ID prevent duplicate vendor/bill-number drafts; posted unique constraints are the final guard. Incurrence event claims prevent using a new bill number for the same expense. `source_used()` and the Step 12 transactional provider guard stay unchanged. A new typed operational event cannot be fed through generic v1 receipt policy; 13b and review-v1 validation must reject mismatched evidence kind/schema.

## 9. Proposed APIs

```python
class PayablesService:
    def __init__(self, ledger, registry): ...
    def ensure_enabled(self, *, actor_id): ...
    def propose_bill(self, *, bill_source_id, incurrence_source_id,
                     expected_revision, actor_id, idempotency_key): ...
    def propose_payment(self, *, bill_id, cash_source_id,
                        expected_revision, actor_id, idempotency_key): ...
    def snapshot(self): ...

def prepare_payable_post(store, approval, revision, entry): ...
def payables_report(snapshot, *, as_of): ...
```

Proposal methods build the known intent/journal/evidence map, compute deterministic draft ID, select known policy and call the shared review service. They never approve/post. Amount and date come from evidence; the browser cannot override them with an extra amount. Correction starts from new registered evidence and a new draft revision. Successful proposals return `DraftRevision`; posting continues to return the existing `PostingReceipt`.

`snapshot()` captures ledger entries, immutable bill/payment tuples and payables context in one ledger read transaction. Refactor the existing ledger snapshot query into a private transaction-internal helper if needed; do not call `ledger.snapshot` inside an already open transaction. That tiny read helper is a justified shared primitive. `payables_report` is pure and takes the captured snapshot, avoiding a current subledger joined against a separately captured historic ledger.

## 10. Reconciliation and historical reports

For an `as_of` date in the ledger period, include a bill only if its linked journal belongs to the captured ledger snapshot and its effective date is at/before cutoff. Include a payment only if its linked journal is likewise included and its date is at/before cutoff. Require payment effective date on/after bill recognition in the posting validator.

Calculate, in Python integers:

```python
bill_outstanding = principal_cents - sum(included_payment_cents)
subledger_cents = sum(bill_outstanding_for_each_included_bill)
ap_control_cents = sum(line.amount.cents if line.side == 'credit' else -line.amount.cents
                       for included_entry in entries for line in included_entry.lines
                       if line.account == '2000')
unassigned_control_cents = ap_control_cents - subledger_cents
```

Report vendor totals, bill ID/reference, recognition/due date, principal, paid and outstanding, AP control total, subledger total and signed unassigned residual. Include snapshot digest, exact included journal IDs, cutoff and report policy `payables-zero-opening-v1`. Compute the report digest from immutable captured values, not the newest registry list. Original documents/digests remain traceable through approvals.

Historical legacy AP activity may net to zero at activation but have a residual at earlier cutoffs. Display that earlier residual honestly, with `reconciled=False`; do not pretend it was assigned to vendors. Captured reports remain reproducible after later payments because their frozen snapshots exclude those entries. New operations must not continue when the *current* control/subledger residual is nonzero; fail readiness and show the residual rather than inserting a balancing entry.

## 11. Reversal boundary

Steps 14a/14b do not support reversing a managed bill or payment. Add an explicit check in public `SQLiteLedger.reverse`, after exact legacy retry lookup but before inserting a new reversal: if original journal belongs to either payables table, reject with `operational_reversal_not_supported`. The AP posting guard also denies a hand-built inverse AP journal without a valid operation effect. No new reversal row or journal is written.

Continue ordinary non-AP reversals and all historical exact reversal retries unchanged. A newly requested reversal of unmanaged historical AP also cannot bypass the active AP guard; expose a clear residual/correction-workflow explanation. Do not delete payable rows, restore a database, update outstanding fields, or free a payment claim to undo a posting.

A future separate correction slice must atomically write inverse allocation records linked to the original, correct the GL through linked reversal, and enforce dependencies (for example, bill recognition cannot be reversed while effective settlement remains). Do not claim reversal support merely because the low-level ledger already has `reverse()`.

## 12. Meaningful acceptance tests and demonstrations

14a:

- [ ] Independent 300.00 bill expectation: Software expense debit 30000 cents, AP credit 30000; one vendor/bill with principal/outstanding 30000, no payments, zero residual. Before explicit approval there are zero posted journals and zero vendor bill rows.
- [ ] Same vendor/bill number under a different source ID conflicts; a different vendor with the same number is valid; same incurrence event with a different number or a prior cash expense conflicts.
- [ ] Missing incurrence, cash-only evidence, mismatched vendor/event/amount/currency, wrong account, unsupported date and invalid due date cannot approve/post.
- [ ] Changing only intent due date, bill target/identity, source roles or principal changes digest; prior approval becomes unusable. Missing or late-inserted intent cannot post.
- [ ] Capture historical receipt/cash revision, approval and retry rows before review migration; compare bytes and returned receipts afterward. Existing provider run resume/recovery passes unchanged.
- [ ] Direct `ledger.admit` and generic review-v1 AP posting fail after activation, including from a connection opened before activation; an unlinked direct-SQL AP posting event fails. No partial journals survive.
- [ ] Existing unassigned AP of 10000 cents blocks activation with unchanged ledger and no invented vendor. Existing non-AP journals/approvals remain usable.
- [ ] Fault injection at intent/event/retry creation, bill effect, journal line/event, review posting and post retry leaves the intended atomic unit absent; retry succeeds once with original actor/time.
- [ ] Bill reversal is refused without mutation; ordinary expense reversal still works. All new table UPDATE/DELETE/REPLACE attempts fail.

14b:

- [ ] Against 30000 principal, payment 10000 gives AP debit 10000/Cash credit 10000, bill outstanding 20000 and AP control 20000, with zero residual. Expense stays 30000.
- [ ] Another independent payment 5000 leaves 15000. Reusing the first cash source/event, including under cash-v1 or a different bill, fails. Exact retries return the same posting receipt across restart.
- [ ] Full cash movement 10000 cannot allocate only 5000 or be split among bills; the UI does not offer split allocation. A full settlement 30000 closes a fresh 30000 bill; another payment fails.
- [ ] Two approved 20000 payments race against 30000 outstanding: exactly one posts, one is refused after transaction-time recheck, remaining outstanding 10000, and no orphan payment/journal/retry record exists.
- [ ] Two concurrent exact retries of the same approval/key return one original receipt and one payment row.
- [ ] Wrong vendor, payment before bill date, nonexistent/unposted bill, out-of-period date, boolean/float/zero cents, overpayment 30001 and forged AP counteraccount fail without balance changes.
- [ ] Approval followed by another valid settlement cannot reserve stale funds: when remaining balance drops below the approved amount, posting that approval fails.
- [ ] A Jan 12 snapshot/cutoff before Jan 15 payment shows 30000 outstanding; Jan 15 shows 20000. Recompute an earlier captured snapshot after later settlement and obtain the identical report/digest.
- [ ] Inject failure after payment-row insertion and at each subsequent existing posting boundary; both payment and journal disappear on rollback. Deferred FK commit denies an orphan effect.
- [ ] Payment reversal and direct inverse AP posting are refused; no allocation is silently released.

Run foundation, guarded full suite, every documented prior demonstration, and new `demo-bill` / `demo-bill-payment`. Add both deterministic demos to CI as they ship. Use real localhost HTTP tests to prove the route derives actor/policy, displays intent/evidence, requires exact revision confirmation and cannot bypass posting checks. These are planned tests, not observed passes.

The new demos should print the independent amounts above, approval/evidence references, source counts, snapshot policy/digest and zero control residual. After each lettered slice inspect the intended diff, commit/push and check that exact SHA's CI under the parent delivery workflow. Live external connections remain deferred. These acceptance checks describe planned behavior until recorded in each substep verification file.
