# Step 36 verification — 2026-10-31

Scope: supplied-input straight-line depreciation projection, under the
[user-selected policy](STEP_36_PLAN.md). No asset enrollment or posting capability.

## Observed checks

- Before implementation, the new focused suite failed because the schedule module
  and CLI command did not exist.
- After implementation, all nine focused tests passed. Reference 1,200.00/12
  gives twelve 100.00 allocations. The 100.00 cost / 10.00 residual / seven-month
  example gives six 12.85 allocations and final 12.90, including 2028-02-29.
- Exact large cents, zero allocations, date boundaries, input refusal, deterministic
  CLI JSON, changed-assumption identities and existing synthetic-ledger preservation
  passed. The demonstration also refused residual above cost.

Independent review found no Critical or Important issues. The reviewer ran all
nine focused tests and 500 deterministic generated schedules checking allocation,
total and residual invariants. All 52 demonstrations passed, including the new projection demo. Foundation,
JavaScript syntax and diff checks passed. Full application regression passed: **976 tests** in 189.667 seconds, exit 0.
The test runner and its zero-discovery guard were unchanged. GitHub delivery is
pending.

This is a CLI/pure calculation slice; no browser behavior or financial schemas
changed. It establishes no recorded depreciation, actual asset balance, tax policy
or live-provider/integration claim. Posted-month uniqueness belongs to a later
approved posting step. Software rollback is a new revert commit.
