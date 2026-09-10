# Phase 10: Deferred extensions

Status: optional backlog. These topics have been accounted for in the source review but are outside the initial service-business workflow. Do not implement them merely because their chapters exist. Select an extension, confirm its policy inputs, and assign one small testable step before starting.

All extensions reuse exact money, evidence, approval, journal, reconciliation and reporting services. The [implementation](../IMPLEMENTATION_GUIDELINES.md), [testing](../TESTING_STRATEGY.md) and [delivery](../GITHUB_WORKFLOW.md) guidelines still apply. Each increment needs its own fictional demonstration, failure cases, commit, push and CI evidence.

| Extension and source | First bounded implementation | Required verification and dependencies |
| --- | --- | --- |
| Receivable estimates/notes/complex contracts — V1 §§9.2, 9.5–9.7 | One versioned allowance estimate based on an approved aging table | Aging totals match AR; allowance roll-forward reconciles; write-off does not duplicate expense. Complex contracts require current policy/framework review before implementation. Depends on AR and close. |
| Long-lived assets — V1 ch. 11 | One straight-line depreciation schedule | A $1,200.00 asset, zero residual and 12 full months allocate $100.00/month; final allocation reconciles; no double posting; policy defines in-service date and partial-month treatment. Later split disposals, intangibles and impairment. |
| Inventory and merchandising — V1 chs. 6, 10 | One perpetual FIFO purchase/sale flow | Units reconcile; cost layers plus COGS equal costs available; reject unsupported negative stock. Add returns, freight, periodic methods and alternative valuation policies separately. |
| Liabilities and payroll import — V1 ch. 12 | Import one approved payroll summary or accrue one simple note's interest | Gross pay reconciles to net pay plus withholdings; employer expense is separate; liability settlement ties out; no live tax rates inferred from textbook examples. Payroll calculation/filing is separate scoped work. |
| Debt instruments — V1 ch. 13; Appendix B | One simple fixed-rate note amortization schedule | Principal + interest = payment; ending principal reconciles; maturity residual follows declared rounding. Add bond premiums/discounts and effective interest later. |
| Corporate and partnership equity — V1 chs. 14–15 | One selected entity's contribution/distribution template | Correct equity accounts; owner cash is not revenue/expense; capital roll-forward ties. Split stock, dividends, partner allocation, admission and liquidation into separate steps. |
| Extended financial reporting — V1 ch. 16 and Appendix A; V2 Appendix A | Indirect cash-flow operating section for an already validated simple period | Reconciles to direct-method cash flow and ending cash; noncash investing/financing events disclosed separately. Add trend and ratio analysis with denominator guards. |
| Manufacturing/process costing — V2 chs. 4–6 | One department's equivalent-unit cost report | Reconcile physical units, equivalent units and total costs; distinguish material and conversion completion; divide costs by equivalent units explicitly. Add subsequent departments and absorption/variable reconciliation later. |
| Standard costs/overhead — V2 chs. 6, 8 | One labor-rate and efficiency variance report | Rate and efficiency components reconcile to total labor variance; activity units and sign policy are explicit. Add materials/overhead pools separately. |
| Responsibility centers — V2 ch. 9 | One controllable-cost report | Department totals tie to actuals; unallocated and uncontrollable costs remain visible. Transfer pricing and multi-entity consolidation need separate policies and scope. |
| Short-term decision support — V2 ch. 10 | One service-capacity scenario | Relevant/avoidable costs and opportunity cost are explicit; rank by contribution per unit of constrained resource, not raw margin; scenario never posts to ledger. |
| Capital budgeting — V2 ch. 11; both Appendix B | One NPV calculation with supplied cash flows and discount rate | Independently computed present values; units and timing explicit; zero-rate case; sensitivity. Add IRR later with no-root/multiple-root handling. No autonomous capital commitments. |
| Scorecard — V2 ch. 12 | One owner-defined nonfinancial KPI beside existing financial results | Metric definition, unit, source and time window reproducible; missing data not shown as zero; avoid causal claims unsupported by inputs. |
| Sustainability — V2 ch. 13 | One sourced operational metric with a defined unit | Provenance and unit conversions verified; framework/version selected from current authoritative guidance before compliance reporting. |
| Tax, FX and other product extensions | Define one jurisdiction-specific or multi-currency use case first | Separate current authoritative research, effective-date policy, conversion/rounding and reconciliation fixtures. Not established by these two introductory books alone. |

Rollback: preserve source records and posted history; reverse accounting effects through approved entries, and version estimates/scenarios. Stop an unsupported extension with a review reason rather than silently applying a simplified textbook example.

Prompt when choosing an extension:

> Scope the next small step for [extension]. Identify the required business policies and dependencies, write independent acceptance examples, and update the plan. Build only the agreed bounded behavior, test and demonstrate it, then commit and push to GitHub.
