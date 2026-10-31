# Step 36: Straight-line depreciation schedule

Selected by the user on 2026-10-31 after choosing Phase 10. This is one
calculation-only delivery; other extensions and Phase 09 live gates stay deferred.

## Contract

Given supplied entity/asset IDs, USD cost, residual value, in-service date and
useful life in months, return a reproducible schedule. Use the existing `Money`
and `accounting_date` boundaries. No new dependencies, databases or migrations.
This schedule is a projection from supplied inputs, not recorded depreciation,
an enrolled asset, an approved estimate or a financial statement from the ledger.
No evidence enrollment, agent tools, approval, posting or UI integration is added.

Policy `straight-line-full-month-final-remainder-v1`:

- Positive cost within the ledger's integer-cent limit; residual from zero to cost.
- Life is an integer from 1 through 1,200 months; booleans and floats are refused.
- The in-service month receives a full allocation even for a mid-month date.
  No daily proration, half-month convention, impairment, disposal or tax policy.
- Divide cost less residual by life using integer floor division. Allocate that
  many cents each month; add all remaining cents to the final month. Zero monthly
  allocations are valid calculations and are never posted as journal lines.
- Use each calendar month's last date, including leap years. Reject schedules
  whose final month exceeds December 9999 before building rows.
- Each row shows period, month-end date, depreciation, accumulated depreciation
  and remaining carrying value. All public monetary values are decimal strings.
- Include normalized input facts, policy/version, projection label and a digest
  of those inputs/policy. Identical requests reproduce identical JSON. A changed
  assumption yields a different digest and cannot change an earlier result.
- Entity/asset identifiers are nonblank printable trimmed strings, at most 200
  characters. Amount text is at most 64 characters before exact-money parsing.

## Independent acceptance examples

1. Cost 1,200.00, residual 0.00, 12 months starting 2026-01-15: twelve 100.00
   allocations, January 31 through December 31; final accumulated 1,200.00 and
   carrying value 0.00.
2. Cost 100.00, residual 10.00, seven months starting 2027-11-30: six 12.85
   allocations and final 12.90; February ends on 2028-02-29; final value 10.00.
3. Cost 0.02, residual 0.00, three months: 0.00, 0.00, 0.02. Cost equal to
   residual: all allocations zero; carrying value unchanged.
4. Reject excess precision, float money, negative or excessive residual, zero cost,
   unsupported currency/policy, invalid dates, unsupported life and date overflow.
5. Repeated CLI/API calculation has no financial writes; an existing synthetic
   ledger retains its journal records and captured trial balance.

## Implementation and validation

- [x] Add `tests/test_depreciation.py` with literal expected rows, boundary cases,
  repeat/change isolation, large exact cents, CLI JSON/error behavior and a real
  synthetic-ledger preservation check. Run it before implementation.
- [x] Add `accounting_harness/depreciation.py` with a pure `depreciation_schedule`
  function and `demo_depreciation`. Add `depreciation-schedule` arguments and
  `demo-depreciation` to `__main__.py`; use its existing error handling.
- [x] Add the synthetic demo to CI and documented commands; add Step 36 to the
  ordered roadmap and update status/next-step guidance.
- [x] Run focused tests, all tests, foundation, JavaScript syntax, all documented
  demos and diff checks. Obtain independent code review and resolve findings.
- [x] Commit only intended files, push without rewriting history, inspect remote
  SHA and exact-SHA CI, then record delivery evidence.

Rollback is a new software revert commit. This step creates no posted entries to
reverse. A later asset/posting step must introduce authenticated evidence-bound
approvals, period locks and duplicate-month protection before recording actuals.
