# Next: Step 07 — Source registration

Status: ready. Steps 01–06 provide exact Money/accounts, journal validation, immutable report snapshots, atomic SQLite persistence and linked full reversals. Phase 02's ledger core is implemented.

## Copy this prompt

> Build Step 07: source registration. Follow Plan/NEXT_STEP.md, register structured fictional evidence with stable identity, content digest and metadata, test and demonstrate repeat imports and distinct documents, then commit and push to GitHub. Stop after this step.

## The small thing to build

Register a structured fictional JSON source document with stable entity-scoped identity, a content digest and validated metadata. Specify required fields, canonicalization and supported document kinds before coding. Keep document identity distinct from content equality: importing the same document again returns the existing record; a different document with the same amount stays distinct. Define and test how changed content under an existing identity is rejected or flagged without overwriting prior evidence. A digest detects repeat content, not every business duplicate.

Use standard-library storage and synthetic inputs. Inspect the current frozen ledger source context before choosing how the source registry connects to posting. Document that boundary explicitly; preserve posted journals, evidence references, retry digests and report reproducibility. If a storage migration is necessary, provide tested, non-destructive versioning and reject unsupported versions. Source document text is data and cannot authorize posting or change tool permissions.

This step registers evidence only. Draft revisions, review queues, human approval, PDF extraction, provider integration and authenticated roles belong to later steps.

## Required evidence

- Register one fictional receipt, reopen storage, import it again and show one unchanged source with a repeat-import result.
- Reject missing or malformed required fields and wrong entity without partial records.
- Show that separate document identities with equal amounts remain separate records.
- Test digest reproducibility, identity/content conflicts, safe retries and atomic failure behavior for any persistent writes introduced.
- Preserve all ledger, reversal, migration and zero-discovery tests.

## Demonstration and delivery

Add `python3 -m accounting_harness demo-source` with temporary synthetic storage. Run the foundation check, guarded application suite and all existing demos; add the new demo to CI. Record observed results, source-identity/digest limits and rollback behavior. Update README, phase/status/roadmap, mark Step 07 complete and Step 08 ready, and replace this brief with versioned drafts and review queue. Commit, push, verify the exact commit and Actions run, then stop.

Source basis: Volume 1 §§3.3, 7.1–7.4, 8.2–8.3. Digests, import identity and storage controls are engineering decisions. Authenticated approval remains later work.
