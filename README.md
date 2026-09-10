# Accounting Harness

An accounting agent harness for bookkeeping at a small service business, built one verifiable step at a time.

The intended workflow is: **evidence → proposed journal entry → validation → human approval → posting → reconciliation → reporting**. Accounting code owns calculations and ledger changes. The agent helps interpret evidence and propose work.

**Current state:** Step 01 establishes the scope, implementation plan, testing rules, and an original bookkeeping reference example. There is no application or agent runtime yet.

Start with the [plan directory tree](Plan/README.md), [current status](Plan/STATUS.md), and [next step](Plan/NEXT_STEP.md). The [source map](Plan/SOURCE_MAP.md) connects the plan to the supplied textbooks, reviewed in order: Volume 1, then Volume 2.

## Verify this step

Use Python 3.12 or newer. No packages, API keys, PDFs, or network access are required for this check.

```sh
python3 scripts/verify_foundation.py
```

This verifies local documentation links, roadmap numbering, fixture structure, and the reference month's expected balances. It is a check of the plan's accounting examples; it is not a production ledger or a substitute for the future application tests.

## Our build cycle

1. Pick the single next step and its acceptance criteria.
2. Implement that step and test its promised behavior and relevant failure cases.
3. Demonstrate the result with fictional data.
4. Update the plan and next-step prompt, commit, and push to GitHub.
5. Verify the remote commit and CI result, report the evidence, and stop until you request the next step.

Next prompt:

> Build Step 02: exact money handling and the service-business chart of accounts. Follow Plan/NEXT_STEP.md, test valid and invalid inputs, demonstrate the result, then commit and push to GitHub. Stop after this step.

The original PDF files and extracted text stay local. Bibliographic details and fingerprints are in [sources](Plan/references/sources.json).
