# Step 23b verification: portable report packages

Observed on 2026-10-08 with the retained closed operational reference workspace.
All files and accounting data used in these checks are synthetic and remain local.

## Native downloads and offline read-back

Reports → Capture and download reports returned `report.json` (96,022 bytes,
application/json) and `reports.zip` (122,658 bytes, application/zip). Native response
headers supplied those attachment filenames and the same package digest. UI copy
states that downloads capture current books together while displayed captures
remain available; unsigned packages grant no provenance or posting authority.

Repeated native downloads of each format were byte-identical. The archive had
exactly `report.json` then `report.csv`; its JSON manifest exactly matched the
standalone JSON. The report files fetched for CLI verification had the same
SHA-256 values as the native browser response bytes.

The local verification command reproduced the same package/report identities from
both files and printed “Imported report · untrusted, read-only” with posting
authority false. Both showed Cash 9,400.00, income 1,100.00 and equity 10,900.00.
A native January 15 JSON download and CLI verification showed Cash 9,100.00,
income 1,300.00 and equity 11,300.00 with a distinct package identity.

Changing the package's reported income to 9,999.00 caused CLI exit 2 with a
capture/calculated-value/digest disagreement. The complete workspace state stayed
unchanged after downloads, read-back and refusal: all sources, drafts, journals,
subsidiary reports, close record and trial balance matched the saved baseline.

At an actual 390px viewport, document width was 390px. The native download control
worked and displayed the same January 31 package identity without overflow.

```sh
python3 -m accounting_harness verify-report-export /path/to/report.json
python3 -m accounting_harness verify-report-export /path/to/reports.zip
```

## Checks and delivery

The focused suite passed 20 tests (2.044s), and the guarded full suite passed
628 tests (45.245s). All 33 demonstrations, foundation, JavaScript syntax and diff
checks passed. The zero-test discovery guard remains. Initial test-first failures
and a subsequently reproduced missing-Cash reference error preceded the fixes.

Both downloaded formats verified with the localhost server stopped. Restarting
the frozen final code reproduced January 31 JSON/ZIP and January 15 JSON bytes
exactly. Complete persisted state (excluding the fresh server CSRF token) and both
cutoffs of the prior financial and cash-flow reports matched saved baselines.
The final native mobile download retained its package identity and 390px width.

Independent review found an exporter/read-back mismatch for CSV fields above
Python's default field limit. The ZIP exporter and reader now enforce the same
131,072-character limit after reversible text encoding, before emitting an
oversized archive. JSON keeps its separate 4 MiB bound. Unicode and formula-prefix
boundary regressions pass without altering global CSV parser settings. Scoped
review approved with no new findings. The final full suite, all demonstrations
and restart checks include this fix. Delivered commit [bf1fbb8](https://github.com/DatasanAli/Accounting_Harness/commit/bf1fbb8e369549babc02b007778574e72bc4ab3d) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37839537188) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_report_export.py -v
python3 -m accounting_harness demo-report-export
node --check accounting_harness/static/app.js
```

## Package scope

Canonical JSON is authoritative; CSV is its documented readable projection.
Read-back is a bounded local CLI operation and never opens an accounting workspace
or imports a journal. Hashes check internal consistency. A deliberately rewritten,
self-consistent unsigned package is new untrusted data, not authenticated evidence.
Real source documents, credentials, database files and provider traces are excluded.
