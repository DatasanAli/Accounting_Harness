# Step 16a verification: customer advance receipt

Observed on 2026-10-08 using synthetic January 2026 data. Supported earning is a
separate Step 16b delivery; receiving cash here does not recognize revenue.

## Behavior

Paired prepayment-obligation and incoming advance-cash facts establish the full
principal for one customer/contract. They must agree on event, customer, amount,
currency and receipt date. An `advance-v1` intent binds that identity, principal,
date and both evidence roles into the exact human-approved revision.

Posting debits Cash and credits Unearned Service Revenue. Immutable advance
effects, journals, review posting and retry receipts share one transaction.
Shared cash-event claims prevent reuse across cash/payment/collection policies.
Account 2100 activates only with zero unexplained balance and then requires the
matching approved effect. Its final journal seal rechecks the current approved
revision, digest and intent after effect insertion. Managed reversal is refused
until a linked obligation-correction workflow exists.

Captured advance reports retain original verified customer names, contract,
principal, earned/remaining values, control balance, residual, cutoff, policy,
explicit report version and digests. Report generation is pure after capture;
current registry changes cannot rewrite earlier names or values.

## Browser demonstration

In a fresh localhost workspace, the operator registered two facts for a 600.00
advance received January 22 under `contract-browser-16a`. Preparing the draft left
zero journals and zero advance items. Review showed both documents, exact intent
and Cash debit600.00 / Unearned Service Revenue credit600.00.

After the separate confirmation checkbox and Approve & post:

| Result | USD |
| --- | ---: |
| Cash debit | 600.00 |
| Unearned liability/control credit | 600.00 |
| Principal / remaining obligation | 600.00 |
| Earned amount / service revenue | 0.00 |
| Unassigned control residual | 0.00 |

There was one journal. The customer/contract, receipt date and both evidence IDs
remained visible. The actual 500px viewport had no horizontal page overflow.
No browser fixes were required. Restarting the final implementation retained one journal, principal/remaining600.00, earned0.00 and residual0.00.

## Verification and delivery

The guarded suite passed **370 tests** in 19.410 seconds, including 25 advance tests. All **19 demos**, foundation, JavaScript syntax and diff checks passed. An initialization regression first demonstrated partial review/approval migration on an advance-schema fault; the fix joins all advance setup into one transaction and the regression now restores the prior schema/version exactly. Standalone review/approval initialization remains supported. Independent review approved spec compliance and code quality with no findings, including the shared constructor transaction ownership. Commands include:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-advance
node --check accounting_harness/static/app.js
```

All prior demonstrations remain required. Focused checks include incorrect facts,
shared cash claims, duplicate contract, forged intent/journal, absent approval,
final-seal supersession, exact concurrent retry, legacy migration preservation,
initialization/write rollback, old/direct connection guards, immutable captured
names/reports and exact large-cent HTTP display.

Commit, remote comparison and exact-SHA CI will be recorded after final checks
and review; no GitHub completion is claimed yet.

## Limits and rollback

One whole advance per customer/contract is supported; further deposits, refunds,
split movements, tax/FX and managed corrections require separate policies. This
slice adds no completion/earning kind, table, policy or route. The existing local
fictional operator model remains; live model and external-account connections are
deferred, and provider proposals retain their bounded expense scope.

Preserve workspace databases together. Revert published code with a new commit;
never delete a valid advance/journal as an accounting correction.
