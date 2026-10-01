# Next: Step 12 — One real provider and proposal evaluation

Status: ready. Steps 01–11 provide deterministic accounting, human approval/posting, typed proposal-only tools, 24 offline contract cases and a durable bounded fake-provider run loop.

## Copy this prompt

> Build Step 12: one real provider and proposal evaluation. Follow Plan/NEXT_STEP.md, add one bounded provider adapter behind the existing tool and run contracts, evaluate supported synthetic expense proposals and abstention against the offline gate, demonstrate a proposal stopping for separate human review, then commit and push to GitHub. Stop after this step.

## The small thing to build

Read [Phase 04](04-agent-harness/README.md), the [Step 11 contract](04-agent-harness/STEP_11_PLAN.md) and [verification](04-agent-harness/STEP_11_VERIFICATION.md), and the agent evaluation gate in [TESTING_STRATEGY.md](TESTING_STRATEGY.md). Select one provider/model, prompt version, supported expense workflow and explicit live time/cost/sample budget before billable calls. Keep credentials local. No provider or real model has been selected or exercised yet.

Design the provider interface around actual structured outputs, tool results and context, while retaining fixed application-owned entity/actor/allowlist and separate human approval. The current fake script is deterministic and fingerprinted; it does not perform inference or expose a general network-provider interface. Do not substitute network calls inside a SQLite transaction or assume simulated billing/time accounting proves live-request safety. Specify request timeouts, cancellation, conservative cost reservation, ambiguous completion after crashes, rate limits, bounded retries and replay before extending the runtime. Exact costs use integer units; provider output cannot raise budgets or grant permissions.

Use only synthetic receipts and supported expense proposals. Confidence/ambiguity, missing/conflicting evidence and unsupported requests must stop for review. Keep raw provider responses, hidden reasoning, financial records and credentials out of GitHub and durable audit logs; retain concise explanations, model/prompt version and evidence/result references.

## Required evidence

Retain all 24 deterministic tool-contract cases and add/freeze at least 20 labeled provider-proposal cases covering clean evidence, ambiguity, missing/conflicting facts, duplicates, unsupported requests and hostile document instructions. A tool-contract score is not a provider accuracy score. Report category numerators/denominators against the documented gate: zero unauthorized postings, zero accepted unbalanced proposals, every successful proposal linked to fixture evidence, all designated ambiguous/unsupported cases routed to review, and at least 90% exact expected proposals on unambiguous supported cases.

Run a bounded live synthetic smoke/evaluation with model/prompt version, sample count, latency, measured cost, failures and nondeterminism recorded. If configuration or credentials prevent the live check, preserve offline work and report that delivery gate honestly; never claim a live result from fake responses. Demonstrate a receipt → proposal → separate human review/approval → single posting without exposing approval/posting tools to the model. Preserve interruption/restart, budget, cancellation and zero-discovery tests. Run foundation, guarded suite and every existing demo; add the new behavior to CI without requiring secrets for deterministic tests. Update status/roadmap and Step 13 brief, commit/push, verify exact SHA/Actions run, then stop.
