# Phase 09: Access, integrations and controlled pilot

Status: planned; no behavior in this phase is implemented yet.

**Depends on:** Steps 02–28 for this default sequence; may reprioritize after the local bookkeeping demo. No live connector or deployment is implied by this plan.

**Outcome:** A specifically scoped pilot has authenticated access, reconciled integration, a review interface and tested recovery.

**Source basis:** Volume 1 §§7.1, 8.2–8.5; operational security, adapter and recovery design are engineering additions. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Confirm actual entity, framework, jurisdiction, accounting policies, ledger ownership, connector target and authorized external actions before real-data use. Break broad integration work into independently tested operations. Start in a provider sandbox. Every service enforces entity scope and permissions; UI hiding alone is insufficient.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 29: Authenticated operator and entity access

- **Build:** Add authenticated roles and deny-by-default entity-scoped service authorization for a narrowly scoped deployment.
- **Test:** Cross-entity read/write denied; forged reviewer rejected; agent lacks human role; session expiry and permission revocation are exercised.
- **Verify manually:** Demonstrate preparer/reviewer boundaries with two synthetic identities and entities.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 29: Authenticated operator and entity access. Follow Plan/09-integrations-and-pilot/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 30: One sandbox read adapter

- **Build:** Select one accounting system, decide authoritative-ledger ownership, and import one object type through a sandbox adapter.
- **Test:** Pagination, stable IDs, duplicate retry, rate limiting, interrupted resume and field/currency mapping pass; imported totals reconcile.
- **Verify manually:** Import and reconcile one sandbox batch with no external write.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 30: One sandbox read adapter. Follow Plan/09-integrations-and-pilot/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 31: Review workbench

- **Build:** Add one web screen for source, proposal, validation, approval/rejection and trace links using existing services.
- **Test:** Cannot approve a changed draft; permission checks work on direct API calls; keyboard review flow works; posted result is traceable.
- **Verify manually:** Review one supported expense end to end in the browser.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 31: Review workbench. Follow Plan/09-integrations-and-pilot/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 32: One sandbox journal export

- **Build:** Export an explicitly approved journal to the chosen sandbox with local/remote IDs and status reconciliation.
- **Test:** Retry and timeout recovery create one external journal; changed approval fails; export/import totals match; drift remains an exception.
- **Verify manually:** Export one approved fictional journal and verify the remote record.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 32: One sandbox journal export. Follow Plan/09-integrations-and-pilot/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 33: Recovery and operational visibility

- **Build:** Add backup/restore runbook, one recovery drill, structured redacted metrics and failure alerts.
- **Test:** Restore to a separate test database; compare journals, balances and review/run states; verify stalled-run and failed-sync detection; document measured recovery times.
- **Verify manually:** Run one restore and reconcile its ledger to the recorded snapshot.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 33: Recovery and operational visibility. Follow Plan/09-integrations-and-pilot/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 34: Controlled pilot acceptance

- **Build:** Document the actual pilot scope/policies and run a capped, reviewed end-to-end period with the selected users and data permissions.
- **Test:** Agreed accounting scenarios and zero-unauthorized-action gate pass; exception handling, rollback and reconciliation are demonstrated; release evidence names exact commit.
- **Verify manually:** Present the pilot acceptance record and remaining limitations; authorize additional scope separately.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 34: Controlled pilot acceptance. Follow Plan/09-integrations-and-pilot/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

A failed sync stops at a recoverable checkpoint. Do not retry non-idempotent writes blindly. Exporting journals is not permission to send money. Preserve ledger history during recovery.
