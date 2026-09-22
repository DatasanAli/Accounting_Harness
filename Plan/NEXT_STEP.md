# Next: Step 08 — Versioned drafts and review queue

Status: ready. Steps 01–07 provide the ledger core and immutable registration of structured fictional receipts. Phase 03 remains in progress; registration does not post or approve journals.

## Copy this prompt

> Build Step 08: versioned drafts and review queue. Follow Plan/NEXT_STEP.md, create immutable draft revisions from registered evidence with validation findings and pending/rejected states, demonstrate an edited proposal and its history, then commit and push to GitHub. Stop after this step.

## The small thing to build

Turn registered evidence into editable journal proposals represented by immutable draft revisions. Define required draft metadata, entity-scoped identity, evidence identity/digest binding, revision identity and allowed pending/rejected transitions before coding. Each edit must append a new revision and preserve earlier content and findings. Reuse the pure journal validator for supported accounting checks; do not treat a balanced proposal or document text as permission to post.

Read the [Step 07 source contract](03-evidence-and-review/STEP_07_PLAN.md) and [verification record](03-evidence-and-review/STEP_07_VERIFICATION.md). Inspect the source registry and frozen ledger context before choosing draft storage. The receipt importer currently supports only synthetic receipts; add another document kind only if essential to this step and explicitly specified/tested. Draft reads must bind the exact registered evidence. Missing or conflicting evidence must remain visible as unresolved review findings. Clarify how validation relates to pending/rejected state and how edits supersede the current revision without erasing history.

Use standard-library storage and synthetic inputs. Persist each revision, its validation findings and mutation event atomically, with scoped retry behavior and explicit conflict handling. If storage changes require migration, test non-destructive versioning, rollback and unsupported-version rejection. Preserve registered evidence, posted journals, posting retry digests and historical snapshots.

This step provides drafts and a review queue only. Human approval binding and application posting are Step 09; agents, PDF extraction, providers and authenticated roles remain later work.

## Required evidence

- Create a proposal from registered fictional evidence, edit its amount, reopen storage and show both unchanged historical and current revisions.
- Show validation findings and a queue with explicit pending/rejected states and reasons.
- Reject invalid transitions; ensure invalid drafts cannot advance toward posting and missing/conflicting evidence remains in review.
- Test entity isolation, stale edits, repeated requests, changed-payload retries, atomic failures and revision history across restart.
- Preserve the entire ledger/reversal/source suite and the zero-discovery guard.

## Demonstration and delivery

Add a CLI demonstration of an edited fictional rent proposal, its revision history and unresolved findings using temporary storage. Run the foundation check, guarded application suite and every existing demo; add the new demo to CI. Record observed results and rollback limits. Update README, phase/status/roadmap, mark Step 08 complete and Step 09 ready, and replace this brief with approval, posting and audit. Commit, push, verify the exact commit and Actions run, then stop.

Source basis: Volume 1 §§3.3, 7.1–7.4, 8.2–8.3. Revision identity, digest binding and retry controls are engineering decisions. Authenticated approval remains later work.
