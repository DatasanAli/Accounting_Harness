# Accounting Harness

An accounting agent harness for bookkeeping at a small service business, built one verifiable step at a time.

The intended workflow is: **evidence → proposed journal entry → validation → human approval → posting → reconciliation → reporting**. Accounting code owns calculations and ledger changes. The agent helps interpret evidence and propose work.

**Current state:** Steps 01–11 are complete. The project has exact USD Money values, a validated entity-scoped chart of accounts, pure journal-entry validation with structured findings, an in-memory ledger with reproducible trial balances, atomic SQLite persistence with safe retries, linked full reversals that preserve original entries, immutable receipt registration, versioned drafts, local human approval with atomic posting, and five typed agent tools with 24 offline contract cases, and a durable bounded fake-provider run loop. Step 12 adds a bounded OpenAI expense adapter and 20 offline proposal cases; its live evaluation is deferred by request. Step 12a adds the persistent localhost UI and Ollama/offline adapters. Step 13a adds audited enrollment for new fictional receipts. Step 13b adds typed cash/recognition facts and reviewed cash expense and earned-service templates. Step 14a adds vendor bill recognition and AP reconciliation. Step 14b adds reviewed partial settlement with atomic payment allocation. Step 15a adds separately evidenced customer invoices and AR reconciliation. Step 15b adds partial collection and captured customer aging. Step 16a adds customer advances as reconciled unearned liabilities. Step 16b adds separately supported earning with unchanged cash and captured earning history. Step 16c hardens payable final approval/allocation checks and atomic upgrades. Step 17 adds immutable synthetic bank CSV import without ledger movement. Step 18 adds deterministic human-confirmed matching, unresolved ambiguity and audited unmatch. Step 19a adds immutable audited activation of the fixed bank-fee expense account. Step 19b adds imported bank-fee evidence, exact human-reviewed posting and separate matching. Step 19c adds captured bank-to-book reconciliation, reviewed timing differences and immutable completion history. Step 20a adds evidenced monthly prepaid insurance consumption with unchanged cash and captured remaining assets. Step 20b adds separately evidenced unbilled expense accruals with exact human review and a reconciled liability. Step 20c adds supported unbilled service revenue, a reconciled accrued asset and versioned combined accrual reports. Authenticated roles remain a future step.

Start with the [plan directory tree](Plan/README.md), [current status](Plan/STATUS.md), and [next step](Plan/NEXT_STEP.md). The [source map](Plan/SOURCE_MAP.md) connects the plan to the supplied textbooks, reviewed in order: Volume 1, then Volume 2.

## Open the localhost workspace

```sh
python3 -m accounting_harness serve
```

Open **http://127.0.0.1:8765**. Python 3.12+ is enough; there are no packages to
install. Records persist in ignored `.local/workspace/`. The initial workspace
contains five fictional January 2026 receipts. The Evidence screen also registers
new structured fictional receipts with stable IDs and audited ledger enrollment. Select a receipt, run the offline
proposal, inspect the review, then explicitly approve/post or reject it. The
ledger and run history survive restart. Stop the server with Ctrl-C.

Offline demo mode uses fixed fixture responses; it is not a model. Provider
choices are shown but disabled by default. No health check, model download or
provider request runs on startup. Real API connection/evaluation is deferred at
your request. The [localhost and wider roadmap](Plan/LOCALHOST_APP_PLAN.md) records
remaining work and the expanded authorization to continue through it.

When you later choose to connect a provider:

```sh
# Ollama must already be running locally with your chosen model installed.
python3 -m accounting_harness serve --enable-providers --ollama-model YOUR_LOCAL_MODEL

# OpenAI: set OPENAI_API_KEY privately in the launching environment first.
python3 -m accounting_harness serve --enable-providers
```

Choose the provider and press **Prepare proposal** in the UI. Ollama targets only
`127.0.0.1:11434`; API support initially uses the existing pinned OpenAI model.
Each click allows one bounded request without network retries. OpenAI requests
are billable and reserve at most $0.007372800 per request under the existing
adapter's configured rates; verify current rates before use. Credentials stay
in the server environment. Neither provider has been connected/evaluated live by
this work. Local model usage records zero provider billing, excluding your own
hardware/energy costs. Unknown completion after interruption requires review.

