# Phase 07: Adjustments, statements and close

Status: planned; no behavior in this phase is implemented yet.

**Depends on:** Steps 02–19. Period policy is explicit before locking dates.

**Outcome:** A fictional month can be adjusted, reported, closed and reproduced from its original records.

**Source basis:** Volume 1 §§4.1–4.5, 5.1–5.4, 11.3, 16.1–16.6. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Separate cutoff, adjustment, reporting, closing and locking. Implement fixed known adjustments first; policy-based depreciation and allowance estimates are later extensions. Preserve pre-close report semantics using entry kinds and snapshots. Owner capital/drawings for the sample must not silently become corporate retained earnings/dividends.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 20: Month-end adjustment proposals

- **Build:** Add documented prepaid consumption, accrued expense/revenue and earned-advance templates, one template at a time if needed.
- **Test:** Reference insurance adjustment is $100.00 and advance release is $200.00; no double recognition if already posted; period cutoff and missing support fail.
- **Verify manually:** Print the adjusted reference trial balance and supporting calculations.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 20: Month-end adjustment proposals. Follow Plan/07-period-close/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 21: Core financial statements

- **Build:** Derive income statement, statement of owner's equity and balance sheet from a defined ledger cutoff.
- **Test:** Reference revenue $2,700.00, expenses $1,600.00, net income $1,100.00; assets $11,500.00 equal liabilities $600.00 plus equity $10,900.00.
- **Verify manually:** Produce the three linked statements with account-level drilldown.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 21: Core financial statements. Follow Plan/07-period-close/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 22: Closing entries and date locks

- **Build:** Close temporary accounts to the sample's owner capital, save the close record, and lock the period.
- **Test:** Revenue/expenses/drawings become zero post-close; capital is $10,900.00; repeat close is idempotent; late posting/reversal is rejected; pre-close income still reports $1,100.00.
- **Verify manually:** Close the reference month and demonstrate a refused backdated posting.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 22: Closing entries and date locks. Follow Plan/07-period-close/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 23: Cash flow and reproducible exports

- **Build:** Add a statement of cash flows for supported transactions, using a direct operating section first, and CSV/JSON report exports.
- **Test:** Reference operating cash flow -$400.00, investing $0.00, financing $9,800.00, ending cash $9,400.00; round-trip export preserves dates/cents and snapshots.
- **Verify manually:** Reconcile opening cash plus cash flows to closing cash and export the month.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 23: Cash flow and reproducible exports. Follow Plan/07-period-close/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Do not reopen a locked period by editing dates. Reopening and prior-period corrections require an explicit future policy and audited operation. A software rollback must preserve journal history.
