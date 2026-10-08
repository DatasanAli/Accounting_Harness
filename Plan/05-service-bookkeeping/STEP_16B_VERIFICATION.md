# Step 16b verification: supported advance earning

Observed on 2026-10-08 using synthetic January 2026 data.

## Behavior

A separately registered service completion binds customer, contract, completion
identity, date and full earned amount to one posted advance. The
`advance-earning-v1` intent and both prepayment/completion evidence roles become
part of the exact human-approved revision. Posting debits Unearned Service Revenue
and credits Service Revenue, leaving cash unchanged.

The completion shares the service-recognition claim used by earned cash and
customer invoices. Approval reserves no balance; posting checks the remaining
principal inside the same transaction as the immutable earning effect, journal,
audit link and retry receipt. The final journal seal rechecks current approval.

Review and advances schemas migrate explicitly. Legacy four-field advance
captures retain schema1 report shape and digests; new captures explicitly use
schema2 and retain their own immutable earning history. Rendering a captured
report never consults current storage.

## Browser demonstration

The delivered Step 16a workspace was reopened with its posted 600.00 advance for
`contract-browser-16a`. The operator registered `browser-completion-16b`, a 200.00
completion dated January 31 for the same customer/contract. Preparing the draft
left one journal, zero earned and the full 600.00 remaining obligation.

The review displayed the original prepayment, completion, exact intent and
Unearned Service Revenue debit200.00 / Service Revenue credit200.00. Only after
the explicit confirmation checkbox and Approve & post did the second journal
appear:

| Result | USD |
| --- | ---: |
| Cash debit, unchanged | 600.00 |
| Original advance principal | 600.00 |
| Earned / service revenue credit | 200.00 |
| Remaining obligation / unearned control credit | 400.00 |
| Unassigned control residual | 0.00 |

The customer/contract and earning source/journal trace remained visible. The
actual 500px viewport had no horizontal page overflow. The first browser attempt
caught a wrong endpoint in the earning form; it was corrected, an HTTP test now
executes the route extracted from that form handler, and the full browser flow
above passed after refresh. Restarting the final application retained two
journals, Cash600.00, earned200.00, remaining400.00 and zero residual.

## Verification and delivery

The guarded suite passed **387 tests** in 20.513 seconds, including 17 new
earning tests. All **20 demos**, foundation, JavaScript syntax and diff checks
passed. Independent review approved spec compliance and task quality with no
findings. Delivered as [d57ca17](https://github.com/DatasanAli/Accounting_Harness/commit/d57ca177a53f0b8f3e8e878d4bdc6ae0d7615270); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37807454834). The remote main SHA matched the local commit.
Required commands include:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-advance-earning
node --check accounting_harness/static/app.js
```

All prior demonstrations remain required. No live provider or external account
was connected.

## Limits and rollback

One whole completion value applies to one advance. Splits across advances,
refunds, managed corrections, FX and tax require separate policies. Source text
cannot authorize posting. The existing fictional local operator remains in use;
authenticated roles are a later delivery.

Preserve workspace databases together. Revert published code through a new commit;
never delete or edit a posted earning as an accounting correction.
