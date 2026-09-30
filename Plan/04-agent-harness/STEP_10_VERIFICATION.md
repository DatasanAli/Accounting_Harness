# Step 10 verification and tool boundary

Observed 2026-09-30: 168 application tests pass. Foundation verification and all nine demos pass. Added 11 agent-tool/evaluator tests and one CLI demo test. Red checks observed missing tool/evaluator modules, missing CLI command, and an evaluator that initially failed to check retained revisions after denied calls. Each passes after implementation/fix. Independent review found no blocking boundary issues and suggested the retained-history assertion now covered by regression.

`AgentTools(store, actor_id).schemas()` returns JSON schemas for exactly `read_accounts`, `get_evidence`, `validate_proposal`, `save_draft`, `request_review`. `call(name, arguments)` enforces those contracts; all arguments include the fixed entity ID. Actor is constructor-controlled, sources require exact registered identity/digest, draft writes reuse atomic scoped retries, and unknown/approval/posting/reversal/SQL operations are denied. Example: `tools.call('get_evidence', {'entity_id': 'demo-service-001', 'source_id': 'rent'})` returns registered content. `request_review` acknowledges the pending item already persisted by save; it is read-only and grants no authority.

`python3 -m accounting_harness demo-tools` demonstrates accounts → evidence → validation → saved rent revision 1 → human review. Proposed lines are 5000 debit 1200.00 / 1000 credit 1200.00 USD. Ledger snapshots remain unchanged; zero unauthorized postings. Observed corpus v1 results:

| Category | Passing / total |
| --- | --- |
| Clean | 3 / 3 |
| Malformed | 4 / 4 |
| Missing | 2 / 2 |
| Conflict | 2 / 2 |
| Ambiguous | 3 / 3 |
| Duplicate | 3 / 3 |
| Unsupported | 4 / 4 |
| Hostile | 3 / 3 |
| Total | 24 / 24 |

Evaluation compares explicit account/amount labels, expected finding codes, rejection messages, revision history and unchanged ledger snapshots. A balanced uncertain classification remains pending human review. Changing an expected account/revision makes evaluation fail; an empty corpus fails. These are deterministic fake tool sequences with real tool results, not a live model or model-accuracy evaluation. The run loop, checkpoint/budget/retry scheduler and real provider remain Steps 11–12.

No storage schema changes. Rollback removes exposure via a new revert commit while retaining drafts and evidence. This is a JSON capability boundary for trusted runtime code, not an untrusted Python sandbox. Local authenticated roles remain Step 29. Exact GitHub commit/Actions evidence is checked after commit/push and reported in the delivery response.
