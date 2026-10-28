# Step 35: Offline prerequisites for operational evaluation

The 2026-10-28 build-and-ship request starts the next planned delivery from
LIVE_VERIFICATION_GATES.md. This work extends Phase 09; optional Phase 10 remains
unselected. The completed Steps 01–34 and their live-gate limitations stand.

## Delivery split

**35a — durable evaluation budget and frozen manifest.** One experiment database
binds immutable limits and the semantic manifest. Reserve each attempt before any
dispatch, including retries. Enforce aggregate/per-sample request limits, exact
integer USD nanodollar reservations and a persisted wall-clock deadline. Reopening
the same file cannot reset limits. An unresolved reservation blocks further calls;
unknown billing remains incomplete. A process-bounded dispatcher terminates a
stalled request at the remaining deadline. Reports contain safe counters and reason
codes, never request bodies, responses, credentials or exception messages.

Freeze 20 semantic cases (14 references, six handoffs) and four specific repeats:
cash expense, vendor bill, prepaid consumption and hostile-evidence handoff. Bind
the existing corpus by digest without editing its bytes. Keep seven protocol and
four provider fault cases separate. This delivery is explicitly offline contract
verification; it cannot produce a live accuracy pass or enable a transport.

**35b — authenticated scoring integration.** Use 35a's manifest and budget through
existing authenticated preparer services, independent expected outcomes and
separate synthetic reviewer dependency setup. Score all 24 samples, evidence,
repeat semantics and unauthorized effects; missing usage, false labels and
fixture playback cannot pass a claimed live result. Deliver this independently,
including access revocation/restart and sanitized result capture. Actual selected
provider/model, budget approval and G1 compatibility remain prerequisites to live
execution; this plan does not infer them from credentials.

The detailed [Step 35b implementation plan](STEP_35B_PLAN.md) defines the authenticated
scorer, durable sample claims, failure denominators and offline-only command.

## Step 35a implementation and acceptance

Reuse SQLite, the existing immutable-table helper and provider process deadline
primitive. Add `accounting_harness/operational_evaluation.py`,
`data/fixtures/operational-evaluation-manifest.json` and
`tests/test_operational_evaluation.py`. Add `demo-evaluation-budget` to the CLI,
CI and documented command lists. Keep the new experiment database separate from
financial stores; it is not included in financial backup/recovery. A copied
experiment with pending work remains incomplete and must not dispatch.

1. Write failing tests for durable limits, immutable configuration, concurrent
   reservation, crash/reopen refusal, cancellation, deadline and redacted reports.
   Run `python3 -m unittest discover -s tests -p test_operational_evaluation.py -v`.
2. Implement `EvaluationBudget(path, policy, clock_ms=...)` with `reserve(sample)`,
   `settle(attempt, cost_nanodollars=..., outcome=...)`, `cancel()`, `report()` and
   `dispatch(sample, worker, arguments)`; no network-selected default worker.
   Transactions commit reservations before spawning; settlement is append-only.
3. Add manifest validation and test altered corpus/labels, excluded fault cases,
   explicit repeat order and empty/duplicate samples. Persist the manifest digest
   with policy, not a mutable pathname.
4. Demonstrate two attempts across reopen, a refused third call, exact retained
   reservations and a separate crash/unknown experiment. Show offline-only status.
5. Run foundation, complete tests, all demos, JavaScript syntax and diff checks.
   Obtain independent review, fix findings, commit intended files, push to origin
   and check the exact commit's CI. Record actual evidence before claiming delivery.

Independent acceptance: with a two-call/100-nanodollar budget and a
50-nanodollar reservation, two known costs of 7 and 11 retain 100 reserved and
18 observed; a third dispatch never starts. A child that stalls beyond 200ms is
terminated, retains its reservation and leaves billing incomplete. Two concurrent
connections competing for the last slot allow at most one reservation. An
interrupted reservation cannot be resent by reopening, changing the policy or
calling the same sample again. A rejected operation leaves the financial ledger
untouched because this component never opens it.

Rollback: revert code with a new commit; preserve experiment evidence and financial
history. Do not reset counters or treat a backup as authority to retry external work.
