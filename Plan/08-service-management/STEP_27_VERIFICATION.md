# Step 27 verification: captured budget variance

Observed on 2026-10-08 using a separate synthetic variance workspace, preserving
the previously closed reference month.

## Inputs and native comparison

Prepared two cash transactions through supported evidence, proposal and separate
human approval services: 1100.00 service revenue and 600.00 software expense.
Recorded two 300-minute service intervals. An immutable operating budget assumes
480 minutes, revenue 125.00/hour, variable software 50.00/hour and fixed software
100.00. Actual facts and budget assumptions remain distinct.

In Budgets, selected the saved budget and captured its variance. Native results:

| Measure | Static | Flexible at 600 minutes | Actual | Favorable impact |
| --- | ---: | ---: | ---: | ---: |
| Revenue | 1000.00 | 1250.00 | 1100.00 | 100.00 favorable |
| Expense | 500.00 | 600.00 | 600.00 | 100.00 unfavorable |
| Income | 500.00 | 650.00 | 500.00 | 0.00 neutral |

The revenue bridge is 250.00 favorable activity plus 150.00 unfavorable remaining
variance. Expense is 100.00 unfavorable activity plus zero remaining variance.
Income bridges 150.00 favorable activity and 150.00 unfavorable remaining to zero.
Every account and total reconciles exactly. Raw expense variance and its opposite
favorable-impact sign are displayed separately.

Expanded journal/evidence references identify both reviewed transactions and
paired source facts. The report also shows both time records, each budget line's
rate/fixed amount and rounding trace. Missing account-level quantity/classification
support is explicit; no causal pricing, efficiency or responsibility claim is made.
The operator's explanation remains an attributed note.

## Retention, layout and restart

The native download produced 28,879 bytes of JSON equal to the displayed complete
comparison. Created a new budget version with an explicit 130.00 revenue rate and
reason through protected HTTP. The original comparison, its downloaded capture
and original-version recapture remained exactly equal. Both original and successor
budgets remain immutable. All financial state, statements and time stayed unchanged.

With the server stopped, `variance_report(saved['capture'])` reproduced the entire
download without opening a workspace. Final-code restart preserved both budgets,
all original financial/time inputs and the original comparison exactly.

At true 390px width, the document is 390px and form 320px. Wide tables stay inside
356px containers with horizontal scrolling, without overflowing the page. Refresh
preserves the displayed comparison. At 1280px after restart, native capture shows
the same reference values with a 1265px document and 560px form, without page
overflow. A full page reload requires a new capture or
the previously downloaded JSON, as stated in the UI.

## Checks and delivery

- Focused suite: 17 variance tests passed with missing-feature and malformed-input
  failures observed before implementation/fixes.
- Guarded full suite: 719 tests passed in 51.722s; discovery guard retained.
- All 38 demonstrations, foundation, JavaScript syntax and diff checks passed.
- Independent review approved spec and quality with no findings.
- Delivered commit [b5b6b02](https://github.com/DatasanAli/Accounting_Harness/commit/b5b6b02c15290b7e446a4a34a5eb881c39451c5b) matches origin/main; [exact-SHA CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37848793541) completed successfully.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_variance.py -v
python3 -m accounting_harness demo-variance
node --check accounting_harness/static/app.js
```

No new database schema. Captures serialize their immutable budget, financial and
time inputs with policy/digests. Hashes establish internal consistency, not source
authenticity or permission. This is a whole-month January USD service-minute
comparison. Zero bases return unavailable percentages and unbudgeted actuals remain
visible. Local operator authentication follows in Step 29; live calls stay deferred.
