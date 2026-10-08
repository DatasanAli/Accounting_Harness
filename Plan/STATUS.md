# Current status

Updated: 2026-10-08.

**Completed work: Steps 01–11. Step 12 adapters/offline evaluation are implemented; live provider connection is explicitly deferred. Step 12a localhost workspace is delivered with verified GitHub CI. Step 13a evidence enrollment is delivered with verified GitHub CI. Step 13b cash templates are delivered with verified GitHub CI. Step 14a vendor bills are delivered with verified GitHub CI. Step 14b partial settlement is delivered with verified GitHub CI. Step 15a invoice recognition is delivered with verified GitHub CI. Step 15b collection and aging is delivered with verified GitHub CI. Step 16a customer advances are delivered with verified GitHub CI. Step 16b supported earning is delivered with verified GitHub CI. Step 16c payable seal hardening is delivered with verified GitHub CI. Step 17 bank import is locally verified and independently reviewed; upload/CI pending.**

The user requested the localhost app **and the wider accounting roadmap** on
2026-10-08. Continue through independent numbered deliveries in this request;
commit/push/check CI for each. Live provider/external-account connections and
actual real-data pilot acceptance are deferred, not successful by inference.
See [the working plan](LOCALHOST_APP_PLAN.md).

| Item | State |
| --- | --- |
| Initial workflow | Confirmed: bookkeeping for a small service business |
| Textbook review | Volume 1 reviewed first, then Volume 2; chapter coverage and reading depth in the source map |
| Plan | Nine sequential phases, 34 small steps, and one optional extension phase |
| Implementation/testing/GitHub guidelines | Written |
| Fictional reference month | Created with independent expected results |
| Foundation verification | See the observed results in the verification record |
| Money and chart of accounts | Implemented: exact USD cents, immutable accounts/catalog, validated JSON loader |
| Application verification | 420 tests passed, including bank CSV identity/atomic import/HTTP boundaries, payable seals and prior accounting behavior |
| Demonstration | 13 accounts; 0.10 + 0.20 = 0.30 USD; excess precision rejected |
| Journal validation | Implemented: pure validation, field/line findings, exact totals, source/account/date checks |
| Journal demonstration | Accepts 1000.00 / 1000.00; rejects 1000.00 / 999.00 with a 1.00 difference |
| In-memory ledger | Implemented: single-entry admission, immutable snapshots, inclusive date cutoffs and exact trial balances |
| Ledger demonstration | T01–T09; 13 accounts; 13300.00 debit/credit totals; Cash 9400.00 debit |
| SQLite persistence | Implemented: atomic journals/events/retry records; schema v3 with additive migrations, immutable context, restart and concurrent safe retry |
| Persistence demonstration | Reopen/retry: 9 journals, 18 lines, 9 events; unchanged 13300.00 totals and 9400.00 Cash |
| Linked reversals | Implemented: exact inverse journals, durable original links, scoped retries, one reversal per original |
| Reversal demonstration | 125.00 expense canceled to zero; original receipt and historical snapshot preserved after reopen |
| Source registration | Implemented: structured fictional receipts, canonical content digests, immutable entity-scoped identities and atomic registration events in a separate SQLite registry |
| Source demonstration | Reopen/repeat retains one unchanged source; separate identity creates a second source; changed content is rejected |
| Draft review | Immutable revisions, evidence binding, pending/rejected queue and atomic retry/event storage |
| Local approval/posting | Exact human-reviewed revision/evidence/policy binding; atomic journal/audit link; immutable source-to-journal trail |
| Agent tools | Five strict entity-scoped tools; runtime-controlled actor; approval/posting unavailable |
| Offline evaluation | 24/24 labeled synthetic tool-contract cases pass across eight categories; no model calls or ledger mutations |
| Fake-provider run loop | Durable scope/checkpoints, integer budgets, bounded retries/cancellation, crash receipt recovery and review handoff |
| Run demonstration | Reopen 16 unchanged checkpoints; acknowledge handoff with one draft revision and zero posted journals |
| Real provider adapter | OpenAI Responses, pinned model/prompt; offline verified, live calls pending |
| Provider proposal evaluation | 20/20 synthetic-response cases; 8/8 exact proposals, 12/12 review handoffs; not model accuracy |
| Authenticated roles and integrations | Not implemented |
| Delivery target | GitHub repository and CI; persistent localhost UI and CLI, no hosted deployment |
| Next step | Step 18 bank matching after exact Step 17 CI |

