# Phase 06: Bank reconciliation

Status: Step 17 bank import is delivered with verified CI; see [import verification](STEP_17_VERIFICATION.md). Step 18 matching is delivered with verified CI. Step 19a account activation is delivered with verified CI. Step 19b fee posting is delivered with verified CI. Step 19c reconciliation is delivered with verified GitHub CI. See [reconciliation verification](STEP_19C_VERIFICATION.md). See [fee verification](STEP_19B_VERIFICATION.md). See [activation verification](STEP_19A_VERIFICATION.md). See [matching verification](STEP_18_VERIFICATION.md).

**Depends on:** Steps 02–16.

**Outcome:** An operator can explain the difference between statement cash and ledger cash without duplicate transactions.

**Source basis:** Volume 1 §8.6, printed pp. 500–502. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Store original bank rows and a stable account/statement/row identity. Sign conventions must be explicit. Import is not posting. Separate matching from adjusting the books. Outstanding payments and deposits in transit normally already exist in the books; bank fees may require a new reviewed journal.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 17: Bank statement CSV import

Detailed bounded implementation: [Step 17 plan](STEP_17_PLAN.md).

- **Build:** Add one documented fictional bank CSV format with account, dates, signed amount and transaction identity.
- **Test:** Import twice without duplication; malformed dates/signs/currency fail; opening plus movements equals statement closing balance.
- **Verify manually:** Import a tiny statement and list rows without ledger changes.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 17: Bank statement CSV import. Follow Plan/06-bank-reconciliation/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 18: Matching and exceptions

Detailed bounded implementation: [Step 18 plan](STEP_18_PLAN.md).

- **Build:** Propose one-to-one matches by amount/date/reference with operator confirmation.
- **Test:** Ambiguous equal-amount rows stay unresolved; unmatched rows persist; repeated matching is idempotent; a transfer is not income.
- **Verify manually:** Confirm a unique receipt match and leave two ambiguous rows for review.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 18: Matching and exceptions. Follow Plan/06-bank-reconciliation/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 19: Reconciliation and reviewed adjustments

The current frozen 13-account catalog has no bank-fee expense account. Before
implementing the reviewed fee, deliver [19a additive bank-fee account](STEP_19A_PLAN.md)
if it is still needed, followed by [19b reviewed bank fee](STEP_19B_PLAN.md) and
[19c captured reconciliation](STEP_19C_PLAN.md). Preserve original ledger context,
approval/retry/provider bytes and captured snapshots; do not relabel software or
rent expense as bank fees. Introduce a clearly named fictional bank-fee expense
account with immutable metadata and audit, and use the effective captured catalog
for new validation/reports. This is a dependency to resolve in the detailed Step
19 plan, not authorization to modify the catalog during bank import.

- **Build:** Produce a bank-to-book reconciliation, supporting book adjustments and completion status.
- **Test:** Example: book $1,000.00 less $10.00 fee equals $990.00; bank $940.00 plus $200.00 deposit in transit less $150.00 outstanding payment equals $990.00. Post only the fee; unexplained differences block completion.
- **Verify manually:** Show both adjusted balances at $990.00 and the evidence for each reconciling item.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 19: Reconciliation and reviewed adjustments. Follow Plan/06-bank-reconciliation/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Unmatch through an audited action. Never generate a balancing plug to force reconciliation. Preserve bank-side errors as exceptions.
