# Step 20d verification: adjusted operational reference month

This slice assembles a synthetic month through the delivered accounting services.
It adds a reusable fixture helper and CLI demonstration, with no new browser
workflow or accounting policy. Step 21 will use the same helper for statements.

## Reference boundary

The operational variant records a new insurance purchase on January 1 so it
precedes the explicit January–December coverage start. The original January 3
fixture and its bytes remain unchanged. January 31 totals match the original
reference, while January 1–2 cutoff expectations explicitly differ.

The fixture uses normal registered evidence, preparation, separate simulated
human approval and posting for rent, invoices/collections, bills/payments,
advances/earning and prepaid consumption. Owner contribution, drawing and the
original prepaid purchase use trusted core fixture entries, labeled as such with
null approval references. Their dedicated reviewed UI policy is planned in 31a.
No managed-control effect is fabricated and no guard is disabled.

## Verification

Ten focused tests passed. The guarded full suite passed all **556 tests in
37.676 seconds**. All **29 demonstrations** passed, along with foundation and diff
checks. Independent review approved spec compliance and task quality with no
findings. Delivered as [56d2548598b089358ad8e1af579446eb9b77ee2e](https://github.com/DatasanAli/Accounting_Harness/commit/56d2548598b089358ad8e1af579446eb9b77ee2e).
Remote main matched exactly; [CI37830844808 passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37830844808) for this SHA.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m unittest discover -s tests -p test_adjusted_month.py -v
python3 -m accounting_harness demo-adjusted-month
```

Verified adjusted balances: 11 journals, eight reviewed approvals and trial
balance totals of 13,300.00 per side. Cash 9,400.00; receivables 1,000.00; prepaid
insurance 1,100.00; payables 200.00; customer advances 400.00; capital 10,000.00;
drawings 200.00; revenue 2,700.00; rent 1,200.00; software 300.00; insurance 100.00.
Other baseline balances and the AP/AR/advance/prepaid residuals are zero.

## Reuse and rollback

`build_adjusted_month(Workspace(path))` returns a stable JSON-safe transaction
map linking each T01–T09/A01/A02 input to its source digests, draft/revision,
approval, journal and relevant subsidiary identity. It also identifies the
fixture, original reference hash, payload digest and date variant. Exact retry
and restart must preserve the original records rather than make another month.

Keep synthetic workspaces separate from unrelated books. No live connection,
real financial document or actual pilot acceptance is introduced. Preserve posted
history; reverting fixture code does not authorize deleting journals.
