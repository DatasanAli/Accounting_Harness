# Step 24a verification: project attribution

Observed on 2026-10-08 in the original retained closed synthetic reference workspace.

## Native attribution and corrections

Created Project A and Project B through native forms. Captured the ordinary
300.00 Software Expense line, entered A 120.00 / B 100.00 and reviewed the whole set.
Before confirmation no assignment existed. Explicit confirmation saved one
revision; recapture showed 220.00 allocated and 80.00 unallocated on that line.

The whole report reconciled revenue 2700.00 and expenses 1600.00. Expense allocated
220.00 plus unallocated 1380.00 equaled actuals. Project/customer/category/behavior/
traceability groups independently partitioned those same 220.00; the closing
journal was excluded. Native source audit showed the vendor bill/incurrence,
journal and one-based line, digest, effective date, posting actor and attribution
actor/prior revision.

A 250.00 plus B 100.00 was refused visibly before a request, retaining entered data
and the old report. A subsequent explicit correction saved A 110.00 / B 100.00 with a
reason. Saving and Refresh retained the displayed prior capture until recapture.
An exact original HTTP retry returned its original revision after the correction;
a new request with a stale predecessor returned 409 without overwriting metadata.
A third explicit correction restored A 120.00 / B 100.00 and the 80.00 remainder.

## Preservation and restart

Complete persisted workspace state stayed equal to its prior baseline: 12 journals,
closed trial balance 11500.00, all evidence, reviews, sources and subsidiary reports.
Both January 31/15 financial statements and cash-flow report objects remained exact.
January 31 JSON/ZIP and January 15 JSON portable downloads stayed byte-identical.
The fresh server CSRF token is operational state and is excluded from comparison.

Frozen-code restart reproduced the entire final attribution report and all those
prior-state/report/download comparisons. At a true 390px viewport the document
width was 390px; the saved allocation form contained 120.00/100.00 and usable source
selection. At 1280px the report was present without horizontal document overflow.

## Checks and delivery

- Focused project suite: 17 tests passed in 1.335s.
- Guarded full suite: 645 tests passed in 46.295s; discovery-zero guard unchanged.
- All 34 demonstrations, foundation, JavaScript syntax and diff checks passed.
- Initial absent-feature and later absent-route/demo failures preceded implementation.
- Independent review approved spec and quality with no blocking findings. One
  Minor UI race is queued for the workbench/final review: a recapture finishing
  during assignment preview can replace displayed source context while the
  pending request remains correctly bound. Server accounting checks remain intact.
- Delivered commit [c5ce264](https://github.com/DatasanAli/Accounting_Harness/commit/c5ce264412de606bd620dbae5538bf4080347b92) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37841528029) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_project_dimensions.py -v
python3 -m accounting_harness demo-project-dimensions
node --check accounting_harness/static/app.js
```

The additive schema is project_dimensions version 1; existing financial/review/
close formats remain unchanged. Metadata does not post, change a closed-period
journal or grant human approval. Local operator remains unauthenticated until
Step 29. All data is synthetic and live connections remain deferred.
