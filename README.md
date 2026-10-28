# Accounting Harness

An accounting agent harness for bookkeeping at a small service business, built one verifiable step at a time.

The intended workflow is: **evidence → proposed journal entry → validation → human approval → posting → reconciliation → reporting**. Accounting code owns calculations and ledger changes. The agent helps interpret evidence and propose work.

**Current state:** Steps 01–11 are complete. The project has exact USD Money values, a validated entity-scoped chart of accounts, pure journal-entry validation with structured findings, an in-memory ledger with reproducible trial balances, atomic SQLite persistence with safe retries, linked full reversals that preserve original entries, immutable receipt registration, versioned drafts, local human approval with atomic posting, and five typed agent tools with 24 offline contract cases, and a durable bounded fake-provider run loop. Step 12 adds a bounded OpenAI expense adapter and 20 offline proposal cases; its live evaluation is deferred by request. Step 12a adds the persistent localhost UI and Ollama/offline adapters. Step 13a adds audited enrollment for new fictional receipts. Step 13b adds typed cash/recognition facts and reviewed cash expense and earned-service templates. Step 14a adds vendor bill recognition and AP reconciliation. Step 14b adds reviewed partial settlement with atomic payment allocation. Step 15a adds separately evidenced customer invoices and AR reconciliation. Step 15b adds partial collection and captured customer aging. Step 16a adds customer advances as reconciled unearned liabilities. Step 16b adds separately supported earning with unchanged cash and captured earning history. Step 16c hardens payable final approval/allocation checks and atomic upgrades. Step 17 adds immutable synthetic bank CSV import without ledger movement. Step 18 adds deterministic human-confirmed matching, unresolved ambiguity and audited unmatch. Step 19a adds immutable audited activation of the fixed bank-fee expense account. Step 19b adds imported bank-fee evidence, exact human-reviewed posting and separate matching. Step 19c adds captured bank-to-book reconciliation, reviewed timing differences and immutable completion history. Step 20a adds evidenced monthly prepaid insurance consumption with unchanged cash and captured remaining assets. Step 20b adds separately evidenced unbilled expense accruals with exact human review and a reconciled liability. Step 20c adds supported unbilled service revenue, a reconciled accrued asset and versioned combined accrual reports. Step 20d assembles and verifies the adjusted operational reference month. Step 21 adds captured income, owner’s equity and balance-sheet reports with exact account and journal drilldowns. Step 22 adds separately confirmed period close and durable January date locks while preserving captured pre-close statements. Step 23a adds captured direct cash flow, approved payable trace and visible classification exceptions. Step 23b adds deterministic JSON/CSV report packages with bounded offline verification. Step 24a adds immutable projects and versioned attribution that reconciles to recorded actuals. Step 24b adds exact service-time records with overlap checks and preserved void/replacement history. Step 25 adds immutable project cost scenarios with captured actuals/time, explicit rates and traceable modeled margins. Step 26 adds separate versioned operating assumptions and dated cash plans with deferred receipts/payments and visible funding gaps. Step 27 adds reproducible static/flexible/actual variance reports with exact favorable impacts, activity bridges and retained input downloads. Step 28 adds versioned single-service contribution/break-even scenarios and captured financial/operational indicators. Step 29a adds local credentials, opaque sessions, fixed entity roles and interactive administration. Step 29b enforces authenticated application/HTTP access, stable human actors, fixed entity roles and session-bound CSRF throughout the existing UI. Step 30 adds an offline contract simulation of one paginated QuickBooks JournalEntry read into a separate staging mirror; the local ledger stays authoritative and live sandbox connections remain deferred. Step 31a adds reviewed owner contribution, owner drawing and prepaid insurance purchase entries from typed cash and explicit classification facts. Step 31b adds bounded operational agent proposals over the delivered services. Step 31c organizes the authenticated workbench into task groups, with readable evidence-to-post trace, native keyboard review and role-aware handoffs. Step 32 adds separately authorized offline journal export, durable uncertain retry and exact simulated readback. Step 33a adds coherent group backup, verified relocation, preserved run identity and disabled restored transports. Step 33b adds authenticated redacted operational status without workflow effects. Step 34 adds the authenticated synthetic release rehearsal, setup runbook and completed adversarial review with fixes.

Step 35a adds durable offline evaluation budgets and a frozen semantic-case manifest; authenticated scoring and live verification remain pending. See [verification](Plan/09-integrations-and-pilot/STEP_35A_VERIFICATION.md).

Start with the [plan directory tree](Plan/README.md), [current status](Plan/STATUS.md), and [next step](Plan/NEXT_STEP.md). The [source map](Plan/SOURCE_MAP.md) connects the plan to the supplied textbooks, reviewed in order: Volume 1, then Volume 2.

