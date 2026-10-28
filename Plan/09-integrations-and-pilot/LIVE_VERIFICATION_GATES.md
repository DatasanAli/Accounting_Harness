# Deferred provider and sandbox verification plan

**Status:** proposed gates, 2026-10-21. Planning only; no network calls authorized or performed by this task. No credentials were inspected. Steps 01–34 retain their delivered offline status; none of the live gates below has passed.

**Goal:** obtain bounded, attributable live evidence for model proposals and one QuickBooks sandbox journal round trip before considering real-data use.

**Approach:** verify providers and sandbox transport independently. First prepare missing controls offline, then authorize each specific live experiment. Keep local SQLite books authoritative, model output subject to human review, and remote observations separate from actuals. Use the existing Python/SQLite application and standard-library tests; do not introduce a general connector platform.

**Basis:** [completed acceptance](STEP_34_VERIFICATION.md), [Step 12 contract](../04-agent-harness/STEP_12_PLAN.md), [operational agent contract](STEP_31B_PLAN.md), [sandbox read](STEP_30_PLAN.md), [export](STEP_32_PLAN.md), [recovery](RECOVERY_RUNBOOK.md), and [local setup](LOCAL_SYNTHETIC_RUNBOOK.md). This plan is based on repository inspection, not newly verified external documentation. Model availability, prices, OAuth requirements and remote API semantics must be checked at G1.

## Follow-up implementation

The 2026-10-28 build-and-ship request starts the offline prerequisite work in
[Step 35](STEP_35_PLAN.md), with decisions tracked in [G0](G0_DECISIONS.md).
The original planning-only restriction above describes the 2026-10-21 task.
Shipping the new offline implementation includes authorized GitHub access;
provider calls, sandbox calls and all live-gate decisions remain separate.

## Existing capability and actual gaps

| Area | Existing local implementation | Prerequisite for live evidence |
| --- | --- | --- |
| Receipt proposals | `provider.py`, `provider_evaluation.py`: explicit `eval-provider --live`, 20 labelled cases plus four repeats; OpenAI adapter pins `gpt-4.1-mini-2025-04-14` and `expense-v1` | Confirm current model access, schema and prices. Retain a sanitized evaluation report. The legacy evaluator uses trusted temporary stores; it does not prove authenticated UI permissions. |
| Operational proposals | `operational_agent.py`: OpenAI and loopback Ollama adapters, 13 workflows, bounded per-run calls; 31 offline playback/injected-fault cases | Build an authenticated live scoring runner with aggregate request/time/cost limits, durable reservations, sanitized results and separately labelled fault tests. `evaluate(directory)` is not that runner. |
| QuickBooks read | `qbo_read.py`: exact parser, scoped configuration, injected transport, staging/checkpoints; workspace uses `SimulatedQBO` | Implement reviewed server-owned sandbox configuration, OAuth/secret handling and bounded HTTPS transport. Fixture realm, account IDs and minor version are not real configuration. |
| QuickBooks export | `qbo_export.py`: separately authorized immutable outbox, three-attempt ceiling, exact readback; `ExportService` constructs a simulator | Add an explicitly selected real sandbox transport/configuration path while preserving the simulator default, approval binding and uncertain-outcome history. This cannot be enabled by adding an API key or setting `--enable-providers`. |
| Recovery | Complete-group backup/restore, revoked sessions, disabled restored transports | Keep recovered live credentials/transports disabled. Any future reactivation needs an explicit reviewed design and approval; it is not part of these experiments. |

OpenAI receipt and operational adapters currently share a pinned model but use different prompts and contracts. Passing one does not pass the other. Ollama model identity and results are separate again. Do not silently substitute a model or merge their scores.

## Gate sequence and authority

| Gate | Deliverable | Calls allowed only after explicit scope approval | Exit condition |
| --- | --- | --- | --- |
| G0 | Operator/configuration decision record and offline prerequisite work | None | Required fields and controls complete; local tests/review pass |
| G1 | Dated official-document compatibility review | Public documentation only | Model/pricing/schema and OAuth/API assumptions verified; discrepancies resolved offline |
| G2 | Existing receipt live evaluation | Selected OpenAI evaluation only | Complete 24-sample report meets all checks below |
| G3 | Operational-agent live evaluation | One selected provider/model at a time | Authenticated semantic corpus, repeats and separate human-review rehearsal pass |
| G4 | Real sandbox read and reconciliation | Explicit sandbox OAuth/metadata/query/read only | Exact ID/version/account totals, resume and unchanged local books |
| G5a | One real sandbox export, lost-response recovery and readback | One approved journal; bounded same-request replay | Exactly one remote journal and exact reconciliation after restart |
| G5b | Optional separately approved live drift experiment | One specified edit to that sandbox journal | Drift remains an exception and local history stays unchanged |
| G6 | Consolidated acceptance decision | None implicitly | Evidence complete for the claimed scope; remaining gates explicitly deferred |

