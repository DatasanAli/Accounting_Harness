# Phase 08: Service costing, budgets and analysis

Status: planned; no behavior in this phase is implemented yet.

**Depends on:** Steps 02–23. These outputs read supported actuals and label assumptions separately.

**Outcome:** The owner can inspect project costs, cash plans, budget variances and service contribution.

**Source basis:** Volume 2 §§2.1–2.3, 3.1–3.5, 4.4–4.8, 6.1–6.4, 7.1–7.5, 8.3–8.5, 9.3–9.4, 12.1–12.4; Volume 1 Appendix A. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Use labor hours and operating overhead for service projects. Management allocations do not automatically post financial accounting entries. Version each budget/scenario and document activity drivers, relevant range and units. Actual financial values must reconcile to statements; estimated hours or allocations are separately labeled.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 24: Project and cost dimensions

- **Build:** Attach validated project/customer/cost-category dimensions and classify fixed, variable, direct and indirect costs.
- **Test:** Dimension totals plus explicitly unallocated amounts equal source actuals; missing classifications remain visible; duplicate time records are detected.
- **Verify manually:** Break a fictional expense total across two projects and show the reconciliation.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 24: Project and cost dimensions. Follow Plan/08-service-management/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 25: Service project costing

- **Build:** Compute direct cost and a documented overhead allocation for one project.
- **Test:** 10 hours at $40.00 plus $100.00 direct costs plus $20.00 overhead per hour equals $700.00; $1,000.00 revenue gives $300.00 project margin; no double-counted ledger expense.
- **Verify manually:** Show a project cost sheet with hours, rates, allocation and revenue references.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 25: Service project costing. Follow Plan/08-service-management/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 26: Versioned operating and cash budgets

- **Build:** Create a one-month revenue/expense budget and a cash plan with collection/payment timing.
- **Test:** Opening $1,000.00 plus collections $1,500.00 less payments $1,200.00 equals ending $1,300.00; deferred collections do not become current cash.
- **Verify manually:** Compare a budget and a changed collection-timing scenario without changing actuals.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 26: Versioned operating and cash budgets. Follow Plan/08-service-management/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 27: Flexible budgets and variance explanations

- **Build:** Flex variable costs to actual activity and compare actuals to static/flexible budgets.
- **Test:** Revenue $1,100.00 vs $1,000.00 budget is $100.00 favorable; expense $600.00 vs $500.00 is $100.00 unfavorable; zero-base percent returns unavailable; volume and rate effects reconcile.
- **Verify manually:** Produce one variance report with cited inputs and clearly labeled explanations.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 27: Flexible budgets and variance explanations. Follow Plan/08-service-management/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 28: Contribution and operating indicators

- **Build:** Add service contribution/break-even, liquidity and a small owner-selected KPI report.
- **Test:** Price $100.00 less variable cost $40.00 gives $60.00 contribution; $1,200.00 fixed costs break even at 20 units; zero/negative contribution has no finite positive break-even; ratios guard zero denominator.
- **Verify manually:** Show a service what-if and supported financial/nonfinancial indicators without investment recommendations.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 28: Contribution and operating indicators. Follow Plan/08-service-management/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Replace a scenario with a new version. Do not modify posted actuals to make a budget or project margin look better.
