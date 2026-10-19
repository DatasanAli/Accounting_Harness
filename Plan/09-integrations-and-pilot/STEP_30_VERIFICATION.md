# Step 30 verification: offline QuickBooks JournalEntry read contract

Date: 2026-10-19. Scope: Step 30 only, as an **offline contract simulation** with
synthetic fixtures. No credentials, OAuth, realm discovery, network call or remote
write exists in this slice. Real sandbox compatibility remains a deferred live gate. Local verification, independent
review, GitHub upload and exact-SHA CI (attempt 2) passed.

## Delivered behavior

`accounting_harness/qbo_read.py` builds bounded QuickBooks Online v3 sandbox
JournalEntry queries for `https://sandbox-quickbooks.api.intuit.com/v3/company/{realm}/query`
(fixed January window, `ORDERBY Id STARTPOSITION n MAXRESULTS 100`, minor version
75). It calls only an injected transport. The shipped transport is a deterministic
in-process simulator over [the synthetic fixture](../../data/fixtures/qbo-journal-entries.json).
Production limits are 100 rows × 100 pages; tests inject page size 2 or fewer pages.

**Ledger ownership:** the local accounting ledger remains the authoritative book.
Staged observations live in a separate per-entity `qbo-staging.sqlite3` mirror.
They never post, approve or become local actuals. Every report and UI result
says so beside the import result and carries the label *Offline contract simulation*.

- **Scope.** Every batch captures entity, connector ID, sandbox realm, USD/multicurrency
  policy, versioned account-ID map, query window and limits. Observations are keyed
  by that scope + JournalEntry `Id` + `SyncToken`. The browser and facade accept only
  `batch_id`; host, URL, path, realm and map are server-owned. A batch cannot change scope.
- **Exact mapping.** JSON numbers are kept as exact lexemes and converted to integer
  cents without rounding. Booleans, strings, nonfinite, negative, zero, exponent and
  excess-precision amounts are refused. Only the captured account-ID map selects a
  local account; names/descriptions are inert display data. Lines must be
  `JournalEntryLineDetail` Debit/Credit with stable unique line IDs, at least two
  positive lines and an exact balance. A missing `CurrencyRef` is accepted only when
  the captured config states USD home currency with multicurrency disabled.
- **Page acceptance.** Malformed/duplicate JSON fields, wrong status/content type,
  `startPosition`/`maxResults` mismatches, duplicate IDs within a page, wrong dates,
  unmapped accounts, precision and balance errors refuse the page. The cursor stays
  put, and the batch requires correction or a new batch (no blind retry). Unsupported
  tax/entity/special detail is accepted only as an explicit `unsupported` finding.
  It is excluded from totals and is never flattened into a simple journal.
- **Checkpoints.** Observations, page receipt and next cursor commit atomically with
  a receipt digest and a chained checkpoint digest. Receipts exclude timestamps, so
  interrupted and clean runs produce identical mirrors and digests. Stale concurrent
  attempts write nothing. Repeated or changed objects within a batch are surfaced
  exceptions. A same-version content conflict is refused, and its original evidence
  is unchanged. A changed `SyncToken` is a new immutable observation.
- **Throttling and failures.** HTTP 429 persists the same cursor and a next-attempt
  time (at least 60 seconds, or a later valid delta/HTTP-date `Retry-After`) from an
  injected clock. Control returns without sleeping. Transport exceptions and 5xx are
  resumable at the same cursor, and only the failure class is retained.
- **Completion.** An empty/short page completes. A full page at the page cap is
  `incomplete`, never a reconciled total. The pure `batch_report(capture)` contains
  every accepted ID/version and content digest, per-account debit/credit cents, totals,
  page/checkpoint digests, policy, exceptions and attempts. It verifies input,
  receipt and checkpoint digests. Only a complete batch with no exceptions is labeled
  *Reconciled full batch total*.
- **Access.** A new preparer/owner capability `stage_external` starts or resumes reads;
  all roles inspect via `external_reads` (`read_reports`). The facade authorizes
  briefly, runs transport work outside the identity lock and rechecks authority
  around every staging commit, so revocation mid-batch writes nothing further.
  The [permission inventory](STEP_29B_INVENTORY.md) lists both entry points.
- **UI and CLI.** An *Integrations* view starts/resumes a batch and loads staged
  batches; reviewers see status without the start control. `demo-sandbox-read`
  demonstrates 429 handling, two pages, 600.00/600.00 reconciliation, exact resume
  and unchanged local books.

## Automated evidence

Final observed results: **824 application tests passed in 106.958 seconds** (802 prior + 22 new),
the 26 authentication-boundary tests passed unchanged, and **all 42 CLI
demonstrations passed**. Foundation links/reference accounting, JavaScript syntax
and diff whitespace checks passed. The reviewer independently reran the 22 focused
tests. Python and Node.js were available locally; CI runs the same checks.