G2/G3 and G4 are independent after their G0/G1 prerequisites. G5a requires G4. G5b requires G5a and new mutation authority. No gate automatically authorizes its successor. Real documents, production realms, payments, tax/payroll and real-data pilot use remain outside this plan.

## G0: decisions and offline prerequisites

Required decision record fields are currently **unselected**, not inferred from credentials or old fixtures:

- Provider order: OpenAI receipt, OpenAI operational and/or installed local Ollama operational. Select exact model/version; for Ollama retain installed model digest/runtime version and machine description. No model downloads or server calls during planning.
- OpenAI project/account, authorized operator, credential storage mechanism, maximum spend/request/time caps and synthetic-data permission. Record only safe account aliases in public evidence; never keys.
- Intuit developer application, dedicated sandbox realm, authorized account owner, callback/consent configuration, token storage/rotation and exact granted scopes. Do not assume a read-only OAuth scope exists; enforce allowed methods and paths in application code regardless of provider scope breadth.
- Fixed local entity, fresh synthetic workspace, January date window, USD/multicurrency settings, exact remote account IDs mapped to local 1000/5000/5100/4000 as needed, mapping version and supported API minor version. Verify these before accepting a batch or preview.
- Separate preparer/reviewer identities, read/write approver, run window, evidence custodian and retention/deletion dates for private diagnostics. A credential's existence grants no experiment authority.
- Fixture ownership: operator provides an isolated sandbox with exactly three known journals (100.00, 200.00, 300.00) in the agreed read window. Creating those records or resetting a sandbox is an external write needing separate fixture-setup approval; it is not hidden inside G4.

Offline prerequisite deliverables, each independently tested and reviewed before live execution:

1. **Provider evaluation controls.** Existing receipt runner may be used unchanged only if current model/pricing/schema checks fit its existing bounds. Add operational scoring in a focused `accounting_harness/operational_evaluation.py` with tests in `tests/test_operational_evaluation.py`, reusing existing adapters/authenticated services. Preserve the offline corpus unchanged; create a versioned semantic evaluation manifest. Persist aggregate reservations before each dispatch, enforce the remaining wall-clock limit during in-flight calls, count retries, and mark crash/unknown billing incomplete without automatic resend. A resumed experiment must not reset its aggregate budget. Test aborted runs, budget exhaustion, false labels, missing usage and accidental fixture playback as failures of a claimed live result.
2. **Sandbox read transport.** Proposed `accounting_harness/qbo_transport.py` and `tests/test_qbo_transport.py` own secret handling and bounded network I/O; integrate through `qbo_read.py`, `workspace.py` and `authenticated.py`. Configuration stays server-side and versioned. Test exact host/realm/method/path allowlists, redirect refusal, TLS verification, bounded body/deadline, token redaction, expiry/revocation, concurrency and crash-safe refresh-token replacement. No network I/O inside database transactions. Credential storage must stay outside ordinary financial backups or be explicitly excluded/re-provisioned under the recovery contract. Determine the exact OAuth exchange from G1 before writing that implementation plan.
3. **Sandbox export transport.** Inject create/read operations into `qbo_export.py` without changing authorized request bytes on retry. Test simulator and live-mode identity separation, stale mapping/realm/model-independent approval, grant revocation, concurrent sends, lost reply/restart, token expiry and persistent drift. Prevent an old simulator authorization from becoming live authority. Update authenticated UI labels to distinguish simulation, live sandbox and unavailable transport; unsupported live modes fail closed. Recovered groups must still reject live operations.

A live mode or credential must never change ordinary CI into a network test. Use fake transports for tests, and verify default commands make zero network requests. Future implementation follows [implementation guidelines](../IMPLEMENTATION_GUIDELINES.md), [testing strategy](../TESTING_STRATEGY.md) and independent review. This planning request does not implement these deliverables.