## Open the localhost workspace

The [synthetic operator runbook](Plan/09-integrations-and-pilot/LOCAL_SYNTHETIC_RUNBOOK.md) collects setup, provider configuration, recovery, status and acceptance commands.

Python 3.12+ is enough; no packages are required. Set up accounts locally before
starting the server. Passphrases are entered in a hidden terminal prompt, never
as command-line arguments. Each grant prompts for `GRANT` confirmation.

```sh
# For a NEW fictional workspace only:
python3 -m accounting_harness access-provision --access-db .local/access.sqlite3 --workspace .local/workspace --entity demo-service-001 --reason "Local synthetic setup"

# If .local/workspace already exists, use THIS instead of access-provision.
# Use the existing immutable entity ID (the original fixture is demo-service-001).
python3 -m accounting_harness access-map-entity --access-db .local/access.sqlite3 --workspace .local/workspace --entity demo-service-001 --reason "Preserve existing workspace"

python3 -m accounting_harness access-create-user --access-db .local/access.sqlite3 --username preparer --reason "Local preparer"
python3 -m accounting_harness access-create-user --access-db .local/access.sqlite3 --username reviewer --reason "Local reviewer"
python3 -m accounting_harness access-grant --access-db .local/access.sqlite3 --username preparer --entity demo-service-001 --role preparer --retry-key preparer-initial --reason "Prepare fictional books"
python3 -m accounting_harness access-grant --access-db .local/access.sqlite3 --username reviewer --entity demo-service-001 --role reviewer --retry-key reviewer-initial --reason "Review fictional books"
python3 -m accounting_harness serve --access-db .local/access.sqlite3
```

Open **http://127.0.0.1:8765** and sign in. A preparer registers evidence and
prepares proposals; a reviewer inspects and approves/posts the exact revision.
Use **Sign out** to change users. The entity selector lists only current grants.
There is no default account, automatic owner login or public registration.
An explicitly granted `owner` combines these roles and can activate fixed AP,
AR, advance, accrued expense/revenue and bank-fee accounts through the sidebar.
Preparers need owner activation before first use of those controls. Owner is a
single-person option, not mandatory independent segregation of duties.

Records remain at their registered paths; the existing workspace is not renamed
or copied. Stop with Ctrl-C. Restart the same command to reuse durable identities,
ledger and runs. Entity selection and CSRF are renewed after restart. Keep the
identity database outside the financial workspace and all `.local/` files out of
GitHub. Account reset, disable and grant/revoke commands are listed by `--help`.

Offline demo mode uses fixed fixture responses; it is not a model. Provider
choices are shown but disabled by default. No health check, model download or
provider request runs on startup. Real API connection/evaluation is deferred at
your request. The [localhost and wider roadmap](Plan/LOCALHOST_APP_PLAN.md) records
remaining work. The current request authorizes the [remaining offline campaign](Plan/AUTONOMOUS_DELIVERY.md).

When you later choose to connect a provider:

```sh
# Ollama must already be running locally with your chosen model installed.
python3 -m accounting_harness serve --access-db .local/access.sqlite3 --enable-providers --ollama-model YOUR_LOCAL_MODEL

# OpenAI: set OPENAI_API_KEY privately in the launching environment first.
python3 -m accounting_harness serve --access-db .local/access.sqlite3 --enable-providers
```

Choose the provider and press **Prepare proposal** in the UI. Ollama targets only
`127.0.0.1:11434`; API support initially uses the existing pinned OpenAI model.
Each click allows one bounded request without network retries. OpenAI requests
are billable and reserve at most $0.007372800 per request under the existing
adapter's configured rates; verify current rates before use. Credentials stay
in the server environment. Neither provider has been connected/evaluated live by
this work. Local model usage records zero provider billing, excluding your own
hardware/energy costs. Unknown completion after interruption requires review.

The server binds only to loopback and checks Host, Origin, cookie authentication,
entity scope and session-bound CSRF. Cookies are host-only, HttpOnly,
SameSite=Strict and Path=/; local HTTP supplies no TLS or Secure-cookie guarantee.
Remote/TLS hosting remains unavailable. Sessions expire after 30 minutes without
application activity or eight hours total; background status polling does not
extend idle life. Revocation/expiry clears the UI on the next request or status
poll (normally within 15 seconds).

