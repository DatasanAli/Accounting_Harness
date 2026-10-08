# Step 30: offline QuickBooks journal-read contract

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 29b.

**Goal:** Import a paginated synthetic QuickBooks Online JournalEntry batch into a
separate, reconciled staging mirror with safe retries and interrupted resume.

**Architecture:** A concrete QBO v3 adapter constructs bounded sandbox requests
and parses exact journal data through an injected transport. This delivery uses
only a deterministic local simulator. The local accounting ledger remains the
authoritative book; staged external records never post themselves or become local
actuals. Keep this ownership decision visible beside the import result.

**Tech stack:** Python standard library, SQLite and the authenticated workbench.
**Spec:** [Phase 09](README.md). Live connection remains explicitly deferred.

## Global constraints

- No credentials, OAuth handshake, real realm discovery, API call or remote write.
  Label every demonstration and UI result **Offline contract simulation**.
- Scope every checkpoint/object/version to local entity, connector identity,
  sandbox realm, USD policy, account map and fixed query window. A browser cannot
  submit an arbitrary host, URL, filesystem path, realm or ledger owner change.
- Decimal JSON numbers are decoded with Decimal or their exact lexical form;
  never convert through a float. Convert to integer cents without rounding.
  Reject boolean/nonfinite/negative amounts and unsupported precision/currencies.
- Remote descriptions are inert data. Retain only necessary normalized synthetic
  fields and response fingerprints; no credentials or raw traces in public files.
- Authenticated preparer/owner starts or resumes reads; authorized readers inspect
  the mirror. All existing human approval and posting policies remain intact.

## Concrete transport and mapping contract

Target only `https://sandbox-quickbooks.api.intuit.com/v3/company/{realm}/query`
and JournalEntry query/read semantics. The transport consumes a server-built
request and returns status/headers/body bytes; no production transport is enabled
in this slice. Use strict server-provided realm and account-ID mapping. The
mapping is versioned and captured in each batch; never guess from account names.

A query uses a fixed inclusive January transaction-date window and explicit
STARTPOSITION/MAXRESULTS pagination, starting at 1 with page size 100. Maximum
100 pages/10,000 records; reaching a cap is incomplete, not a successful total.
Each next position follows the observed accepted page length. Validate response
start position, count and row IDs; a repeated or nonadvancing page is an exception.
Empty/short pages terminate the synthetic batch. Do not claim that offset
pagination is an atomic snapshot of a changing live company: changed/repeated
objects during the batch are surfaced, and real remote snapshot verification is
part of the deferred live gate.

Map `Id`, `SyncToken`, `TxnDate`, `CurrencyRef`, line `Id`, `Amount`, `DetailType`,
`JournalEntryLineDetail.PostingType` and `AccountRef.value`. Require supported
JournalEntryLineDetail debit/credit lines, at least two positive lines and exact
balance. Require unique remote journal IDs within a page and stable line identity.
Optional descriptions/names can be displayed but cannot select an account.
Unsupported tax/entity/special detail cannot be silently flattened into a simple
local journal. Preserve an explicit unsupported-record finding.

CurrencyRef must be USD, or may be absent only when the captured connector config
explicitly says this fictional realm has USD home currency and multicurrency is
disabled. Missing knowledge is an error, not an automatic USD assumption.
Unmapped account IDs, wrong dates, malformed/duplicate JSON fields, excess amount
precision and unbalanced records stop page acceptance without advancing its cursor.

Remote identity is realm + JournalEntry Id; changed SyncToken/content becomes an
immutable new observed version, never an edit to the old observation. The same
version with different accounting content is a conflict. Exact repeated pages
reuse their observations and cannot double-count totals. Persist normalized
observations, page receipt and next cursor atomically; a crash before/after any
write resumes from a defined checkpoint without touching local journals.

For 429, retain the same cursor and a persisted next-attempt time: at least 60
seconds, or a later valid Retry-After. Use an injected clock and return control;
never sleep inside a request. Bounded transport failures remain resumable; schema,
identity or mapping errors require explicit correction/new batch, not blind retry.

A completed report captures every accepted ID/version, per-account debit/credit
cents, total debits/credits, page/checkpoint digests and policy. An incomplete batch
shows accepted counts and exceptions without calling them a reconciled full total.
Reference fixture: three journals of 100.00, 200.00 and 300.00, served in two pages,
gives 600.00 debits and credits, three distinct IDs and no local journal changes.
Use page size 2 in that injected test configuration, preserving production limits.

## Primary contract references

Checked in rendered official Intuit documentation on 2026-10-08:
[JournalEntry fields and sandbox endpoint](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/journalentry),
[query pagination](https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api/data-queries),
and [rate limits](https://static.developer.intuit.com/output_html/qbo/docs/learn/limits-and-throttles.html).
The selected source schema is an implementation contract, not observed remote
compatibility. Recheck version details before enabling a real sandbox connection.

## Task 1: staged, resumable synthetic journal import

**Files:** Focused QBO mapping/transport and staging service/tests, synthetic
fixtures and CLI/workspace/HTTP/static integration. Root owns docs/CI/browser.

- [ ] RED: import two synthetic pages, reconcile three remote IDs and 600.00 per
  side, with exact local ledger/approval/report bytes unchanged.
- [ ] Build strict exact mapping and immutable scoped observations/checkpoints.
  Reject wrong realm/entity/currency/map, malformed pages, duplicate fields,
  precision errors, unsupported lines and account-name guessing.
- [ ] Interrupt before/after page commit; restart and retry yield the same mirror,
  totals and history. A same-version content conflict cannot overwrite evidence.
- [ ] Exercise 429/Retry-After, transport failure, repeated cursor, row/page caps,
  changing versions and incomplete reports with deterministic clocks/fixtures.
- [ ] Verify authenticated read/start/resume permissions, cross-entity denial,
  write rollback, concurrent same-page retry and pure captured reports.
- [ ] Add a small integration status view and `demo-sandbox-read`; all labels say
  offline simulation and no external or local-ledger writes are performed.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, independent
  review, commit/push/exact CI. Keep real sandbox verification deferred.
