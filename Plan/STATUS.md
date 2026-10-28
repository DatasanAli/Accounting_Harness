# Current status

Updated: 2026-10-28.

**Delivered:** [Step 35b authenticated offline scoring](09-integrations-and-pilot/STEP_35B_VERIFICATION.md):
14/14 exact proposals, 6/6 handoffs, 4/4 repeats, zero agent financial/close effects;
66 synthetic requests and 87 separate reviewer dependency postings. All 967 tests
and 51 demos passed locally and in [exact CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/40731822177).
Commit [`657481c`](https://github.com/DatasanAli/Accounting_Harness/commit/657481c5cbc3b97eb256d99d87321bf433b107d3) was pushed and matched `origin/main`.
Independent review fixes passed re-review. Step 35's offline provider controls are
complete; remaining G0 decisions, public compatibility review and live gates are next.

**Delivered:** [Step 35a durable evaluation controls](09-integrations-and-pilot/STEP_35A_VERIFICATION.md):
immutable experiment budgets, frozen semantic manifest and crash/deadline refusal.
Independent review fixes were rechecked; 950 tests and all 50 demonstrations passed
in [exact CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/40721400386). Commit [`ffed155`](https://github.com/DatasanAli/Accounting_Harness/commit/ffed1553da35bcff3bb763b960a097ba54d35acd)
was pushed and matched `origin/main`. [Step 35b authenticated scoring](09-integrations-and-pilot/STEP_35_PLAN.md)
is delivered; [G0 decisions](09-integrations-and-pilot/G0_DECISIONS.md) and all live gates
remain incomplete. The original 01–34 campaign below remains complete.

**Delivered:** Steps 01–11 and offline/local slices 12a–34. Step 31c local
verification, native browser rehearsal, independent review, upload and exact CI
passed; see [verification](09-integrations-and-pilot/STEP_31C_VERIFICATION.md).
Step 12 provider adapters/offline evaluation are implemented; live evaluation is deferred.
**Delivered:** [Step 32 approved offline journal export](09-integrations-and-pilot/STEP_32_VERIFICATION.md): 879 tests/46 demos, native browser and independent re-review passed. Commit `9bc2e49` and [exact CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39665520410) verified. Step 33a is also delivered: 899 tests/47 demos, restored browser and independent re-review passed; commit `ea85484` and [exact CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39669686628). [Recovery evidence](09-integrations-and-pilot/STEP_33A_VERIFICATION.md). Step 33b is delivered: 922 tests/48 demos, read-only native browser and independent re-review passed; commit `8e451a9` and [exact CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39672699408) verified. [Status evidence](09-integrations-and-pilot/STEP_33B_VERIFICATION.md). Step 34 and final adversarial fixes are delivered: 931 tests/49 demos, native browser and fresh recovery. Commit [`0a7b181`](https://github.com/DatasanAli/Accounting_Harness/commit/0a7b181424ce1944cc894897c8d727725bba8fc6) was pushed and matched `origin/main`; [exact GitHub CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39676697662) passed. See [acceptance evidence](09-integrations-and-pilot/STEP_34_VERIFICATION.md).

The 2026-10-21 request authorizes the [remaining offline campaign](AUTONOMOUS_DELIVERY.md). The remaining numbered offline implementation and adversarial review are complete. No further numbered offline step remains in that original campaign. Live provider/external-account connections and actual real-data pilot acceptance remain deferred.

The subsequent planning request is recorded in [deferred live verification gates](09-integrations-and-pilot/LIVE_VERIFICATION_GATES.md). This is a locally prepared plan only: no external calls or credential inspection, no new implementation, and no live gate marked passed. Provider scoring, sandbox transport/OAuth prerequisites, bounded experiments and separate approvals are explicit. It was initially kept local under that request’s no-external-calls constraint; the subsequent 2026-10-28 build-and-ship request authorized its upload with Step 35a.

## Verified application boundary

The persistent localhost app has exact USD cents, audited source enrollment,
immutable journal/reversal history, versioned drafts and separate human approval.
Supported services include cash recognition, vendor bills/settlement, customer
invoices/collections/aging, advances/earning, bank import/matching/fees/reconciliation,
supported prepaid consumption and evidenced unbilled expense/revenue accruals.
Every posted operation retains its source, effective date and actor; managed
controls enforce their approved effects.

Step 29b protects HTTP and direct application calls before financial storage opens.
Native preparer evidence/proposal followed by separate reviewer approval produced
one 125.00 USD journal; stable actors, fresh-process restart, revocation and entity
switching were observed. Historical records and report/package digests remain
unchanged in preservation tests. **802 tests and 41 demonstrations passed**, with foundation/JS/diff checks.
Independent review has no remaining Important or Critical findings. Verified
implementation commit and exact CI evidence are in
[Step 29b verification](09-integrations-and-pilot/STEP_29B_VERIFICATION.md).
A foundation check is not application proof.

Step 30 adds an **offline contract simulation** of one QuickBooks Online
JournalEntry read: bounded sandbox queries through an injected deterministic
simulator into a separate `qbo-staging.sqlite3` mirror. The local ledger stays
authoritative; staged journals never post. Two synthetic pages reconcile three IDs
at 600.00 USD per side with unchanged local books. Strict mapping/page refusals,
unsupported findings, atomic checkpoints, versions/conflicts, 429/transport resume,
caps and authenticated start/read permissions are tested. **824 tests and 42
demonstrations passed**; a native browser check passed. Live sandbox OAuth/compatibility
remains deferred. See [Step 30 verification](09-integrations-and-pilot/STEP_30_VERIFICATION.md).

Step 31a adds reviewed `nonoperating-cash-v1` owner contribution, owner drawing and
prepaid insurance purchase entries from a typed cash movement plus a separate
explicit classification fact. Preparing 10,000.00 / 200.00 / 1,200.00 creates no
journals. Three separate approvals give Cash 8,600.00, Capital 10,000.00 credit,
Drawings 200.00 and Prepaid 1,200.00. The existing coverage/consumption then gives
100.00 expense and 1,100.00 remaining with Cash unchanged. Review schema 12 adds the
policy's intent seal. **833 tests and 43 demonstrations passed**; a native browser
reference flow passed. See [Step 31a verification](09-integrations-and-pilot/STEP_31A_VERIFICATION.md).

Step 31b adds versioned `operational-v1` agent runs. A preparer selects one of the 13
delivered workflows and its registered inputs; per-run strict schemas expose only
read, propose (role assignment through the existing service) and handoff tools.
Approval, posting, account activation, evidence enrollment and closing stay human.
31/31 offline contract cases (fixture/reference playback, not model accuracy) gave
exact drafts for every workflow, handoffs (including fresh inactive 2000/2050) and
protocol/provider refusals with 0 journals posted by any run. Strict OpenAI/Ollama
tool-call adapters are tested with mocked transports. **842 tests and 44
demonstrations passed**; a native browser preparer/reviewer flow passed. See
[Step 31b verification](09-integrations-and-pilot/STEP_31B_VERIFICATION.md).

Step 31c integrates all 18 existing views into six task groups, with persistent
identity/entity/role/period/provider context, native history, readable evidence and
exact audit traces, and role-aware source/draft/approval/journal/report links.
Separate keyboard preparation/reviewer approval, refresh/Back confirmation reset,
process restart, revoked-session clearing and actual 390px/desktop layout checks
passed. Both assigned stale-context UI issues and the review-discovered malformed
hash/initialization issue are fixed. **860 tests and 45 demonstrations passed**;
independent re-review has no remaining findings. See [verification](09-integrations-and-pilot/STEP_31C_VERIFICATION.md).

The Step 20c implementation uses ledger schema 6, review schema 11 (12 since Step 31a), prepaid
schema 1 and expense/revenue-accrual schema 1. Step 22 adds close schema 1. Old expense captures remain v1;
new combined captures identify v2 even when empty. Account extensions are audited; old baseline contexts, approvals and captured reports
remain immutable. Provider choices exist for offline fixtures, Ollama and OpenAI;
real calls require explicit startup configuration and remain unverified. Receipt-expense
adapters keep their original contract; bounded operational proposals for the delivered
operations are versioned separately in [31b](09-integrations-and-pilot/STEP_31B_VERIFICATION.md), with live model accuracy unmeasured.

Captured financial statements, direct cash flow, portable report verification, confirmed close and durable date locks are implemented.
Project attribution, auditable service time, versioned project costing, operating/cash budgets, captured variances and contribution/indicator scenarios are implemented. Reviewed owner contribution, drawing and prepaid-purchase entry paths are implemented. Credentials, sessions, fixed entity roles and authenticated application/UI
enforcement are implemented. An offline QuickBooks journal-read contract into a
separate staging mirror is implemented; separately authorized offline export and verified recovery are implemented. New human actions carry authenticated stable user IDs. The [Phase09 plan](09-integrations-and-pilot/README.md)
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
| 29a | [Local identities and entity grants](09-integrations-and-pilot/STEP_29A_VERIFICATION.md) | [c480771](https://github.com/DatasanAli/Accounting_Harness/commit/c48077187bf96b0383f28f877292de7b9110e1b5) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/37853022426) |
| 29b | [Authenticated application and UI](09-integrations-and-pilot/STEP_29B_VERIFICATION.md) | [81a1d02](https://github.com/DatasanAli/Accounting_Harness/commit/81a1d021b4edd4aa3fc4bbce0f95e9177b363213) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/38635277919) |
| 31a | [Reviewed owner and prepaid cash entries](09-integrations-and-pilot/STEP_31A_VERIFICATION.md) | [68c450b](https://github.com/DatasanAli/Accounting_Harness/commit/68c450bf99bd173b63afbe54acc019f78602d4e8) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39453521635) |
| 31b | [Bounded operational agent proposals](09-integrations-and-pilot/STEP_31B_VERIFICATION.md) | [a0a9d86](https://github.com/DatasanAli/Accounting_Harness/commit/a0a9d86666ed39a19ad577692cb0d685cf24f433) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39463094489) |
| 30 | [Offline QuickBooks journal read](09-integrations-and-pilot/STEP_30_VERIFICATION.md) | [c022dfa](https://github.com/DatasanAli/Accounting_Harness/commit/c022dfa54b0d5a9042e5faecbf70cf33cd92beca) | [Passed (attempt 2)](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39278821004) |
| 31c | [Authenticated workbench](09-integrations-and-pilot/STEP_31C_VERIFICATION.md) | [068729a](https://github.com/DatasanAli/Accounting_Harness/commit/068729a5c10afc5c670bf77c3a5cdfdd25f85a98) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39644580556) |
| 32 | [Offline authorized export](09-integrations-and-pilot/STEP_32_VERIFICATION.md) | `9bc2e49` | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39665520410) |
| 33a | [Verified group recovery](09-integrations-and-pilot/STEP_33A_VERIFICATION.md) | `ea85484` | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39669686628) |
| 33b | [Redacted operational status](09-integrations-and-pilot/STEP_33B_VERIFICATION.md) | `8e451a9` | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39672699408) |
| 34 | [Synthetic acceptance and final adversarial fixes](09-integrations-and-pilot/STEP_34_VERIFICATION.md) | [0a7b181](https://github.com/DatasanAli/Accounting_Harness/commit/0a7b181424ce1944cc894897c8d727725bba8fc6) | [Passed](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39676697662) |

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

The two carried-forward accounting Minor findings (receipt list/tuple validation
and revenue error labels) and three additional final-review findings are fixed
and independently rechecked; see the [final review](09-integrations-and-pilot/ADVERSARIAL_REVIEW.md).
Step 31c resolved the two UI findings: project capture can no longer replace
attribution context during preview, and indicator month edits/failed reloads
invalidate cached inputs. Prior payable seal and
migration findings were resolved in16c. A copied-workspace run-path limitation was
reproduced in19a and is corrected by verified relocation in
[33a](09-integrations-and-pilot/STEP_33A_PLAN.md); file copying alone is not recovery.

Keep this page, [NEXT_STEP.md](NEXT_STEP.md), active phase and [roadmap.json](roadmap.json)
synchronized after each delivery. Full roadmap: [Plan index](README.md).
