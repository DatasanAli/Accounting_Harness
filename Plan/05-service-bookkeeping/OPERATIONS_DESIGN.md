# Service Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. This document is design guidance for the parent roadmap plan, not authorization to skip its review or delivery gates.

**Goal:** Add synthetic evidence enrollment and reviewed cash templates to the localhost workspace, then add bills, invoices and advances in independently verifiable increments.

**Architecture:** Preserve the frozen ledger context and all existing retry/approval bytes. Enroll additional immutable sources through an additive ledger migration; use explicitly versioned deterministic evidence policies for operations. Continue posting through the trusted human approval application, with operation allocations committed in the same ledger transaction when subledgers arrive.

**Tech Stack:** Existing Python standard library, SQLite, local HTML forms, integer cents; no new package or network dependency.

**Spec:** `Plan/05-service-bookkeeping/README.md`, `Plan/05-service-bookkeeping/STEP_13_PLAN.md`, and [the localhost roadmap design](../LOCALHOST_APP_PLAN.md). The parent reports that the user has explicitly authorized broader localhost work and deferred external/live gates; update the obsolete Step 12 prerequisite text before implementation, without reporting a live pass.

## Global constraints and existing behavior

- Exact USD integer cents; external amounts use the existing strict two-decimal string parser. Reject floats and booleans.
- Synthetic documents only. Typed facts are evidence assertions reviewed by the operator, not authentication or permission grants.
- Receiving cash alone cannot establish service completion or expense incurrence.
- Preserve old journal snapshots, approval bindings, run context and idempotency digests; do not reconstruct their context from the growing registry.
- Posted entries and document histories remain immutable; corrections use linked reversals or later reviewed credit workflows.
- Keep provider runs on `review-v1` and their current source-use guard. Adding operations does not add agent approval/posting tools.
- Remain within January 2026 and the existing 13-account catalog for these steps. Do not silently expand the frozen period/catalog.
- Each lettered substep gets observed verification, demonstration, reviewed commit, push, and exact-SHA CI evidence under the parent delivery agreement.

The blockers are concrete:

1. `persistence.py:114` includes `known_source_ids` in `_context`; `sources_frozen` rejects every source insertion. `journal_sources.source_id` references `sources(id)`. Merely adding to `ledger._sources` cannot satisfy that FK, and rebuilding context changes approval, retry and run identity.
2. `review.py:96` validates exactly one registered source and equates its amount to total debits. Globally deleting those checks weakens provider receipts and does not establish recognition.
3. `source_used()` considers every historical draft and journal. The Step 12 save-time `require_unused_evidence=True` check is transactional and must remain. That global rule cannot be used unchanged for a bill referenced by multiple partial settlements.
4. `approval.py:110` already owns the correct atomic posting boundary. Subledger allocation cannot be appended after that transaction commits.
5. `workspace.py` currently lists a fixed fixture map and creates a `review-v1` store/run engine for every request. New registry sources and operations need deliberate enumeration and policy routing.

## Step 13a: enroll new synthetic evidence without changing context

**Files:** Modify `accounting_harness/persistence.py`, `sources.py`, `review.py`, `workspace.py`, `web.py`, `tests/test_persistence.py`, `test_sources.py`, `test_review.py`, `test_approval.py`, `test_runs.py`, `test_web.py`; add a focused `tests/test_enrollment.py` if migration/concurrency cases would overwhelm the persistence test class. Update phase/status/CI demonstration documentation in the same slice.

**Small public API additions:**

```python
SQLiteSourceRegistry.list_documents() -> tuple[SourceRecord, ...]
SQLiteLedger.known_source_ids() -> frozenset[str]
SQLiteLedger.enroll_source(registry, document_id: str, *, actor_id: str)
```

`list_documents()` is entity-local, deterministically ordered, and returns complete immutable registry records. `known_source_ids()` reads `sources` on the active connection, so already-open connections see committed enrollment at their next transaction. Keep `_sources` as the original baseline; use `known_source_ids()` in `_validate_entry` and review journal validation. Never include the growing result in `_context` or run scope.

`enroll_source()` obtains the registered record, checks matching entity, recomputes canonical SHA-256, and accepts only registered supported synthetic content. It returns the stored enrollment receipt on exact repetition. A baseline source already in the frozen context needs no new enrollment; return an explicit `already_known` result rather than fabricate a historical enrollment actor/time. Identity is the enrollment retry key. Changed content/digest for an enrolled identity fails. No caller-supplied arbitrary record object is treated as trusted registry evidence.

**Ledger schema v3:** Preserve `ledger_context.canonical` and existing `sources` rows byte-for-byte. Preserve the journal FK target. Add an append-only enrollment table holding source ID, registry entity, evidence digest, canonical evidence bytes, actor, timestamp, and versioned operation. The digest/content provide an immutable enrollment audit anchor; source registration retains its separate original actor/time.

