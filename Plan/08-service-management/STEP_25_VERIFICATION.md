# Step 25 verification: versioned project costing

Observed on 2026-10-08 in the retained closed synthetic operational workspace.

## Native input preparation and costing

Project A retained 600 active minutes. Through native attribution review and
confirmation, a fourth Software Expense revision assigned A 100.00/B 100.00 and
left 100.00 unallocated; a separate invoice-revenue assignment attributed 1000.00
to A. Earlier assignments remain in history. Financial state and time did not change.

Captured actuals and time together, explicitly selected the 100.00 software
portion, entered 40.00/hour labor and 20.00/hour overhead and reviewed the version.
Before confirmation there were zero saved cost versions. Explicit save produced:
400.00 modeled labor + 100.00 direct actual + 200.00 modeled overhead = 700.00 cost;
1000.00 attributed revenue minus 700.00 = 300.00 modeled margin.

The native sheet distinguishes recorded actuals, operational minutes and rate
assumptions. It displays each actual's treatment, a 100.00 actual expense total,
600.00 model-to-actual difference, whole-ledger reconciliation and exact rational
calculation trace. Audit includes source invoice/bill/incurrence, journal/portion/
revision, time correction links, policy, actor and date.

Used the saved version as predecessor and changed only labor to 50.00/hour with
an explicit reason. Version 2 shows 800.00 modeled cost and 200.00 margin; version 1
still reproduces its original complete scenario and 700.00/300.00 sheet. An exact
old request returned version 1 after version 2 existed. A new update naming the
stale predecessor returned 409; only two saved versions remain.

## Preservation, layout and restart

Costing actions left the prepared attribution report, complete 600-minute time
history and all financial workspace state unchanged. Both prior January 31/15
financial and cash-flow report objects and all three saved portable download
byte streams remained exact. CSRF token rotation is excluded from persisted state.

Final-code restart reproduced both complete saved scenarios/cost sheets and every
prior state/report/download comparison. At a true 390px viewport, the document
was 390px and costing form 320px. Native selection reopened version 1 with 700.00/300.00;
its expanded complete audit retained source/time links without document overflow.
At 1280px, native version 2 shows 800.00/200.00 with a 560px form and
1265px document; there is no horizontal page overflow.

## Checks and delivery

- Focused suite: 19 tests passed in 1.633s, including initial missing-feature and
  missing unclassified-behavior finding failures before their implementations.
- Final guarded full suite: 682 tests passed in 49.083s; discovery guard unchanged.
- All 36 demonstrations, foundation, JavaScript syntax and diff checks passed.
- Independent review approved spec and quality with no findings.
- Delivered commit [c95bf45](https://github.com/DatasanAli/Accounting_Harness/commit/c95bf4599fd4fa63bddd8ae72cfb8e37f500d0ad) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37845470497) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_project_cost.py -v
python3 -m accounting_harness demo-project-cost
node --check accounting_harness/static/app.js
```

Additive project_cost schema 1 seals each scenario's request, audit, server-owned
actual/time captures and original sheet in one immutable row. Existing financial
formats are unchanged. Model labor/overhead are assumptions, not recorded wages
or financial net income. Local operator is not authenticated until Step 29.
Live connections remain deferred.
