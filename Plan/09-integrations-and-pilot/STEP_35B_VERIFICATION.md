# Step 35b verification

Date: 2026-10-28. Scope: authenticated offline operational scoring, not live
provider accuracy or a completed G0/live verification gate.

## Implemented behavior

`eval-operational --directory PATH` creates or reopens a bound synthetic experiment.
Its 20 semantic cases and four repeats use isolated workspaces and authenticated
preparer actions. Synthetic owner activations and separate reviewer dependency
postings are counted separately. The evaluated agent retains only existing read,
proposal and handoff tools; the HTTP interface cannot inject the evaluator adapter.

Every synthetic provider attempt reserves the durable 35a budget before dispatch;
strict response parsing supplies integer token/cost usage. Aggregate and per-call
deadlines, cancellation, immutable policy and unknown-billing refusal still apply.
The scorer binds source code, worker, prompt/schema/model, manifest/labels, root and
synthetic operators. Sample claims precede setup; incomplete samples cannot replay.
Completed reopen returns the same captured report without more calls or postings.

Stored proposals must match independent lines, policy, date, entity, currency and
evidence scope/digests. The run's summary must agree with the stored draft. Snapshot
checks detect journal, approval, account and close effects. The report retains all
24 planned samples in denominators; failures, missing usage and skipped samples
cannot become successful handoffs. Unknown setup/effect counts remain explicit.
Reports contain safe IDs, digests, counters and outcomes, not raw explanations,
source text, passwords, tokens or exception messages. `live_verified` is always
false and there is no live/provider CLI selector.

The synthetic envelopes exercise the existing parser but their model identifier
and cost arithmetic do not establish current API availability or pricing. No
provider credentials were inspected; no provider or sandbox network calls were made.

## Verification and review

Tests first failed for the absent harness. The initial ten cases then passed,
including a complete authenticated 24-sample run. Further regressions cover usage,
setup exceptions, request deadlines, false date labels, separate approval/post
permissions, CLI refusal of a live flag and immutable score records.

Independent review identified a scorer that trusted projected lines rather than
the stored proposal, and failure reporting that represented unmeasured setup
postings as zero. Both were reproduced with failing tests and fixed. Re-review
confirmed the fixes and reported no remaining findings. **17 scoring tests** and
**19 durable-budget tests** pass. The test-only SQLite connection was explicitly
closed after a ResourceWarning; the final focused run is clean.

All **51 demonstrations passed**. The new demonstration produced 14/14 exact
proposals, 6/6 required handoffs and 4/4 repeats using 66 synthetic provider requests.
It recorded zero agent posting/account/close effects and 87 separately authenticated
reviewer dependency postings across the isolated workspaces. Completed reopen
preserved the report and request count; a one-request cap remained incomplete.
Foundation, JavaScript syntax and diff checks passed.

The complete application suite passed **967 tests in 188.978 seconds**, with no
failures or ResourceWarnings. Exact-commit GitHub evidence is pending; no upload
or CI success is claimed until observed.

## Reproduce

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-operational-evaluation
node --check accounting_harness/static/app.js
git diff --check
```

All 51 demonstrations in the testing strategy/CI are also required. To retain a
new synthetic experiment locally:

```sh
python3 -m accounting_harness eval-operational --directory .local/evaluation
```

Exit 0 means the complete offline contract passed; exit 1 means an incomplete or
failed report, and invalid CLI/configuration input exits 2. Reusing that directory
reads/resumes its existing binding; it never resets budgets. An interrupted sample
requires inspection and separately scoped new work, not automatic replay. Existing
financial or identity stores cannot be adopted by the evaluator. Known fixture
passwords belong solely to these disposable synthetic accounts.

No UI behavior changed. Existing UI, provider, accounting and recovery checks run
as regressions. Roll back with a new revert commit, preserving experiment records
and posted history. G0 operator/account choices, current-document compatibility,
sandbox transport and all live gates remain separate and incomplete.
