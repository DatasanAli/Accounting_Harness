# Phase 04: A bounded accounting agent

Status: planned; no behavior in this phase is implemented yet.

**Depends on:** Steps 02–09. No model provider is required for Steps 10–11.

**Outcome:** One agent proposes a supported bookkeeping entry, explains its evidence, and stops for review.

**Source basis:** Volume 1 §§7.1, 8.2–8.3; Volume 2 §§1.1–1.4 for roles. Runtime/tool design is an engineering proposal. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Expose a tiny typed tool set: read accounts, retrieve scoped evidence, validate proposal, save draft, request review. Approval/posting are application operations unavailable to the agent. Add allowlists and tool contract tests before model calls. Record concise explanations and structured events. Use synthetic evidence for all initial evaluations.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 10: Typed tools and offline evaluation cases

- **Build:** Define allowed tool schemas, entity-scoped access, fake responses and a labeled evaluation corpus.
- **Test:** Malformed arguments, unknown tools, fabricated sources and cross-entity references fail; direct approval/post tools are unavailable.
- **Verify manually:** A scripted tool sequence creates a valid rent draft without changing ledger balances.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 10: Typed tools and offline evaluation cases. Follow Plan/04-agent-harness/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 11: Resumable fake-provider run loop

- **Build:** Implement persisted run states, checkpoints, tool-call/time/cost budgets, retry limits and cancellation with a fake provider.
- **Test:** Interrupt/resume; exhaust budgets; inject invalid output/timeouts; replay cannot duplicate a draft or any side effect.
- **Verify manually:** Start a run, pause at review, resume, and show a complete bounded trace.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 11: Resumable fake-provider run loop. Follow Plan/04-agent-harness/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 12: One real provider and proposal evaluation

- **Build:** Add a single configurable provider behind the existing interface and test a supported expense proposal plus abstention.
- **Test:** Pass the versioned offline gate and bounded live synthetic evaluation described in TESTING_STRATEGY.md; document model/prompt versions and observed cost.
- **Verify manually:** Give a fictional receipt, inspect the proposal and evidence, approve separately, and verify the resulting journal.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 12: One real provider and proposal evaluation. Follow Plan/04-agent-harness/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

A failed or cancelled run leaves a draft or a review item, never an unapproved posting. Provider outages must not affect the ledger.
