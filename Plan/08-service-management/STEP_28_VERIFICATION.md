# Step 28 verification: contribution and captured indicators

Observed 2026-10-08 on the original closed synthetic reference workspace, retaining
12 journals,600 active service minutes and all prior management versions.

## Native scenarios and reference values

Loaded scenarios and entered explicit assumptions: price 100.00, variable 40.00,
fixed 1200.00, relevant range 0–100 whole units and quantity 20. Review created no
version; separate confirmation saved the first immutable scenario. The UI showed
60.00 unit contribution, 60.00%margin, exact 120000/6000threshold and 20 whole units.
Model profit at 20 units was 0.00, distinct from recorded actuals.

| Captured indicator | Display | Exact numerator / denominator |
| --- | ---: | --- |
| Current ratio | 19.17 | 1150000 / 60000 |
| Quick ratio | 17.33 | 1040000 / 60000 |
| Net profit margin | 40.74% | 110000 / 270000 |
| Recorded service minutes | 600 | 600 / 1 |
| Revenue per recorded service hour | 270.00 USD/hour | 16200000 / 600 |

Expanded trace identifies sources, journals, account classifications and excluded
closing entries. Prepaid 1100.00 is current but not quick; noncurrent equipment and
accumulated depreciation are excluded. Recorded time does not establish capacity,
completeness or utilization. Unknown classification and invalid denominators have
explicit unavailable results; no financial-health or investment claim is made.

Native Use as prior created version 2 with quantity 21 and Quick ratio deselected:
profit 60.00 and four selected indicators. Version 3 changed price to 40.00 while
variable cost remained 40.00: contribution 0.00, profit −1200.00 and both continuous
and whole-unit thresholds unavailable. Fixed/contribution inputs remain visible.
Original-version retry returns its exact receipt after both successors; a new
request with stale predecessor returns 409 and leaves exactly three versions.

## Retention, mobile and restart

Native Download displayed indicator JSON produced 80,709 bytes equal to the entire
first saved result. With the server stopped, the pure renderer reproduced the
complete report from its retained capture. All three historical responses remain
exact after the final-fix server restart. Financial state, attribution, full time
history, both cost models, all three budgets, January 15/31 financial/cash-flow
reports and all three earlier portable export byte streams remain unchanged.

At true 390px mobile width the document is 390px and form 320px; wide indicator
tables scroll within 356px containers without page overflow. Refresh preserves the
visible version 3. At 1280px after final-fix restart, native View saved indicators
reopened version 1 with all original values; document 1265px/form 560px fit the page.

## Review and checks

Initial review found a shallow copy of nested liquidity-policy lists. Mutating a
returned report could change global calculation policy. The failing regression
reproduced this; detached canonical JSON output fixes it without changing stored
versions, report values or hashes. Independent scoped re-review approved spec and
quality with no Critical/Important finding. A separate Minor—edited month controls
can retain cached inputs after a failed reload—is assigned to 31c/final review.

- 22 focused indicator tests passed in 1.294s, including policy output mutation,
 historical rerender, signed ratios, invalid inputs, concurrency and migration.
- 741 guarded application tests passed in 53.114s; zero-discovery guard retained.
- All 39 demonstrations passed; the indicator demo was rerun after the alias fix.
- Foundation, JavaScript syntax and diff checks passed.
- Delivered commit [b7f4a3a](https://github.com/DatasanAli/Accounting_Harness/commit/b7f4a3a93ab651b1e60444c4e2904a9e7f373469) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37851117480) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_indicators.py -v
python3 -m accounting_harness demo-indicators
node --check accounting_harness/static/app.js
```

Indicator schema 1 adds immutable whole versions with audit and a financial/time
capture from one transaction. Positive contribution uses exact integer ceiling;
zero-fixed/zero-contribution is indeterminate. Scenarios do not post entries.
Authentication follows in 29a/29b; live provider connections remain deferred.