Use this migration shape, with real existing validators/checks and append-only protections:

```sql
CREATE TABLE source_enrollments (
    source_id TEXT PRIMARY KEY REFERENCES sources(id)
        DEFERRABLE INITIALLY DEFERRED,
    entity_id TEXT NOT NULL REFERENCES ledger_context(entity_id),
    content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
    canonical_content TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation='enroll-source-v1')
) STRICT, WITHOUT ROWID;
DROP TRIGGER sources_frozen;
CREATE TRIGGER sources_enrollment_required BEFORE INSERT ON sources
WHEN EXISTS (SELECT 1 FROM sources WHERE id=NEW.id)
  OR NOT EXISTS (SELECT 1 FROM source_enrollments WHERE source_id=NEW.id)
BEGIN SELECT RAISE(ABORT, 'source requires new enrollment'); END;
```

Insert enrollment first and `sources` second in one `BEGIN IMMEDIATE`; the deferred FK makes the cycle safe at commit. Keep existing source UPDATE/DELETE triggers and add enrollment UPDATE/DELETE/REPLACE guards. Protect replacement of existing baseline source rows through the new INSERT trigger. Direct SQL cannot introduce a source without its audit enrollment, but SQL does not prove the contents came from the separate registry; the service validates that fact, consistent with existing SQL/application enforcement boundaries.

The existing `_migrate_v2()` writes `SCHEMA_VERSION`, so changing that constant to 3 without restructuring would mislabel v1 databases. Make migrations advance explicitly through version 2 and then 3, all within the initialization transaction. Fresh databases take the same chain. Unknown versions still fail, and older application versions reject v3 safely. Fault injection must restore old version and triggers.

The constructor still requires the original baseline set. Workspace keeps its existing five seed IDs as that baseline forever; it must not pass `set(registry.list_documents())`. On startup, reconcile registered nonbaseline documents lacking enrollment. Registration and enrollment use separate database files: register first, enroll second, report a recoverable enrollment error if the second fails. Exact resubmission and restart repair the gap. Do not claim cross-file atomicity, delete the registered evidence on failure, or silently report it ready for posting.

**UI:** Add a structured synthetic receipt form using the current v1 schema. The backend supplies entity, schema and `synthetic=True`, constrains the date to the workspace period, validates amount strictly, and uses a stable user-visible document ID. Display registration/enrollment state. List all registry sources, but keep offline fixture playback limited to its supported samples; a newly typed receipt is not magically supported by fixture playback. Registration does not draft, approve or post.

**Acceptance checklist:**

- [ ] A posted legacy journal, an unposted approved legacy draft, and an in-progress run survive enrollment/reopen with identical context, approval binding, retry digests and receipts.
- [ ] The old immutable snapshot/trial balance remains identical; new enrollment alone changes no balances.
- [ ] A new source can be validated and posted through the ordinary human-review path after enrollment; an unenrolled source cannot.
- [ ] Two already-open ledger connections observe the same enrolled IDs; concurrent enrollment produces one audit record and one source row.
- [ ] Same identity/content retries return the original actor/time; conflict and wrong entity fail without writes.
- [ ] Failure between registration/enrollment is visible and recoverable; failure between enrollment/source-row insertion rolls back both ledger rows.
- [ ] A real v2 populated database migrates, and the checked-in v1 fixture still migrates through v2. Injected DDL failure leaves original version, triggers and historical records.
- [ ] Existing direct-SQL immutability tests remain; replace the old assertion that *every* source insertion fails with assertions that unregistered, unaudited and replacement insertion fail.
- [ ] Existing provider duplicate-source race tests and zero-discovery guard still pass.

Demonstration: enroll a new 125.00 synthetic receipt after an existing post and approval, reopen, show original trial balance and retry receipt unchanged, then show the new document available for review with zero additional journals.

## Step 13b: cash templates with typed recognition evidence

**Files:** Add `accounting_harness/operations.py` for the two deterministic templates and their narrow evidence validator; extend `sources.py` for versioned typed facts, `review.py` for explicit policy dispatch/common validation, `workspace.py`/`web.py` for forms and policy routing. Add `tests/test_operations.py` and source/review/web regression tests. Keep `approval.py` posting semantics unchanged for this slice.

**Document schema:** Leave v1 canonicalization, accepted fields, digest and receipt semantics unchanged. Add schema v2 with the same base identity/entity/date/currency/amount fields and exact per-kind additional fields. Initially support only:

- `cash_movement`: `event_id`, `counterparty_id`, `direction` (`in`/`out`) and `purpose` (`earned_service`, `incurred_expense`, `owner_contribution`, `owner_draw`, `transfer`, `customer_advance`, `settlement`, `unclassified`). These labels cannot substitute for recognition evidence.
- `incurred_expense`: `event_id`, `counterparty_id`, `expense_account` restricted initially to `5000` or `5100`, and `incurred_date`.
- `service_completion`: `event_id`, `counterparty_id`, and `completion_date`.