The server binds only to loopback and checks Host, Origin and a browser CSRF
token. It is a single-operator fictional prototype; the operator label is not
multi-user authentication. Structured fictional receipt entry and paired cash/recognition evidence are available. File extraction and wider workflows are subsequent roadmap deliveries. `--workspace PATH` selects another local directory;
`--port PORT` changes the loopback port. Preserve ledger, sources and runs together.

## Run the demonstration

From the repository root, use Python 3.12 or newer with SQLite 3.37 or newer. No package installation, API keys, PDFs, or network access are required.

```sh
python3 -m accounting_harness demo-accounts
python3 -m accounting_harness demo-journal
python3 -m accounting_harness demo-ledger
python3 -m accounting_harness demo-persistence
python3 -m accounting_harness demo-reversal
python3 -m accounting_harness demo-source
python3 -m accounting_harness demo-review
python3 -m accounting_harness demo-approval
python3 -m accounting_harness demo-tools
python3 -m accounting_harness demo-run
python3 -m accounting_harness demo-provider
python3 -m accounting_harness demo-web
python3 -m accounting_harness demo-enrollment
python3 -m accounting_harness demo-cash
python3 -m accounting_harness demo-bill
python3 -m accounting_harness demo-bill-payment
python3 -m accounting_harness demo-invoice
python3 -m accounting_harness demo-collection
python3 -m accounting_harness demo-advance
python3 -m accounting_harness demo-advance-earning
python3 -m accounting_harness demo-bank-import
python3 -m accounting_harness demo-bank-match
python3 -m accounting_harness demo-bank-fee-account
python3 -m accounting_harness demo-bank-fee
python3 -m accounting_harness demo-reconciliation
python3 -m accounting_harness demo-prepaid-consumption
python3 -m accounting_harness demo-expense-accrual
python3 -m accounting_harness demo-revenue-accrual
```

