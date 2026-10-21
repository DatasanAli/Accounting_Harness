# Step 34 synthetic release acceptance

Verified locally on 2026-10-21: **931 tests and all 49 CI demonstrations passed**. Authenticated native-browser preparation/review, exact reports, verified recovery and final independent adversarial review passed. Commit [`0a7b181`](https://github.com/DatasanAli/Accounting_Harness/commit/0a7b181424ce1944cc894897c8d727725bba8fc6) was pushed and matched `origin/main`; [exact GitHub CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39676697662) passed. This is offline synthetic acceptance; live providers, real sandbox compatibility and actual real-data pilot acceptance remain deferred.

## Authenticated reference month

`demo-acceptance` creates a fresh private two-entity group with distinct preparer and reviewer identities. T01–T09, A01 insurance allocation and A02 advance earning use registered evidence, supported preparation services and separate authenticated human approval. No authoritative journals or managed effects are seeded by SQL. T03 uses the explicit January 1 operational variant; the original [published reference](../../data/fixtures/service-business-month.json) remains unchanged.

| Observed result | USD |
| --- | ---: |
| Adjusted trial balance, each side; 11 journals | 13,300.00 |
| Revenue / expenses / income | 2,700.00 / 1,600.00 / 1,100.00 |
| Assets / liabilities / equity | 11,500.00 / 600.00 / 10,900.00 |
| Cash / receivables / prepaid insurance | 9,400.00 / 1,000.00 / 1,100.00 |
| Payables / customer advances | 200.00 / 400.00 |
| Operating / investing / financing cash flow | -400.00 / 0.00 / 9,800.00 |
| Post-close trial balance, each side; 12 journals | 11,500.00 |
| Post-close capital | 10,900.00 |

All four subsidiary residuals are zero. Captured statements and cash flow reproduce from their retained snapshot and policy; JSON and ZIP CSV/manifest readback agree exactly. Closing clears five temporary accounts, preserves pre-close package bytes and locks January. Reopening and replaying exact close/post requests creates no duplicates. An authorized reviewer can retain approval for a backdated draft, but subsequent posting fails the period lock: its draft is approved, with no journal or subsidiary effect. Approval and posting are separate durable operations, not an atomic combined action.

## Separate scenarios and refusal gates

- Authenticated bank scenario: bank 940.00, books 990.00, timing +200.00/-150.00, adjusted bank 990.00 and zero difference, with four reviewed journals. Offset +7.00/-7.00 statement exceptions also yield zero difference, but both remain visible and completion is refused.
- Reviewed owner/prepaid journal IDs exceed the external bank identity limit. Matching and timing now validate local ledger references correctly; external bank/import/retry identities retain their bounds. A real reviewed-workflow regression covers both paths.
- Separate delivered accrual and management fixtures retain their original assertions and independently check returned results: expense accrual 150.00, revenue accrual 250.00, project cost 400.00 + 100.00 + 200.00 = 700.00 and margin 300.00; cash plans 1,300.00 and -200.00 with a 200.00 gap; static/flexible/actual revenue-cost-margin of 1,000/500/500, 1,250/600/650 and 1,100/600/500. Contribution is 60.00 and break-even 20 units; reference indicators include 19.17, 17.33 and 40.74%, with unavailable hourly output for zero actual time. These are labelled `isolated_delivered_fixture_regression`, separate from the authenticated reference month. Management assumptions do not post actuals.
- Offline import reconciles three synthetic records at 600.00 per side. A separately authenticated 125.00 export loses its simulated creation response, reopens the facade and retries the same immutable request. Exact readback confirms one simulator receipt and unchanged local report bytes.
- The 31-case operational-agent corpus checks offline/mock contracts. An authenticated preparer run leaves **one pending draft and zero journals before review**; separate reviewer approval yields one journal. Missing-evidence handoff, hostile/conflicting source cases, stale revision, denied role/entity actions and revocation are checked. Live model accuracy is unmeasured.
- Recovery compares both entities' evidence, drafts, journals, balances, run checkpoints, close/package and uncertain export. An interrupted run with a durable draft but missing checkpoint resumes after fresh login without duplicating the draft. Old sessions fail and recovered transports remain disabled.

## Native browser and final recovery

A browser preparer registered two fresh facts and prepared a 33.00 owner drawing dated January 27 in the secondary entity. Preparation left its journal count at one. After sign-out, a distinct reviewer inspected debit Drawings 3100 / credit Cash 1000, evidence and revision digest; the checkbox enabled approval and the native keyboard action posted exactly once, bringing the count to two. Keyboard links reached the journal and original source with retained actor, date and digest. Native forms were filled through browser controls; the complete flow is not claimed as keyboard-only.

The main entity's native reports displayed the reference statements and cash flow above; its close screen retained the January lock, approval, close journal and 10,900.00 capital. Checks used 1365×900 desktop and 390×844 viewports. At the narrow viewport, document and client widths were both 375 pixels, without page-level horizontal overflow.

After this posting, a fresh backup/restore using the final corrected code preserved all ten financial/run/integration SQLite logical dumps across both entities. The access database intentionally changes for relocation and session revocation. A new isolated browser login displayed the main entity's 12 journals and 11,500.00 trial balance, the secondary entity's posted 33.00 source/approval/journal trace, an unresolved uncertain export and verified restore checkpoint. Transports stayed disabled even with `--enable-providers`; status did not retry the export. The restored narrow layout measured 375/375 pixels.

Observed recovery volume: **2,138,112 bytes, two entities**. Backup took 224 ms, backup verification 32 ms, and restore 207 ms including 171 ms verification. These are one workstation's synthetic observations, not a recovery SLA. Private credentials, databases, backups and browser artifacts remain ignored under `.local/`.

## Operator setup

See the [local synthetic runbook](LOCAL_SYNTHETIC_RUNBOOK.md) and [recovery runbook](RECOVERY_RUNBOOK.md). Configuration is not a verified live connection. Real-data decisions remain the legal entity, framework, jurisdiction, fiscal calendar, recognition/correction policies, operators, retention and authorized external actions.

## Final review and delivery

- `python3 scripts/run_tests.py`: **931 passed in 141.661 seconds**; zero-test discovery guard retained.
- All **49** demonstration commands from CI passed after the fix wave.
- `python3 scripts/verify_foundation.py`: 134 Markdown files, 455 local links after the delivery update, 34 ordered steps and all reference accounting identities passed. `node --check accounting_harness/static/app.js` and `git diff --check` passed.
- Three independent reviews challenged accounting/close, identity/agents/UI, and integration/recovery/reporting. Five Minor findings were corrected and independently rechecked; no findings remain open. See the [adversarial review record](ADVERSARIAL_REVIEW.md), including earlier consequential campaign fixes.

Delivery: verified, uploaded and exact CI passed. Commit [`0a7b181`](https://github.com/DatasanAli/Accounting_Harness/commit/0a7b181424ce1944cc894897c8d727725bba8fc6) was pushed and matched `origin/main`; [exact GitHub CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39676697662) passed. Earlier deliveries have their own exact-SHA evidence: [32](STEP_32_VERIFICATION.md), [33a](STEP_33A_VERIFICATION.md), [33b](STEP_33B_VERIFICATION.md).

Step 12 live model evaluation, Steps 30/32 real sandbox compatibility and actual Step 34 pilot acceptance remain deferred. Optional Phase 10 is outside this offline campaign.
