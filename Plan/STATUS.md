# Current status

Updated: 2026-10-08.

**Delivered:** Steps 01–11 and offline/local slices 12a–28, plus identity-core 29a (upload pending). Step 12 provider
adapters/offline evaluation are implemented; the live evaluation is deferred.
**Next:** [Step 29b authenticated application/UI](09-integrations-and-pilot/STEP_29B_PLAN.md).

The user authorized the localhost app **and the wider accounting roadmap** on
2026-10-08. Continue through independently verified deliveries in this request;
commit/push/check exact CI for each. Do not stop for the earlier one-step cadence.
Live provider/external-account connections and actual real-data pilot acceptance
remain deferred, never passed by inference. See the [working plan](LOCALHOST_APP_PLAN.md)
and [exact next prompt](NEXT_STEP.md).

## Verified application boundary

The persistent localhost app has exact USD cents, audited source enrollment,
immutable journal/reversal history, versioned drafts and separate human approval.
Supported services include cash recognition, vendor bills/settlement, customer
invoices/collections/aging, advances/earning, bank import/matching/fees/reconciliation,
supported prepaid consumption and evidenced unbilled expense/revenue accruals.
Every posted operation retains its source, effective date and actor; managed
controls enforce their approved effects.

Latest local Step 29a checks: **776 tests and 40 demonstrations passed**.
Interactive hidden-passphrase CLI setup, two distinct entities, fixed role/entity
denials, grant revocation, logout and fresh-process sessions passed. A real draft
is prepared under an authenticated stable user ID with zero posting authority.
Original financial files, prior reports and scenario versions remain unchanged.
Independent review approved spec and quality with no findings. Commit/push/exact
CI are pending. Observations and commands are in
[Step 29a verification](09-integrations-and-pilot/STEP_29A_VERIFICATION.md).
HTTP and UI remain unauthenticated until the separate Step 29b integration.
A foundation check is not application proof.

The Step 20c implementation uses ledger schema 6, review schema 11, prepaid
schema 1 and expense/revenue-accrual schema 1. Step 22 adds close schema 1. Old expense captures remain v1;
new combined captures identify v2 even when empty. Account extensions are audited; old baseline contexts, approvals and captured reports
remain immutable. Provider choices exist for offline fixtures, Ollama and OpenAI;
real calls require explicit startup configuration and remain unverified. Existing
agent adapters initially cover receipt expenses; broader bounded operational
proposals are planned in [31b](09-integrations-and-pilot/STEP_31B_PLAN.md).

Captured financial statements, direct cash flow, portable report verification, confirmed close and durable date locks are implemented.
Project attribution, auditable service time, versioned project costing, operating/cash budgets, captured variances and contribution/indicator scenarios are implemented. The identity core now supplies credentials, sessions and fixed entity roles.
Authenticated application/UI enforcement, integration contracts and verified
recovery remain planned. The existing HTTP local operator is not an authenticated reviewer. The [Phase09 plan](09-integrations-and-pilot/README.md)
separates implemented offline contracts from future live gates.

## Delivery evidence

Each row links observed local/browser/review evidence, the delivered commit and
its successful exact-SHA GitHub run. Historical intermediate failures/fixes are
retained in the verification record and Git history.

