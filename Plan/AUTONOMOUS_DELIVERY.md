# Remaining offline delivery campaign

The user authorized autonomous completion on 2026-10-21 of the remaining numbered steps, starting at Step 32, followed by an adversarial review of the important phases and correction of identified loopholes. This supersedes the usual stop-after-one-step cadence for this campaign. Each delivery still requires verification, a commit, upload and exact-commit CI evidence.

| Delivery | State | Evidence |
|---|---|---|
| 32: separately authorized offline journal export | Delivered; exact CI passed | [Verification](09-integrations-and-pilot/STEP_32_VERIFICATION.md) |
| 33a: coherent backup and verified relocation | Local verification complete; upload/CI pending | [Verification](09-integrations-and-pilot/STEP_33A_VERIFICATION.md) |
| 33b: redacted operational visibility | Next | Pending |
| 34: authenticated synthetic release rehearsal | Pending | Pending |
| Cross-phase adversarial review and fixes | Pending | Pending |

The optional Phase 10 backlog is outside this campaign. Live model evaluation, real sandbox connections and actual real-data pilot acceptance remain deferred. No offline result satisfies those gates.

Preserve unrelated `.cognee-dataset`, `.vscode/`, and `CLAUDE.md` files. Keep local evidence, databases, backups and credentials out of commits.

CI budget: increased the job timeout from five to ten minutes. Step 31c already took 4m02s in GitHub (860 tests); the remaining recovery and acceptance checks add work. This is a job ceiling, not a relaxed test assertion.

## Final adversarial review scope

After Step 34, independently challenge these boundaries and correct material findings with regression checks and re-review:

- Accounting authority: exact arithmetic, supported entry shapes, source binding, stale approval, atomic posting, linked reversals, period locks and subsidiary controls.
- Identity and agents: direct API role/entity enforcement, revocation, browser state isolation, document injection, agent tool permissions and durable replay.
- Integration: separate export authorization, immutable destination/body/request ID, lost-response retry, concurrent send, exact readback, drift and local reversal.
- Recovery: complete group roster, coherent maintenance snapshot, strict manifest/path handling, historical identity preservation, authenticated relocation, session revocation and disabled transports.
- Reports and management: captured snapshot reproducibility, portable exact readback and separation of modeled assumptions from actual journals.

Carry-forward review items: receipt list/tuple validation consistency, shared revenue validation errors using an expense label. These must receive an explicit disposition in the final review record.
