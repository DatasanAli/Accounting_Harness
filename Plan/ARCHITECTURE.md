# Intended architecture

Status: Steps 02–11 implemented. The standard-library package contains exact money/accounts, pure validation, ledger snapshots/trial balances, SQLite persistence/reversals, immutable source registration, versioned drafts, local human approval/atomic posting, five typed proposal tools, and a durable bounded fake-provider run loop. Ten CLI demos cover these behaviors. Live providers, authenticated roles and financial statements remain future work. SQLite serializes writes; this remains a synthetic local prototype.


## Responsibility boundaries

```text
Source evidence → intake and normalization → versioned draft
                                             ↑
                                      agent + typed tools
                                             ↓
Accounting rules → validation → human review → posting service
                                                  ↓
                                      journal + audit record
                                                  ↓
                            ledger → reconciliation → statements
                                                  ↓
                             management reports and scenarios
```

The agent harness supplies task state, scoped context, tool permissions, execution limits, review handoffs, and replayable run records. The accounting engine supplies exact calculations, business rules, transactional posting, and reproducible reports. These responsibilities meet through application services.

## Core records

| Record | Purpose and essential identity |
| --- | --- |
| Entity/policy | Entity ID, functional currency, calendar, entity form, policy version |
| Account | Entity-scoped stable code, classification, normal side, active state |
| Source document | ID, source identity, content digest, document date, observed time, safe stored location |
| Draft/revision | Proposed entry, evidence references, revision digest, validation findings |
| Approval | Human actor, exact revision/evidence/policy, action, decision time |
| Journal/line | Immutable posted entry, effective date, recorded time, account/side/amount, source and approval references |
| Posting request | Entity-scoped idempotency key and canonical request digest |
| Audit event | Actor/action, affected record, prior/new state references, recorded time, result |
| Run/checkpoint | Task/run ID, authorized context, current state, tool/result references, limits, model/prompt version |
| Accounting period | Boundaries, lock status, close ID and supporting report snapshot |
| Report/scenario | Entity, date range/as-of date, ledger snapshot, policy version; actual/budget/scenario label |

Add each record when its step needs it; this is not an instruction to scaffold every table now.

## Planned code organization

```text
accounting_harness/          # Introduced in Step 02
  domain/                   # Money, accounts, journals, pure accounting rules
  review.py                 # Implemented immutable revisions and pending/rejected queue
  approval.py               # Implemented local decisions, atomic posting and audit
  review_cli.py             # Explicit local human confirmation
  application/              # Future reconciliation and close use cases
  persistence.py            # Implemented SQLite storage, retries and v1→v2 migration
  sources.py                # Implemented separate SQLite source registry and JSON receipt loader
  agent_tools.py            # Implemented strict JSON allowlist, fixed runtime scope
  tool_evaluation.py        # Implemented scripted offline contract runner
  runs.py                   # Implemented fake provider, persisted budgets/checkpoints and safe recovery
  run_demo.py               # Reopen and acknowledge a synthetic review handoff
  agent/                    # Future live provider adapter
  reporting/                # Statements and management calculations
  integrations/             # External accounting/provider adapters
  cli/                      # Local operator commands
tests/                      # Introduced in Step 02; grows with each layer
data/fixtures/              # Fictional examples, including Step 01 reference month
```

The initial CLI works locally with a single fictional entity. SQLite is the implemented persistence store. Full reversals append an opposite journal and an immutable link/retry record in one transaction. Provider adapters keep accounting rules independent of any model vendor. Production storage, authentication, web UI, and hosting are decisions for their later steps.

The source registry uses a separate entity-bound SQLite file with its own application ID and schema v1. The ledger keeps schema v2 and its frozen source-ID context, preserving posting retry digests and historical reports. Registration records evidence only; it does not extend an existing ledger’s source set. Review schema v1 and approval schema v1 are optional additive tables in the ledger file. Approval binds entity, revision/evidence digests, policy and posting action. Posting and audit links commit together after revalidation; evidence identities must already be provisioned in the frozen ledger context. Agent tools never receive approval/posting capabilities. The local trusted-file/CLI boundary is not production authentication.

The run log is a separate entity-bound SQLite file (AHRN, schema v1). Fixed task/run scope and append-only checkpoints bind script/prompt identity and integer budgets. A durable tool intent and dispatch reservation precede each side effect; interrupted saves recover their original review receipt. A local advisory lock spans dispatch transactions on macOS/Linux. Cancellation and time enforcement occur at bounded local-call boundaries. Acknowledging review completes the run without approving or posting. Restore the run, source and ledger files consistently.

## Hard boundaries

- A model response cannot write a journal directly or act as a human approval.
- A valid proposal is revalidated when posted, including period bounds and revision identity; explicit period locks arrive in Step 22.
- Invalid, unsupported, or incomplete evidence produces a review item with a reason.
- An external accounting system's ownership of the authoritative ledger must be decided before integration. In mirror mode, this application's ledger is a reconciled local view; it must not create a second independently authoritative book.
- Posting or exporting accounting records is distinct from sending money. Bank transfers, payments, filings, and customer/vendor messaging require separately scoped future work.
- Deterministic historical reports use the original effective-date entries and explicit treatment of closing entries; closing must not turn the old income statement into zeros.
