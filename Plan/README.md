# Accounting Harness implementation plan

Steps 01–02 establish the plan and implement exact Money values and a chart of accounts. The next small build is **Step 03: journal validation**. The selected initial workflow is bookkeeping for a small service business.

An agent harness is the application around an agent: its task state, evidence context, allowed tools, execution limits, approvals, and recorded results. Our ledger and accounting rules must be testable independently of the model.

## Directory tree

These plan files exist now. The [architecture](ARCHITECTURE.md) distinguishes the implemented Money/accounts package from the remaining design target.

```text
Plan/
├── README.md
├── STATUS.md
├── NEXT_STEP.md
├── IMPLEMENTATION_GUIDELINES.md
├── TESTING_STRATEGY.md
├── GITHUB_WORKFLOW.md
├── ARCHITECTURE.md
├── SOURCE_MAP.md
├── roadmap.json
├── references/
│   └── sources.json
├── 01-foundation/
│   └── README.md                      # Steps 01–01
├── 02-ledger-core/
│   ├── README.md                      # Steps 02–06
│   └── STEP_02_VERIFICATION.md
├── 03-evidence-and-review/
│   └── README.md                      # Steps 07–09
├── 04-agent-harness/
│   └── README.md                      # Steps 10–12
├── 05-service-bookkeeping/
│   └── README.md                      # Steps 13–16
├── 06-bank-reconciliation/
│   └── README.md                      # Steps 17–19
├── 07-period-close/
│   └── README.md                      # Steps 20–23
├── 08-service-management/
│   └── README.md                      # Steps 24–28
├── 09-integrations-and-pilot/
│   └── README.md                      # Steps 29–34
└── 10-deferred-extensions/
    └── README.md                      # Optional; requires a new scoped step
```

The foundation verification record is also stored in `01-foundation/VERIFICATION.md`.

## Stage order and completion evidence

| Phase | Deliverable | Steps |
| --- | --- | --- |
| [01: Scope and reference examples](01-foundation/README.md) | A bounded bookkeeping scope, staged plan, shared engineering rules, and a verified fictional accounting example. | 01–01 |
| [02: Exact money and ledger core](02-ledger-core/README.md) | A deterministic local journal and ledger that preserve balanced entries and survive restart. | 02–06 |
| [03: Evidence, review and audit](03-evidence-and-review/README.md) | An operator can trace, review, and approve an exact draft before application posting. | 07–09 |
| [04: A bounded accounting agent](04-agent-harness/README.md) | One agent proposes a supported bookkeeping entry, explains its evidence, and stops for review. | 10–12 |
| [05: Daily service-business operations](05-service-bookkeeping/README.md) | Supported day-to-day cash, payable, receivable, and advance transactions reconcile to the ledger. | 13–16 |
| [06: Bank reconciliation](06-bank-reconciliation/README.md) | An operator can explain the difference between statement cash and ledger cash without duplicate transactions. | 17–19 |
| [07: Adjustments, statements and close](07-period-close/README.md) | A fictional month can be adjusted, reported, closed and reproduced from its original records. | 20–23 |
| [08: Service costing, budgets and analysis](08-service-management/README.md) | The owner can inspect project costs, cash plans, budget variances and service contribution. | 24–28 |
| [09: Access, integrations and controlled pilot](09-integrations-and-pilot/README.md) | A specifically scoped pilot has authenticated access, reconciled integration, a review interface and tested recovery. | 29–34 |
| [10: Deferred extensions](10-deferred-extensions/README.md) | Explicit backlog for broader financial and managerial capabilities | Assign small steps when selected |

Every phase contains implementation guidance, per-step tests, a manual demonstration, a delivery rule, rollback considerations, and copyable prompts. The phase is a group of commits, not a single large task. The order is a starting backlog, not a fixed schedule; change it when the user's needs warrant and keep dependencies explicit.

## Confirmed scope and starting assumptions

**Confirmed:** accounting operations; read Volume 1 before Volume 2; small service-business bookkeeping first; small tested increments; GitHub upload after each completed step; wait for the next request between steps.

**Starting assumptions:** local CLI, Python 3.12+, single fictional entity, USD, accrual bookkeeping, monthly periods, owner capital/drawings, human-approved posting, structured fictional inputs before document extraction. No provider or deployment platform has been selected.

**Later decisions:** actual legal entity and reporting framework/jurisdiction; fiscal calendar and accounting policies; existing ledger ownership; bank/accounting connector; reviewer roles; model budget/provider; deployment and retention needs. Ask when the answer becomes necessary, rather than stopping the foundation work.

## Scope boundaries

The initial harness prepares, reviews and records supported bookkeeping activity. Payment execution, tax filing/calculation, payroll processing, manufacturing, inventory, complex revenue contracts, and external customer/vendor messaging are deferred. The [source map](SOURCE_MAP.md) and [extension backlog](10-deferred-extensions/README.md) preserve the broader textbook coverage.

**Next action:** use the exact prompt and acceptance criteria in [NEXT_STEP.md](NEXT_STEP.md). After that one step is built, tested, committed, pushed and verified, stop.
