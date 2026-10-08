# Phase 05: Daily service-business operations

Status: Step 13a is delivered; Step 13b cash templates are delivered with verified CI. See [13a verification](STEP_13A_VERIFICATION.md) and [13b verification](STEP_13B_VERIFICATION.md). Step 14a vendor bill recognition is delivered with verified CI. Step 14b partial settlement is delivered with verified CI; see [payment verification](STEP_14B_VERIFICATION.md). Step 15a invoice recognition is delivered with verified CI; see [invoice verification](STEP_15A_VERIFICATION.md). Step 15b collection and aging is delivered with verified CI; see [collection verification](STEP_15B_VERIFICATION.md). Step 16a customer advances are delivered with verified CI; see [advance verification](STEP_16A_VERIFICATION.md). Step 16b earning is locally verified and independently reviewed; see [earning verification](STEP_16B_VERIFICATION.md). Upload/CI pending; Step 16c payable seal hardening follows.

**Depends on:** Steps 02–11 and Step 12 offline contracts. Live model connection is deferred by user. Each workflow uses existing evidence, approval, and posting services.

**Outcome:** Supported day-to-day cash, payable, receivable, and advance transactions reconcile to the ledger.

**Source basis:** Volume 1 §§3.5, 7.2–7.4, 9.1–9.3, 12.1–12.2. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Introduce one workflow at a time and one document per demo. Define recognition from service delivery/incurrence evidence. Receiving cash alone does not determine revenue. Subledgers must reconcile to their control accounts. Recording a payment that occurred does not execute a bank payment or send a customer message.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 13: Cash receipts and expenses

Split into [13a evidence enrollment](STEP_13A_PLAN.md) and
[13b reviewed cash templates](STEP_13B_PLAN.md). The expanded 2026-10-08 request
authorizes continuing after each separately verified delivery.


- **Build:** Support incurred cash expenses and immediately earned service receipts through reviewed templates.
- **Test:** Owner contributions, transfers and customer advances must not be misclassified as earned revenue; duplicate receipts fail safely.
- **Verify manually:** Post rent $1,200.00 and a separately evidenced earned cash receipt; inspect classifications.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 13: Cash receipts and expenses. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 14: Vendor bills and partial settlement

Split into [14a bill recognition](STEP_14A_PLAN.md) and [14b recorded partial settlement](STEP_14B_PLAN.md) under [the Step 14 contract](STEP_14_PLAN.md). Each has independent verification and delivery.

- **Build:** Add a vendor subledger, expense bill, due date and allocation of recorded payments.
- **Test:** A $300.00 bill and $100.00 payment leave $200.00 payable; duplicate bill and over-allocation fail; AP equals vendor totals.
- **Verify manually:** Show one partly paid vendor bill and the $200.00 control-account balance.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 14: Vendor bills and partial settlement. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 15: Customer invoices and collection

Split into [15a invoice recognition](STEP_15A_PLAN.md) and [15b collection and aging](STEP_15B_PLAN.md), under [the Step 15 contract](STEP_15_PLAN.md).

- **Build:** Add service-completion evidence, receivable invoice, due date, receipt allocation and aging.
- **Test:** A $2,500.00 invoice and $1,500.00 receipt leave $1,000.00 receivable; collection does not recognize revenue twice; aging cutoff and over-allocation are checked.
- **Verify manually:** Display the invoice, payment and remaining $1,000.00 due.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 15: Customer invoices and collection. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 16: Customer advances and earning

Split into [16a advance receipt](STEP_16A_PLAN.md) and [16b supported earning](STEP_16B_PLAN.md), under [the Step 16 contract](STEP_16_PLAN.md). Before Phase 05 acceptance, [16c payable seal hardening](STEP_16C_PLAN.md) resolves the concrete earlier migration/approval observations.

- **Build:** Track customer prepayments as liabilities and recognize only supported earned amounts.
- **Test:** A $600.00 advance with $200.00 earned leaves $400.00 unearned; reject excess release and duplicate recognition.
- **Verify manually:** Trace advance receipt and service evidence to separate liability and revenue postings.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 16: Customer advances and earning. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Corrections use linked reversals or credit documents with review. Never silently delete a settled invoice or bill.
