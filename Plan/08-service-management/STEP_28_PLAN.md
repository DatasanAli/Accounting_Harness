# Step 28: contribution, break-even and supported indicators

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 27.

**Goal:** Show 60.00 contribution from a 100.00 service price and 40.00 variable cost,
20 whole units to cover 1,200.00 fixed costs, and a few traceable operating/financial
indicators without turning a scenario into recorded accounting.

**Architecture:** Pure exact calculations use one explicitly versioned service
scenario and captured financial/time inputs. Reuse the management scenario/audit
conventions. Display assumptions, calculation policy and unavailable indicators
beside the result; do not introduce a forecasting or investment-advice engine.

**Spec:** [Phase 08](README.md).

## Global constraints

- Exact cents, integer service units/minutes and rational ratios; no float money.
  Strict nonnegative two-decimal price/variable-cost/fixed-cost inputs in USD.
- Scenario assumptions, recorded actuals and operational minutes stay visibly
  separate. Editing a scenario produces a new immutable version with a reason.
- Ratios are descriptions of captured data, not recommendations or accounting
  entries. No posts, money movements, model approvals or live connections.
- Each result identifies entity/period, scenario version, captured inputs and
  explicit policy/digest. Historical results are pure and reproducible.

## Single-service contribution policy

Contribution per unit equals price minus variable cost. For positive contribution,
continuous break-even is fixed-cost cents divided by contribution cents; retain
that exact numerator/denominator. Whole-unit break-even is the integer ceiling.
Zero fixed cost with positive contribution gives zero units. For nonpositive
contribution, report no finite positive profitable break-even under this model;
do not divide by zero or display a negative threshold as an attainable target.
Explain the zero-fixed/zero-contribution indeterminate case separately.

Reference price 100.00-variable 40.00 gives 60.00 contribution; fixed 1,200.00 yields
20 whole units. Profit at 19 units is-60.00, at 20 is0.00 and at 21 is60.00. At a
nonintegral threshold, the whole-unit result must be the first unit count with
nonnegative model profit. Contribution margin ratio is contribution/price, with
zero price unavailable even if contribution is also zero. A signed negative
contribution remains visible rather than being coerced to zero.

Support one service and constant unit economics over a stated relevant range.
Do not average multiple services or infer a sales mix. Quantities outside an
explicit supported range remain visibly outside the scenario assumptions.
An optional what-if quantity changes only the scenario calculation and never
actual revenue, time or expense. Rates and range are human assumptions.

## Captured indicators

Provide a small fixed menu: current ratio, quick ratio, net profit margin, and
recorded service minutes/revenue per recorded service hour. The owner can select
which to show; do not invent extra KPIs or label unmeasured capacity as utilization.
Every indicator shows numerator, denominator, dates and source references.

Use explicit current-account policy for this synthetic chart: Cash 1000,
AR 1100, accrued service revenue 1150 when activated, and prepaid insurance 1200
are current assets; AP 2000, accrued expenses 2050 when activated and advances 2100
are current liabilities. Equipment 1500/accumulated depreciation 1590 are noncurrent.
Quick assets omit prepaid insurance. Do not infer current status from normal side
or the word asset alone. Unknown newly introduced classifications yield a finding
until the policy explicitly covers them. Opposite-side balances stay signed.

Profit margin uses the delivered ordinary income/revenue statement, excluding
closing transfers consistently. Revenue per service hour is revenue cents*60
-divided-by captured active minutes, with exact rational calculation and labeled
rounding; it is a descriptive rate, not evidence of hourly billing or productivity.
Zero denominator gives unavailable with a reason. For nonpositive current
liabilities, show underlying values and mark liquidity ratios unavailable under
this bounded policy rather than presenting a misleading positive liquidity score.

For the adjusted reference month, current assets 11,500.00 and liabilities 600.00
supply the current-ratio inputs; quick assets 10,400.00 supply the quick-ratio
numerator; income 1,100.00/revenue2,700.00 supplies margin. Retain exact fractions
and use a documented two-decimal half-up display. Never assert financial health
from a ratio alone or substitute ratios for the underlying reconciled statements.

## Task 1: exact scenario thresholds and evidence-backed indicators

**Files:** Focused contribution/indicator functions and tests, existing immutable
scenario/capture integration, workspace/HTTP/CLI/static. Parent owns docs/CI/browser.

- [ ] RED: 100-40=60, fixed 1,200/60=20 units;19/20/21 profit-60/0/60; verify
  ceiling threshold when contribution does not divide fixed costs exactly.
- [ ] Cover zero/negative contribution, zero fixed cost/price/denominators, invalid
  rates/units/range, large values, negative income and opposite account balances.
- [ ] Assert independent reference ratio inputs, exact rational/display rounding,
  unmeasured activity unavailable and excluded noncurrent/prepaid classifications.
- [ ] Bind same-snapshot income/balance/time inputs; refuse scope/policy mismatch.
  Preserve old results after scenario/time/account/ledger/closing changes.
- [ ] Prove all scenario/KPI selections leave actual journals, financial reports
  and budgets unchanged. Unknown data stays explicit, never silently guessed.
- [ ] Add an assumption-led contribution view and selectable cited indicators;
  `demo-indicators` prints 60 contribution/20 units and unavailable-zero examples.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; parent browser,
  independent review, commit/push and exact CI before authenticated access.
