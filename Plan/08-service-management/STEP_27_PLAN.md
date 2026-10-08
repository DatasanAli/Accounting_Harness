# Step 27: reproducible flexible-budget variance

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 26.

**Goal:** Explain revenue 1,100.00 versus budget1,000.00 as 100.00 favorable, expense
600.00 versus500.00 as 100.00 unfavorable, and reconcile activity and remaining
variance without changing actuals or budgets.

**Architecture:** A pure comparison binds one immutable operating-budget version
to one captured financial/management/time snapshot. Flex variable rates to observed
service minutes, retain fixed costs, and report arithmetic bridges with referenced
inputs. No model-generated causal assertions or automatic scenario changes.

**Spec:** [Phase 08](README.md), delivered26 service-minute budget policy.

## Global constraints

- Exact integer cents/minutes and the same documented per-line half-up rounding
  as 26. Percentages retain exact integer numerator/denominator and a labeled
  two-decimal half-up display string; no binary floating-point money.
- Match entity/currency/month/account scope and captured catalog. Current account
  labels or later budget/time revisions cannot change an old comparison report.
- Actual revenue/expense comes from captured ordinary posted journals. Observed
  activity comes from supported active time facts, not an assumed cash total.
- Budget/scenario and actual ledger records stay untouched. A variance is neither
  a journal adjustment nor proof that an employee/vendor caused the difference.
  Live connections remain deferred.

## Variance and bridge policy

Static budget is the selected stored version. Flexible budget retains every fixed
line and recomputes each variable line using actual captured minutes at the same
budget rate. Do not divide by planned activity: zero planned minutes can still
have an explicit rate and a valid flexible amount for nonzero actual minutes.

For every account, raw variance is actual minus budget. Favorable impact is that
same sign for revenue and its negative for expense. Positive favorable impact is
Favorable, negative is Unfavorable, zero is Neutral. Show opposite/credit actual
balances faithfully. Net-income variance is actual income minus budget income;
its favorable impacts must equal revenue impact plus expense impact exactly.

The activity bridge is flexible minus static; the remaining performance bridge is
actual minus flexible. Their signed sum must equal actual minus static for every
account and total. Preserve each rounded line contribution so rounding cannot
create an unexplained residual between line and total bridges.

Example: planned 480 minutes at revenue 125.00/hour and variable expense 50.00/hour
plus fixed expense 100.00 yields static revenue 1,000.00/expense500.00. Actual600
minutes yields flexible revenue 1,250.00/expense600.00. Captured actual revenue
1,100.00 and expense 600.00 means revenue activity impact250.00 favorable and
remaining 150.00 unfavorable, totaling 100.00 favorable. Expense activity impact
100.00 unfavorable plus zero remaining impact totals100.00 unfavorable. Static
and actual income are each500.00; the net-income variance is zero.

Describe the remaining amount as rate/spending only where captured quantity and
classification support that calculation; otherwise label it remaining variance
with the missing support visible. An arithmetic actual revenue-per-hour ratio is
not proof of a causal pricing change. Avoid ungrounded explanations about volume,
efficiency, mix, behavior or responsibility. Operator explanations are attributed
notes, distinct from the computed evidence.

Percent difference uses the absolute static or flexible base named by the column.
A zero base returns unavailable even when actual is also zero; never divide by
zero or invent 0 percent. Display the exact cents difference regardless. Accounts
present in actuals but absent from the budget are explicitly unbudgeted with a
zero comparison base, not silently dropped. Budget-only accounts have zero actuals.

Capture the chosen scenario, financial inputs, current time facts and any used
management classifications in one consistent workspace read transaction. Store or
serialize the complete comparison inputs with policy/digest; pure rendering and
later exports must not query current stores. Old comparisons survive corrections,
new budget versions, later posting and closing classification changes unchanged.

## Task 1: exact F/U signs and activity bridge

**Files:** Focused comparison/capture module and tests, workspace/HTTP/CLI/static.
Reuse delivered budget and financial/time contracts; parent owns docs/CI/browser.

- [ ] RED: independent example above, all account/total F/U labels and exact
  volume+remaining bridges; revenue 100 favorable/cost100 unfavorable/net0.
- [ ] Cover zero planned/actual activity, zero budget percentage unavailable,
  unbudgeted/budget-only accounts, credits, losses, no activity, rounding and
  large values. Fixed lines never flex with activity.
- [ ] Refuse mismatched entity/currency/period/policy or malformed snapshots; show
  missing explanatory classifications without manufacturing a rate/causal claim.
- [ ] Prove all actual drilldowns reconcile to financial reports and all budget
  lines to their selected version; comparison never mutates either store.
- [ ] Test frozen comparison after new scenario/time/ledger/close activity and
  consistent capture under concurrent mutation. Verify exact JSON/browser values.
- [ ] Add static/flexible/actual table, F/U and two-part bridge with source/rate/
  activity references; `demo-variance` prints reference100F/100U and bridge totals.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff; parent browser,
  independent review, commit/push and exact CI before contribution/indicators.