The bank import demonstration uses the [documented fictional CSV format](data/fixtures/README.md#fictional-bank-statement). Bank imports retain statement records separately from ledger postings.

The account demo prints 13 fictional accounts, including credit-normal accumulated depreciation and debit-normal owner drawings. It demonstrates `0.10 + 0.20 = 0.30 USD (30 cents)` and rejects the unsupported precision in `1.005`.

The journal demo accepts a balanced $1,000 contribution and rejects a $999 credit against a $1,000 debit, reporting the exact $1 difference. Validation checks metadata, calendar dates, known source IDs, active accounts and positive amounts. It does not establish correct classification or approval.

The ledger demo applies ordinary reference entries T01–T09 and prints all 13 unadjusted account balances through 2026-01-31: **13300.00 USD** in each column and **9400.00 USD** Cash. Reports retain an immutable ledger snapshot, cutoff and zero-opening policy. Ledger admission revalidates entries and rejects duplicates or out-of-period dates without changing existing records. This is a synthetic, single-threaded local demonstration; data is lost when the process exits.

The persistence demo writes T01–T09 to a temporary synthetic SQLite database, closes and reopens it, then retries every entry. All three stages retain 9 journals, 18 lines, 9 posting events and 9 retry records, with the same balances and original operator/timestamps. The temporary database is removed afterward. The persistence API preserves caller-selected database files across restarts.

The reversal demo cancels a fictional 125.00 USD expense using a linked journal. It shows exact opposite lines, a zero net effect on the reversal date, an unchanged earlier report snapshot, and preserved original receipts after reopen/retry. Storage schema v2 migrates matching v1 files atomically; back up caller-owned files before opening them with the new version.

The source demo registers a fictional receipt in a separate temporary SQLite registry, reopens it, and recognizes the repeat import without changing the original evidence or audit receipt. A separate identity with identical content stays distinct; changed content under the original identity is rejected. Registration does not change the ledger’s frozen source context or authorize posting. Only structured synthetic receipts are supported in this step.

The review demo edits a fictional rent proposal, reopens both immutable revisions, shows unresolved amount findings and a rejected queue item, and verifies zero posted journals. See the [Step 08 contract and verification](Plan/03-evidence-and-review/STEP_08_VERIFICATION.md).

The approval demo binds a simulated local human decision, posts once, reopens/retries and traces the journal to the receipt and all revisions/decisions. For existing synthetic databases, `python3 -m accounting_harness review-post --ledger PATH --registry PATH --draft ID --actor ID` displays the proposal and requires `approve DIGEST`; EOF or other text cancels. The ledger must already contain the receipt identity in its frozen source context. Local actor labels are not authentication. See [Step 09 verification](Plan/03-evidence-and-review/STEP_09_VERIFICATION.md).

The tools demo runs a scripted rent sequence and **24 labeled offline cases** across clean, malformed, missing, conflicting, ambiguous, duplicate, unsupported and hostile inputs. Every saved proposal waits for human review; all ledger snapshots stay unchanged. This checks tool contracts, not model accuracy. See [Step 10 contract and verification](Plan/04-agent-harness/STEP_10_VERIFICATION.md).

The run demo persists a fake-provider task with integer time/cost/call/retry limits, pauses for review, closes and reopens all storage, and acknowledges the handoff with one unchanged draft and zero posted journals. Runs recover committed draft receipts after interruption, preserve budgets, and support cancellation. The local run execution lock currently supports macOS/Linux; no network calls or real model costs occur. See the [Step 11 contract](Plan/04-agent-harness/STEP_11_PLAN.md) and [verification](Plan/04-agent-harness/STEP_11_VERIFICATION.md).

## Verify the implementation

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
```

The foundation check validates plan links, roadmap numbering, and the reference month's accounting identities. The application suite has 546 tests covering money, catalog construction/loading, journal validation, ledger admission/snapshots/trial balances, SQLite restart/rollback/concurrency/constraints/retries, linked reversals/migration/correction rollback, source identity/digest/rollback/concurrency/schema safety, CLI behavior, and the test runner's failure handling. CI runs both checks and all twenty-eight demonstrations.

Money uses nonnegative integer cents. Parsing requires unsigned decimal strings with exactly two fractional digits; floats, booleans, unsupported currency, and silent rounding are rejected. Leading zeros are accepted and formatting normalizes them. Accounts and catalogs are immutable; catalog loading rejects malformed fields and duplicate codes/JSON keys. Inactive accounts remain visible when listed but cannot be resolved for posting use. Durable synthetic posting is implemented; authenticated approval is not. SQLite line cents must fit a positive signed 64-bit integer; larger line amounts are rejected before writes. Report totals use Python integers.

See [Step 02 verification and API examples](Plan/02-ledger-core/STEP_02_VERIFICATION.md), [Step 03 validation contract and verification](Plan/02-ledger-core/STEP_03_VERIFICATION.md), [Step 04 ledger API and verification](Plan/02-ledger-core/STEP_04_VERIFICATION.md), [Step 05 persistence/retry contract and verification](Plan/02-ledger-core/STEP_05_VERIFICATION.md), [Step 06 reversal/migration contract and verification](Plan/02-ledger-core/STEP_06_VERIFICATION.md), and [Step 07 source contract and verification](Plan/03-evidence-and-review/STEP_07_VERIFICATION.md).

## Delivery

The delivery target is this repository on GitHub with its verification workflow and the localhost workspace. Run `python3 -m accounting_harness serve` after cloning; a hosted deployment is not configured.

## Our build cycle

1. Pick the single next step and its acceptance criteria.
2. Implement that step and test its promised behavior and relevant failure cases.
3. Demonstrate the result with fictional data.
4. Update the plan and next-step prompt, commit, and push to GitHub.
5. Verify the remote commit and CI result and report the evidence. The expanded 2026-10-08 request authorizes continuing through the wider roadmap; otherwise stop until the next request.

Next prompt:

> Build Step20d: Assemble the supported adjusted operational month through the delivered services and explicit synthetic approvals, with the documented Jan1 insurance-purchase variant. Follow Plan/07-period-close/STEP_20D_PLAN.md. Verify all11 journals,13,300.00 trial-balance totals and zero subsidiary residuals, retain a stable source/approval/journal map, and test interruption/restart/exact retries without bypassing any managed controls. Verify, review, commit/push/exact CI, then continue Step21 statements. Keep live connections deferred.

The original PDF files and extracted text stay local. Bibliographic details and fingerprints are in [sources](Plan/references/sources.json).

## Provider evaluation

`demo-provider` exercises the real adapter/parser/runtime with handwritten
synthetic response envelopes: eight exact proposals, twelve abstentions, and a
separate simulated human approval followed by one rent posting and safe retry.
These are contract results, not model accuracy. All demonstrations remain offline.

The supported provider workflow is paid, incurred rent (5000) or consumed
software services (5100), with Cash (1000). The model cannot approve or post.
Ambiguous completion after a crash stops for review without repeating the API
request. Duplicate-source prevention is checked atomically when saving the draft.

For an explicit billable synthetic evaluation, configure `OPENAI_API_KEY` in the
local process environment (never commit it), then run:

```sh
python3 -m accounting_harness eval-provider --live
```

This pins `gpt-4.1-mini-2025-04-14` / `expense-v1`, permits at most 24 requests,
300 seconds and $0.25 reserved cost, and emits sanitized JSON with per-category
results, token usage, usage-derived cost, latency, failures and four repeat
comparisons. Individual requests have a 10-second deadline and no automatic
network retries. Returned usage is an estimate at documented uncached rates,
not an invoice; uncertain attempts retain the full reservation. No key means
a nonzero exit with no calls. `eval-provider` without `--live` is offline.
Keep any local report in ignored `.local/`; raw provider traces are not recorded.
See the [Step 12 contract](Plan/04-agent-harness/STEP_12_PLAN.md) and
[verification](Plan/04-agent-harness/STEP_12_VERIFICATION.md).

`demo-enrollment` proves that registering new evidence preserves old journal
snapshots, posting retry receipts and approval bindings. Existing ledgers migrate
additively to schema v3; preserve all workspace files together before migration.
If registration succeeds but enrollment fails, the receipt stays visible as
pending and exact resubmission or startup repair completes it. New typed receipts
are not supported by offline fixture playback. See the [Step 13a verification](Plan/05-service-bookkeeping/STEP_13A_VERIFICATION.md).

`demo-cash` registers separate typed cash and recognition facts for rent 1200.00
and earned service revenue 800.00, prepares drafts, and demonstrates simulated
human approval. Its isolated zero-opening ledger ends with Cash credit 400.00,
Rent debit 1200.00 and Revenue credit 800.00. The negative cash is intentional in
this isolated example. In the UI use **Register cash and recognition facts**,
then **Prepare a reviewed cash proposal**. Amount, accounts and date come from
matching facts; approval remains a separate action. Owner contributions,
transfers, advances and settlement cash cannot use these recognition templates.
Event claims remain reserved after rejection; correcting an existing cash draft
is not yet offered by the UI. Provider receipt proposals retain their existing
policy and scope. See the [Step 13b contract](Plan/05-service-bookkeeping/STEP_13B_PLAN.md).

`demo-bill` recognizes a 300.00 software bill only after matching separate
incurrence evidence and human approval. The **Vendor bills** screen shows
principal, due date, outstanding and reconciliation to Accounts Payable. New AP
postings require the matching approved bill record once the payable workflow is
activated; unexplained opening AP blocks activation. Registration or preparation
does not post. The existing `review-post` CLI remains receipt-only; review bills and cash drafts
in the localhost UI or direct services. Recorded partial payments use separately registered cash evidence and exact bill-bound approval; managed bill/payment reversals are
currently refused because they require linked subledger corrections. See the
[Step 14a verification](Plan/05-service-bookkeeping/STEP_14A_VERIFICATION.md).

Step 14b records one whole outgoing settlement movement against one posted bill.
A 300.00 bill paid by 100.00 leaves 200.00 payable and expense unchanged.
Approval does not reserve unpaid balance; posting refuses an overpayment.
No money is transmitted. See the [payment verification](Plan/05-service-bookkeeping/STEP_14B_VERIFICATION.md).

Customer invoices use paired invoice and completion evidence. Recognition posts
Accounts Receivable debit and Service Revenue credit after exact human review;
customer balances reconcile to AR. Recorded whole cash movements can settle part of an invoice without recognizing revenue again. Aging shows the outstanding amount by due date at the captured cutoff. See
[invoice verification](Plan/05-service-bookkeeping/STEP_15A_VERIFICATION.md).

Collection checks include posting-time remaining balance and shared cash-event
protection. A 2500.00 invoice collected by 1500.00 leaves 1000.00 due, with
revenue unchanged. See [collection verification](Plan/05-service-bookkeeping/STEP_15B_VERIFICATION.md).

Customer advances pair prepayment-obligation evidence with recorded incoming cash.
A reviewed 600.00 advance increases Cash and Unearned Revenue by 600.00 and leaves
service revenue zero. See [advance verification](Plan/05-service-bookkeeping/STEP_16A_VERIFICATION.md).
