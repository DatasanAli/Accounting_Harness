# Step 13b verification: reviewed cash recognition

Observed on 2026-10-08 using synthetic January 2026 evidence. Live provider and
external-account connections remain deferred.

## Delivered behavior

Schema v2 supports typed cash movement, incurred expense and service completion
facts. Existing schema v1 receipt canonical content and digest bytes remain
unchanged. The cash policy requires separate cash and recognition documents with
matching event, counterparty identity, amount, currency and date. Cash purpose
alone does not establish earning or incurrence.

The localhost Evidence screen registers the paired facts and prepares a draft.
Accounts, date and amount derive from the evidence. Review displays both complete
documents, evidence digests, exact journal and saved policy before the operator
checks the confirmation and invokes approval/posting. Registration and proposal
preparation never post. Provider runs retain their original receipt policy and
cannot use typed v2 facts through the weaker one-receipt path.

Semantic claims reserve entity/event/role in the same transaction as each cash
draft. New source IDs cannot reuse a known cash or recognition event through
another draft. Claims remain after rejection. Historical receipt approval,
posting retry and run context remain compatible.

## Observed checks

- `python3 scripts/verify_foundation.py`: passed, including roadmap and reference accounting identities.
- `python3 scripts/run_tests.py`: **268 tests passed**, including 11 new cash/schema/HTTP/CLI tests and the zero-discovery failure guard.
- All **14 documented demos** passed, including new `python3 -m accounting_harness demo-cash`.
- `node --check accounting_harness/static/app.js` and `git diff --check`: passed.

The cash demo begins with two pending drafts and zero posted journals, then
simulates two separate human confirmations. After reopen and exact retries:

| Account | Debit USD | Credit USD |
| --- | ---: | ---: |
| Cash | 0.00 | 400.00 |
| Rent expense | 1200.00 | 0.00 |
| Service revenue | 0.00 | 800.00 |
| Trial balance total | 1200.00 | 1200.00 |

There are exactly two journals. Each trace retains two exact evidence digests,
revision, policy, operator and effective date. Negative cash is intentional in
this isolated zero-opening demonstration, which does not include owner funding.

Real Chromium checks on a fresh ignored workspace registered the rent 1200.00
pair and earned-service 800.00 pair using the forms, prepared each draft, observed
no new journal before confirmation, then explicitly approved each. The Ledger
screen showed the table above and the evidence/approval trail. Evidence and
Ledger had no horizontal overflow at the browser's actual narrow 500px viewport.
The check also led to replacing receipt-specific copy with general evidence copy
for typed facts.

Tests reject owner contributions, transfers, advances, settlement cash, missing
recognition, mismatched event/counterparty/amount/date, invalid currency/account,
extra or unbound evidence, forged journal mappings and typed facts under the old
receipt policy. Concurrent duplicate drafts leave one owner; injected claim
failure rolls back the whole draft transaction. Prior receipt approvals still
post after adding cash drafts. The tests use expected accounting values defined
independently of the implementation.

## Limits and rollback

This is one fictional operator, USD, January 2026, with immediate whole-amount
cash recognition and expense accounts 5000/5100. The UI does not yet revise a
rejected cash draft; reserved evidence cannot be released by creating another
identity. Deliberately inventing a different event identity cannot be detected
from fictional assertions. No model accuracy or production authentication is
claimed.

Revert published software with a new commit and retain all workspace databases
together. Posted accounting activity remains immutable; use supported linked
corrections rather than deleting entries or restoring over valid history.

## Delivery evidence

Delivered as [887cc4e974c196913432c0006bf7d1e24e5af096](https://github.com/DatasanAli/Accounting_Harness/commit/887cc4e974c196913432c0006bf7d1e24e5af096). Local HEAD and remote `main` matched. [GitHub Actions run 37791223746](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37791223746) completed successfully for that exact SHA, including the guarded suite and all 14 demonstrations. The reviewed enrollment-helper extraction passed the affected 22 tests and two demos locally before upload.
