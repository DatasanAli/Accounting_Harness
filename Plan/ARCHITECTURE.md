# Intended architecture

Status: design target with Steps 02–06 implemented. The package contains exact Money/accounts, pure journal validation, strict calendar dates, immutable ledger snapshots and trial balances, atomic SQLite persistence and linked full reversals. The five local CLI demonstrations cover accounts, journal validation, ledger reports, persistence and reversals. Approval, agents and financial statements remain future work. SQLite handles concurrent requests with serialized transactions; this remains a synthetic local prototype with no hosted deployment.

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
  application/              # Use cases, approvals, posting, reconciliation, close
  persistence.py            # Implemented SQLite storage, retries and v1→v2 migration
  evidence/                 # Source registration and import formats
  agent/                    # Typed tools, run loop, provider adapter, checkpoints
  reporting/                # Statements and management calculations
  integrations/             # External accounting/provider adapters
  cli/                      # Local operator commands
tests/                      # Introduced in Step 02; grows with each layer
evals/                      # Introduced with agent tools
data/fixtures/              # Fictional examples, including Step 01 reference month
```

The initial CLI works locally with a single fictional entity. SQLite is the implemented persistence store. Full reversals append an opposite journal and an immutable link/retry record in one transaction. Provider adapters keep accounting rules independent of any model vendor. Production storage, authentication, web UI, and hosting are decisions for their later steps.

## Hard boundaries

- A model response cannot write a journal directly or act as a human approval.
- A valid proposal is revalidated when posted, including date locks and revision identity.
- Invalid, unsupported, or incomplete evidence produces a review item with a reason.
- An external accounting system's ownership of the authoritative ledger must be decided before integration. In mirror mode, this application's ledger is a reconciled local view; it must not create a second independently authoritative book.
- Posting or exporting accounting records is distinct from sending money. Bank transfers, payments, filings, and customer/vendor messaging require separately scoped future work.
- Deterministic historical reports use the original effective-date entries and explicit treatment of closing entries; closing must not turn the old income statement into zeros.
