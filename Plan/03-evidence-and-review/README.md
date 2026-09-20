# Phase 03: Evidence, review and audit

Status: Step 07 is ready following the completed ledger-core implementation. No behavior in this phase is implemented yet.

**Depends on:** Steps 02–06.

**Outcome:** An operator can trace, review, and approve an exact draft before application posting.

**Source basis:** Volume 1 §§3.3, 7.1–7.4, 8.2–8.3. Revision binding and idempotency are engineering controls. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Start with structured JSON evidence and a CLI, with content digest and explicit document identity. A content digest detects repeat bytes, not every business duplicate. Source identity and possible duplicate warnings remain separate. Introduce state and immutable audit events alongside each mutation. The local operator identity is a prototype convention until Step 29.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 07: Source registration

- **Build:** Register one structured fictional source document with stable identity, digest and metadata.
- **Test:** Missing required fields fail; identical import is recognized; same amount with different document identity stays distinct.
- **Verify manually:** Register a receipt twice and show one source record with a repeat-import result.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 07: Source registration. Follow Plan/03-evidence-and-review/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 08: Versioned drafts and review queue

- **Build:** Turn registered evidence into editable draft revisions with validation findings and pending/rejected states.
- **Test:** Changing an amount produces a new revision; invalid drafts cannot advance; missing or conflicting evidence stays in review.
- **Verify manually:** Edit a rent proposal and show its revision history and unresolved findings.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 08: Versioned drafts and review queue. Follow Plan/03-evidence-and-review/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 09: Approval, posting and audit

- **Build:** Bind a human CLI decision to a validated revision; post through the application service and record transitions atomically.
- **Test:** Reject no approval, rejected approval, changed draft/evidence/policy, and repeated posting; reconstruct the source-to-journal trail.
- **Verify manually:** Approve one valid draft, post once, then trace it back to the exact evidence.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 09: Approval, posting and audit. Follow Plan/03-evidence-and-review/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Keep original evidence and prior revisions. Reject stale approvals. Failures may record an audit event but must not change the posted ledger.
