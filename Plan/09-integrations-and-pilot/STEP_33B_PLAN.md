# Step 33b: redacted operational status and local alerts

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 33a.

**Goal:** Show failed/stalled work and the last verified recovery checkpoint without
exposing secrets/evidence bodies or mutating accounting records.

**Architecture:** One captured read-only status projection over existing run,
integration, enrollment and recovery records. Render the same structured values
in authenticated UI and CLI; no external monitoring or notification service.
**Tech stack:** Existing Python/SQLite application and native UI.
**Spec:** [Step 33 visibility contract](STEP_33_PLAN.md), all global constraints and
its recovery-proof/status policy apply.

## Task 1: scoped failure visibility without sensitive payloads

**Files:** Focused status projection/tests, workspace/authenticated endpoint/static
and CLI. Parent owns documentation/CI/browser.

- [ ] RED: a nonterminal run idle15 minutes is stalled; a terminal review handoff
  is not. Use injected UTC time and exact threshold boundaries without sleeps.
- [ ] Report failed runs, pending enrollment, incomplete reads, uncertain exports,
  drift and last verified backup/restore with counts, stable scoped IDs, codes,
  times and durations. Missing prior backup is unavailable, not a green result.
- [ ] Preserve all accounting/workflow records during reads. No automatic retries,
  posting, external calls, restore or alert messages leave this status view.
- [ ] Plant synthetic secret/body/description sentinel strings in underlying
  records; none may appear in metrics, logs or UI. Unknown errors use safe codes.
- [ ] Exercise authorization, cross-entity denial, corrupted/incomplete status
  metadata, clock thresholds and later changes without rewriting old captures.
- [ ] Add local status/alert view and `demo-operations-status`, with links to the
  relevant authorized run/import/export/recovery record and explicit next action.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, parent browser,
  independent review, commit/push/exact CI before final synthetic acceptance.
