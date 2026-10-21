# Final adversarial review of the offline campaign

Reviewed 2026-10-21 across accounting, identity/agent/UI, integration/recovery and report/management boundaries. Three independent reviewers examined the campaign from `dbaa8a1` through Steps 32–33b and the frozen Step 34 working tree on `803009e`, including new files. They reproduced suspected failures and tested the acceptance contract. Final reviewed fixes ship with [Step 34](STEP_34_VERIFICATION.md).

No Critical or Important defect was reproduced in this final review. Five Minor findings were corrected in one focused wave and independently re-reviewed. **No review findings remain open.** This records tested scope, not a claim that no possible defects exist.

| Finding | Observed loophole | Correction and recheck |
| --- | --- | --- |
| A1: receipt containers | Direct tuple input could report false evidence binding or omit extension-account/storage-overflow findings; saved JSON normalized to lists and refused unsupported entries. | Apply the same checks to lists and tuples. Original reproductions and regressions agree; malformed shapes remain invalid. No posting bypass was reproduced. |
| A2: accrual error identity | Shared revenue validation/posting errors named expense accrual. | Use existing policy metadata in both paths; regressions retain correct revenue and expense labels. |
| B1: acceptance metric | A field named pending counted zero journals despite one pending draft. | Report measured `agent_journals_before_review=0`, `agent_pending_drafts_before_review=1` and one journal after review. Authenticated acceptance recheck passed. |
| C1: project-cost ownership | Caller request mutation changed returned recomputed cost from 700.00 to 600.00; returned policy edits changed later eligible inputs. Persisted scenarios/journals were unchanged. | Detach nested request and outward policy metadata through existing canonical JSON. Reproduction now retains recorded/recomputed/persisted 700.00 and one eligible input after caller edits. |
| C2: export evidence | Step 32 attributed lost-response/reopen behavior to a CLI demo that performs normal send/readback and same-facade replay. | Correct attribution to focused tests and Step 34's actual fault-injection scenario. Re-review confirmed the evidence. |

Initial reviewers ran 24 accounting, 74 identity/agent and 12 integration/report checks, plus independent reproductions. Scoped re-reviews ran four accounting checks, one authenticated acceptance check and four project-cost checks, and inspected the documentation correction. Root then ran **931 tests and all 49 demonstrations** and completed native-browser/restored-group checks. Exact release/CI evidence is in the [acceptance record](STEP_34_VERIFICATION.md).

Earlier campaign review corrected consequential failures before those steps shipped:

- Step 32: drift could be lost across a later timeout/matching read; historical drift now remains an exception. Canonical audit text also avoids JavaScript large-integer rounding. [Evidence](STEP_32_VERIFICATION.md).
- Step 33a: altered schema with an unchanged version marker could pass recovery validation; verification now compares complete normalized schemas with shipped initializers. Receipt publication also syncs its parent directory. [Evidence](STEP_33A_VERIFICATION.md).
- Step 33b: Skip to workspace followed by Refresh could load ordinary state and enroll pending evidence during status inspection. Routing/startup now retain the status view; native reproduction and unchanged-store checks passed. [Evidence](STEP_33B_VERIFICATION.md).

Final review covered exact posting/evidence/approval/period locks and controls, direct role/entity/revocation enforcement, bounded agent tools and durable replay, export authority/immutable retries/concurrency/drift, complete-group recovery/schema/path/session/transport boundaries, and report/management reproducibility. Trusted local file ownership is not an adversarial filesystem boundary. Offline simulators do not prove live provider quality, external API compatibility, production deployment safety or actual real-data pilot acceptance; those gates remain deferred.