| Step | Delivered behavior and verification | Commit | Exact CI |
| --- | --- | --- | --- |
| 12a | [Localhost workspace](04-agent-harness/STEP_12A_VERIFICATION.md) | [ddf53f9](https://github.com/DatasanAli/Accounting_Harness/commit/ddf53f93846ec92edf179b62b4523f72c497e2f7) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37786950606) |
| 13a | [Evidence enrollment](05-service-bookkeeping/STEP_13A_VERIFICATION.md) | [67ca31c](https://github.com/DatasanAli/Accounting_Harness/commit/67ca31ca8afcd12d42810d8e3690830c96488fc7) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37788816873) |
| 13b | [Cash templates](05-service-bookkeeping/STEP_13B_VERIFICATION.md) | [887cc4e](https://github.com/DatasanAli/Accounting_Harness/commit/887cc4e974c196913432c0006bf7d1e24e5af096) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37791223746) |
| 14a | [Vendor bills](05-service-bookkeeping/STEP_14A_VERIFICATION.md) | [ff9a1cb](https://github.com/DatasanAli/Accounting_Harness/commit/ff9a1cba9f26d83010112657a52adcb45df9b505) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37794830614) |
| 14b | [Partial vendor settlement](05-service-bookkeeping/STEP_14B_VERIFICATION.md) | [0e06160](https://github.com/DatasanAli/Accounting_Harness/commit/0e061604d57c3f70400a10e6f39bb1e7a5c0ecf8) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37797498803) |
| 15a | [Customer invoices](05-service-bookkeeping/STEP_15A_VERIFICATION.md) | [0176f99](https://github.com/DatasanAli/Accounting_Harness/commit/0176f99c6bce416f2f38ab83c00221e8a1e9af09) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37800424176) |
| 15b | [Collections and aging](05-service-bookkeeping/STEP_15B_VERIFICATION.md) | [f29ac94](https://github.com/DatasanAli/Accounting_Harness/commit/f29ac946ae743c630100feae42ebc1d3c458136a) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37802605944) |
| 16a | [Customer advances](05-service-bookkeeping/STEP_16A_VERIFICATION.md) | [8deae9b](https://github.com/DatasanAli/Accounting_Harness/commit/8deae9b781ddf1a8621647cd0e8d76017290e0b6) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37805104017) |
| 16b | [Supported advance earning](05-service-bookkeeping/STEP_16B_VERIFICATION.md) | [d57ca17](https://github.com/DatasanAli/Accounting_Harness/commit/d57ca177a53f0b8f3e8e878d4bdc6ae0d7615270) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37807454834) |
| 16c | [Payable seal hardening](05-service-bookkeeping/STEP_16C_VERIFICATION.md) | [0cc3e5f](https://github.com/DatasanAli/Accounting_Harness/commit/0cc3e5f9fc4f66d0412d45d31f9559ba22e2cea6) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37809290761) |
| 17 | [Bank statement import](06-bank-reconciliation/STEP_17_VERIFICATION.md) | [4971d13](https://github.com/DatasanAli/Accounting_Harness/commit/4971d138d0100eea4cca05534659a8cd3fd0eb56) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37811461472) |
| 18 | [Confirmed bank matching](06-bank-reconciliation/STEP_18_VERIFICATION.md) | [aa7a975](https://github.com/DatasanAli/Accounting_Harness/commit/aa7a97575878aa9e32a395ad2b4e69c6b339526a) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37814013196) |
| 19a | [Audited fee account](06-bank-reconciliation/STEP_19A_VERIFICATION.md) | [361459d](https://github.com/DatasanAli/Accounting_Harness/commit/361459d215050cc4bc05ebcb98180a83360d6258) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37815799255) |
| 19b | [Reviewed bank fee](06-bank-reconciliation/STEP_19B_VERIFICATION.md) | [757e6fd](https://github.com/DatasanAli/Accounting_Harness/commit/757e6fda735da408c4717e7579d0351847a29cda) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37817880835) |
| 19c | [Captured reconciliation](06-bank-reconciliation/STEP_19C_VERIFICATION.md) | [c4edae4](https://github.com/DatasanAli/Accounting_Harness/commit/c4edae4bc77151bad6dd796a89d5200158f1aa8c) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37820570127) |
| 20a | [Prepaid consumption](07-period-close/STEP_20A_VERIFICATION.md) | [ab557e4](https://github.com/DatasanAli/Accounting_Harness/commit/ab557e4581a705a776d613a4790e384eb71b038b) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37823178380) |
| 20b | [Unbilled expense accrual](07-period-close/STEP_20B_VERIFICATION.md) | [d3511be](https://github.com/DatasanAli/Accounting_Harness/commit/d3511be23bfcdea6fb23629e91bb0f0f592932ec) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37826947400) |
| 20c | [Unbilled service revenue](07-period-close/STEP_20C_VERIFICATION.md) | [57e1ad9](https://github.com/DatasanAli/Accounting_Harness/commit/57e1ad97761124ca4d0990910e4f265d15c6bcea) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37829402673) |
| 20d | [Adjusted operational month](07-period-close/STEP_20D_VERIFICATION.md) | [56d2548](https://github.com/DatasanAli/Accounting_Harness/commit/56d2548598b089358ad8e1af579446eb9b77ee2e) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37830844808) |
| 21 | [Captured financial statements](07-period-close/STEP_21_VERIFICATION.md) | [511d932](https://github.com/DatasanAli/Accounting_Harness/commit/511d93203a82227b00794462267b372a2e275178) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37832868799) |
| 22 | [Confirmed close and date locks](07-period-close/STEP_22_VERIFICATION.md) | [1bdb15e](https://github.com/DatasanAli/Accounting_Harness/commit/1bdb15e9e98dc1f188fb5de2b410c5f9793b620c) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37834858650) |
| 23a | [Captured direct cash flow](07-period-close/STEP_23A_VERIFICATION.md) | [969b783](https://github.com/DatasanAli/Accounting_Harness/commit/969b783b2cf105114501403c0879380d696743c5) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37836761506) |
| 23b | [Portable report packages](07-period-close/STEP_23B_VERIFICATION.md) | [bf1fbb8](https://github.com/DatasanAli/Accounting_Harness/commit/bf1fbb8e369549babc02b007778574e72bc4ab3d) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37839537188) |
| 24a | [Project attribution](08-service-management/STEP_24A_VERIFICATION.md) | [c5ce264](https://github.com/DatasanAli/Accounting_Harness/commit/c5ce264412de606bd620dbae5538bf4080347b92) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37841528029) |
| 24b | [Auditable project time](08-service-management/STEP_24B_VERIFICATION.md) | [d745540](https://github.com/DatasanAli/Accounting_Harness/commit/d74554063e385b57b66d69301e7fa7cac1d93d73) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37843247067) |
| 25 | [Versioned project costing](08-service-management/STEP_25_VERIFICATION.md) | [c95bf45](https://github.com/DatasanAli/Accounting_Harness/commit/c95bf4599fd4fa63bddd8ae72cfb8e37f500d0ad) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37845470497) |
| 26 | [Operating and cash budgets](08-service-management/STEP_26_VERIFICATION.md) | [4affff5](https://github.com/DatasanAli/Accounting_Harness/commit/4affff50b34a527152e121fdd66a12f152312d32) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37847329847) |
| 27 | [Captured flexible-budget variance](08-service-management/STEP_27_VERIFICATION.md) | [b5b6b02](https://github.com/DatasanAli/Accounting_Harness/commit/b5b6b02c15290b7e446a4a34a5eb881c39451c5b) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37848793541) |
| 28 | [Contribution and captured indicators](08-service-management/STEP_28_VERIFICATION.md) | [b7f4a3a](https://github.com/DatasanAli/Accounting_Harness/commit/b7f4a3a93ab651b1e60444c4e2904a9e7f373469) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37851117480) |
| 29a | [Local identities and entity grants](09-integrations-and-pilot/STEP_29A_VERIFICATION.md) | Local checks/review passed | Upload pending |

Earlier foundations and Steps 02–11 are documented in [Phase01](01-foundation/README.md),
[ledger core](02-ledger-core/README.md), [evidence/review](03-evidence-and-review/README.md)
and [agent harness](04-agent-harness/README.md). Step 12's [verification record](04-agent-harness/STEP_12_VERIFICATION.md)
records only offline adapter results; no live accuracy, latency or billed-cost
claim is made. Its user-deferred live gate remains visible in [roadmap.json](roadmap.json).

## Policy and remaining scope

The working example is a fictional USD service business, accrual bookkeeping,
owner capital/drawings and January2026. Actual legal form, reporting framework,
fiscal calendar, accounting policies, users/data permissions and retention must be
confirmed before a real-data pilot. Books/PDFs, extracted text, databases and
credentials stay local; GitHub contains original code/docs and synthetic fixtures.
Textbook coverage is recorded in the [source map](SOURCE_MAP.md).

The original T03 insurance purchase is Jan3, while the supported policy requires
purchase by its Jan1 coverage start. Step20d explicitly uses a new synthetic Jan1
purchase variant, preserving original fixture/history bytes and identical
January 31 totals; early cutoff results are intentionally different.

Four Minor issues are queued for final whole-work review: receipt list/tuple
validation consistency (saved proposals normalize before posting), shared
revenue-validation errors using an expense label, and an in-flight project capture
replacing attribution preview context (server binding remains protected), and
indicator month controls retaining cached inputs after an edit or failed reload.
The two UI findings are assigned to Step 31c. Prior payable seal and
migration findings were resolved in16c. A copied-workspace run-path limitation was
reproduced in19a and has an explicit verified-relocation plan in
[33a](09-integrations-and-pilot/STEP_33A_PLAN.md); file copying alone is not recovery.

Keep this page, [NEXT_STEP.md](NEXT_STEP.md), active phase and [roadmap.json](roadmap.json)
synchronized after each delivery. Full roadmap: [Plan index](README.md).
