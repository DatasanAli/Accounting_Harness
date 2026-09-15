# Next: Step 04 — Ledger and trial balance

Status: ready. Steps 01–03 established the foundation, exact Money/account catalog, and pure journal validation.

## Copy this prompt

> Build Step 04: ledger and trial balance. Follow Plan/NEXT_STEP.md, apply validated entries to an in-memory ledger and demonstrate the reference trial balance, test it, then commit and push to GitHub. Stop after this step.

## The small thing to build

Add an in-memory ledger for one entity/catalog and a defined inclusive accounting date range, plus an as-of-date trial balance. Use the Step 03 validator with explicitly supplied known source IDs on every entry admission. A caller-provided validation result must not bypass revalidation. Reject invalid entries, duplicate entry IDs and effective dates outside the ledger range without changing existing entries or balances.

Use integer cents, with signed per-account balances or separate debit/credit totals. Preserve a snapshot of accepted entries and their IDs, dates, descriptions, sources and lines so later caller mutations cannot alter history. This is a local synthetic ledger demonstration; authenticated approval, durable posting, idempotency and audit events remain in their planned steps. Do not add SQLite or an agent.

The report includes entity, currency, inclusive date cutoff, included entry IDs (the in-memory snapshot), and an explicit unadjusted/all-zero-opening report policy. Include all catalog accounts in stable code order. Net debit balances appear in the debit column; net credit balances appear in the credit column, regardless of normal-side metadata. Zero balances have zero in both columns. Reject invalid or out-of-range report dates. Report generation must not change the ledger.

## Acceptance examples

- Explicitly adapt only ordinary transactions T01–T09 from `data/fixtures/service-business-month.json` to the journal contract. Leave adjustments and closing entries for their later steps.
- At 2026-01-31, compare every account against the independent `expected.unadjusted_trial_balance` fixture. Both columns total **13300.00 USD**, with Cash **9400.00 USD** debit.
- Earlier cutoffs include only entries effective on or before that date, including transactions on the cutoff itself. Empty ledgers show zero totals and all catalog accounts.
- Duplicate IDs, unbalanced proposals, invalid evidence/accounts, and dates before or after the ledger range fail without partial changes. Different IDs with identical amounts remain separate transactions.
- A malformed batch must not leave an undocumented partial import; either keep the API single-entry or define atomic batch behavior explicitly.
- Repeated reports are identical for an unchanged snapshot; modifying input dicts/lists after admission cannot alter the stored entries or report.
- Include a credit balance in an asset account to verify display follows the actual net balance rather than the account's normal side.

## Files and verification

Add a focused ledger module, meaningful tests, and `python3 -m accounting_harness demo-ledger`. Keep these checks passing:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-accounts
python3 -m accounting_harness demo-journal
```

Add the ledger demo to CI, update the root README and phase verification record, mark Step 04 complete and Step 05 ready in status/roadmap, and replace this document with a small persistence/retry specification. Commit, push, verify the exact commit and CI run, then stop.

Source basis: Volume 1 §§3.5–3.6. Snapshot metadata and validation boundaries are engineering decisions.
