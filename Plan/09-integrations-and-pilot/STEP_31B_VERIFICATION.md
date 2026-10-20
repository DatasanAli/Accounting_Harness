# Step 31b verification: bounded operational agent proposals

Date: 2026-10-20. Scope: Step 31b only, with temporary synthetic workspaces and
fictional evidence. No live Ollama/OpenAI call, model download, live connection or
real financial data. Local verification and independent review passed.

## Delivered behavior

`accounting_harness/operational_agent.py` adds the versioned `operational-v1` run
contract beside the unchanged receipt-expense runs, in a separate
`agent-runs.sqlite3` log.

- **Fixed workflows.** An authenticated preparer selects one of the 13 delivered
  operations and the registered inputs the agent may read:
  - cash expense and earned cash;
  - vendor bill and payment;
  - customer invoice and collection;
  - customer advance and earning;
  - bank fee;
  - prepaid consumption;
  - expense and revenue accrual;
  - owner/prepaid cash.

  A run takes at most 8 evidence IDs and exactly one target (bill, invoice, advance or
  bank transaction) when the workflow needs one. Starting a run validates the
  selection: evidence must be enrolled schema-v2 in this entity, and the target must
  be an existing posted item.
- **Tools.** Each run stores strict per-run schemas for `read_accounts`,
  `read_evidence`, `read_target`, `read_report` (trial balance with snapshot digest and
  policy), `propose_operation` and `handoff_review`.
  - Enums narrow every reference to the human selection, and the prepaid month to the
    open period.
  - There are no fields for journal lines, amounts, accounts, actor, entity, SQL,
    paths, URLs or code. Unknown tools and extra fields are refused.
  - Resumed runs validate calls against their stored schemas, never against an
    expanded current toolset. A changed contract cannot reopen the log.
- **Service routing.** `propose_operation` supplies only role assignments to the
  existing `Workspace.prepare_*` service, which rebuilds the journal from evidence.
  - Drafts are attributed to `operational-agent`; the run records its initiating user.
  - The bank-fee classification is fixed by the workflow, and its reason is an
    operator input the human enters at run start, bound to the one selected
    transaction.
  - The bank-fee service registers its deterministic copy of the human-imported
    statement line, exactly as the human path does; the agent never supplies that
    content.
- **No implicit activation.** If a workflow would activate 2000, 1100, 2100, 2050,
  1150 or 5300, the run hands off until an authorized human activates the account.
  This holds even when an owner started the run.
- **Handoffs.** A service refusal, a model handoff or a saved draft with findings
  ends in `awaiting_review` with attributable findings. Model prose is stored and
  shown as an *unverified explanation*, with citations limited to the selected
  inputs. Successful drafts await a separate exact human approval. A later human
  revision is shown against the handed-off revision.
- **Durability.**
  - Each tool call has a stable run-specific idempotency key; human requests keep
    their prior data-derived keys byte for byte.
  - A tool commit runs inside the guarded run transaction, so revocation stops it and
    cancellation cannot interleave. A process stop after a draft commit is recovered
    from the review receipt as exactly one draft.
  - The identity lock is never held across a provider request.
  - Timeouts retry once, then fail visibly. Tool-call, time and cost budgets exhaust
    visibly, and a cancellation beats a late response.
- **Stored data.** The run log stores task, contract and tool schemas, provider/model/
  prompt identity and fingerprints, source/report references and digests, usage,
  findings and stop reasons. It stores no prompts, raw provider payloads, hidden
  reasoning or credentials.
- **Adapters.** OpenAI uses Responses function calling: strict tools,
  `tool_choice: required`, `parallel_tool_calls: false`, `store: false`, exactly one
  `function_call` item. Ollama uses loopback `/api/chat` tool calling with exactly one
  `tool_calls` entry whose arguments are an object. Schemas were checked against
  current official docs: every property is required, there is no `minLength`, and
  enums are non-empty.
  - Real calls still need the existing startup opt-in; tests inject transports.
  - Offline playback is a deterministic reference script that binds roles by typed
    evidence kind. It is labeled "not a model".
- **UI, HTTP and CLI.**
  - The Agent runs view has a workflow, provider and evidence selection form (preparer
    only) and run cards. Cards show the model, outcome, service-built lines,
    handoff findings and unverified explanations, and a cancel control for the
    initiator.
  - `POST /api/agent-proposals` (`start_run`) and `/api/agent-cancel` (`cancel_run`).
  - New demo: `demo-operational-agent`.

## Offline contract results

These are application-enforcement results only. Fixture and reference playback is
not model inference, and **live Ollama/OpenAI accuracy remains unmeasured**.
[`operational-agent-cases.json`](../../data/fixtures/operational-agent-cases.json) has
31 cases, each with an independently written expected outcome, policy and journal
lines. **31/31 matched, and every run posted 0 journals.**