All kinds remain synthetic; every kind's exact required field set and enum are validated. The shared `event_id` binds the separate cash and recognition documents. Two documents with matching amounts or descriptions but different events/counterparties do not constitute a match. No text classifier or description keyword establishes the evidence kind. These are fictional user-entered assertions displayed in full at review.

**APIs:**

```python
cash_expense_proposal(registry, *, entry_id, cash_source_id, recognition_source_id)
earned_cash_proposal(registry, *, entry_id, cash_source_id, recognition_source_id)
validate_cash_evidence(proposal, records) -> tuple[Finding, ...]
```

Each pure template returns the normal journal dict and complete `{source_id: digest}` mapping. Derive amount, effective date and approved account mapping from evidence; do not accept a second freely editable amount/account from the browser. For this bounded immediate-cash policy require two sources, same event/counterparty/currency/amount, and cash date equal incurred/completion date. Other timing, partial recognition or mixed-purpose cases yield explicit review findings and cannot post under this policy.

Mappings are fixed: expense debit 5000/5100 and cash credit 1000; cash debit 1000 and service revenue credit 4000. The validator reconstructs the expected mapping independently of a successful template call and checks proposal lines, source set, amount/date and evidence facts. That prevents a direct forged draft from using the correct policy label with wrong accounts.

**Version routing:** Extract shared journal, period, storage-limit and evidence digest checks from the receipt-specific checks. Keep `review-v1` exactly as it is; add `cash-v1` to an explicit application-owned policy dispatch. Do not allow a document or model to select arbitrary validators. Unknown operational policy names fail closed. A store's configured policy still controls its writes and current-policy check; do not globally switch the provider store to `cash-v1`.

Workspace reads the persisted draft policy to select the appropriate known store/application for status, approval and posting. It lists drafts with their saved policy, and routes actions by the stored value, not a policy sent by the browser. Existing provider runs keep their original `review-v1` store/run database scope. A new cash store uses the same ledger/review tables but no run engine. This preserves the existing changed-policy denial semantics while allowing two explicit policies to coexist. Do not weaken `_get` to silently accept arbitrary historical policies.

**Duplicate guard:** Cash templates call `save(..., require_unused_evidence=True)` inside the existing transaction. Deterministic template draft identity/retry keys bind entity, source IDs, policy and operation; retries are checked before duplicate detection. No preflight-only `source_used()` test can replace the atomic save guard. Historical rejected evidence stays conservatively used; correction means an explicit same-draft new revision under existing edit rules, not a new draft ID. If that correction UI is excluded from 13b, state the restriction instead of bypassing the guard.

For v2 operation events also reject a newly assigned document ID reusing the same event-and-role within a cash workflow, using an operation claim stored in the same review transaction or a small indexed immutable event/role registration mapping. Equal content under genuinely distinct event identities remains legitimate. Do not globally deduplicate by amount or content digest; existing source tests intentionally permit equal-content distinct identities. This protects known duplicate identity, not fraudulently relabeled economic events.

**Acceptance checklist:**

- [ ] Rent 1200.00 and earned cash 800.00 create pending drafts, explicit approval posts each once. Independent expected balances: Cash credit 400.00, Rent debit 1200.00, Revenue credit 800.00; trial balance debit/credit 1200.00. Negative Cash from this isolated zero-opening demonstration is allowed and disclosed.
- [ ] Each audit trace includes both exact evidence digests, revision, policy, operator and effective date.
- [ ] Owner contributions, transfers, advances, existing-AR settlement, raw v1 cash receipts and descriptive claims without completion/incurrence facts cannot use earned-cash/expense templates.
- [ ] Different event, counterparty, amount, date, missing document, wrong currency/account and extra/unbound evidence fail without posting.
- [ ] Provider receipt behavior is unchanged. An existing approved `review-v1` draft remains postable after a `cash-v1` draft is added.
- [ ] Concurrent duplicate template attempts produce at most one draft; exact resubmission returns the original receipt; different source ID/same economic event cannot create duplicate cash posting.
- [ ] HTML shows exact proposed journal and both factual documents before explicit confirmation; all server actions enforce the same checks as direct services.

## Steps 14–16: bounded extension points, not a generic workflow framework

Do not implement these capabilities inside 13a/13b. Keep the accepted interfaces above small. Their introduction requires explicit operation intents because allocation amount and target bill/invoice/advance are not derivable from one receipt's face amount.

