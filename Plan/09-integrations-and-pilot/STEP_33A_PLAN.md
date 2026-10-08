# Step 33a: coherent backup and verified relocation

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 32.

**Goal:** Restore the entire configured synthetic workspace group to a separate
location and safely resume its interrupted local runs.

**Architecture:** Enforced maintenance snapshot, strict manifest and staged restore;
explicit logical-to-physical relocation preserves historical scopes and retry IDs.
**Tech stack:** Python, SQLite backup API, file locking and existing run engine.
**Spec:** [Step 33 recovery contract](STEP_33_PLAN.md), all global constraints and
its coherent snapshot/relocation/recovery-proof sections apply. Operational metrics
are delivered separately in33b; this slice records its own recovery measurements.

## Task 1: verified restoration without history rewrite

**Files:** Focused recovery module/tests, run relocation boundary, workspace locking,
CLI and a synthetic drill fixture. Root owns runbook, restored browser and CI.

- [ ] RED: direct copied workspace fails current scope validation; a verified
  relocation opens at a new path with exact financial/review/run history intact.
- [ ] Implement bounded coherent backup, strict versioned manifest and staged
  empty-destination restore with original preservation and private permissions.
- [ ] Preserve old scope and logical run-path retry identity across relocation;
  recover an effect-before-checkpoint run without duplicate work and reject
  arbitrary alias forgery or mismatched entity/context/tool-policy bindings.
- [ ] Test writer exclusion, multi-store/group consistency and injected faults
  before/after each snapshot/file/manifest/finalization operation. Reject corrupt,
  missing, traversal, symlink, overlapping, wrong-schema/entity/context artifacts.
- [ ] Restore mappings only to verified new files, revoke old sessions with audit,
  disable providers/external writes and retain uncertain exports without sending.
- [ ] Add `demo-recovery` with observed backup/restore/validation milliseconds,
  exact recorded journal/balance/source/review/report/run comparisons and no SLA
  claim. Parent opens actual restored UI with fresh login and inspects traces.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, independent
  review, commit/push/exact CI before operational status visibility.