Read the [Step 01 verification record](01-foundation/VERIFICATION.md), [Step 02 verification record](02-ledger-core/STEP_02_VERIFICATION.md), [Step 03 verification record](02-ledger-core/STEP_03_VERIFICATION.md), [Step 04 verification record](02-ledger-core/STEP_04_VERIFICATION.md), [Step 05 verification record](02-ledger-core/STEP_05_VERIFICATION.md), [Step 06 verification record](02-ledger-core/STEP_06_VERIFICATION.md), and [Step 07 verification record](03-evidence-and-review/STEP_07_VERIFICATION.md) for observed checks and limitations. GitHub's [commit history](https://github.com/DatasanAli/Accounting_Harness/commits/main/) and [verification workflow](https://github.com/DatasanAli/Accounting_Harness/actions/workflows/verify.yml) provide delivery evidence for each commit. The completion response must identify the exact commit and CI run.

[roadmap.json](roadmap.json) records the ordered step states. Keep it synchronized with this page and [NEXT_STEP.md](NEXT_STEP.md) after every completed increment. The complete roadmap is in [README.md](README.md).

## Starting policy decisions

- Use a fictional USD service business with accrual bookkeeping and owner capital/drawings accounts.
- Use a local Python CLI and exact integer cents; Step 05 adds standard-library SQLite persistence.
- Agents create proposals; a person reviews the exact revision before the application posts it.
- Confirm actual legal form, reporting basis/framework, currency, fiscal calendar and operational permissions before a real-data pilot.
- Keep the PDFs and extracted source text local. Only references, original implementation material and fictional fixtures go to GitHub.

These are scoped starting decisions, not a claim of production or regulatory readiness.

Step 08: [contract](03-evidence-and-review/STEP_08_PLAN.md) and [verification](03-evidence-and-review/STEP_08_VERIFICATION.md).

