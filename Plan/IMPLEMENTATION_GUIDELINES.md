# Implementation guidelines

## Make each step independently reviewable

Before coding, name the user-visible behavior, required inputs, expected outputs, accounting rule, and excluded work. Keep one runnable demonstration. Prefer a pure function or a single command before introducing services. If a step requires several independent behaviors, split it into lettered substeps, each with its own tests and commit.

Use Python 3.12+ for the initial local implementation, standard-library tests, and a CLI. Introduce SQLite when persistence is required. These are starting engineering decisions, not textbook requirements. Choose an agent provider, UI framework, and deployment platform only when their respective steps need them.

## Define accounting policy explicitly

The initial example uses one fictional service business, USD, accrual bookkeeping, monthly reporting, and owner capital/drawings accounts. This does not select the user's actual legal entity or tax treatment. Record real entity structure, currency, fiscal calendar, reporting framework, recognition policies, capitalization policy, and retention needs before a real-data pilot.

Give amounts one canonical representation. The initial external format is an unsigned decimal string with exactly two fractional digits, such as `"1200.00"`. Store cents as integers; debit or credit supplies direction. Reject floats, booleans, negative amounts, non-finite values, exponent notation, and excess precision. Zero is valid for a Money value but invalid for a journal line. Quantities and rates may need higher precision later; specify their rounding separately. Never silently round an invalid posted amount into validity.

Each account has a stable code, name, classification, normal balance, active flag, and entity. Contra accounts and owner drawings need explicit normal-balance metadata. Normal balance is an expectation, not a ban on an account having an opposite-side balance.

Each journal entry has an ID, entity, currency, effective date, description, source references, and at least two lines. Every line has a known active account, exactly one side, and a positive amount. Total debits equal total credits. Balancing alone does not establish correct classification, evidence, timing, or completeness.

## Preserve records through change and failure

Treat posted journals as the authoritative record; balances and statements are derived views. Commit a journal, its lines, posting event, and idempotency record atomically. Reusing the same scoped idempotency key with the same payload returns the previous result; a changed payload fails. Two different transactions with equal amounts must remain distinct.

Use linked reversal entries to correct a posting. Apply current period rules to the reversal; an earlier effective date cannot bypass a locked period. Store effective accounting dates separately from recorded UTC timestamps. Version schema migrations, accounting policies, report definitions, and draft revisions when introduced.

A database restore is for disaster recovery. It is not the ordinary way to undo valid accounting activity. A normal software rollback reverts code without discarding ledger history.

## Keep approval enforceable

Use explicit states: draft → validated → awaiting approval → approved → posted. Rejection and failure have recorded reasons. A changed draft becomes a new revision and loses any old validation or approval. An approval binds entity, draft revision/digest, evidence digest, policy version, and action. Recheck validity and period status within the posting transaction.

For the local prototype, the operator reviews and confirms through the CLI. This is not a production authentication system or independent segregation of duties. Before shared or real-data use, enforce authenticated roles and entity authorization in every application service; add a separate reviewer where the agreed policy requires one. The agent cannot impersonate that reviewer.

## Build the agent around trusted tools

The runtime gives the agent a small allowlist of typed tools and data for the selected entity. Use deterministic tools for calculations and validation. The agent initially reads, proposes, explains, and requests review; posting is invoked by the application after a human approval. Documents and tool output cannot change tool permissions.

Persist task/run IDs, workflow state, allowed tool calls, result references, model/prompt version, time and cost budgets, and reasons for stopping. Store concise supporting explanations and evidence references, not hidden model reasoning. Handle timeout, retry, cancellation, exhausted budgets, and process restart explicitly. Replaying a run must not replay side effects blindly.

Start with a fake provider so the same cases run offline. Add one real provider only after its contract and evaluations pass. Low-confidence, conflicting, missing, or out-of-scope evidence results in a review task. Confidence never bypasses accounting validation or permission checks.

## Deliver a complete slice

Update the active phase, status, and next-step prompt. Include test commands, observed results, a demonstration, and rollback notes. Run relevant checks; inspect the diff; commit and push; check CI and the remote SHA. Then stop. See the [GitHub workflow](GITHUB_WORKFLOW.md).
