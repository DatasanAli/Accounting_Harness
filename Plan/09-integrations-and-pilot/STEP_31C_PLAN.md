# Step 31c: coherent authenticated workbench and keyboard review

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 31b.

**Goal:** Make the delivered accounting, reporting, planning and agent workflows
navigable and reviewable in one localhost UI with a complete source-to-post trace.

**Architecture:** Organize existing views and forms, preserving their tested
application services. Use native controls, consistent status messages and exact
server data. Add no framework, duplicate state store or UI accounting engine.

**Tech stack:** Existing HTML/CSS/JS, authenticated Python endpoints and SQLite.
**Spec:** [Step 31](STEP_31_PLAN.md), all global constraints apply.

## UI and acceptance contract

Group navigation by actual user tasks: evidence/preparation, human review,
ledger/subsidiaries/bank, period reports/close, project/planning, and operational
status/providers. Give the selected entity, identity, period, role and offline
provider state a persistent home. Avoid an expanding undifferentiated list of
forms or exposing implementation JSON as the only way to understand a proposal.
Keep exact canonical trace details available in an expandable audit view.

Each flow shows required inputs, validation findings, resulting pending draft and
its next human action. Changes/errors preserve entered data; busy state prevents
accidental repeated clicks and a retry uses the same operation identity. After
posting, link back to original sources, approval/revision and the resulting
journal/report. Rejected/stale/claimed evidence is explained instead of silently
resetting the workflow. Every supported action remains subject to server checks.

All monetary values use server-rendered exact decimals; never JavaScript Number
arithmetic on cents. Render external text with textContent/native text nodes.
Sign, currency, effective date and status are visible. Management scenarios and
recorded actuals are distinct, and bank timing differences are not presented as
new journals. Unsupported settlement/correction/period policies remain explicit.

Keyboard users can reach navigation, forms, evidence, confirmation and results;
labels and validation are associated with controls, focus moves to the relevant
result/error, and status announcements do not steal focus. Approval has a separate
unchecked confirmation for the exact displayed revision. Native browser back/
refresh/restart must not submit an approval or reuse confirmation on another draft.
Layout must work at desktop and the actual narrow browser viewport without
horizontal document overflow; long IDs/trace JSON wrap or scroll inside their
own container. Do not weaken authorization merely to make an action button work.

## Task 1: integrate and demonstrate the supported workflows

**Files:** Static workbench plus necessary read-only API presentation hooks and
focused UI/HTTP contract checks. Root owns browser rehearsal, docs and CI.

- [ ] Inventory every supported operation/report and link it from the appropriate
  existing view; no missing owner/prepaid/adjustment or later management flows.
- [ ] Make role/entity/provider context and permission denial understandable;
  stale sessions clear protected state. Keep direct-route server denial coverage.
- [ ] Improve source/proposal/review/post handoffs and cited journal/report traces;
  use readable summaries with optional exact audit details.
- [ ] Cover hostile text, huge exact cents, pending/rejected/stale/posted states,
  failed retry, unavailable providers and empty data without misleading success.
- [ ] Parent performs keyboard-only preparation/review with separate identities,
  direct API preparer denial and reviewer approval, then refresh/restart trace
  inspection at desktop and narrow view. Journal count changes only on approval.
- [ ] Add `demo-workbench` for authenticated presentation/route contracts, run
  focused then guarded suite/foundation/all demos/JS/diff, independent review,
  commit/push/exact CI before the offline journal export contract.
