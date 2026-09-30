# Step 08 verification

Observed 2026-09-30: 142 application tests pass. Red phase: missing review module; CLI test then failed for missing demo command. Added 13 review tests and one CLI test. Independent code review found no blocking issues; its suggested rollback/reject-retry coverage was added.

`python3 scripts/run_tests.py` checks edit/reopen/history, unchanged input snapshots, pending/rejected reasons, exact retry results and conflicts, stale/concurrent edits, entity isolation, missing/conflicting evidence, period/amount/overflow findings, current evidence rechecks, SQL immutability, bounded locking, event/retry write failures and initialization rollback. Existing ledger receipt/snapshot compatibility remains covered.

`demo-review` prints two unchanged revisions (1200.00 original, 1100.00 edited debit), unbalanced/evidence_amount findings, a rejected item and reason, and zero posted journals. All seven demos and `python3 scripts/verify_foundation.py` pass.

Storage is additive optional review schema v1 in ledger v2; existing context/retry semantics stay unchanged. Source registration remains separate. One receipt per proposal is the supported evidence policy; classification remains a human review responsibility. Rejected drafts can be edited to a new pending revision. SQL guards immutability; application code owns validation/transitions. No authentication or approval is provided yet.

Rollback retains optional review tables; revert software through a new commit without deleting history. GitHub delivery is checked after commit/push; exact commit and Actions links are reported in the delivery response, not predicted here.
