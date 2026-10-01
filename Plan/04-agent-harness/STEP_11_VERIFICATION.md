# Step 11 verification

Observed 2026-10-01: **203 application tests pass**, including 34 new run tests and one CLI assertion. Foundation verification and all ten demos pass. The existing 24-case tool-contract evaluation remains green. No model/provider network calls or real costs occurred.

## Behavior and observed evidence

- `SQLiteRunEngine` stores immutable task/configuration and append-only checkpoints in a separate single-entity run file, schema v1/application AHRN. Scope binds ledger/registry paths, frozen context, policy, allowlist and tool-schema digest. Config includes actor, task ID, provider/prompt version and fingerprint, and exact integer limits. Reopen requires the same fake script/configuration.
- The rent demo pauses at `awaiting_review` after five tools, five provider attempts and five simulated cost units. It closes all three databases, reopens 16 identical checkpoints, and acknowledges the handoff as `completed` with checkpoint 16. One unchanged draft revision remains pending human review; the ledger snapshot is unchanged and has zero posted journals. Resuming never executes a script tail after review or grants approval.
- An actual child process exits with code 73 immediately after a draft commits, before its result checkpoint. Restart finds the exact immutable review retry receipt, records `tool_result_recovered`, and retains one revision without repeating the save or charging another provider request.
- Tests inject failures before dispatch and after the side effect, exercise cancellation before execution and after an uncertain result, check time expiry after side effects, and preserve result references even when recovery occurs after expiry with zero retries remaining.
- Provider timeouts charge each attempt. Tool storage-lock retries are bounded without provider replay. Wall time includes downtime; recorded elapsed never decreases, and usage is the maximum of wall elapsed and cumulative simulated provider latency. Call/cost/time limits persist across reopen. Completed, failed, exhausted and cancelled runs cannot restart.
- Forced concurrent interleaving proves one resumer cannot steal a live dispatch reservation or consume its retries. A macOS/Linux advisory file lock spans reservation commit and dispatch; process death releases it. SQLite serializes run-log writes and bounds lock waits. Contention returns `PersistenceBusy` without changing budgets.
- Tests reject changed scripts, prompts/configs, entity/ledger/registry/policy scope, malformed outputs, fabricated evidence and unauthorized tools. Hostile document text does not alter permissions or appear in result logs. Run logs store validated intents needed for replay and compact result identities/digests/finding codes, not raw provider scripts, hidden reasoning or full evidence responses.
- SQL update/delete/replace protections, contiguous checkpoint sequences, unsupported/wrong/unversioned schema rejection, atomic initialization/start rollback and unchanged existing ledger receipts/snapshots/source evidence are checked. Existing storage schemas and zero-test discovery guard remain unchanged.

Red checks were observed for the missing module/CLI, missing audit-config accessor, dispatch-reservation race, elapsed-time double counting and non-fake provider acceptance on resume. All pass after implementation/fix. Independent review identified the reservation and elapsed issues; a second review reran all 34 run tests and found no remaining important correctness issues within the documented scope.

## Reproduction

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-run
python3 -m accounting_harness demo-tools
```

CI also runs accounts, journal, ledger, persistence, reversal, source, review and approval demos.

## Limits and rollback

The fake provider has deterministic, simulated integer usage and no blocking/network work. Time enforcement is cooperative at local operation boundaries; a completed tool may leave its pending draft if the deadline is crossed, but the runtime records the result and stops. This does not implement hard cancellation of an in-flight network request or real billing. Live-provider behavior is Step 12.

The run database and `.dispatch.lock` file use stable local paths on macOS/Linux. Do not unlink the lock file while workers are active. Run, ledger and source databases must be restored consistently; independent file replacement/restore or hostile administrator changes are outside the guarantee. Prototype writers serialize per run log. Local actors are audit references, not authenticated roles. No provider can approve/post through the five-tool allowlist.

Rollback is a new software revert commit while retaining run/draft/evidence/journal history. No migration or downgrade of existing ledger/source/review/approval tables is needed. Exact commit/push and GitHub Actions evidence is checked after commit and reported in the delivery response.
