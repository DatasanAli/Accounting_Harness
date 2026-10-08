# Localhost accounting workspace plan

Updated: 2026-10-08. User direction: defer API connection and build toward a
localhost UI with a local Ollama model or a frontier API provider.

## Design and scope

Reuse the Python ledger, evidence registry, review application and durable run
engine. Serve a small HTML/CSS/JavaScript interface from a loopback-only Python
server. This avoids a second application stack and keeps money and permission
decisions in the existing application. A desktop wrapper adds packaging without
needed behavior; a separate React/API stack adds deployment and dependencies.

The first deliverable is **Step 12a**, an independently verifiable extension of
Step 12: a persistent synthetic workspace from receipt to proposal, human review,
posting, audit and trial balance. Offline fixture mode works immediately.
Ollama and the existing pinned OpenAI adapter are selectable but network use is
disabled unless the operator explicitly enables it at startup. No provider will
be connected or called during this delivery. A provider error or abstention is
visible in the run history and never posts a journal.

The existing ledger freezes its source identities and accounting period. Step
12a therefore uses a fixed set of registered fictional January 2026 receipts;
it does not pretend to accept arbitrary uploads or real books. Custom evidence
onboarding must preserve old context/approval bindings and gets its own step.

## Remaining path and acceptance

| Order | Deliverable | Acceptance |
| --- | --- | --- |
| 12a (this request) | Localhost workspace; offline/Ollama/OpenAI selection; review, reject, post, audit and trial balance | Offline browser walkthrough; persistent restart; stale/duplicate approval refusal; network disabled by default; adapter contract tests |
| 13a | Register new structured synthetic receipts through the UI | Additive evidence enrollment without rewriting ledger context or old approvals; import retry/conflict/restart tests |
| 13b | Cash receipts and expenses in the UI | Supported income/expense forms, exact cents, review before posting, negative and duplicate cases |
| 14–16 | Bills, invoices, partial settlement and customer advances | Subledger/control-account reconciliation, overpayment and duplicate protection |
| 17–19 | Bank CSV, matching and reviewed reconciliation | Ambiguity queue, timing differences, no unexplained completion |
| 20–23 | Adjustments, statements, close/locks and exports | Reference-month expected results, frozen snapshots/policies, reproducible exports |
| 24–28 | Service costs, budgets and scenarios | Recorded actuals separated from plans; deterministic comparisons |
| 29–34 | Authenticated roles, selected integrations, recovery and pilot | Scoped human permissions, restore exercise, selected real-data policies and pilot checks |
| 12b (when requested) | Connect and evaluate the chosen actual model | Bounded synthetic live evaluation, observed accuracy/latency/usage; no offline score substituted |

Steps 13 onward may proceed offline under the user's new direction. The deferred
live evaluation remains a requirement for claiming model readiness and for a
real-data pilot. The numbered accounting roadmap remains intact; lettered
substeps record independently reviewable deliveries without renumbering history.
The user explicitly expanded this request to **complete the wider accounting
roadmap too**. This overrides the default stop-between-requests cadence for this
request: continue through the numbered steps/substeps, with a separate reviewed
commit and verified CI per delivery. Do not claim deferred live connections or
actual pilot acceptance have occurred.

## Step 12a implementation plan

**Execution:** execute inline using the executing-plans workflow; existing solo
checkout and main delivery follow the repository's GitHub workflow.

**Stack:** Python 3.12+, standard-library HTTP/SQLite/unittest, browser-native UI.
**Spec:** this document's design and scope.

**Constraints:** exact integer cents; immutable journals; evidence/digest-bound
human approval; fictional fixtures only; no keys or raw provider traces stored;
no outbound requests during delivery; default bind 127.0.0.1; one local operator.

- [x] Write failing tests in `tests/test_local_providers.py` for schema parsing,
  provider identity, valid/review/invalid outcomes, input limits, duplicate source
  prevention and uncertainty recovery. Use real runtime/storage with only the
  external transport substituted.
- [x] Add `accounting_harness/local_providers.py`; extend `provider.py` and
  `runs.py` with explicit adapters that share bounded request processing. Ollama
  uses local `/api/chat`, a JSON schema, no streaming, bounded output and timeout;
  fixture mode uses exact frozen responses and reports no live-model accuracy.
- [x] Write failing HTTP tests in `tests/test_web.py`: loopback/Host/Origin/CSRF
  boundaries, bounded JSON, disabled provider denial, end-to-end review/post and
  exact balances, retry, stale confirmation, restart and rendered hostile data.
- [x] Add `accounting_harness/workspace.py` for storage and trusted actions;
  `web.py` for local HTTP and `static/` for accessible receipt/review/ledger UI.
  `GET /api/state` returns evidence/drafts/runs/snapshot; explicit POST actions
  run, cancel, reject and approve/post. Each request owns its SQLite connections.
