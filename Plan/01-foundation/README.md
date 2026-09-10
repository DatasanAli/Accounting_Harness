# Phase 01: Scope and reference examples

Status: foundation delivered in Step 01.

**Depends on:** None. This is the first delivery.

**Outcome:** A bounded bookkeeping scope, staged plan, shared engineering rules, and a verified fictional accounting example.

**Source basis:** Volume 1 §§1.1–1.4, 2.1–2.3, 3.2–3.6; Volume 2 §§1.1–1.2. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Use the supplied books as conceptual references. Map every chapter to a phase or an explicit deferred extension. Keep business assumptions separate from confirmed user requirements. Do not implement the future ledger during this step.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 01: Establish the foundation

- **Build:** Create the plan, source map, working agreement, reference month, and offline verification/CI.
- **Test:** All phase links resolve; all 34 steps are ordered; reference month balances match; deliberate fixture corruption fails.
- **Verify manually:** Show the phase tree and the reference month's expected totals.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 01: Establish the foundation. Follow Plan/01-foundation/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Document and fixture rollback is a normal revert commit; keep the original PDFs untouched.
