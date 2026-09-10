# Next: Step 03 — Journal validation

Status: ready. Steps 01–02 established the foundation and implemented exact Money values and the service-business account catalog.

## Copy this prompt

> Build Step 03: journal-entry validation. Follow Plan/NEXT_STEP.md, accept balanced entries and reject invalid ones, test and demonstrate the result, then commit and push to GitHub. Stop after this step.

## The small thing to build

Add a pure journal-entry validator and one CLI demonstration. It accepts a proposed entry only when its metadata and lines are valid and its debit/credit totals match exactly. The validator returns structured findings that can later be used by review workflows.

Use the existing `Money`, `Account`, `AccountCatalog`, and `get_for_posting` validation boundaries. This step does not apply entries to balances, save a database, manage approval, or call an agent. Those capabilities remain in their existing later steps.

## Proposed contract

A proposed entry contains a nonblank ID, entity ID, USD currency, effective accounting date, nonblank description, source IDs, and two or more lines. Each line contains one active account code, one side (`debit` or `credit`), and a positive Money amount. Inputs with both debit and credit fields should not be coerced into a single-sided line.

The entry entity/currency must match the supplied catalog, and every line's currency must match the entry. Use actual calendar dates; serialized dates must use `YYYY-MM-DD`. Reject date/time strings masquerading as accounting dates. Closed-period validation belongs to the later period-lock step.

Require at least one nonblank source ID and check it against explicitly supplied known source IDs. For this step, the validator's tests and demo can supply IDs from the fictional fixture; source registration, storage, digest verification and document interpretation remain later work. A known source ID is not proof that its accounting classification is correct.

Return a result that clearly identifies accepted/rejected status, exact debit and credit totals when computable, and field/line-specific findings with stable error codes. Invalid input must not be silently rounded, coerced, dropped, or accepted after only some lines have been checked. Keep input objects/catalog unchanged.

## Acceptance examples

| Example | Expected result |
| --- | --- |
| Owner contribution: Cash debit 1000.00, Owner Capital credit 1000.00 | Accepted, totals 1000.00 / 1000.00 |
| Same example with credit 999.00 | Rejected as unbalanced; difference 1.00 |
| Compound earned service receipt: Cash debit 700.00, Accounts Receivable debit 300.00, Service Revenue credit 1000.00 | Accepted; multiple lines on one side are supported |
| Empty/one-line entry, zero amount, negative or floating-point amount, invalid side | Rejected with relevant line/entry finding |
| Unknown/inactive account | Rejected using the catalog boundary |
| Wrong entity, unsupported currency or currency mismatch | Rejected before acceptance |
| Blank ID/description; impossible date such as 2026-02-30; timestamp instead of date | Rejected with field-specific finding |
| Missing, blank or unknown source ID | Rejected; no fabricated evidence |
| Repeat validation of the same proposal | Same result; proposal and catalog unchanged |

Balancing verifies arithmetic, not all accounting meaning. Do not claim this validator can establish correct recognition, classification, approval, posting idempotency or business completeness.

## Files and verification

Add a focused domain module such as `accounting_harness/domain/journal.py` and meaningful tests in `tests/test_journal.py`. Extend the CLI with a `demo-journal` command that shows the valid 1000.00 contribution and refused 999.00 credit. No third-party dependencies are needed.

Keep these existing commands passing:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-accounts
```

Add the new demonstration to CI when it exists, record observed results, and update the root README and active phase. Mark Step 03 complete and Step 04 ready in the roadmap/status. Replace this document with a small Step 04 ledger/trial-balance specification. Commit, push, verify that exact commit and CI run, then stop.

Source basis: Volume 1 §§3.3–3.6. Exact types and structured validation findings are engineering decisions.