Local verification commands before authorizing live execution:

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-provider
python3 -m accounting_harness demo-operational-agent
python3 -m accounting_harness demo-sandbox-read
python3 -m accounting_harness demo-sandbox-export
python3 -m accounting_harness demo-recovery
python3 -m accounting_harness demo-acceptance
node --check accounting_harness/static/app.js
git diff --check
```

Run all documented demonstrations for an implementation delivery, retain the zero-test guard, and obtain exact-commit CI once GitHub access is authorized. No new application tests are needed for this documentation-only plan.

## G1: current compatibility, before account traffic

After permission for documentation retrieval, read current official OpenAI model/Responses/structured-output/function-tool and pricing documentation, Ollama documentation if selected, and Intuit OAuth, sandbox, JournalEntry, query pagination, throttling, request-ID replay and token lifecycle documentation. Record exact URLs, retrieval date, relevant versions and conclusions. Existing links in the Step 12/30/32 plans are starting references, not current verification.

Check model access separately during the authorized experiment; public documentation alone cannot prove account entitlement. Recompute conservative integer-nanodollar reservations from current uncached rates. Verify request-ID replay scope and retention before any create. If retention or replay conditions are unclear, do not run a lost-response resend experiment. Review actual OAuth scopes and token endpoints; identify whether account/metadata reads need additional consent. Resolve contract discrepancies offline with regression tests; never relax parsers merely to make a live result green.

## G2: receipt evaluation

Proposed scope retains the existing limits: **24 requests, 300 seconds, $0.25 conservative reservation**, 10-second per-request deadline and no automatic network retry. These are experiment ceilings, not current pricing claims. Abort before dispatch if verified rates cannot fit the ceiling. The initial trial is part of the 24 requests; additional probes or reruns need a new explicit budget.

Only after G0/G1 and explicit live approval, the existing command is:

```sh
python3 -m accounting_harness eval-provider --live
```

Keep the key solely in the server environment, run against synthetic temporary storage, and capture stdout to a private operator-selected location. This command is not run by the planning task.

Pass requires 20 labelled cases plus four repeats, exact supported proposals **8/8**, required handoffs **12/12**, correct evidence/date/account/amount bindings, no accepted unbalanced entries and **zero journals posted by model runs**. A transport failure is not a successful abstention. Require no failures, no semantic repeat differences, complete usage/reservation accounting and elapsed time within the ceiling. The existing `passed` boolean alone is insufficient: independently check cost completeness and repeat statistics. Missing billing data means incomplete cost evidence; retained reservations are not refunded. Report observed latency and usage-derived cost separately from conservative reservations; neither is an invoice reconciliation or production SLA.

## G3: operational evaluation and authenticated handoff

Use the 14 reference cases spanning all 13 delivered workflows and six evidence/policy handoff cases as **20 semantic cases**, plus four repeat cases frozen before execution: cash expense, vendor bill, prepaid consumption and hostile-evidence handoff. Preserve seven protocol-refusal and four provider-fault cases as separate injected offline boundary tests; do not score forced timeouts or scripted tool frames as live model accuracy.

Proposed per-provider limits: **24 runs, at most eight provider requests per run and 192 overall**. OpenAI: **$3.00 reserved and 30 minutes overall**; installed local Ollama: **60 minutes overall**, no download/cloud fallback, hardware cost unmeasured. Existing per-call deadlines remain 10 seconds/OpenAI and 120 seconds/Ollama. These aggregate controls require G0 implementation. Include every provider attempt in the aggregate count, enforce cancellation against the remaining aggregate time and report a capped/incomplete experiment honestly. Current code constants would reserve $2.673868800 for 192 OpenAI operational requests; that is a repository arithmetic observation, not verified current pricing. A rate change requires recalculation and a new approved budget if the proposed ceiling no longer fits.

Pass requires 14/14 exact service-built drafts, 6/6 correct handoffs, correct repeat semantics, no out-of-selection references, no duplicate effects and zero unauthorized postings/export/close actions. Evaluate under authenticated preparer grants. Setup and necessary dependency postings use separate explicit synthetic reviewer actions and are counted apart from model effects. Record per-workflow results, requests, prompt/schema/model/corpus digests, usage, reasons and latency. Every failure remains in the denominator; reruns are separately identified.

Drive one of the 24 scored runs through the native browser within the same aggregate budget: preparer starts the selected live provider, inspects the pending draft with zero journal effects, signs out; reviewer logs in, inspects evidence and exact revision, approves and posts once. Restart and replay must retain one journal and its trace without another provider call. Revoke the initiating preparer and demonstrate denial. This proves the selected configuration and flow, not general model reliability or production readiness. Run each additional provider/model as a separate approved evaluation.

## G4: real sandbox read

Proposed limit: **10 sandbox GET requests, 10 minutes**, plus at most one initial OAuth token exchange and one refresh within a separately authorized consent session. Count metadata, failed calls, page retries and verification reads; no hidden polling. Stop at the limit or on authentication failure. Do not generate traffic to force 429s; retain deterministic 429 tests as offline evidence.

Before starting, record the three fixture IDs/versions, currency, date range and per-account expected totals independently of the importer; freeze concurrent sandbox writers. Use page size two and a bounded maximum of five pages for this small experiment. Import to a fresh staging batch, stop after a committed page, restart and resume, then repeat an explicit read within the request cap. Verify **three unique IDs, 600.00 debit and credit totals, exact account/date/currency/version reconciliation**, no same-version conflict and no duplicate observations. Offset paging is not an atomic remote snapshot: use independent before/after inventory and refuse a stable-snapshot claim if concurrent changes cannot be excluded.

Compare local journal/approval/source/report captures before and after; they must be identical. Staging and access-session metadata may change. Record unsupported remote fields and incomplete pages as exceptions. Do not rewrite remote data or local actuals to obtain a match. If a fixture requires Account/CompanyInfo reads, list those GETs in the authorization and include them in the cap.

## G5a: one export and uncertain-outcome recovery

Proposed scope: **one** separately reviewed local 125.00 USD cash expense (Cash 1000 and Rent 5000 or Software 5100), **at most two create attempts with the identical persisted request ID/body**, at most **six GET readback/inventory calls**, one token refresh and **10 minutes**. No remote deletes, updates, second journal or replacement request ID. G4 credentials do not authorize these writes.

Prepare a fresh sandbox-bound preview showing realm, mapping version, local evidence/approval/journal, date, exact request bytes and digest. Obtain separate authenticated reviewer/owner export authorization. Record a remote baseline. For the single approved create, a controlled client-side test hook discards the returned creation response after the server has replied, retaining only a safe test marker; the outbox must record uncertainty. Restart the app and reconcile/replay only under G1's verified retention contract. Count the replay as the second create attempt. Confirm the same remote journal ID and exactly one new remote journal, with exact 125.00 per-side readback. Keep local journal/report bytes unchanged and all attempt history intact.

A live fault hook demonstrates this controlled lost-reply case, not every possible network partition. If it cannot be performed safely, run ordinary create/readback only and leave the live uncertainty gate incomplete. On any unresolved timeout, unknown ID, drift or retention doubt: stop, retain uncertainty, reconcile by authorized read/operator inspection and never mint a new request identity. Account/token refresh must not cause automatic create replay. A backup restore cannot undo an external journal.

## G5b: separate live drift test

If specifically approved, allow one manual edit of the same disposable sandbox journal from 125.00 to balanced 126.00, plus at most two readbacks. Capture the remote version change, retain the earlier confirmation and report a persistent exception without local journal/report changes. This is a new write authorization, not covered by G5a. Do not automatically restore, delete or recreate the remote journal afterward; retain it as labelled synthetic evidence. Without this gate, report drift handling as offline-tested only.

## Stop, evidence and completion rules

Immediately stop new requests on a wrong realm/host, leaked secret, unauthorized action, unbalanced/unsupported accepted entry, changed authorized payload, duplicate remote creation, exhausted budget, unresolved export or failed reconciliation. Disable the selected transport, retain sanitized history, revoke affected credentials where authorized, fix locally and re-review. Never delete evidence, reset counters or silently exclude failed samples. Correct local posted entries only through supported linked corrections; restore is disaster recovery, not an accounting undo.

Each experiment record must contain: approved scope/operator/time window; code SHA and relevant CI; provider/model or connector/realm alias; prompt/schema/map/corpus digests; synthetic fixture references; request/attempt/row counts; before/after ledger/report fingerprints; exact expected and observed results; latency, usage/reservation and uncertainty; denied actions and exceptions; separate human approvals; and a pass/fail/incomplete conclusion. Public GitHub evidence is sanitized synthetic summaries only. Credentials, OAuth codes/tokens, real account identifiers where sensitive, prompts/raw traces and databases remain private. Hashes do not authorize disclosure of sensitive source material.

G6 reports provider receipt, each operational model, sandbox read, create/readback, uncertain retry and live drift independently. A green CI run proves offline regression checks, not a live gate. Model metrics from a small synthetic corpus are not a deployment guarantee. Actual pilot acceptance additionally needs entity/framework/jurisdiction/calendar/recognition/correction policies, users/data permission, retention and operational ownership; that remains separately deferred.

## Next request

Recommended next prompt:

> Prepare G0's decision record and refine the offline prerequisite implementation plan from LIVE_VERIFICATION_GATES.md. Do not make network calls, inspect credentials or enable live transports.

For a later live request, explicitly name the gate, exact provider/model or sandbox realm, authorized actions, operator, synthetic dataset, request/time/spend caps and evidence location. No such approval is implied by this planning document. GitHub upload and current-document retrieval were also not performed during this network-free planning task.