`--workspace PATH` optionally verifies an already registered path; it cannot
select an arbitrary directory. `--port PORT` changes the loopback port. Preserve
all workspace files together; use the [verified recovery workflow](Plan/09-integrations-and-pilot/RECOVERY_RUNBOOK.md) to relocate.
The authenticated public boundary is `AuthenticatedWorkspace.call(token,
entity_id, method, *args)`. `Workspace`, store APIs, fixture demos and `review-post`
are trusted local administrative primitives available to the OS file owner.
See [route and side-effect inventory](Plan/09-integrations-and-pilot/STEP_29B_INVENTORY.md).

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
python3 -m accounting_harness demo-adjusted-month
python3 -m accounting_harness demo-statements
python3 -m accounting_harness demo-close
python3 -m accounting_harness demo-cash-flow
python3 -m accounting_harness demo-report-export
python3 -m accounting_harness demo-project-dimensions
python3 -m accounting_harness demo-project-time
python3 -m accounting_harness demo-project-cost
python3 -m accounting_harness demo-budget
python3 -m accounting_harness demo-variance
python3 -m accounting_harness demo-indicators
python3 -m accounting_harness demo-access
python3 -m accounting_harness demo-authenticated-workspace
python3 -m accounting_harness demo-sandbox-read
python3 -m accounting_harness demo-owner-prepaid-cash
python3 -m accounting_harness demo-operational-agent
python3 -m accounting_harness demo-workbench
python3 -m accounting_harness demo-sandbox-export
python3 -m accounting_harness demo-recovery
python3 -m accounting_harness demo-operations-status
python3 -m accounting_harness demo-acceptance
python3 -m accounting_harness demo-evaluation-budget
```

The adjusted-month demonstration uses a distinct January 1 insurance-purchase variant; the original January 3 fixture stays unchanged. It labels trusted owner/purchase fixture entries separately from the eight reviewed operations.

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

The full suite also requires Node.js available as `node` for the native browser-control and exact-rendering regressions. No npm packages are needed.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
```

The foundation check validates plan links, roadmap numbering, and the reference month's accounting identities. The application suite has 931 tests covering money, catalog construction/loading, journal validation, ledger admission/snapshots/trial balances, SQLite restart/rollback/concurrency/constraints/retries, linked reversals/migration/correction rollback, source identity/digest/rollback/concurrency/schema safety, CLI behavior, and the test runner's failure handling. CI runs both checks and all 49 demonstrations.

Money uses nonnegative integer cents. Parsing requires unsigned decimal strings with exactly two fractional digits; floats, booleans, unsupported currency, and silent rounding are rejected. Leading zeros are accepted and formatting normalizes them. Accounts and catalogs are immutable; catalog loading rejects malformed fields and duplicate codes/JSON keys. Inactive accounts remain visible when listed but cannot be resolved for posting use. Durable synthetic posting and authenticated reviewer approval are implemented. SQLite line cents must fit a positive signed 64-bit integer; larger line amounts are rejected before writes. Report totals use Python integers.

See [Step 02 verification and API examples](Plan/02-ledger-core/STEP_02_VERIFICATION.md), [Step 03 validation contract and verification](Plan/02-ledger-core/STEP_03_VERIFICATION.md), [Step 04 ledger API and verification](Plan/02-ledger-core/STEP_04_VERIFICATION.md), [Step 05 persistence/retry contract and verification](Plan/02-ledger-core/STEP_05_VERIFICATION.md), [Step 06 reversal/migration contract and verification](Plan/02-ledger-core/STEP_06_VERIFICATION.md), and [Step 07 source contract and verification](Plan/03-evidence-and-review/STEP_07_VERIFICATION.md).

## Delivery

The delivery target is this repository on GitHub with its verification workflow and the localhost workspace. Complete local access setup above, then run `python3 -m accounting_harness serve --access-db .local/access.sqlite3`; a hosted deployment is not configured.

## Our build cycle

1. Pick the single next step and its acceptance criteria.
2. Implement that step and test its promised behavior and relevant failure cases.
3. Demonstrate the result with fictional data.
4. Update the plan and next-step prompt, commit, and push to GitHub.
5. Verify the remote commit and CI result and record the evidence. Normally stop for the next request; the current campaign explicitly authorizes continuing through the remaining offline steps.

The [Step 34 synthetic acceptance](Plan/09-integrations-and-pilot/STEP_34_VERIFICATION.md) and [adversarial review/fixes](Plan/09-integrations-and-pilot/ADVERSARIAL_REVIEW.md) are delivered with exact-commit CI. The authorized numbered offline campaign is complete. Live gates remain deferred.

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

## Local identity setup

The identity core, interactive user/grant commands and authenticated HTTP/UI
boundary are implemented. Follow the login-first startup instructions above. See the [identity-core verification and exact
setup commands](Plan/09-integrations-and-pilot/STEP_29A_VERIFICATION.md). Passwords
are entered through hidden terminal prompts, and new users have no implicit grants.
