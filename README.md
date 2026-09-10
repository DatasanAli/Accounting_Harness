# Accounting Harness

An accounting agent harness for bookkeeping at a small service business, built one verifiable step at a time.

The intended workflow is: **evidence → proposed journal entry → validation → human approval → posting → reconciliation → reporting**. Accounting code owns calculations and ledger changes. The agent helps interpret evidence and propose work.

**Current state:** Steps 01–02 are complete. The project has exact USD Money values, a validated entity-scoped chart of accounts, and a local CLI demonstration. Journal validation, ledger posting, persistence, and the agent runtime are future steps.

Start with the [plan directory tree](Plan/README.md), [current status](Plan/STATUS.md), and [next step](Plan/NEXT_STEP.md). The [source map](Plan/SOURCE_MAP.md) connects the plan to the supplied textbooks, reviewed in order: Volume 1, then Volume 2.

## Run the demonstration

From the repository root, use Python 3.12 or newer. No package installation, API keys, PDFs, or network access are required.

```sh
python3 -m accounting_harness demo-accounts
```

The command prints 13 fictional accounts, including credit-normal accumulated depreciation and debit-normal owner drawings. It demonstrates `0.10 + 0.20 = 0.30 USD (30 cents)` and rejects the unsupported precision in `1.005`.

## Verify the implementation

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
```

The foundation check validates plan links, roadmap numbering, and the reference month's accounting identities. The application suite has 30 tests covering money, catalog construction/loading, CLI behavior, and the test runner's failure handling. CI runs both checks and the demonstration.

Money uses nonnegative integer cents. Parsing requires unsigned decimal strings with exactly two fractional digits; floats, booleans, unsupported currency, and silent rounding are rejected. Leading zeros are accepted and formatting normalizes them. Accounts and catalogs are immutable; catalog loading rejects malformed fields and duplicate codes/JSON keys. Inactive accounts remain visible when listed but cannot be resolved for posting use. No posting is implemented yet.

See [Step 02 verification and API examples](Plan/02-ledger-core/STEP_02_VERIFICATION.md).

## Our build cycle

1. Pick the single next step and its acceptance criteria.
2. Implement that step and test its promised behavior and relevant failure cases.
3. Demonstrate the result with fictional data.
4. Update the plan and next-step prompt, commit, and push to GitHub.
5. Verify the remote commit and CI result, report the evidence, and stop until you request the next step.

Next prompt:

> Build Step 03: journal-entry validation. Follow Plan/NEXT_STEP.md, accept balanced entries and reject invalid ones, test and demonstrate the result, then commit and push to GitHub. Stop after this step.

The original PDF files and extracted text stay local. Bibliographic details and fingerprints are in [sources](Plan/references/sources.json).
