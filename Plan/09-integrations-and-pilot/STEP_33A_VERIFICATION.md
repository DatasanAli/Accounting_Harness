# Step 33a verification: coherent group backup and recovery

Local implementation, restored-browser rehearsal and independent re-review passed. The guarded suite, upload and exact CI passed.

## Delivered behavior

The maintenance CLI captures the identity database and every configured synthetic entity as one bounded group. Shared application locks, exclusive maintenance locks and a fixed SQLite writer-reservation order prevent mixed snapshots. SQLite backup APIs capture committed data; a strict manifest records the fixed roster, content/schema hashes, schema/context identities, counts and exact cross-store verification results.

Restore validates a private staging directory, rejects overlap/symlink/path/schema/context/corruption problems, and publishes through an atomic no-replace operation. Originals remain intact. Recovery activation remaps entity destinations and revokes old sessions with audit. A fresh login is required.

Versioned relocation records retain historical logical ledger/source/run paths and scope bytes while using new physical files and dispatch locks. Both legacy and operational effect-before-checkpoint runs resume without another proposal effect. Subsequent relocation preserves the first logical origin. Pending evidence enrollment is retained until an explicit supported action.

Recovered provider and external transports remain disabled, including when the server receives `--enable-providers`. Uncertain exports remain inspectable and unresolved; restore does not send them. Successful backup and restore receipts are operational metadata, separate from financial/run history.

See the [operator runbook](RECOVERY_RUNBOOK.md). Hashes detect damage relative to a trusted local manifest; they do not authenticate an arbitrary imported backup. Supported runtime is the existing local macOS/Linux application.

## Synthetic drill and checks

The two-entity drill includes posted/pending/rejected reviews, legacy and operational runs interrupted after a proposal effect, bank/report/management records and a simulated uncertain export. It preserves 11 journals and 11 drafts; both interrupted runs recover without another draft. Journal, trial-balance, source, review, report and checkpoint comparisons passed. The browser's ten financial/run/integration store dumps were identical before and after inspection and denied transport attempts; session activity is intentional authentication metadata.

Final demonstration on Python 3.13.1, SQLite 3.45.3, macOS: 1,753,088 bytes, backup 186ms (verification 28ms), restore 63ms (verification 29ms). These are observed synthetic timings, not a recovery SLA. Cold schema validation includes constructing disposable reference schemas.

Recovery tests cover 38 injected fault boundaries, all optional stores, supported migration variants, concurrency, wrong context/version, corruption, path attacks, prior-session revocation, repeated relocation and immutable historical identity. Review found that same-version altered columns/constraints/protections could pass a table-roster check. Verification now compares full normalized schema structure against shipped initializers. A second finding added directory synchronization after receipt replacement. Both received regression checks; independent scoped re-review ran four targeted tests and approved with no remaining finding.

The complete 47-demo command set passed before those two recovery fixes; the affected recovery demonstration passed again afterward. Foundation, JavaScript syntax and diff checks passed. Final guarded suite: **899 tests passed in 127.140s**. The zero-discovery guard remains intact.

## Browser rehearsal

A fresh restored artifact opened in the actual loopback server with fresh owner login. It displayed 11 journals, exact 13,300.00 per-side trial balance, 24 evidence records and pending/rejected/posted reviews. Keyboard navigation followed the original approval to its journal and source evidence. The uncertain export appeared without a send control. At 390px, the document width matched the 375px content width.

Direct authenticated export-send and OpenAI-run requests returned HTTP 409, despite starting the server with the enable flag; journal and run counts stayed 11 and 2. Offline playback remained available; Ollama/OpenAI were unavailable. A misleading role hint for recovery-disabled controls was corrected, regression-tested and verified in the final browser. The final bundle still verifies after the schema-hardening fix without changing its format or identity.

## Delivery

Implementation commit `ea8548448059dc3fc02b154e1d00ab0e2220f076` was pushed to `origin/main`. [Exact-commit GitHub CI](https://github.com/DatasanAli/Accounting_Harness/actions/runs/39669686628) passed. Next authorized delivery: Step 33b operational status, then Step 34 and final cross-phase adversarial review/fixes. Live gates remain deferred.
