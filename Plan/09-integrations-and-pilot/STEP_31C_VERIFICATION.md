# Step 31c verification: authenticated workbench

Date: 2026-10-21. Scope: existing localhost workflows with temporary synthetic
identities, evidence and ledgers. No new accounting policy, database migration,
live model call, external connection or actual pilot acceptance.

Local implementation, native browser acceptance and independent review are complete.
Final local verification passed: **860 tests and all 45 demonstrations**, foundation
links/reference checks, JavaScript syntax and diff whitespace. Exact GitHub CI
is pending at the implementation commit.

## Workflow inventory

| Task area | Existing services reachable from the workbench |
| --- | --- |
| Evidence and preparation | Receipt registration/provider preparation; cash expense and earned cash; owner contribution/drawing/prepaid purchase; bill and payment; invoice and collection; advance and earning; corresponding paired evidence and draft forms |
| Human review | Current draft revision, validation findings, source evidence, separate unchecked exact-revision confirmation, rejection, approval and posted audit |
| Ledger, subsidiaries and bank | Journals/trial balance; AP bills/payments; AR invoices/collections/aging; advances/earning; statement import, matching/unmatching, fee classification/proposal, timing differences and reconciliation |
| Period reports and close | Prepaid coverage/consumption; expense/revenue accrual evidence and proposal; statements, cash flow and portable report export; close preview/confirmation and locked-period result |
| Projects and planning | Projects/attribution and unallocated actuals; service time/void; project cost scenarios; operating/cash budgets and static/flexible variances; contribution and captured indicators |
| Operational status and providers | Receipt and operational agent runs, cancellation/handoff, provider availability, offline QuickBooks read staging, owner-only fixed-account activation |

Existing authenticated services still authorize each action. UI visibility is a
convenience, not permission. Management assumptions stay separate from actuals;
bank timing classifications do not create journals. Live model accuracy and real
sandbox compatibility remain deferred.

## Automated verification

Before implementation, all 842 existing tests passed (111.903 seconds).
After the final fixes, the guarded full suite passed all **860 tests** (116.806
seconds). All **45 demonstrations**, including `demo-workbench`, passed on that
code. Foundation verification passed 126 Markdown files, 406 local links and
34 ordered steps. JavaScript syntax and diff whitespace checks passed.
The new HTTP contract tests pass for exact 90071992547409.93 USD values, hostile
source text retained as data, source/revision/approval/journal/report trace,
preparer denial, stale digest refusal, posting retry, store reopening, rejected
revision, disabled provider and grant revocation. The new CLI test first failed
because `demo-workbench` did not exist, then passed after implementation.

Commands for this step:

```sh
python3 -m unittest discover -s tests -p 'test_workbench*.py' -v
python3 scripts/run_tests.py
python3 scripts/verify_foundation.py
node --check accounting_harness/static/app.js
python3 -m accounting_harness demo-workbench
git diff --check
```

The demo starts a temporary loopback HTTP server and real local identity store.
It verifies all six navigation groups, real login/entity selection, provider
availability and the preparer/reviewer route contract. A preparer registers two
rent facts and prepares a draft with no journals. Direct preparer approval gives
403; separate reviewer approval gives one 125.00 USD journal. Retrying preserves
that journal and its source-to-report trace. This is a presentation/HTTP contract
demo; native browser evidence is recorded separately.

## Native browser rehearsal

The parent drove Chrome through the browser tools with a synthetic workspace on
127.0.0.1:8799 and isolated preparer/reviewer browser contexts. Login, evidence
entry, preparation, confirmation and approval used Tab, keyboard text entry,
Enter and Space. Read-only browser evaluation inspected resulting state/focus;
a separate deliberate direct fetch tested the preparer denial.

- The preparer navigated the owner/prepaid workflow disclosure, entered both
  125.00 owner-contribution facts, and prepared revision 1. Entered data remained
  in the form; the review handoff focused the main result. Journal count was 0.
- A direct authenticated preparer `POST /api/approve-post` returned 403 and left
  journal count 0. No approval control was visible for that identity.
- The reviewer saw exact accounts 1000/3000 and both evidence summaries, with an
  unchecked revision-specific confirmation and disabled approval. Checking it
  enabled approval. Following the original-source link selected the exact source;
  native browser Back cleared confirmation. Reload also cleared confirmation,
  with no journal created by either navigation.
- Keyboard confirmation and approval created one 125.00 owner journal.
- A separate keyboard preparation of the existing 125.00 software receipt created
  a pending expense without changing journal count. Keyboard reviewer approval
  created the second journal and focused the retained posted draft card. The
  resulting-journal link opened and focused its exact ledger article.
- An additional *unposted* huge-amount fixture used 90071992547409.93 USD, long
  source IDs and hostile `<script>`/`<img>` text. The browser displayed
  `$90,071,992,547,409.93` exactly and created no script/image DOM nodes from that
  text. Its pending proposal did not change the two posted journals.
- At an actual 390×844 CSS viewport, all 18 views had document scroll width equal
  to client width (375 pixels with the browser scrollbar). At 1280×900 desktop,
  all 18 also fit. Review, source, journal and exact-audit text remained readable;
  the persistent identity/entity/role/period/provider header stayed visible while
  scrolling. Table overflow stays within its own container.
- The server process was stopped and a new process opened the same synthetic
  databases. The serialized journals and draft ID/revision/status/evidence/approval
  traces compared exactly equal before/after restart. The journal deep link still
  selected the correct article; captured statements referenced both posted entries.
- After the routing fix below, a hard reload at `#evidence/source-%` displayed a
  bad-link message while retaining the authenticated identity. Revoking the
  preparer's entity grant then triggered the session monitor: state became null,
  all protected views were hidden and the no-entity-access screen appeared.

Final browser console checks contained only expected 403 resource/access probes;
no application JavaScript exception remained. Browser keyboard/viewport evidence
is a synthetic rehearsal, not a complete assistive-technology certification.

## Independent review and corrections

An independent agent reviewed the complete step diff for specification compliance
and code quality. One Important issue was found: malformed percent encoding in a
source hash could throw after initialization unlocked the page, leaving identity
null and disabling session monitoring. Source decoding now reports the bad link
locally, and any unexpected initialization failure clears/locks protected state.
Both regressions were observed failing before the fix and passing afterward.
Scoped re-review approved both verdicts with no remaining findings.

The parent's browser checks also found and corrected lost focus after posting and
narrow report overflow. Successful decisions focus their retained draft after the
last redraw; failed refresh keeps error focus. Explicit grid tracks and wrapping
of standalone snapshot-digest paragraphs fixed all three adjustment views.

The two previously assigned UI issues are fixed: in-flight project capture blocks
attribution preview, and indicator month edits/failed reloads invalidate cached
inputs. Other historical accounting-code minor findings remain outside this step.

## GitHub delivery

Implementation upload and exact-SHA CI are pending. No previous green run is
substituted for this step's result.

## Rollback and limitations

Use a new revert commit for published code. This step changes presentation and
adds demonstrations/tests; financial schemas, policies and historical records
remain unchanged. Posted activity is corrected only through supported linked
reversal services, never by removing data.

Synthetic offline acceptance does not establish live model accuracy, remote
sandbox compatibility, live export delivery or real-data pilot readiness.
