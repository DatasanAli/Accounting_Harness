# Step 35a verification

Date: 2026-10-28. Scope: offline durable evaluation controls and semantic manifest.

## Implemented

One versioned SQLite experiment binds immutable limits and manifest digest.
Requests reserve full integer nanodollar amounts before dispatch; costs do not
refund reservations. Request/per-sample/cost ceilings, observed deadline expiry,
clock regression and cancellation prevent further dispatch. Reopening cannot
change the policy or resend an unresolved attempt. Unknown/missing usage stays
incomplete. Only safe counters/reason codes are stored; raw worker responses and
exceptions are discarded. No financial databases are opened by the new control.

The frozen manifest retains 20 semantic cases and four repeats, binds the original
corpus bytes and expected labels, and excludes 11 scripted faults. It does not
score model accuracy. Authenticated scoring is Step 35b; all live gates remain
pending. No credentials were inspected and no live providers/sandbox were called.

## Review and regression evidence

Initial tests failed because the control was missing; the implementation passed
13 focused tests. Follow-up tests reproduced mutable in-memory limits, non-durable
expiry and missing wall-clock polling; fixes added read-only policy, durable stop
records and in-flight checks. Independent review reproduced two Important issues:
mutable policy and a shared provider pipe receive that could block after a partial
message. Both were fixed. The shared helper now supervises receipt on a separate
thread, leaving the main timeout/cancellation loop responsive; workers and receiver
threads are cleaned up. A partial-frame test failed before the fix and passed after.

Independent re-review found no remaining Important or Critical findings and
verified 17 evaluation tests plus 31 existing provider tests. Two further focused
tests verify external-connection cancellation and raw provider-error redaction;
all 19 focused tests pass. All 50 demonstrations passed, including the existing
acceptance/recovery flows. Foundation, JavaScript syntax and diff checks pass.
The final full-suite run passed **948 tests in 142.353 seconds**. The focused
19-test run also passed after adding the two cancellation/redaction cases (950
tests now discovered by the runner). The zero-test discovery guard is unchanged.
GitHub shipping and exact-SHA CI are pending; no CI success is claimed yet.

## Reproduce

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-evaluation-budget
node --check accounting_harness/static/app.js
git diff --check
```

Also run every demonstration listed in the testing strategy and CI. The new demo
shows two requests across reopen, 100 reserved / 18 observed nanodollars, refusal
of the third request, and a separate unresolved attempt whose billing stays
incomplete. All are synthetic control values, not measured live provider cost.

Rollback: new revert commit only; preserve existing experiment records and all
financial history. Do not reset budgets or use restored files to authorize resend.
