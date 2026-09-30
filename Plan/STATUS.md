# Current status

Updated: 2026-09-30.

**Completed work: Steps 01–09 — foundation, ledger core, evidence, review and local approval/posting. Next implementation: Step 10 — typed tools and offline evaluation cases.**

| Item | State |
| --- | --- |
| Initial workflow | Confirmed: bookkeeping for a small service business |
| Textbook review | Volume 1 reviewed first, then Volume 2; chapter coverage and reading depth in the source map |
| Plan | Nine sequential phases, 34 small steps, and one optional extension phase |
| Implementation/testing/GitHub guidelines | Written |
| Fictional reference month | Created with independent expected results |
| Foundation verification | See the observed results in the verification record |
| Money and chart of accounts | Implemented: exact USD cents, immutable accounts/catalog, validated JSON loader |
| Application verification | 156 tests pass, including invalid inputs, CLI behavior and zero-test discovery failure |
| Demonstration | 13 accounts; 0.10 + 0.20 = 0.30 USD; excess precision rejected |
| Journal validation | Implemented: pure validation, field/line findings, exact totals, source/account/date checks |
| Journal demonstration | Accepts 1000.00 / 1000.00; rejects 1000.00 / 999.00 with a 1.00 difference |
| In-memory ledger | Implemented: single-entry admission, immutable snapshots, inclusive date cutoffs and exact trial balances |
| Ledger demonstration | T01–T09; 13 accounts; 13300.00 debit/credit totals; Cash 9400.00 debit |
| SQLite persistence | Implemented: atomic journals/events/retry records; schema v2 with additive v1 migration, immutable context, restart and concurrent safe retry |
| Persistence demonstration | Reopen/retry: 9 journals, 18 lines, 9 events; unchanged 13300.00 totals and 9400.00 Cash |
| Linked reversals | Implemented: exact inverse journals, durable original links, scoped retries, one reversal per original |
| Reversal demonstration | 125.00 expense canceled to zero; original receipt and historical snapshot preserved after reopen |
| Source registration | Implemented: structured fictional receipts, canonical content digests, immutable entity-scoped identities and atomic registration events in a separate SQLite registry |
| Source demonstration | Reopen/repeat retains one unchanged source; separate identity creates a second source; changed content is rejected |
| Draft review | Immutable revisions, evidence binding, pending/rejected queue and atomic retry/event storage |
| Local approval/posting | Exact human-reviewed revision/evidence/policy binding; atomic journal/audit link; immutable source-to-journal trail |
| Authenticated roles, agents, integrations | Not implemented |
| Delivery target | GitHub repository and CI; local CLI, no hosted deployment configured |
| Next step | Step 10 ready; Phase 03 complete; typed tools are next |

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
