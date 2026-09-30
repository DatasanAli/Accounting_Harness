# Step 09 verification

Observed 2026-09-30: 156 application tests pass, foundation verification passes, all eight demos pass. Missing approval module and missing demo command provided the initial red checks. Added 13 approval tests and one CLI demo test. A reproduced audit regression (missing superseded approvals) failed before the trace fix; the complete decision-history test now passes.

Coverage includes missing/stale/rejected approval, changed draft/evidence/policy, malformed confirmations/retry inputs, exact retry after reopen, duplicate journal rejection, concurrent posting, mutation denial after posting, immutable SQL records, approval initialization rollback preserving old revisions, and failures after journal/approval insertions rolling back all related writes. The actual CLI subprocess cancels on EOF/incorrect confirmation and posts only after the exact digest phrase.

`demo-approval` reports approved revision 1, a reopened retry retaining one 1200.00 USD rent journal, and `rent -> rent-draft revision 1 -> rent-journal`. Audit output also includes every superseded approval and rejection revision. Full earlier ledger/reversal/source/draft suite and discovery guard pass.

Optional approval schema v1 is additive to review v1 and ledger v2. Existing low-level admission remains an internal trusted primitive. Source identities must be provisioned in the ledger's original frozen context. Posting rechecks current immutable registry evidence; hostile filesystem replacement/administrator tampering is outside this local prototype. No model can call approval/posting through a tool; authenticated application roles are Step 29. Rollback retains all tables and journals; corrections use linked reversals.

Independent review found the audit history gap above; fixed and verified before delivery. Commit/push and exact GitHub CI result are checked after the commit and reported in the delivery response.
