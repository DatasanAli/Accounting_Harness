# Step 26 verification: operating and cash budgets

Observed on 2026-10-08 in the retained closed synthetic operational workspace.

## Native scenarios and immutable versions

Loaded active budget accounts and entered a new cash scenario with explicit
1000.00 opening cash, 1500.00 January 31 receipt and 1200.00 January 31 payment.
Review alone left zero saved versions and 12 posted journals. Separate confirmation
saved version 1 with 1300.00 ending cash and no funding gap.

Used that saved version as predecessor, changed the receipt date to February 28
through the native date control, and recorded an explicit reason. Version 2 shows
January ending cash -200.00, funding gap 200.00 and deferred receipts 1500.00.
The January payment remains 1200.00. The original complete version still matches
its first response, including audit and report. An exact historical request returns
version 1 after version 2 exists; a new request with the stale predecessor fails
409. There are two versions of this cash scenario.

Created a separate operating scenario with 480 planned minutes: account 4000 at
125.00/hour, account 5100 at 50.00/hour plus a fixed 100.00 line. Native review/save
shows revenue 1000.00, expense 500.00 and income 500.00. Cash stays zero because no
cash rows were entered. The report retains each line, captured account label,
amount/rate, integer numerator/denominator and rounding delta. No wages, payments,
borrowing or accounting entries are inferred from these assumptions.

## Browser finding, preservation and restart

Initial browser review was blocked because the optional source-reference selector
was marked required. An executing JavaScript regression reproduced this, and the
fix allows no reference while requiring an ID when actual/external is selected.
After reload, the complete native cash and operating flows above passed.

All budget actions preserved financial workspace state, current attribution,
complete time history, both old costing versions, January 31/15 financial and
cash-flow reports, and all three previously downloaded portable byte streams.
Final-code restart reproduced all three saved budgets and every preservation
comparison exactly. Ephemeral CSRF rotation is excluded from persisted state.

At true 390px width, the saved delayed scenario, cash schedule and funding gap are
readable with a 390px document and 320px form. At 1280px, the native saved operating
budget is readable with a 1265px document and 560px form. Neither has horizontal
page overflow.

## Checks and delivery

- Focused suite: 20 tests passed in 1.266s, including missing-feature and native
  optional-reference RED/GREEN evidence.
- Guarded full suite: 702 tests passed in 50.620s; zero-discovery guard retained.
- All 37 demonstrations, foundation, JavaScript syntax and diff checks passed.
- Independent review approved spec and quality with no findings.
- Commit/push/remote/exact CI checks are pending.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_budget.py -v
python3 -m accounting_harness demo-budget
node --check accounting_harness/static/app.js
```

Node.js is required by the native-control regression; the application and offline
CLI demos continue to use Python's standard library. Additive budget schema 1
retains whole immutable scenarios; existing financial formats stay unchanged.
This slice supports January USD budgets with a service-minute driver. Source
links prove enrolled identity only, not projected cash realization. Local operator
is not authenticated until Step 29. Live connections remain deferred.
