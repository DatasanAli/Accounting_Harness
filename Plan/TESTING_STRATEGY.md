# Testing strategy

## Current verification

```sh
python3 scripts/verify_foundation.py
```

Step 01 checks documentation links, the ordered roadmap, and the arithmetic/structure of [the original reference month](../data/fixtures/service-business-month.json). It checks all expected account balances, statement totals, cash movements, and closing results. It does not test any production application: none exists yet.

Step 02 introduces application tests using Python's standard library. Tests must fail on unexpected zero-test discovery. Add the same test runner to CI and the README when it exists. Dependencies and paid model calls are unnecessary for the first implementation steps.

## Test the outcome and the failure boundary

For each numbered step, supply a valid example, a meaningful invalid example, and an edge case affecting its behavior. Use predetermined accounting outcomes, not values computed by the function under test. A failing operation must leave posted balances and unrelated records unchanged; a recorded rejection event is allowed.

| Layer | Evidence required when that layer is introduced |
| --- | --- |
| Money/accounts | Exact cents; accepted/rejected formats; duplicate account IDs; normal balances and contra accounts |
| Journal/ledger | Balanced entry accepted; imbalance rejected; all expected per-account balances; date cutoff; empty ledger; wrong-account-but-balanced case identified by semantic fixtures |
| Persistence | Close/reopen database; injected mid-write failure; duplicate retry; changed-payload retry; concurrent attempts; constraints survive direct service calls |
| Evidence/review | Missing source; changed evidence; changed draft; stale/rejected approval; unsupported transition; posting without human approval |
| Operations | Invoice and bill lifecycle; partial settlement; duplicate document; overpayment policy; subledger totals equal control accounts |
| Reconciliation | Timing differences versus book adjustments; ambiguous matches; transfer handling; unexplained difference prevents completion |
| Close/reports | Independent expected statements; cutoff; accrual/deferral; owner drawings; locked period; repeated close; historical reports survive closing |
| Agent | Correct structured proposal; evidence trace; abstention; invalid tool call; document instruction attack; denied approval/post request; bounded retry/cost/time; restart without duplicate posting |
| Management | Actual/budget/scenario separation; allocation totals; denominator zero; relevant-range limits; favorable/unfavorable sign conventions |
| Integration/operations | Sandbox contract; pagination; rate limit; interrupted sync; external duplicates; scoped authorization; export round trip; restore and reconciliation |

## Growing accounting fixtures

Start with the reference month's owner contribution, rent, prepaid insurance, earned invoice, partial collection, supplier bill/payment, customer advance, owner withdrawal, and two adjustments. All amounts and company details are original fictional examples.

At Step 04, use its ordinary transactions for an unadjusted trial balance. At Step 20 add the two adjustments. At Step 21 check net income of $1,100.00, assets of $11,500.00, liabilities of $600.00, and ending equity of $10,900.00. At Step 22 check temporary accounts clear without losing historical performance reports. At Step 23 check the $9,400.00 closing cash balance and its operating/financing sources.

Add fixtures when a capability is introduced: bad-debt estimates, depreciation, reversals, prior balances, multiple periods, loss months, no activity, and contra accounts. Add property-based generation when handwritten cases stop covering ledger combinations; conserve total debits/credits and test reversal identities. Do not require a new test framework in advance.

## Agent evaluation gate

Before a live provider step is complete, freeze a versioned offline suite with at least 20 labeled cases covering clean evidence, ambiguity, missing facts, conflicting amounts, duplicate documents, out-of-scope requests, and hostile document instructions. The human-review action is an accepted outcome for ambiguous cases.

Release criteria for that suite: zero unauthorized postings; zero accepted unbalanced proposals; every successful proposal links real fixture evidence; every designated ambiguous/unsupported case routes to review; at least 90% exact expected proposals on the unambiguous supported cases. Report numerators and denominators by category. The threshold is a project gate, not a claim of general accuracy. Add every discovered regression as a new case.

CI runs the fake provider and deterministic cases on every relevant change. Run an explicitly bounded live-provider smoke/evaluation with synthetic data when adding or changing the provider/model/prompt. Record model, prompt version, sample size, latency, cost, failures, and nondeterminism. A live score cannot waive permission checks.

## Definition of done

The promised behavior works; relevant negative cases fail correctly; accounting totals match independent expectations; the demonstration is reproducible; docs describe the implemented scope; local checks pass; the reviewed commit is on GitHub; CI for that commit passes. A blocked remote upload or failed CI leaves delivery incomplete and must be reported.
