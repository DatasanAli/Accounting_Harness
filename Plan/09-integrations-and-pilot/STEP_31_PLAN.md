# Step 31: complete the authenticated local workbench

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 30; deliver the three slices separately.

**Goal:** Make the supported accounting month usable from the localhost UI and
make Ollama/API adapters ready to propose supported work when the user connects one.

**Architecture:** Extend the existing deterministic templates and run engine,
then organize their authenticated UI into one coherent workflow. Keep one review
boundary and one trace from source through exact approval to the posted journal.
No second app, agent-owned ledger or live connection is required.

**Tech stack:** Existing Python/SQLite services, native HTML/CSS/JS and adapters.
**Spec:** [Phase 09](README.md), [localhost objective](../LOCALHOST_APP_PLAN.md).

## Global constraints

- Every monetary result is an exact server-calculated value; a model response is
  a proposal and never substitutes for deterministic evidence/ledger validation.
- Authenticated preparers initiate runs/proposals; authenticated reviewers/owners
  confirm the exact current revision. Models have no approve/post/close/export
  authority and cannot create or expand their own grants or tool allowlist.
- Existing run checkpoints, expense adapters, approval digests and historical
  reports retain their original contracts. New runtime capabilities are versioned.
- Live Ollama/frontier API calls remain deferred. Provider configuration and
  readiness may be shown, but offline fixtures are not model-accuracy evidence.
- All reference-month entry paths must be usable without editing SQLite or using
  a hidden trusted fixture function. Unsupported scope is visible at the point
  of action, with no silent fallback to a generic journal.

## Independently verified deliveries

1. [31a reviewed owner/prepaid cash entries](STEP_31A_PLAN.md): complete the missing
   ordinary reference-month UI inputs with bounded supported templates.
2. [31b bounded operational agent proposals](STEP_31B_PLAN.md): versioned read and
   propose tools and offline adapter contracts for already supported operations.
3. [31c integrated workbench](STEP_31C_PLAN.md): coherent navigation, role-aware
   workflow handoffs, keyboard/accessibility checks and end-to-end browser proof.

Use the delivered services instead of reimplementing accounting in JavaScript or
new UI-specific stores. A successful synthetic run demonstrates application
wiring and enforcement. The later user-supplied live provider and real-data pilot
remain separate gates with their own evidence.
