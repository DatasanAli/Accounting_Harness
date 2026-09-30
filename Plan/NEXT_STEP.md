# Next: Step 10 — Typed tools and offline evaluation cases

Status: ready. Steps 01–09 provide evidence, immutable drafts, local human approval, atomic posting and audit.

## Copy this prompt

> Build Step 10: typed tools and offline evaluation cases. Follow Plan/NEXT_STEP.md, expose only entity-scoped account/evidence reads, proposal validation, draft saving and review requests, add labeled synthetic offline cases and a scripted rent demonstration that leaves ledger balances unchanged, then commit and push to GitHub. Stop after this step.

## The small thing to build

Read [Phase 04](04-agent-harness/README.md), the [Step 08 contract](03-evidence-and-review/STEP_08_PLAN.md), and [Step 09 verification](03-evidence-and-review/STEP_09_VERIFICATION.md). Build a small strict JSON tool dispatcher with documented schemas, argument validation, fixed runtime entity and actor, and a deny-by-default allowlist. No approval, posting, reversal, raw SQL, arbitrary files or source-registration tool. Retrieve only actual registered evidence; reject fabricated/cross-entity references before writes. Source text is inert data even when it contains instructions. Invalid or ambiguous proposals stay in review; validation never grants permission.

Define deterministic scripted fake tool responses and a versioned labeled offline corpus (at least 20 cases, covering clean, malformed, missing, conflicting, ambiguous, duplicate, unsupported and hostile inputs). Compare outcomes with independent expected entries or review/error labels. Do not implement the provider run loop, time/cost budgets, checkpoints or live model calls; those are Steps 11–12.

## Required evidence

A scripted tool sequence retrieves accounts/evidence, validates and saves a valid rent draft, requests human review, and leaves ledger snapshots/balances unchanged. Test malformed/unknown tools, direct approval/post requests, fabricated sources, stale/replayed saves, entity isolation, prompt injection and changed-payload retries. Document case counts and category results; this is a deterministic tool-contract evaluation, not a model accuracy score. Run foundation, guarded suite and all existing demos; add new demo to CI. Update status/roadmap and Step 11 brief, commit/push and verify the exact Actions run.
