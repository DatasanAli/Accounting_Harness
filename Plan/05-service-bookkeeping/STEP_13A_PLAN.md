# Step 13a: additive synthetic evidence enrollment

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

- [x] A posted legacy journal, an unposted approved legacy draft, and an in-progress run survive enrollment/reopen with identical context, approval binding, retry digests and receipts.
- [x] The old immutable snapshot/trial balance remains identical; new enrollment alone changes no balances.
- [x] A new source can be validated and posted through the ordinary human-review path after enrollment; an unenrolled source cannot.
- [x] Two already-open ledger connections observe the same enrolled IDs; concurrent enrollment produces one audit record and one source row.
- [x] Same identity/content retries return the original actor/time; conflict and wrong entity fail without writes.
- [x] Failure between registration/enrollment is visible and recoverable; failure between enrollment/source-row insertion rolls back both ledger rows.
- [x] A real v2 populated database migrates, and the checked-in v1 fixture still migrates through v2. Injected DDL failure leaves original version, triggers and historical records.
- [x] Existing direct-SQL immutability tests remain; replace the old assertion that *every* source insertion fails with assertions that unregistered, unaudited and replacement insertion fail.
- [x] Existing provider duplicate-source race tests and zero-discovery guard still pass.

Demonstration: enroll a new 125.00 synthetic receipt after an existing post and approval, reopen, show original trial balance and retry receipt unchanged, then show the new document available for review with zero additional journals.


## Delivery checklist

- [x] Write tests that fail on the existing frozen-source API.
- [x] Implement additive enrollment and migration without changing old context/digest bytes.
- [x] Add source list/register endpoints and structured fictional receipt form; no provider call on registration.
- [x] Add `demo-enrollment` and CI/documentation commands.
- [x] Run foundation, guarded suite, prior demonstrations, new demonstration and browser import.
- [x] Review diff, commit intended files, push and verify exact SHA/CI.
- [x] Record delivery and continue to Step 13b under the expanded user authorization.
