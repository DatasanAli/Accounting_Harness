# Step 13a verification: additive synthetic evidence enrollment

Observed 2026-10-08. No provider or external account was connected.

## Implemented behavior

The localhost Evidence screen now registers structured fictional January 2026
receipts. Entity, schema, currency and synthetic marker are application-owned;
the operator supplies a stable document ID, date, exact amount, counterparty and
description. Registration creates evidence only. It cannot draft, approve or post.

Ledger schema v3 adds immutable source enrollment records and source identities
without changing the original ledger context. Version 1 and 2 files migrate
through an atomic additive chain. Already-open connections see enrolled sources;
older snapshots, posting retries, approvals and run scope remain unchanged.

Registration and enrollment use separate files. If enrollment fails after
registration, the source remains visible as pending. Exact resubmission or startup
repair completes enrollment; neither path deletes evidence or invents a posting.
The enrollment anchor also detects a substituted registry with different content.

## Observed checks

- Guarded suite: **257 tests pass**, including 11 focused enrollment cases and
  11 HTTP cases. The existing zero-discovery failure guard remains unchanged.
- All **13 demos** pass, including `demo-enrollment`. The new demo enrolls a
  125.00 USD receipt, reopens/retries with the original actor/time, preserves the
  old trial balance and posting receipt, and retains the prior approval binding.
  Additional journals: zero. Model calls: zero.
- Enrollment tests cover concurrent/open connections, identity/content conflict,
  wrong entity, corrupted/substituted content, rollback between audit/source
  insertion, direct SQL immutability, populated v2 migration and injected DDL
  rollback. The checked-in v1 database fixture still migrates and retries safely.
- HTTP checks cover strict fields/date/amount validation, register/list/retry,
  restart, visible pending enrollment and resubmission/startup recovery. Existing
  Host/Origin/CSRF, bounded-body and posting tests remain green.
- Foundation, JavaScript syntax and diff checks pass.
- Actual Chromium form submission registered `browser-typed-006` with 125.00 USD,
  then repeated the same submission. Both showed six total sources, the same
  evidence digest, zero drafts/runs/journals and no horizontal page overflow.
  Offline fixture playback was disabled for the typed receipt.

## Boundaries and rollback

Only existing synthetic v1 receipts are accepted. Typed recognition facts and
reviewed cash templates belong to Step 13b. The UI does not infer earning or
incurrence from receipt text, and fixture playback does not pretend to understand
new documents. Real provider evaluation remains deferred.

The public enrollment service checks the registry; SQL enforces audit presence
and append-only identity but cannot authenticate a separate database file. This
is consistent with the existing local file-owner trust boundary. There is no
cross-file atomicity claim.

Back up ledger, registry and run files together before migration. Older v2-only
code refuses v3 files; do not downgrade by editing schema markers or deleting
history. Software rollback uses a new commit; posted corrections use reversals.
The next delivery records the exact uploaded commit and observed CI result.