| Category | Cases | Covered |
| --- | --- | --- |
| Reference | 14 | One exact service-built draft per workflow (13) plus an owner drawing after a timeout |
| Handoff | 6 | Inactive 2000 and fresh inactive 2050, missing basis, conflicting amounts, duplicate evidence, hostile-text model handoff |
| Protocol refusal | 7 | Forged `approve_post` after hostile evidence, injected journal lines, forged actor/entity fields, unselected reference, invented citation, malformed output, tool outside the run |
| Provider fault | 4 | Retry exhaustion, tool-call budget, script exhaustion, timeout then success |

Only the five simulated human approvals in the corpus posted journals.

## Automated evidence

Observed local results: **842 application tests** (833 prior + 9 new) and **all 44
CLI demonstrations** passed, along with the foundation links/reference accounting,
JavaScript syntax and diff whitespace checks.

```sh
python3 -m unittest discover -s tests -p test_operational_agent.py -v
python3 scripts/run_tests.py
python3 scripts/verify_foundation.py
node --check accounting_harness/static/app.js
git diff --check
python3 -m accounting_harness demo-operational-agent
```

The new tests cover:
- the corpus against its expectations;
- a fresh inactive accrual account left inactive;
- crash-after-commit recovery through both resume and cancel;
- a human-changed draft whose old handoff cannot post;
- cancellation during a live request, immutable per-run contracts and an unchanged
  legacy expense run;
- strict OpenAI/Ollama parsing, schema bounds and stored references, with no stored
  secrets, raw payloads or prompt;
- start-scope refusals, including a second bank line;
- authenticated attribution, role denial, owner handoff and mid-run revocation;
- HTTP, UI and the demo.

Red/green: the tests were written after the first implementation, so four mutation
checks substituted for the missing red step. Removing the activation check, the
schema check, receipt recovery or the per-step authority guard each made a test
fail. The first full run exposed a UI test slicing app.js from its last
`setInterval(async () => {` to the end of the file; the new block was moved above it.

## Browser demonstration

A temporary workspace (`alpha`) with separate preparer and reviewer users was
served on 127.0.0.1:8799. Headless Chrome 155 was driven over the DevTools protocol
by a throwaway script outside the repository.

The preparer registered owner contribution (5,000.00) and drawing facts through the
existing native forms. In Agent runs, the only provider offered was "Offline reference
playback · not a model", and a fresh run ID was generated (and regenerated after
submit).
- An owner-contribution run prepared one `nonoperating-cash-v1` draft with
  server-calculated lines 1000 / 3000 at 5,000.00.
- A run with only the drawing cash document handed off as missing evidence. Its
  unverified-explanation label and citation were shown.
- Result: **0 journals** and no approve control for the preparer.

The reviewer did not get the run form. The reviewer approved the agent draft in the
review queue, giving 1 journal (Cash 5,000.00 / Capital 5,000.00). The approval was
attributed to the reviewer and the draft to `operational-agent`.

No JavaScript exception or app console error occurred. The only failed requests
were the existing signed-out `/api/session` probe before each login and Chrome's
automatic `/favicon.ico` request (403). The server and browser were stopped.

## Review, delivery and rollback

Independent adversarial review probed:
- service side effects and account activation;
- forged and unselected inputs and role swaps;
- authority, deadlock ordering, cancellation and revocation;
- crash recovery across all 31 corpus runs (15/15 drafts recovered exactly once);
- busy retries and duplicate runs (0 extra drafts);
- regressions of keys, trial balance and legacy scope;
- strict-schema compatibility and UI slices and escaping.

It found **one Important issue, now fixed**: with several bank lines selected, the
model chose which line received the operator's fee classification. A run now takes
exactly one human-selected target. It also found five Minors, all fixed:
- an unrestricted prepaid month now enumerates only the open period, and a draft
  with findings reports `draft_not_reviewable`;
- the handoff explanation schema now advertises its server pattern;
- the UI run ID is now generated per run;
- read checkpoints now record source/report references;
- human-changed drafts are now visible and tested.

A re-review reran every probe against the fixed tree and confirmed all six fixes,
with no regressions and **no remaining Critical or Important issues**. Its cosmetic
nit (a non-reviewable draft card still said "awaits separate human review") is fixed.

GitHub delivery and exact-SHA CI are pending at the time of this record.

Rollback uses a new revert commit. The run log is a separate new file and no
ledger, review or source schema changed. Reverting leaves `agent-runs.sqlite3`
unused, and agent-prepared drafts remain ordinary reviewable drafts. Correct posted
entries with linked reversals.
