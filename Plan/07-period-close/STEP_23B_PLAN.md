# Step 23b: portable reports with exact read-back

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 23a.

**Goal:** Download the captured financial statements and cash-flow report as
portable JSON and readable CSV, then reproduce exactly the same reports offline.

**Architecture:** One strict versioned export package contains the capture and
its pure derived reports. Canonical JSON is the authoritative portable format.
A deterministic readable CSV projection is distributed with that same JSON
manifest, avoiding a second incomplete snapshot representation in CSV columns.
Read-back validates both and never imports journals into a workspace.

**Spec:** [Step 23 contract](STEP_23_PLAN.md).

## Global constraints

- Exact cents, ISO dates, captured account names/metadata, entity/period, report
  policies, ordinary/closing classifications and full journal/source references.
- Package identity derives from canonical captured data and report policy. It is
  an integrity fingerprint, not a signature, proof of provenance or authorization.
- A download uses one immutable capture for all reports. A concurrent post cannot
  mix a new balance sheet with an old income/cash-flow statement.
- Read-back is offline and read-only. Unknown fields/versions, duplicate JSON keys,
  floats/bools as cents, malformed dates, missing references and inconsistent
  digests or recalculated totals fail; no best-effort financial reconstruction.
- No filesystem path from a browser is opened by the server. Exports contain only
  the selected synthetic accounting/report data, never secrets or provider traces.

## Package and projection

Use the standard library. Define explicit schema and report-policy identifiers.
Canonical JSON carries the immutable capture and derived statement objects;
cent values travel as signed decimal-integer strings to remain exact in consumers
that default JSON numbers to floating point. Strictly validate and rehydrate into
integer cents before calculation. Preserve recorded decimal money strings too
only where required by the existing report shape; reject disagreement.

Create a readable UTF-8 CSV with one header and deterministic statement/section/
row ordering. Include report kind, row identity/label, account or journal reference,
exact signed cents, decimal amount, currency and snapshot/report identifiers.
Repeat necessary metadata in explicit columns or a documented manifest reference.
Never export Python object repr or rely on locale-specific date/number formatting.
Use csv writer/reader for commas, quotes, newlines and Unicode. Spreadsheet text
cells beginning with formula triggers need an explicit reversible safe encoding;
keep original values in the canonical manifest, document the CSV encoding, and
never let that presentation encoding silently change financial identities.

Bundle `report.json` and `report.csv` with fixed names using a small ZIP download
when the user selects CSV plus manifest. Deterministic member order, fixed archive
metadata and no current-time field in hashed content make repeated export from
one capture byte-identical. JSON-alone download remains available. A display
export time may be separate from the snapshot identity if needed; do not add it
merely to make downloads differ.

Read-back accepts the JSON package alone or the fixed two-member archive. Validate
sizes/member names before reading; reject traversal names, duplicate/extra members
and oversized content. Do not extract archive paths to disk. Recalculate reports
from the captured facts and compare canonical bytes/digests. For CSV packages,
regenerate the documented projection and require exact parsed values/ordering.
Changing a label, date, cents value or referenced journal must be detected unless
the whole self-consistent package is explicitly treated as a new untrusted capture.
Do not claim these unsigned packages resist a deliberate complete rewrite.

The accepted package can be inspected in a read-only preview carrying its original
entity/period/digests and a clear imported-report label. It cannot supply evidence,
approval, model instructions or posted transactions. Bound upload/read-back bytes
explicitly for synthetic fixtures; do not silently raise the existing general
HTTP JSON limit for unrelated endpoints. If native browser read-back is omitted
from this slice, a documented CLI verification command must demonstrate it.

## Task 1: deterministic export and strict portable reproduction

**Files:** Focused report-export module/tests, CLI and workspace/download/static
integration. Parent owns docs/CI/browser/delivery.

- [ ] RED: export the verified reference snapshot; read JSON and CSV+manifest back
  without a live database and reproduce all dates, exact cents, trace and report
  digests, including Cash9,400.00/income1,100.00/equity10,900.00.
- [ ] Assert repeated same-capture downloads are byte-identical; later ledger,
  account and close changes leave the old package/reproduction unchanged.
- [ ] Refuse malformed/duplicate fields, unsupported schema/policy, bad references,
  changed totals/digests, altered CSV rows and unsafe/oversized archives. Cover
  Unicode/CSV quoting/formula-leading labels, negative/large cents and no activity.
- [ ] Verify export/read-back performs no ledger/source/review mutation and cannot
  authorize a post. Fetch all linked reports from one capture under concurrency.
- [ ] Add JSON and CSV+manifest download controls and a verification CLI command;
  `demo-report-export` round-trips a temporary synthetic package and prints common
  snapshot/report identities. Browser-check filename/content/exact values.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; independent
  review, commit/push and exact CI before management dimensions.
