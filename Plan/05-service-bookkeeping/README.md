# Phase 05: Daily service-business operations

Status: planned; no behavior in this phase is implemented yet.

**Depends on:** Steps 02–12. Each workflow uses existing evidence, approval, and posting services.

**Outcome:** Supported day-to-day cash, payable, receivable, and advance transactions reconcile to the ledger.

**Source basis:** Volume 1 §§3.5, 7.2–7.4, 9.1–9.3, 12.1–12.2. See the [source map](../SOURCE_MAP.md).

## Implementation approach

Introduce one workflow at a time and one document per demo. Define recognition from service delivery/incurrence evidence. Receiving cash alone does not determine revenue. Subledgers must reconcile to their control accounts. Recording a payment that occurred does not execute a bank payment or send a customer message.

## Small build steps

Build only one numbered step per request. Split a row further if it cannot be demonstrated and reviewed as one small change.

### Step 13: Cash receipts and expenses

- **Build:** Support incurred cash expenses and immediately earned service receipts through reviewed templates.
- **Test:** Owner contributions, transfers and customer advances must not be misclassified as earned revenue; duplicate receipts fail safely.
- **Verify manually:** Post rent $1,200.00 and a separately evidenced earned cash receipt; inspect classifications.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 13: Cash receipts and expenses. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 14: Vendor bills and partial settlement

- **Build:** Add a vendor subledger, expense bill, due date and allocation of recorded payments.
- **Test:** A $300.00 bill and $100.00 payment leave $200.00 payable; duplicate bill and over-allocation fail; AP equals vendor totals.
- **Verify manually:** Show one partly paid vendor bill and the $200.00 control-account balance.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 14: Vendor bills and partial settlement. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 15: Customer invoices and collection

- **Build:** Add service-completion evidence, receivable invoice, due date, receipt allocation and aging.
- **Test:** A $2,500.00 invoice and $1,500.00 receipt leave $1,000.00 receivable; collection does not recognize revenue twice; aging cutoff and over-allocation are checked.
- **Verify manually:** Display the invoice, payment and remaining $1,000.00 due.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 15: Customer invoices and collection. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

### Step 16: Customer advances and earning

- **Build:** Track customer prepayments as liabilities and recognize only supported earned amounts.
- **Test:** A $600.00 advance with $200.00 earned leaves $400.00 unearned; reject excess release and duplicate recognition.
- **Verify manually:** Trace advance receipt and service evidence to separate liability and revenue postings.
- **Delivery:** run relevant checks, update status and next prompt, commit, push and verify that commit's CI.

Copyable prompt:

> Build Step 16: Customer advances and earning. Follow Plan/05-service-bookkeeping/README.md and the shared implementation/testing guidelines. Implement only this step, demonstrate it with fictional data, test it, then commit and push to GitHub. Report the evidence and stop.

## Phase acceptance and rollback

The phase is complete only when each of its steps has its own observed verification and GitHub delivery evidence. Apply the [shared testing rules](../TESTING_STRATEGY.md) and [GitHub workflow](../GITHUB_WORKFLOW.md).

Corrections use linked reversals or credit documents with review. Never silently delete a settled invoice or bill.
