# Accounting Harness

An accounting agent harness for bookkeeping at a small service business, built one verifiable step at a time.

The intended workflow is: **evidence → proposed journal entry → validation → human approval → posting → reconciliation → reporting**. Accounting code owns calculations and ledger changes. The agent helps interpret evidence and propose work.

**Current state:** Steps 01–07 are complete. The project has exact USD Money values, a validated entity-scoped chart of accounts, pure journal-entry validation with structured findings, an in-memory ledger with reproducible trial balances, atomic SQLite persistence with safe retries, linked full reversals that preserve original entries, and immutable registration of structured fictional receipts. Authenticated approval and the agent runtime are future steps.

Start with the [plan directory tree](Plan/README.md), [current status](Plan/STATUS.md), and [next step](Plan/NEXT_STEP.md). The [source map](Plan/SOURCE_MAP.md) connects the plan to the supplied textbooks, reviewed in order: Volume 1, then Volume 2.

## Run the demonstration

From the repository root, use Python 3.12 or newer with SQLite 3.37 or newer. No package installation, API keys, PDFs, or network access are required.

```sh
python3 -m accounting_harness demo-accounts
python3 -m accounting_harness demo-journal
python3 -m accounting_harness demo-ledger
python3 -m accounting_harness demo-persistence
python3 -m accounting_harness demo-reversal
python3 -m accounting_harness demo-source
```

The account demo prints 13 fictional accounts, including credit-normal accumulated depreciation and debit-normal owner drawings. It demonstrates `0.10 + 0.20 = 0.30 USD (30 cents)` and rejects the unsupported precision in `1.005`.

The journal demo accepts a balanced $1,000 contribution and rejects a $999 credit against a $1,000 debit, reporting the exact $1 difference. Validation checks metadata, calendar dates, known source IDs, active accounts and positive amounts. It does not establish correct classification or approval.

The ledger demo applies ordinary reference entries T01–T09 and prints all 13 unadjusted account balances through 2026-01-31: **13300.00 USD** in each column and **9400.00 USD** Cash. Reports retain an immutable ledger snapshot, cutoff and zero-opening policy. Ledger admission revalidates entries and rejects duplicates or out-of-period dates without changing existing records. This is a synthetic, single-threaded local demonstration; data is lost when the process exits.

The persistence demo writes T01–T09 to a temporary synthetic SQLite database, closes and reopens it, then retries every entry. All three stages retain 9 journals, 18 lines, 9 posting events and 9 retry records, with the same balances and original operator/timestamps. The temporary database is removed afterward. The persistence API preserves caller-selected database files across restarts.

The reversal demo cancels a fictional 125.00 USD expense using a linked journal. It shows exact opposite lines, a zero net effect on the reversal date, an unchanged earlier report snapshot, and preserved original receipts after reopen/retry. Storage schema v2 migrates matching v1 files atomically; back up caller-owned files before opening them with the new version.

The source demo registers a fictional receipt in a separate temporary SQLite registry, reopens it, and recognizes the repeat import without changing the original evidence or audit receipt. A separate identity with identical content stays distinct; changed content under the original identity is rejected. Registration does not change the ledger’s frozen source context or authorize posting. Only structured synthetic receipts are supported in this step.

## Verify the implementation

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
```

The foundation check validates plan links, roadmap numbering, and the reference month's accounting identities. The application suite has 128 tests covering money, catalog construction/loading, journal validation, ledger admission/snapshots/trial balances, SQLite restart/rollback/concurrency/constraints/retries, linked reversals/migration/correction rollback, source identity/digest/rollback/concurrency/schema safety, CLI behavior, and the test runner's failure handling. CI runs both checks and all six demonstrations.

Money uses nonnegative integer cents. Parsing requires unsigned decimal strings with exactly two fractional digits; floats, booleans, unsupported currency, and silent rounding are rejected. Leading zeros are accepted and formatting normalizes them. Accounts and catalogs are immutable; catalog loading rejects malformed fields and duplicate codes/JSON keys. Inactive accounts remain visible when listed but cannot be resolved for posting use. Durable synthetic posting is implemented; authenticated approval is not. SQLite line cents must fit a positive signed 64-bit integer; larger line amounts are rejected before writes. Report totals use Python integers.

See [Step 02 verification and API examples](Plan/02-ledger-core/STEP_02_VERIFICATION.md), [Step 03 validation contract and verification](Plan/02-ledger-core/STEP_03_VERIFICATION.md), [Step 04 ledger API and verification](Plan/02-ledger-core/STEP_04_VERIFICATION.md), [Step 05 persistence/retry contract and verification](Plan/02-ledger-core/STEP_05_VERIFICATION.md), [Step 06 reversal/migration contract and verification](Plan/02-ledger-core/STEP_06_VERIFICATION.md), and [Step 07 source contract and verification](Plan/03-evidence-and-review/STEP_07_VERIFICATION.md).

## Delivery

The current delivery target is this repository on GitHub with its verification workflow. Run the CLI locally after cloning; a hosted service and deployment platform are not configured at this stage.

## Our build cycle

1. Pick the single next step and its acceptance criteria.
2. Implement that step and test its promised behavior and relevant failure cases.
3. Demonstrate the result with fictional data.
4. Update the plan and next-step prompt, commit, and push to GitHub.
5. Verify the remote commit and CI result, report the evidence, and stop until you request the next step.

Next prompt:

> Build Step 08: versioned drafts and review queue. Follow Plan/NEXT_STEP.md, create immutable draft revisions from registered evidence with validation findings and pending/rejected states, demonstrate an edited proposal and its history, then commit and push to GitHub. Stop after this step.

The original PDF files and extracted text stay local. Bibliographic details and fingerprints are in [sources](Plan/references/sources.json).