```sh
python3 -m unittest discover -s tests -p test_qbo_read.py -v
python3 scripts/run_tests.py
python3 scripts/verify_foundation.py
node --check accounting_harness/static/app.js
git diff --check
python3 -m accounting_harness demo-sandbox-read
```

The reference test serves three synthetic journals (100.00, 200.00, 300.00) in two
pages with injected page size 2. Requests target only the bounded sandbox query
(STARTPOSITION 1 then 3). Results: three IDs, 600.00 USD debits and credits, and
per-account rows 1000 200.00/400.00, 4000 0.00/200.00, 5000 100.00/0.00 and
5100 300.00/0.00. Ledger, source and run file bytes, report package and workspace
state are unchanged, and an exact resume makes no request.

Red/green observations: the new suite failed before the module existed. The
first ledger-bytes check failed because the existing first `state()` call
lazily creates empty subsidiary schemas; the baseline now follows that read.
Inserting the UI block inside the variance renderer's sliced region broke an
existing Node renderer test; moving the block fixed it. Independent review then
found one Important gap: unsupported records returned before line checks, so
`100.001`, `true` or an unmapped account behind a tax field could advance the
cursor, and same-version changes looked identical. It also found seven Minor
items: lone-surrogate IDs, Retry-After overflow and missing cap, 429 timing measured
before the request, a failure erasing a 429 wait, malformed transport returns,
re-derivation of stored terminal state, and REPLACE through partial indexes.
Each now has a regression test that fails without its fix.

## Browser demonstration

A temporary synthetic workspace (`alpha`) with separate preparer and reviewer users
was served on 127.0.0.1:8799 with `serve --access-db`. Headless Google Chrome was
driven over the DevTools protocol by a throwaway script outside the repository.
The preparer logged in through the native form, opened **Integrations** and saw
the *Offline contract simulation* notice. Starting batch `january-read` showed
*complete · Reconciled full batch total* with three IDs, account rows and 600.00 /
600.00 totals at production limits (one page of three rows). The posted-journal
metric stayed 0. After logout, the reviewer saw no start/resume form and loaded
the same staged batch read-only. A direct reviewer POST to `/api/qbo-read` with the
session's valid CSRF token returned 403. At 390px width the document stayed 390px
wide. No JavaScript exception or console error occurred. The server was stopped
afterward; no real accounts or files were used.

## Review, delivery and rollback

Independent review found no Critical issues, one Important issue and seven Minor
issues (above). All eight were fixed. Re-review reran the probes and confirmed
each fix, with **no remaining Critical or Important findings**. A remaining Minor
(unchecked Amount on non-journal-detail lines) was also fixed and tested. Cosmetic
and live-gate notes are listed under limits.

Implementation commit [c022dfa](https://github.com/DatasanAli/Accounting_Harness/commit/c022dfa54b0d5a9042e5faecbf70cf33cd92beca) was pushed to origin/main; local and remote
SHA were compared. Its [exact-SHA GitHub CI run](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39278821004) concluded **success on
attempt 2**: the log shows `Ran 824 tests ... OK`, every demonstration including
`demo-sandbox-read` (600.00 / 600.00) and job cleanup about 2.5 minutes after start.
Attempt 1 ran every step successfully in 3m21s but was marked *cancelled: exceeded
5m*. That happened during GitHub's open incident "Degraded availability for GitHub
Actions, GitHub Pages and Webhooks" (from 15:49 UTC on 2026-10-19). Job and
check-run records lagged as `queued` during that incident; the run conclusion was
used as the exact-SHA result. This evidence update changes documentation only.

Rollback uses a new revert commit. The staging file is separate. Leaving or
removing `qbo-staging.sqlite3` cannot change local journals, approvals or reports.
Real accounting corrections still use linked reversals.

## Deferred and limits

Live sandbox OAuth, realm discovery, real response compatibility, rate-limit
behaviour and snapshot consistency across a changing company remain the deferred
live gate. Offset pagination is not claimed to be an atomic snapshot. The query
shape, `ORDERBY Id` and minor version are an implementation contract checked
against rendered Intuit documentation on 2026-10-08, not observed remote behavior.
The first `Workspace.state()` call lazily creates empty subsidiary schemas in a
fresh ledger (existing behavior); byte checks therefore baseline after that read.
Known Minor notes: after an expired 429 wait and a later transport failure, the
report still shows the past *next attempt* time (status is correctly resumable).
A transport exception other than `OSError`/`TransportError` propagates unrecorded,
with the cursor safe. A future live transport must return a plain `int` status.
