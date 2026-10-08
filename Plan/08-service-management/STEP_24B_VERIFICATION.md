# Step 24b verification: auditable project time

Observed on 2026-10-08 using Project A in the retained closed synthetic workspace.

## Native time and correction history

Recorded January 10 and 11 intervals, 09:00–14:00 (minutes 540–840), under one
worker and two distinct stable events. The report showed exactly 600 minutes,
10h 0m. Repeating the second event retained two records and its original audit.
The native date control was changed through keyboard Tab/Arrow keys.

A different event with the same active interval was refused with a visible
overlap error and retained inputs. Selected the first interval from history,
entered a void identity/reason and explicitly confirmed. Current active time
became 300 minutes; the displayed prior 600-minute capture remained intact until
recapture. An HTTP retry of the original event returned the original actor/time
with voided status and did not add any active minutes.

Selected its voided reference and entered a replacement with a new event ID.
An initially overlapping replacement was refused while the completed void
remained recoverable. The valid January 10 replacement restored active time to
600 minutes. Final history has three original facts and one void: recorded 900
minus voided 300 equals active 600. Both directions of the correction link are
retained. No wage expense, financial journal or assignment change was created.

## Captures, layout and restart

Refresh retained the exact displayed time capture. Complete prior workspace
state, the Step 24a attribution report, both January 31/15 financial/cash-flow
reports and the three saved portable report byte streams remained unchanged.
The fresh server CSRF token is excluded from persisted-state comparison.

At a true 390px viewport the document width was 390px and the time form 320px.
Captured history showed 600 active minutes and all active/voided records. At
1280px, the restarted native report also displayed correctly without document
overflow.
Final-code restart reproduced the complete current time report and every prior
state/report/download comparison exactly.

## Checks and delivery

- Focused suite: 18 tests passed in 1.266s.
- Guarded full suite: 663 tests passed in 47.629s; zero-discovery guard retained.
- All 35 demonstrations, foundation, JavaScript syntax and diff checks passed.
- Initial missing-module/CLI and missing-native-route failures preceded implementation.
- Independent review approved spec and quality with no findings.
- Delivered commit [d745540](https://github.com/DatasanAli/Accounting_Harness/commit/d74554063e385b57b66d69301e7fa7cac1d93d73) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37843247067) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_project_time.py -v
python3 -m accounting_harness demo-project-time
node --check accounting_harness/static/app.js
```

Project time uses additive schema version 1; existing financial, attribution and
report formats remain unchanged. Time is operational evidence, separate from
recorded costs and future rate assumptions. Supported intervals are within a
single January day; overnight work requires separate records. Local operator
remains unauthenticated until Step 29. Live connections remain deferred.
