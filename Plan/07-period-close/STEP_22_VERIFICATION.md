# Step 22 verification: confirmed close and date lock

Observed on 2026-10-08 using the original-path Step 21 browser workspace and its
verified January 1 insurance purchase variant. Live connections remained disabled.

## Browser demonstration

Before closing, both complete January 31 and January 15 financial report objects
matched the saved Step 21 reports exactly. Original journals and trial balance
were unchanged: 11 journals, 13,300.00 in each trial-balance column.

Native Period close → Capture close preview displayed net income 1,100.00,
assets 11,500.00, liabilities 600.00, ending equity 10,900.00 and a 900.00 capital
transfer. The preview registered/enrolled one generated calculation artifact; it
created no journal or lock. Its readiness details showed reconciled activated
controls and no imported bank statement. The separate confirmation checkbox was
unchecked and Close and lock January was disabled until checked.

Native confirmation produced exactly one compound closing journal and a January
1–31 lock. The 12-journal ledger retained all 11 originals; temporary balances were
zero, Owner Capital 10,900.00 credit, Cash 9,400.00 debit, and post-close trial balance
11,500.00 per side. The view exposed the original preview digest, human actor,
recorded timestamp, approval and closing journal references.

The saved close's entire pre-close statement object matched the Step 21 January 31
report. Fresh statements explicitly excluded the closing journal and retained
income 1,100.00, equity 10,900.00 and a zero balance-sheet residual. An exact HTTP
confirmation retry returned 200 and the original close without another journal.

A native offline proposal for the unused 125.00 software receipt dated January 5
produced a reviewable draft. Separate Approve & post returned 409: “period is
closed; posting date is locked”, visibly displayed in the UI. The existing
approval action retained an approved, unposted draft; all journals and balances
remained unchanged. This demonstrates refusal of the posting, not removal of its
human approval. No provider call occurred.

Actual 390px viewport and document width both measured 390px with the closed
period view displayed. A fresh process running the frozen final code returned
identical complete state (close, sources, drafts, journals and trial balance) and
identical complete January 31/15 reports. The persisted pre-close statements still
matched the original Step 21 capture.

## Automated verification and delivery

- Guarded full suite: **588 tests passed in 40.827 seconds**.
- Focused close suite: **19 tests passed in 1.630 seconds**.
- All **31 demonstrations** passed, including `demo-close`.
- Foundation, JavaScript syntax and diff whitespace checks passed.
- Independent review approved spec compliance and task quality with no findings.
- Delivered commit [1bdb15e](https://github.com/DatasanAli/Accounting_Harness/commit/1bdb15e9e98dc1f188fb5de2b410c5f9793b620c) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37834858650) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_close.py -v
python3 -m accounting_harness demo-close
node --check accounting_harness/static/app.js
```

## Scope

Only the configured synthetic January period and owner-capital policy are
supported. A local operator confirmation is not authenticated access; that remains
Step 29. Reopening and prior-period corrections require a later audited policy.
Preparing calculation evidence does not grant posting permission. A code rollback
must preserve a valid close and its immutable accounting history.