- [x] Add `serve` and `demo-web` CLI commands, update CI and startup documentation.
  Run `python3 -m unittest discover -s tests -p 'test_local_providers.py' -v`
  and the equivalent `test_web.py` command during red/green development.
- [x] Run foundation, guarded full suite, all prior demos and `demo-web`; use a
  real browser for desktop/mobile layout and the proposal/review/post flow.
- [x] Record results and limitations, inspect/stage only intended paths, commit,
  push and inspect the exact remote SHA/Actions run. Then continue with Step 13a
  under the user's expanded authorization.

## Provider references

Ollama's [chat API](https://docs.ollama.com/api/chat) and
[structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
were checked on 2026-10-08. Live compatibility is unverified until 12b; supported
models must produce the strict decision schema. Frontier support initially means
the existing OpenAI adapter, not every provider or arbitrary compatible endpoint.

## Rollback

Revert published code with a new commit. Preserve the workspace's ledger,
source registry and run log together. Posted accounting corrections still use
linked reversals, not deletion or a database reset.

## Delivery ledger

- Step 12a: `ddf53f93846ec92edf179b62b4523f72c497e2f7`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37786950606). 243 tests, 12 demos and browser checks. Live providers remain unconnected.
- Step 13a: `67ca31ca8afcd12d42810d8e3690830c96488fc7`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37788816873). 257 tests, 13 demos, browser registration/retry.
- Step 13b: `887cc4e974c196913432c0006bf7d1e24e5af096`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37791223746). 268 tests, 14 demos and browser cash review/posting.
- Step 14a: `ff9a1cba9f26d83010112657a52adcb45df9b505`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37794830614). 287 tests, 15 demos, browser normal bill/restart and exact large-amount review.
- Step 14b: `0e061604d57c3f70400a10e6f39bb1e7a5c0ecf8`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37797498803). 301 tests, 16 demos, browser partial settlement and independent review.
- Step 15a: `0176f99c6bce416f2f38ab83c00221e8a1e9af09`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37800424176). Final 328 tests/17 demos in CI, browser posting and exact large amounts.
- Step 15b: `f29ac946ae743c630100feae42ebc1d3c458136a`; [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37802605944). 345 tests, 18 demos, browser collection/aging and review without findings.
- Step 16a: delivered as `8deae9b`, exact CI run 37805104017 passed; 370 tests/19 demos, browser advance/restart and review without findings. See [verification](05-service-bookkeeping/STEP_16A_VERIFICATION.md).

- Step 16b: delivered as `d57ca17`, exact CI run 37807454834 passed; 387 tests/20 demos, browser earning/restart and independent review without findings. See [verification](05-service-bookkeeping/STEP_16B_VERIFICATION.md).

- Step 16c: delivered as `0cc3e5f`, exact CI run 37809290761 passed; 398 tests/20 demos, preserved payable-workspace browser upgrade and independent review without findings. See [verification](05-service-bookkeeping/STEP_16C_VERIFICATION.md).

- Step 17: delivered as `4971d13`, exact CI run 37811461472 passed; 420 tests/21 demos, browser import/retry/rejection/restart and independent review without findings. See [verification](06-bank-reconciliation/STEP_17_VERIFICATION.md).

- Step 18: delivered as `aa7a975`, exact CI run 37814013196 passed; 440 tests/22 demos, browser matching/unmatch/rematch/restart and independent review without findings; see [verification](06-bank-reconciliation/STEP_18_VERIFICATION.md).

- Step 19a: delivered as `361459d`, exact CI run 37815799255 passed; 454 tests/23 demos, browser activation/refresh/restart and independent review approved with one minor validation consistency finding. See [verification](06-bank-reconciliation/STEP_19A_VERIFICATION.md).

- Step 19b: delivered as `757e6fd`, exact CI run 37817880835 passed; 470 tests/24 demos, browser prepare/review/post/match/restart and independent review with no new findings. See [verification](06-bank-reconciliation/STEP_19B_VERIFICATION.md).

- Step 19c: delivered as `c4edae4`, exact CI37820570127 passed; 485 tests/25 demos, browser timing/completion/drift/re-completion/restart and independent review without findings. See [verification](06-bank-reconciliation/STEP_19C_VERIFICATION.md).

- Step 20a: delivered as `ab557e4`, exact CI37823178380 passed; 508 tests/26 demos, browser coverage/prepare/approve/restart and independent review with no findings. See [verification](07-period-close/STEP_20A_VERIFICATION.md).

- Step20b: local528 tests/27 demos, browser registration/preparation/approval/frozen restart and independent review pass after workspace migration fix. Delivered as d3511be; [exact CI37826947400 passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37826947400), remote matched; see [verification](07-period-close/STEP_20B_VERIFICATION.md).

- Step20c: local546 tests/28 demos, revenue browser/restart and actual20b report/book preservation pass; review approved with one Minor validation-label issue queued. Commit/remote/exact CI pending; see [verification](07-period-close/STEP_20C_VERIFICATION.md).
