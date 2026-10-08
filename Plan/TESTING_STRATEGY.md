# Testing strategy

## Current verification

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
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
```

The foundation check validates documentation links, the ordered roadmap, and the arithmetic/structure of [the original reference month](../data/fixtures/service-business-month.json). It checks expected account balances, statement totals, cash movements, and closing results. These are fixture checks, separate from the application's tests.

Steps 02–20b have 528 application tests using Python's standard library. The suite exercises exact arithmetic, strict parsing/direct construction, full catalog contents, invalid metadata, immutable snapshots, entity-local lookups, inactive accounts, JSON validation, CLI output, and test-runner failure handling. The runner must fail on unexpected zero-test discovery and on a failing test; both behaviors have subprocess tests. Journal coverage includes balanced and compound entries, signed imbalance, exact large amounts, invalid line shapes and fields, source/account/date/currency checks, complete findings without partial totals, repeatability, and unchanged inputs. A balanced but misclassified contribution documents the semantic limit. Ledger tests compare every ordinary reference account against independently defined expected balances, check inclusive cutoffs, immutable historical snapshots, duplicate/invalid entry refusal without mutation, large integer cents, zero/credit asset balances, and explicit report scope. Persistence tests cover restart with every reference balance, canonical retries/conflicts, concurrent connections, lock exhaustion, injected rollback, integer storage limits, incompatible context/schema refusal and direct SQL immutability/constraints. See the [Step 05 verification record](02-ledger-core/STEP_05_VERIFICATION.md) for precise SQL versus application enforcement boundaries. Reversal tests cover exact cancellation, immutable originals and snapshots, inclusive date cutoffs, scoped retries, one reversal under concurrent requests, invalid context, SQL link constraints, injected rollback and migration from a synthetic Step 05 database. See the [Step 06 verification record](02-ledger-core/STEP_06_VERIFICATION.md). Source registration tests cover strict fictional receipt metadata, canonical digests, stable entity/document identity, unchanged audit receipts across retries/reopen, content conflicts, equal-content separate identities, concurrent imports, bounded lock failures, atomic initialization and event-write rollback, SQL immutability, schema/application rejection, and preservation of existing ledger snapshots and retry results. See the [Step 07 verification record](03-evidence-and-review/STEP_07_VERIFICATION.md). CI runs the same commands above. No external packages or model calls are needed.

## Test the outcome and the failure boundary

For each numbered step, supply a valid example, a meaningful invalid example, and an edge case affecting its behavior. Use predetermined accounting outcomes, not values computed by the function under test. A failing operation must leave posted balances and unrelated records unchanged; a recorded rejection event is allowed.

| Layer | Evidence required when that layer is introduced |
| --- | --- |
| Money/accounts | Exact cents; accepted/rejected formats; duplicate account IDs; normal balances and contra accounts |
| Journal/ledger | Balanced entry accepted; imbalance rejected; all expected per-account balances; date cutoff; empty ledger; wrong-account-but-balanced case identified by semantic fixtures |
| Persistence | Close/reopen database; injected mid-write failure; duplicate retry; changed-payload retry; concurrent attempts; constraints survive direct service calls |
| Evidence/review | Missing source; changed evidence; changed draft; stale/rejected approval; unsupported transition; posting without human approval |
| Operations | Invoice and bill lifecycle; partial settlement; duplicate document; overpayment policy; subledger totals equal control accounts |
| Reconciliation | Timing differences versus book adjustments; ambiguous matches; transfer handling; unexplained difference prevents completion |
| Close/reports | Independent expected statements; cutoff; accrual/deferral; owner drawings; locked period; repeated close; historical reports survive closing |
| Agent | Correct structured proposal; evidence trace; abstention; invalid tool call; document instruction attack; denied approval/post request; bounded retry/cost/time; restart without duplicate posting |
| Management | Actual/budget/scenario separation; allocation totals; denominator zero; relevant-range limits; favorable/unfavorable sign conventions |
| Integration/operations | Sandbox contract; pagination; rate limit; interrupted sync; external duplicates; scoped authorization; export round trip; restore and reconciliation |

## Growing accounting fixtures

Start with the reference month's owner contribution, rent, prepaid insurance, earned invoice, partial collection, supplier bill/payment, customer advance, owner withdrawal, and two adjustments. All amounts and company details are original fictional examples.

Step 04 uses its ordinary transactions for an unadjusted trial balance (13300.00 USD per column; Cash 9400.00 USD debit). At Step 20 add the two adjustments. At Step 21 check net income of $1,100.00, assets of $11,500.00, liabilities of $600.00, and ending equity of $10,900.00. At Step 22 check temporary accounts clear without losing historical performance reports. At Step 23 check the $9,400.00 closing cash balance and its operating/financing sources.

Add fixtures when a capability is introduced: bad-debt estimates, depreciation, reversals, prior balances, multiple periods, loss months, no activity, and contra accounts. Add property-based generation when handwritten cases stop covering ledger combinations; conserve total debits/credits and test reversal identities. Do not require a new test framework in advance.

## Agent evaluation gate

Before a live provider step is complete, freeze a versioned offline suite with at least 20 labeled cases covering clean evidence, ambiguity, missing facts, conflicting amounts, duplicate documents, out-of-scope requests, and hostile document instructions. The human-review action is an accepted outcome for ambiguous cases.

Release criteria for that suite: zero unauthorized postings; zero accepted unbalanced proposals; every successful proposal links real fixture evidence; every designated ambiguous/unsupported case routes to review; at least 90% exact expected proposals on the unambiguous supported cases. Report numerators and denominators by category. The threshold is a project gate, not a claim of general accuracy. Add every discovered regression as a new case.

CI runs the fake provider and deterministic cases on every relevant change. Run an explicitly bounded live-provider smoke/evaluation with synthetic data when adding or changing the provider/model/prompt. Record model, prompt version, sample size, latency, cost, failures, and nondeterminism. A live score cannot waive permission checks.

## Definition of done

The promised behavior works; relevant negative cases fail correctly; accounting totals match independent expectations; the demonstration is reproducible; docs describe the implemented scope; local checks pass; the reviewed commit is on GitHub; CI for that commit passes. A blocked remote upload or failed CI leaves delivery incomplete and must be reported.

Step 08 adds revision/restart, evidence conflicts, pending/rejected transitions, stale concurrent edits, retry/event rollback, schema initialization rollback and legacy ledger preservation checks.

Step 09 adds local confirmation, stale/rejected/changed-evidence/policy denial, atomic journal/link/retry failure rollback, concurrent posting, exact retry, immutable decisions, additive initialization rollback and complete decision history in audit traces.

Step 10 adds strict tool schemas/allowlist, runtime actor/entity binding, fabricated/conflicting evidence denial, inert hostile text, pending/rejected/posted review boundaries and 24 labeled deterministic offline cases. The evaluator checks independent proposed-account/amount labels, findings, retained history after denial and unchanged ledger snapshots. Deliberately wrong expected labels and empty corpus tests prove the evaluation can fail. No provider/model accuracy is measured.

Step 11 adds 34 run tests plus a CLI check: real child-process death after draft commit, durable intent/receipt recovery, fault-injected checkpoints, forced concurrent reservation interleaving, cancellation, changed scope/script identity, integer call/cost/time budgets and timeout/lock retry exhaustion across restart. The separate run schema rejects incompatible files and rolls back failed initialization; old ledger snapshots/retries remain unchanged. Simulated usage and local cooperative deadlines do not establish live-provider billing/timeout correctness.

Step 12 adds 24 tests for the OpenAI structured-decision adapter, proposal/review
routing, invalid/refused/incomplete output, request/response bounds, integer
usage/cost reservations, no network transaction, expiry during preparation,
cancellation and actual child-process termination, uncertain restart, atomic
duplicate-source guards and live-save receipt recovery. The 20-case provider
corpus is distinct from the 24 tool cases. Mutated labels/responses and empty
corpora prove the gate can fail. CI uses synthetic response envelopes, no API key
or network. `python3 -m accounting_harness eval-provider --live` is a separate
bounded delivery gate (24 calls, 300 seconds, $0.25 reservation); missing
credentials fail clearly and cannot be reported as a live pass.

Step 12a adds loopback HTTP tests over real SQLite services, offline and Ollama
adapter contracts, strict malformed-output handling, duplicate/uncertain-run
protection, exact human-confirmed posting/retry/restart and Host/Origin/CSRF/body
boundaries. Browser evidence is recorded separately. Live API/model evaluation
is explicitly deferred; it no longer blocks independent accounting/UI work.
Roadmap schema v2 permits an explicitly reasoned deferred gate behind the progress
cursor; deferred is never treated as verified completion.

Step 13a adds audited source enrollment, versioned migration/rollback, exact
historical context/approval/run/retry preservation, concurrent/open-connection
visibility, enrollment-anchor conflicts, and HTTP registration/retry/pending-gap
recovery. Typed source text remains data and registration never posts.

Step 13b adds typed cash/recognition schema, independent template validation,
semantic event claims, concurrent duplicate/rollback protection, prior receipt
approval compatibility, explicit saved-policy routing and localhost cash flow.
See the [Step 13b verification](05-service-bookkeeping/STEP_13B_VERIFICATION.md).

Step 14a adds intent-bound bill recognition, atomic review migration, zero-opening
AP activation, shared cash/bill event claims, mandatory approved subledger effects,
old-connection/direct-admission guards, effect/journal rollback, immutable report
snapshots, unsupported managed reversal refusal and exact large-amount browser
serialization. See the [Step 14a verification](05-service-bookkeeping/STEP_14A_VERIFICATION.md).

Step 14b covers atomic payment allocations, posting-time remaining-balance checks,
competing approvals, shared cash claims, concurrent exact retries, migration and
write-fault rollback, historical payment readability, cutoffs and exact browser
amount serialization. See [payment verification](05-service-bookkeeping/STEP_14B_VERIFICATION.md).

Step 15a checks invoice/completion identity, shared service recognition claims,
exact intent and human approval, AR activation/sealing, immutable atomic effects,
legacy migration/approval bytes, original customer-name capture, concurrent retry,
AP coexistence and exact HTTP/CLI/browser amounts. See [invoice verification](05-service-bookkeeping/STEP_15A_VERIFICATION.md).

Step 15b covers whole-receipt allocation, unchanged revenue, shared cash claims,
competing approvals and exact retries, current approval at final journal seal,
versioned migration/history preservation, write-fault rollback, due-date aging
boundaries, captured cutoff reports and exact localhost values. See [collection verification](05-service-bookkeeping/STEP_15B_VERIFICATION.md).

Step 16a covers paired advance facts, shared cash claims, zero-earned liability
recognition, mandatory 2100 effects and current approval at final sealing, atomic
review/approval/advance initialization, migration history, concurrent exact retries,
original-name capture and exact HTTP/browser values. See [advance verification](05-service-bookkeeping/STEP_16A_VERIFICATION.md).

Step 16b adds separately supported earning, shared service claims across policies,
competing approvals/remaining checks, current approval at final sealing, atomic
review/advance migrations, schema1 legacy report compatibility, frozen schema2
captures, write faults, concurrent retries, and exact large amounts. Its HTTP test
executes the route extracted from the shipped earning form. See [earning verification](05-service-bookkeeping/STEP_16B_VERIFICATION.md).

Step 16c adds real-guard payable supersession/over-allocation regressions, explicit
schema1/2-to-3 migration, historical row/report/retry preservation, old-connection
enforcement and rollback of shared review plus payable initialization. See
[payable seal verification](05-service-bookkeeping/STEP_16C_VERIFICATION.md).

Step 17 covers strict bank CSV/metadata parsing, signed exact money, byte/row/field
bounds, stable statement/transaction identity, overlapping membership, repeat and
conflicting concurrent imports, initialization/write rollback, immutable records,
unchanged ledger/evidence/approval state and exact HTTP/CLI values. See
[bank import verification](06-bank-reconciliation/STEP_17_VERIFICATION.md).

Step 18 covers reciprocal matching uniqueness, exact references/dates/signs, stale
bindings, one-to-one concurrent claims, historical retries after audited unmatch,
overlapping statement identity, immutable events, migration/write rollback and
unchanged journals/imports. See [bank matching verification](06-bank-reconciliation/STEP_18_VERIFICATION.md).

Step 19a covers fixed-account metadata/activation/retry, already-open catalog
visibility, atomic migration/enrollment rollback, immutable rows, preserved
approval/run/scope/retry bytes, old versus new captured report identities, bounded
legacy expense policy and localhost field rejection/restart. See [account activation verification](06-bank-reconciliation/STEP_19A_VERIFICATION.md).

Step 19b covers bank-derived fee evidence, explicit classification/intent, shared
cash/row uniqueness, matched/late-candidate refusal, rejected revision recovery,
current approval at final seal, immutable atomic effects, source enrollment
recovery, legacy migration/rollback and exact HTTP/restart behavior. See
[reviewed fee verification](06-bank-reconciliation/STEP_19B_VERIFICATION.md).

Step 19c covers pure single-transaction reconciliation captures, exact fee/timing
bridges, zero-residual exceptions, later-clearing cutoffs, immutable timing and
completion/retry history, current drift, concurrent capture/write behavior,
rollback and exact browser/HTTP values. See [reconciliation verification](06-bank-reconciliation/STEP_19C_VERIFICATION.md).

Step 20a adds23 prepaid tests covering exact allocations, immutable coverage/claims,
current approval seals, durable reversal dependencies, transaction faults, concurrent
retries and frozen control/residual reports. See [verification](07-period-close/STEP_20A_VERIFICATION.md).

Step 20b adds20 expense-accrual tests covering paired incurrence/basis facts,
shared cash/bill/accrual recognition claims, audited fixed2050 activation, current
approval and final-seal revalidation, rejected/new-pending supersession, direct and
old-connection guards, atomic ledger4-to-5/review9-to-10/accrual1 initialization,
write rollback, frozen pure reports, exact concurrent retry and native HTTP forms.
The separate150.00 fixture leaves Cash/AP unchanged and reconciles to zero residual.