**Shared decision for later allocations:** Add an immutable operations intent associated with a draft revision, containing operation kind, target document/contract, exact allocated cents, document roles, effective date, and policy version. The revision content digest must include this intent; approval binds it through that digest. Preserve old revision digests exactly when no intent exists. Do not merely write mutable target metadata beside an approval or interpret an entry description as an allocation reference.

Store document headers, settlement/recognition allocations and their journal links in the ledger database. Extend the trusted posting transaction with an explicit operations check/write path selected by known policy/intent. Recheck outstanding amount and competing allocations under `BEGIN IMMEDIATE`, then write journal, event, approval link, allocation and retry receipt atomically. A hook that can post without an operation allocation is insufficient. Direct generic human posting of a managed operation must use the same required path or fail.

Use a separate narrow validator per known policy in `operations.py`; add a module only when a bounded bill/invoice service outgrows that file. All validators share digest/balance/period checks. Do not extend the old `review-v1` amount rule into partial settlement, or suppress all evidence amount checks. Assign evidence roles explicitly: the bill/invoice establishes original principal; the payment/receipt establishes this settlement amount; completion establishes this recognition amount. A reused principal document is allowed, whereas a settlement event has a unique usage identity and cumulative allocated amount cannot exceed its recorded amount.

`require_unused_evidence=True` remains for standalone provider/cash proposals. Operations with reusable principal evidence use a separate operation-aware atomic claim/allocation guard; they do not pass that boolean off and rely on UI checks. Bound draft retries to the complete immutable intent. New approval is required after an intent amount/target change.

| Increment | Minimal deliverable and independent acceptance |
| --- | --- |
| 14a bill recognition | Register typed vendor bill + incurrence facts, vendor ID, bill identity and due date; reviewed debit expense 300.00 / credit AP 300.00; immutable journal-linked vendor document; duplicate identity/event refusal; AP control equals vendor outstanding totals. |
| 14b partial bill settlement | Recorded cash payment allocated to one bill; reviewed debit AP 100.00 / credit Cash 100.00; 200.00 outstanding. Reject over-allocation, concurrent competing over-allocation, wrong vendor/date/currency, duplicate payment and missing bill. Roll back journal and allocation together on injected failure. No actual bank transfer. |
| 15a invoice recognition | Typed invoice plus service completion, customer ID and due date; debit AR 2500.00 / credit revenue 2500.00; original principal with immutable journal link; duplicate invoice/service recognition guards. |
| 15b collection and aging | Recorded receipt 1500.00 gives debit Cash / credit AR and 1000.00 outstanding, with revenue unchanged. Aging uses due dates and allocations at a defined ledger snapshot/cutoff, excluding later collections; customer totals reconcile to AR. Reject over-allocation, duplicate receipt, missing completion and wrong-customer allocation. |
| 16a advance receipt | Typed prepayment/contract evidence plus recorded cash, customer/contract identity; debit Cash 600.00 / credit Unearned 600.00. Cash does not create revenue; subsidiary liability reconciles to 2100. |
| 16b earning an advance | Completion evidence supports 200.00; debit Unearned / credit revenue 200.00, leaving 400.00. Reject repeated completion event, cumulative excess, wrong contract/customer, and completion before applicable recognition date. |

Control reconciliation must account for legacy direct entries already posted to 1100/2000/2100. Display and fail readiness on an unassigned control residual rather than silently claiming subledger equality. The simplest initial workflow allows operational onboarding only when the relevant control account has zero unexplained balance; report any existing residual as needing explicit opening-item mapping. Do not invent vendor/customer allocations for historical journal lines. A later reviewed migration can add those opening items if requested.

Reversals must also be reflected in operation outstanding amounts. Before exposing reversal for an operational journal, either implement linked inverse allocations and dependency checks atomically or reject that workflow with a clear unsupported-operation result. Reversing only a GL payment while leaving the subledger allocation consumed breaks reconciliation. Corrections are a separate tested slice if they exceed 14b/15b scope.

## Verification and handoff risks

Run `python3 scripts/verify_foundation.py`, `python3 scripts/run_tests.py`, all documented legacy demos and each slice's new CLI demo. Add the new deterministic demos to `.github/workflows/verify.yml` and `Plan/TESTING_STRATEGY.md`. Verify localhost endpoints with actual HTTP tests in addition to direct service tests; preserve request-origin/session protections from 12a. Use fresh temporary synthetic workspaces for acceptance and a populated pre-migration fixture for preservation tests.

Most material risks are accidental identity changes: growing `_context`, switching the one run store's policy, recomputing old evidence canonical bytes, or recomputing old revision digests with newly added null fields. Explicit before/after comparisons are required for each. A complete UI does not itself prove the accounting boundaries. Live provider evaluation and real authentication remain explicitly deferred, not passed.

This is a read-only architecture review except for this requested notes artifact. No application changes, test execution, commits or network calls were performed by this planning task.
