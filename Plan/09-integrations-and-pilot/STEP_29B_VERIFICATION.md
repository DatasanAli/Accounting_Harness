# Step 29b verification: authenticated application and UI

Date: 2026-10-14. Scope: Step 29b only, with temporary synthetic workspaces.
Local verification, independent review, GitHub upload and exact-SHA CI passed.

## Delivered behavior

Every protected HTTP route uses the authenticated facade. Session, entity and
role checks precede financial workspace construction; direct facade calls enforce
the same boundary. Stable user IDs reach new human actions. Agent runs retain a
separate runtime actor and initiating user, with authorization rechecked around
short effects after provider I/O. Unknown mappings deny. Owner activation is
required before preparers can use implicit control-account setup.

The UI starts with login and shows current user, role and entity. It hides
unauthorized controls, clears old financial state during logout/entity changes,
and ignores obsolete request/download/status-poll completions. Scoped pending
run metadata survives reload only for the matching authenticated user/entity;
users cannot cancel somebody else's run. The sidebar keeps logout reachable and
shows identity on mobile.

See the [exhaustive route/method and side-effect inventory](STEP_29B_INVENTORY.md)
and [local setup commands](../../README.md). Local portable report downloads are
report reads. The future external journal export requires separate authorization
in Step 32. Local HTTP is not TLS; remote hosting and live calls remain deferred.

## Automated evidence

Final observed results: **802 application tests passed in 100.288 seconds**;
**26 focused authentication tests passed** and were independently rerun by the
reviewer; **41 CLI demonstrations passed**. Foundation links/reference accounting,
JavaScript syntax and diff whitespace checks passed. README access-provision and
access-map-entity commands were executed successfully against a temporary
workspace. Python and Node.js were available locally; CI runs the same checks.

Commands:

```sh
python3 -m unittest discover -s tests -p test_authenticated_workspace.py -v
python3 scripts/run_tests.py
python3 scripts/verify_foundation.py
node --check accounting_harness/static/app.js
git diff --check
python3 -m accounting_harness demo-authenticated-workspace
```

The new tests exercise all public methods/action mappings and HTTP role denials
without opening financial files, native preparation/reviewer posting, forged
actors, stale confirmation, revoked retry, cookie replay/duplication, CSRF replay
and cross-session use, idle expiry, separate entities/foreign identifiers,
initiator-bound run control, provider-time revocation and concurrent posting/
revocation. Historical serialized database records and report/package values
remain identical after authenticated reads. Node executes actual UI handlers for
late report bodies, stale status polls, scoped recovery and run-control ownership.
Legacy HTTP tests now create real synthetic sessions and assert stable user actors;
trusted-core accounting tests retain their original actor contracts.

Red/green observations: idle polling initially extended sessions; report body and
status-poll continuations initially ignored scope changes; reload initially lost
pending run recovery; cancellation UI initially offered other users' runs. Each
regression failed before the fix. Owner accrual activation initially violated its
deferred FK outside a transaction. Existing close tests exposed the enrollment
signature mismatch. These were fixed and their checks rerun. The initial 780-test
suite had 12 failures/21 errors; the subsequent 796-test run passed before the
additional historical, concurrency and UI regression checks were added.

## Browser demonstration

A temporary workspace with alpha/beta and separate preparer/reviewer/owner users
was served on 127.0.0.1:8799. Native username/passphrase login and cash evidence
forms registered two January 5 facts for 125.00 USD. The preparer created the cash
draft; no approval control was visible and a direct browser POST returned 403
with zero journals. After logout, the reviewer logged in, inspected the two facts
and exact revision, checked confirmation and clicked Approve & post. Exactly one
journal posted; debit/credit totals were 125.00 with distinct stable preparer and
reviewer actors. Reviewer evidence-edit controls were hidden.

A fresh server process at the same port and path recognized the durable reviewer
session and retained the same journal/approval. Revoking the reviewer's alpha
grant through the trusted temporary fixture administrator cleared financial text
at the next status poll; the locked screen explained that no entity access
remained. No real financial files or provider accounts were used.

The owner then switched alpha (one journal) to beta (zero journals/five fixture
sources). The UI locked immediately and cleared the journal metric before the
selection request completed; beta displayed no alpha source text. At 390px width,
identity/role/logout were visible and document width remained 390px. At the
847px-high desktop viewport, logout was inside the viewport after the sidebar fix.
No JavaScript exception was observed; expected denied HTTP requests returned 403.

## Review, delivery and rollback

Independent initial review identified idle polling and a late-download race.
Re-review identified stale status-poll interruption, pending-run recovery and
other-user cancellation controls. Fixes and regression tests are included;
final independent re-review found no Important or Critical issues and independently reran all 26 authentication tests successfully.

Implementation commit [81a1d02](https://github.com/DatasanAli/Accounting_Harness/commit/81a1d021b4edd4aa3fc4bbce0f95e9177b363213) was pushed to origin/main; local and remote SHA were compared. Its [exact-SHA GitHub CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/38635277919) completed successfully, including all tests and demonstrations. This evidence update changes documentation only. Step 29a prerequisite was checked against
origin/main and successful [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37853022426)
for c48077187bf96b0383f28f877292de7b9110e1b5 before this delivery.

Rollback uses a new revert commit, preserving financial files and historical
actors/digests. Do not serve an older unauthenticated version to users. Stop the
server during rollback; restore/recovery and relocation need Step 33a's verified
procedure. Correct posted accounting with linked reversals, never deletion.
