# Step 23a verification: captured direct cash flow

Observed on 2026-10-08 against the retained, closed operational reference month.
Live providers and external accounts remained disconnected.

## Browser demonstration

Before the new view was used, the complete Step 22 workspace state and January 31/15
financial report objects matched their saved baselines. The workspace retained
12 journals, including one explicitly classified closing journal.

Native Reports → Capture cash flow at January 31 showed operating receipts 2,100.00,
operating payments −2,500.00, net operating −400.00, investing 0.00, financing 9,800.00,
opening 0.00 and ending Cash 9,400.00. The cash bridge residual was 0.00 and
classification was complete with no exceptions. The closing journal was excluded.

Expanding the January 20 software payment showed Cash credit 100.00/AP debit 100.00,
the original bill and cash evidence, posting actor and timestamp. The nested
approved-payment trace retained both payment and bill approval references and
identified the bill's Software Expense 5100 classification.

Changing the cutoff input retained the January 31 capture until Capture cash flow
was pressed. Native January 15 then showed receipts 1,500.00, payments −2,400.00,
operating −900.00, investing 0.00, financing 10,000.00, ending Cash 9,100.00 and residual
0.00. Ordinary Refresh retained identical rendered capture HTML.

Actual device emulation measured 390px viewport and 390px document width after
recapturing January 31. The report remained visible without document overflow.
All sources, drafts, journals, close record, subsidiary reports and trial balance
were unchanged after these read-only actions. Both cash-flow report objects were
saved before restart. A fresh process on the frozen final code returned both
complete cash-flow report objects exactly, with identical full workspace state
and unchanged earlier financial statements.

## Verification and scope

- Guarded full suite: **608 tests passed in 42.346 seconds**.
- Focused cash-flow suite: **20 tests passed**.
- All **32 demonstrations** passed, including `demo-cash-flow`.
- Foundation, JavaScript syntax and diff whitespace checks passed.
- Initial review found an approval-content identity gap: altered captured evidence
  or revision digests could leave an AP payment classified complete. The fix checks
  exact binding/actor identity for both approvals; eight mutation cases failed
  before the fix and passed afterward. Scoped review marked the finding addressed
  with no new findings. The final full suite and frozen restart include this fix.
- Delivered commit [969b783](https://github.com/DatasanAli/Accounting_Harness/commit/969b783b2cf105114501403c0879380d696743c5) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37836761506) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_cash_flow.py -v
python3 -m accounting_harness demo-cash-flow
node --check accounting_harness/static/app.js
```

The report is a bounded direct-method policy over captured facts, not a posting
or a claim that descriptions establish classification. Unsupported transactions
remain visible exceptions; a balanced cash bridge alone does not establish
complete classification. The original financial statement contracts are preserved.
