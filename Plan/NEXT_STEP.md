# Next: Step 09 — Approval, posting and audit

Status: ready. Steps 01–08 provide immutable evidence and draft revisions with an explicit pending/rejected review queue.

## Copy this prompt

> Build Step 09: approval, posting and audit. Follow Plan/NEXT_STEP.md, bind a human CLI decision to an exact validated revision and evidence/policy digests, post atomically through the application, demonstrate the source-to-journal audit trail, then commit and push to GitHub. Stop after this step.

## The small thing to build

Read the [Step 08 contract](03-evidence-and-review/STEP_08_PLAN.md) and [verification](03-evidence-and-review/STEP_08_VERIFICATION.md). Add durable human decisions and application posting in the same SQLite transaction as ledger writes. Bind entity, draft/revision digest, evidence identities/digests, policy version and posting action. Recheck current revision, source bindings, policy and period at posting. A changed or rejected revision cannot reuse approval; a posted draft cannot be edited or posted again under another key. Exact request retries return original receipts.

Keep the ledger context and existing posting retry bytes unchanged. Use only registered receipt identities already provisioned in the frozen ledger context; missing/unprovisioned evidence blocks approval. The local operator CLI is a prototype boundary; authenticated roles remain Step 29. Do not expose approval/posting to agent tools.

## Required evidence

Test no approval, rejection, stale revisions, changed evidence/policy, malformed decisions, duplicate/repeated posting, concurrent posting, reopen, migration/initialization rollback and failures after journal writes. Trace original evidence through every revision/decision to the posted journal, actor and date. Preserve the complete suite and zero-discovery guard. Add a synthetic approval demo to CI, run all checks/demos, update status/roadmap and Step 10 brief, then commit/push and inspect that exact commit's Actions run.