Step 09: [contract](03-evidence-and-review/STEP_09_PLAN.md) and [verification](03-evidence-and-review/STEP_09_VERIFICATION.md). Step 08 delivered as [0984747](https://github.com/DatasanAli/Accounting_Harness/commit/09847473cf77453e105ba6249eeee391fc5b468c), [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/36762898574).

Step 10: [contract](04-agent-harness/STEP_10_PLAN.md) and [verification](04-agent-harness/STEP_10_VERIFICATION.md). Step 09 delivered as [48b4848](https://github.com/DatasanAli/Accounting_Harness/commit/48b4848106d23d3769613ded5c73ee21bd8a7cd5), [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/36764276544).

Step 11: [contract](04-agent-harness/STEP_11_PLAN.md) and [verification](04-agent-harness/STEP_11_VERIFICATION.md). Step 10 delivered as [0d77750](https://github.com/DatasanAli/Accounting_Harness/commit/0d777509d579f0fb8f6c53a06cbd6fcd9911844c), [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/36765306760).

Step 12: [contract](04-agent-harness/STEP_12_PLAN.md) and
[verification](04-agent-harness/STEP_12_VERIFICATION.md). The implementation and
offline checks are available, but Step 12 and Phase 04 are **not complete** until
the bounded live synthetic evaluation passes. No API key was present; no live
accuracy, latency or billed-cost result is claimed. The user deferred that live gate on 2026-10-08 and authorized independent
accounting/UI work. Roadmap schema v2 records Step 12 as deferred, with Step 12a
tracked separately. The [Step 13 brief](05-service-bookkeeping/STEP_13_PLAN.md)
is authorized next, split into evidence enrollment and cash templates.

Step 11 delivered as [9888182](https://github.com/DatasanAli/Accounting_Harness/commit/98881822bab680930aa91e01ac5a0200c82f2dbf),
[CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/36860770328).

Step 12a: [plan](LOCALHOST_APP_PLAN.md) and [verification](04-agent-harness/STEP_12A_VERIFICATION.md). Next: [Step 13a enrollment](05-service-bookkeeping/STEP_13A_PLAN.md).

Step 12a delivered as [ddf53f9](https://github.com/DatasanAli/Accounting_Harness/commit/ddf53f93846ec92edf179b62b4523f72c497e2f7); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37786950606). Local verification: 243 tests, 12 demos and desktop/mobile browser checks.

Step 13a: [contract](05-service-bookkeeping/STEP_13A_PLAN.md) and [verification](05-service-bookkeeping/STEP_13A_VERIFICATION.md). Next: [Step 13b reviewed cash templates](05-service-bookkeeping/STEP_13B_PLAN.md).

Step 13a delivered as [67ca31c](https://github.com/DatasanAli/Accounting_Harness/commit/67ca31ca8afcd12d42810d8e3690830c96488fc7); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37788816873). Local verification: 257 tests, 13 demos and browser registration/retry.

Step 13b: [contract](05-service-bookkeeping/STEP_13B_PLAN.md) and [verification](05-service-bookkeeping/STEP_13B_VERIFICATION.md). Local checks: 268 tests, 14 demos, browser paired-fact registration and explicit posting. A shared enrollment helper passed 22 focused tests and both affected demos after review. Exact commit/CI evidence follows. Next: [Step 14a](05-service-bookkeeping/STEP_14A_PLAN.md).

Step 13b delivered as [887cc4e](https://github.com/DatasanAli/Accounting_Harness/commit/887cc4e974c196913432c0006bf7d1e24e5af096); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37791223746).

Step 14a: [contract](05-service-bookkeeping/STEP_14A_PLAN.md) and [verification](05-service-bookkeeping/STEP_14A_VERIFICATION.md). 287 tests and 15 demos pass; browser review/posting and exact large-amount display observed. Next: [Step 14b partial settlement](05-service-bookkeeping/STEP_14B_PLAN.md).

Step 14a delivered as [ff9a1cb](https://github.com/DatasanAli/Accounting_Harness/commit/ff9a1cba9f26d83010112657a52adcb45df9b505); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37794830614).

Step 14b: [contract](05-service-bookkeeping/STEP_14B_PLAN.md) and [verification](05-service-bookkeeping/STEP_14B_VERIFICATION.md). 301 tests, 16 demos and browser partial settlement passed. Review approved with one deferred migration-maintenance observation. Delivered as [0e06160](https://github.com/DatasanAli/Accounting_Harness/commit/0e061604d57c3f70400a10e6f39bb1e7a5c0ecf8); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37797498803). Next: [Step 15a customer invoices](05-service-bookkeeping/STEP_15A_PLAN.md).

Step 15a: [contract](05-service-bookkeeping/STEP_15A_PLAN.md) and [verification](05-service-bookkeeping/STEP_15A_VERIFICATION.md). Broad 327 tests/17 demos passed, then 27 focused invoice tests and its demo passed after the reviewed final-seal fix (328 tests now in the suite). Browser normal/large exact amounts and explicit posting passed. Delivered as [0176f99](https://github.com/DatasanAli/Accounting_Harness/commit/0176f99c6bce416f2f38ab83c00221e8a1e9af09); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37800424176). Next: [Step 15b](05-service-bookkeeping/STEP_15B_PLAN.md).

Step 15b: [contract](05-service-bookkeeping/STEP_15B_PLAN.md) and [verification](05-service-bookkeeping/STEP_15B_VERIFICATION.md). 345 tests, 18 demos and browser collection/aging passed; independent review approved with no findings. Delivered as [f29ac94](https://github.com/DatasanAli/Accounting_Harness/commit/f29ac946ae743c630100feae42ebc1d3c458136a); [CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37802605944). Next: [Step 16a](05-service-bookkeeping/STEP_16A_PLAN.md).

Step 16a: [contract](05-service-bookkeeping/STEP_16A_PLAN.md) and [verification](05-service-bookkeeping/STEP_16A_VERIFICATION.md). 370 tests, 19 demos and browser advance/restart passed; independent review approved with no findings. Delivered as [8deae9b](https://github.com/DatasanAli/Accounting_Harness/commit/8deae9b781ddf1a8621647cd0e8d76017290e0b6); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37805104017). Next: [Step 16b](05-service-bookkeeping/STEP_16B_PLAN.md), then [16c payable seal hardening](05-service-bookkeeping/STEP_16C_PLAN.md).

Step 16b: [contract](05-service-bookkeeping/STEP_16B_PLAN.md) and [verification](05-service-bookkeeping/STEP_16B_VERIFICATION.md). 387 tests, 20 demos and browser earning flow passed. Independent review approved with no findings. Delivered as [d57ca17](https://github.com/DatasanAli/Accounting_Harness/commit/d57ca177a53f0b8f3e8e878d4bdc6ae0d7615270); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37807454834). Next: [Step 16c](05-service-bookkeeping/STEP_16C_PLAN.md).

Step 16c: [contract](05-service-bookkeeping/STEP_16C_PLAN.md) and [verification](05-service-bookkeeping/STEP_16C_VERIFICATION.md). 398 tests, 20 demos and browser legacy-workspace migration passed; independent review approved with no findings. Delivered as [0cc3e5f](https://github.com/DatasanAli/Accounting_Harness/commit/0cc3e5f9fc4f66d0412d45d31f9559ba22e2cea6); [exact-SHA CI passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37809290761). The prior AP seal and unchecked migration observations are resolved by verified regressions and explicit schema3 migration.

Step 17: [contract](06-bank-reconciliation/STEP_17_PLAN.md) and [verification](06-bank-reconciliation/STEP_17_VERIFICATION.md). 420 tests, 21 demos and browser import/retry/rejection/restart passed. Independent review approved with no findings; upload/exact CI pending. Next: [Step 18](06-bank-reconciliation/STEP_18_PLAN.md).
