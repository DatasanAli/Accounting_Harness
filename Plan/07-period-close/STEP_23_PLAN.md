# Step 23: cash flow and reproducible exports

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 22.

**Goal:** Explain the reference month's 9,400.00 cash from captured financial
records, then export and reproduce the same reports without a live database.

**Architecture:** Deliver two independent slices: a pure direct-method cash-flow
report over the existing captured financial data, followed by portable validated
JSON/CSV report packages. Neither slice imports or posts ledger transactions.

**Spec:** [Phase 07](README.md), using delivered statements and closing policy.

## Global constraints

Exact integer cents, USD and the configured synthetic January period. Preserve
ordinary/closing classifications, immutable journal/source trace, captured account
metadata and every old report format/digest. Report policy is explicit; unsupported
cash classifications stay visible rather than being guessed from descriptions.
No live connections, arbitrary client-supplied totals or changes to actual books.

## Independently verifiable deliveries

1. [23a direct cash-flow statement](STEP_23A_PLAN.md): explain operating -400.00,
   investing 0.00, financing 9,800.00 and ending Cash 9,400.00, with traceable
   unsupported cases and a pure frozen capture.
2. [23b portable report packages](STEP_23B_PLAN.md): deterministic JSON plus a
   readable CSV and its same-capture manifest; strict read-back reproduces dates,
   cents, references and report digests without ledger writes.

Each slice requires focused/full checks, demonstrations, browser review,
independent review, commit/push and its exact GitHub CI before the next slice.
