# Step 21 verification: captured financial statements

Observed on 2026-10-08 using the verified Step 20d operational month. The original
reference fixture remains unchanged; the operational purchase date is January 1.

## Browser demonstration

A fresh browser opened the retained 11-journal operational workspace. Native
Reports → Capture statements produced the linked January 31 statements:

- Revenue 2,700.00; expenses 1,600.00; income 1,100.00.
- Opening capital 0.00; contributions 10,000.00; drawings 200.00; equity 10,900.00.
- Assets 11,500.00; liabilities 600.00; equation residual 0.00.

The three statements shared the same snapshot and policy. Expanding Service
Revenue displayed its 2,500.00 invoice and 200.00 earning, with their exact journal,
source and posting-actor references. The account total remained 2,700.00.

Changing the date input left the January 31 capture visible until Capture was
pressed. A native January 15 capture then showed five journals, revenue 2,500.00,
expenses 1,200.00, income 1,300.00, assets/equity 11,300.00, liabilities 0.00 and zero
residual. Statement selection showed only the requested balance sheet.

Device emulation used an actual 390px viewport with 390px document width. After
recapturing on the emulated page, ordinary Refresh retained identical report HTML.
The complete sources, drafts, journals and trial balance matched the saved seed
state after the read-only browser actions. A fresh process running the frozen
final code returned byte-identical complete January 31 and January 15 report JSON,
unchanged journal/trial-balance JSON, and the same 11 journals.

## Automated verification

- 13 financial-report tests and 11 existing HTTP tests passed.
- Guarded full suite: **569 tests passed in 39.063 seconds**.
- All **30 demonstrations** passed, including `demo-statements`.
- Foundation, JavaScript syntax and diff whitespace checks passed.
- Independent review approved spec compliance and task quality with no findings.
- Delivered commit [511d932](https://github.com/DatasanAli/Accounting_Harness/commit/511d93203a82227b00794462267b372a2e275178) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37832868799) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_financial_reports.py -v
python3 -m accounting_harness demo-statements
node --check accounting_harness/static/app.js
```

## Capture and scope

The immutable capture retains the effective catalog, posted journal lines, actors,
recorded times, source references, reversal links and explicit ordinary/closing
classification. Rendering uses only the capture, exact integer cents, and the
frozen USD/accrual/zero-opening/owner-capital policy. Signed and contra balances
remain visible; a nonzero equation residual cannot be called reconciled.

Existing ledger and subsidiary snapshot formats remain unchanged. Current storage
classifies every journal as ordinary; Step 22 will provide the persisted closing
classification in the same capture transaction. Pure statements already exclude
closing transfers consistently. No close, posting, schema migration, external
connection or unsupported reporting basis is added by this slice.
