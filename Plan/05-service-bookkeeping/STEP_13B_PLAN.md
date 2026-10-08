# Step 13b: reviewed cash receipts and expenses

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

Once v2 document kinds exist, the old receipt policy must explicitly require a
v1 receipt. Typed cash/completion/incurrence documents cannot enter a weaker
one-source provider/receipt path. Existing v1 behavior and digest bytes stay
unchanged. Test that a forged direct `review-v1` draft against v2 facts fails.

**Duplicate guard:** Cash templates call `save(..., require_unused_evidence=True)` inside the existing transaction. Deterministic template draft identity/retry keys bind entity, source IDs, policy and operation; retries are checked before duplicate detection. No preflight-only `source_used()` test can replace the atomic save guard. Historical rejected evidence stays conservatively used; correction means an explicit same-draft new revision under existing edit rules, not a new draft ID. If that correction UI is excluded from 13b, state the restriction instead of bypassing the guard.

For v2 operation events also reject a newly assigned document ID reusing the same event-and-role within a cash workflow, using an operation claim stored in the same review transaction or a small indexed immutable event/role registration mapping. Equal content under genuinely distinct event identities remains legitimate. Do not globally deduplicate by amount or content digest; existing source tests intentionally permit equal-content distinct identities. This protects known duplicate identity, not fraudulently relabeled economic events.

Recognition claims must identify the economic event and role, independent of
template name. For example, the same incurred-expense event cannot later be
recognized again through a vendor bill. Preserve this shared identity boundary
for Step 14; do not implement bill behavior in this slice.

**Acceptance checklist:**

- [x] Rent 1200.00 and earned cash 800.00 create pending drafts, explicit approval posts each once. Independent expected balances: Cash credit 400.00, Rent debit 1200.00, Revenue credit 800.00; trial balance debit/credit 1200.00. Negative Cash from this isolated zero-opening demonstration is allowed and disclosed.
- [x] Each audit trace includes both exact evidence digests, revision, policy, operator and effective date.
- [x] Owner contributions, transfers, advances, existing-AR settlement, raw v1 cash receipts and descriptive claims without completion/incurrence facts cannot use earned-cash/expense templates.
- [x] Different event, counterparty, amount, date, missing document, wrong currency/account and extra/unbound evidence fail without posting.
- [x] Provider receipt behavior is unchanged. An existing approved `review-v1` draft remains postable after a `cash-v1` draft is added.
- [x] Concurrent duplicate template attempts produce at most one draft; exact resubmission returns the original receipt; different source ID/same economic event cannot create duplicate cash posting.
- [x] HTML shows exact proposed journal and both factual documents before explicit confirmation; all server actions enforce the same checks as direct services.


## Delivery checklist

- [x] Write failing source/template/review/HTTP tests with independent expected amounts and invalid fact cases.
- [x] Implement typed synthetic facts and explicit cash policy while preserving historical review-v1 behavior.
- [x] Add UI evidence/operation forms and per-draft policy routing with human-only approval/posting.
- [x] Add `demo-cash` and update CI/documentation.
- [x] Run foundation, guarded suite, all demos and browser flow.
- [ ] Commit, push and verify exact SHA/CI after the clean task review, then continue Step 14a.
