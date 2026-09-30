# Next: Step 11 — Resumable fake-provider run loop

Status: ready. Steps 01–10 provide deterministic accounting, evidence/review/approval and an entity-scoped typed tool boundary with 24 labeled offline cases.

## Copy this prompt

> Build Step 11: resumable fake-provider run loop. Follow Plan/NEXT_STEP.md, persist bounded run states and checkpoints around the existing typed tools, handle retries, cancellation and restart without duplicate drafts or posting, demonstrate a run pausing for human review and resuming safely, then commit and push to GitHub. Stop after this step.

## The small thing to build

Read [Phase 04](04-agent-harness/README.md), the [Step 10 contract](04-agent-harness/STEP_10_PLAN.md) and [verification](04-agent-harness/STEP_10_VERIFICATION.md). Add one fake-provider run loop over the existing five-tool allowlist. Define durable run/task IDs, entity/actor/policy scope, states and legal transitions, checkpoints, tool/result references, fake provider/prompt version, explicit stop reasons, cancellation and bounded tool-call/time/cost/retry budgets before implementation. Budget amounts require exact integer units. Model/document text cannot alter scope, budgets or permission. No real provider/network calls or approval/posting tool.

Persist concise explanations and references, never hidden reasoning or raw sensitive provider traces. Make the crash boundary around draft writes explicit: restart/replay must reuse the same scoped request and cannot create a second revision accidentally. Preserve the existing review/approval/ledger schemas and history; test any additive migration and unsupported-version rejection. A run awaiting human review must not resume by impersonating a reviewer or posting.

## Required evidence

Use deterministic fake outputs/timeouts to test interruption before/after a side effect, restart/replay, invalid output/tool calls, exhausted budgets, bounded retry, cancellation and cross-entity access. Demonstrate start, pause at review, restart/resume and a complete persisted trace with one unchanged draft and zero unapproved postings. Keep the 24-case offline suite and discovery guard. Add the run demo to CI, run the foundation check, guarded suite and every demo. Update status/roadmap and the Step 12 brief, commit/push, inspect the exact Actions run, then stop.
