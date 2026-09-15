# Accounting Harness

An accounting agent harness for bookkeeping at a small service business, built one verifiable step at a time.

The intended workflow is: **evidence → proposed journal entry → validation → human approval → posting → reconciliation → reporting**. Accounting code owns calculations and ledger changes. The agent helps interpret evidence and propose work.

**Current state:** Steps 01–03 are complete. The project has exact USD Money values, a validated entity-scoped chart of accounts, and pure journal-entry validation with structured findings. Ledger posting, persistence, and the agent runtime are future steps.

Start with the [plan directory tree](Plan/README.md), [current status](Plan/STATUS.md), and [next step](Plan/NEXT_STEP.md). The [source map](Plan/SOURCE_MAP.md) connects the plan to the supplied textbooks, reviewed in order: Volume 1, then Volume 2.

## Run the demonstration

From the repository root, use Python 3.12 or newer. No package installation, API keys, PDFs, or network access are required.

```sh
python3 -m accounting_harness demo-accounts
python3 -m accounting_harness demo-journal
```

The command prints 13 fictional accounts, including credit-normal accumulated depreciation and debit-normal owner drawings. It demonstrates `0.10 + 0.20 = 0.30 USD (30 cents)` and rejects the unsupported precision in `1.005`.

The journal demo accepts a balanced $1,000 contribution and rejects a $999 credit against a $1,000 debit, reporting the exact $1 difference. Validation checks metadata, calendar dates, known source IDs, active accounts and positive amounts. It does not establish correct classification or approval.

## Verify the implementation

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
```

The foundation check validates plan links, roadmap numbering, and the reference month's accounting identities. The application suite has 50 tests covering money, catalog construction/loading, journal validation, CLI behavior, and the test runner's failure handling. CI runs both checks and both demonstrations.

Money uses nonnegative integer cents. Parsing requires unsigned decimal strings with exactly two fractional digits; floats, booleans, unsupported currency, and silent rounding are rejected. Leading zeros are accepted and formatting normalizes them. Accounts and catalogs are immutable; catalog loading rejects malformed fields and duplicate codes/JSON keys. Inactive accounts remain visible when listed but cannot be resolved for posting use. No posting is implemented yet.

See [Step 02 verification and API examples](Plan/02-ledger-core/STEP_02_VERIFICATION.md) and [Step 03 validation contract and verification](Plan/02-ledger-core/STEP_03_VERIFICATION.md).

## Our build cycle

1. Pick the single next step and its acceptance criteria.
2. Implement that step and test its promised behavior and relevant failure cases.
3. Demonstrate the result with fictional data.
4. Update the plan and next-step prompt, commit, and push to GitHub.
5. Verify the remote commit and CI result, report the evidence, and stop until you request the next step.

Next prompt:

> Build Step 04: ledger and trial balance. Follow Plan/NEXT_STEP.md, apply validated entries to an in-memory ledger and demonstrate the reference trial balance, test it, then commit and push to GitHub. Stop after this step.

The original PDF files and extracted text stay local. Bibliographic details and fingerprints are in [sources](Plan/references/sources.json).
