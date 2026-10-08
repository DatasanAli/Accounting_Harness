# Step 31b: bounded operational agent proposals

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 31a.

**Goal:** Let a configured local or frontier model read supported accounting state
and prepare supported operational drafts through deterministic existing services.

**Architecture:** Add a versioned operational run contract beside the existing
receipt-expense contract. The user selects a supported task and registered input
references; the runtime exposes only that task's read/propose/review-handoff tools.
Adapters translate model responses to strict requests. Services reconstruct all
journals and amounts, and human approval remains outside the run.

**Tech stack:** Existing Python run engine, Ollama/OpenAI adapters and offline tests.
**Spec:** [Step 31](STEP_31_PLAN.md), all global constraints apply.

## Supported capability boundary

Inventory current deterministic proposal entry points and route through them:
cash expense/earned service, vendor bill/payment, invoice/collection, customer
advance/earning, bank fee, prepaid consumption, expense/revenue accrual, and owner/
prepaid cash templates. A model may propose an operation only when the user has
selected that workflow and the required registered source IDs or existing
subsidiary IDs are in its authorized entity context. Do not add accounting policies
or infer missing structured facts to make an unsupported task succeed.

Read tools provide current account metadata, selected registered evidence,
current eligible subsidiary balances, and captured deterministic reports with
snapshot/policy/digest references. Use fixed report and operation enums, strict
per-operation JSON schemas and bounded result sizes; no SQL, paths, URLs or
arbitrary Python. A proposal request uses evidence/target IDs and only the explicit
inputs already accepted by its deterministic service. Never accept model-supplied
journal lines or an unchecked amount for a calculated coverage/accrual/fee result.

A request for missing/conflicting evidence, unsupported calculation or unclear
classification ends in an attributed review handoff with findings. Statements
and numeric reports display server-calculated values. Model prose is labeled as
an unverified explanation with cited input references; invented references or
unsupported causal claims cannot become validated accounting facts.

Check service side effects as well as tool names. If a supported proposal would
implicitly activate a missing account, the agent must hand off until an authorized
human activates it; wrapping an activating service in `propose_operation` does not
make activation an allowed model action. Tests must exercise a fresh inactive
accrual account, not only an already prepared demonstration workspace.

No tools for evidence enrollment, account activation, approval, posting, bank
completion, closing, permission changes, backup restore or export authorization.
The model cannot name its actor or gain a reviewer role from the initiating user.
Before a tool side effect, revalidate authenticated entity access and run scope;
revoked users cannot continue mutating drafts through an old run token.

Extend the existing durable run receipt/checkpoint mechanism, including stable
per-call idempotency keys and recovery after a draft save before checkpoint.
Record task/toolset/schema/model/prompt versions, source/report references and
stop reasons without storing hidden reasoning or credentials. Old runs resume
under their original contract, never an automatically expanded toolset.

## Provider and evaluation contract

Keep explicit startup opt-in for real provider calls and secrets server-side.
Ollama base is a bounded configured loopback service; frontier API credentials
remain environment/local-secret inputs, never browser storage. Do not connect,
download models or invoke a live provider during this request.

Inspect the installed adapter code and current official provider docs before
choosing structured-output details. Use the OpenAI documentation skill for any
OpenAI-specific API changes. Preserve old adapters and model identities; version
new operational prompts/schemas and make the configured model visible in the UI.
Errors such as unavailable provider, invalid JSON, wrong schema, unsupported tool,
timeout, exhausted budget or cancellation must yield a recoverable visible state
without unauthorized journal changes or silent fixture responses.

Offline cases must include one valid reference per supported operation plus
wrong entity, missing/conflicting/hostile evidence, malformed JSON, invented IDs,
forged human actions, changed drafts, duplicate tool calls, timeout/cancellation,
retry exhaustion and restart recovery. Exact expected proposals and handoffs are
asserted independently, and posted journal count stays unchanged for every run.
Fixture playback is explicitly labeled; report contract-case counts separately
from live model accuracy, which remains unmeasured.

## Task 1: versioned read/propose runtime and adapter contract

**Files:** Existing tools/runs/provider modules or one focused operational adapter,
contract fixtures/tests, workspace/HTTP/CLI/static. Root owns docs/CI/browser.

- [ ] RED: offline operational runs prepare valid typed drafts via each delivered
  service, hand off for exact human review and produce zero posted journals.
- [ ] Implement fixed task/tool schemas and service dispatch, with scoped selected
  sources and current deterministic calculation; reject arbitrary lines/authority.
- [ ] Test source prompt injection, forged tool names/actor/entity, invented refs,
  revoked grants and missing support; all stop safely with attributable findings.
- [ ] Exercise durable duplicate-call recovery, budgets/cancel/restart, unchanged
  old run contracts and no raw traces/secrets in stored/public output.
- [ ] Add Ollama/frontier operational response adapters with mocked transports and
  strict parse/schema errors; preserve startup opt-in and no-live-call defaults.
- [ ] Add workflow/source selection and proposal handoff UI plus
  `demo-operational-agent`; publish exact offline evaluation results and limits.
- [ ] Run focused then guarded suite/foundation/all demos/JS/diff, browser,
  independent review, commit/push/exact CI before final workbench integration.
