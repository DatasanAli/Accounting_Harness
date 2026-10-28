# Step 35b: Authenticated offline operational scoring

The user's confirmation selects provider evaluation controls. Deliver 35b under
Step 35's existing contract; do not enable live transports or inspect credentials.

## Design and boundary

Use the 35a budget and unchanged semantic manifest. A new
`operational_scoring.py` owns one offline experiment, authenticated synthetic setup,
24 isolated sample workspaces and an append-only score database. Synthetic owner,
preparer and reviewer identities use the same AccessStore and application boundary
as HTTP. Their credentials are deliberate fixtures, valid only in a newly created
evaluation directory. Existing workspaces cannot be adopted. On reopen, verify the
experiment binding before logging into its synthetic identity store.

Each sample starts durably before setup. Earlier approved fixture dependencies are
prepared through deterministic authenticated services and posted by the separate
reviewer, outside model effects. Each repeat has its own fresh workspace. The agent
uses a distinctly identified offline evaluation adapter, the existing strict OpenAI
envelope parser and existing operational tools. An injected process worker supplies
synthetic responses; every attempt goes through the shared durable budget, bounded
by both remaining experiment time and the per-request timeout. The runtime still
rechecks preparer authority before every effect. The HTTP provider selector gains
no provider or live flag.

Extend the budget's dispatcher to return its in-memory response to a trusted caller,
accept an optional usage decoder/per-call timeout/cancellation callback, and persist
only validated cost and safe reason codes. This preserves 35a database schema and
old dispatch callers. The injected adapter identity binds manifest, prompt/schema,
worker source digest and experiment identity; ordinary live/playback run identities
remain unchanged. No real provider name is allowed to turn fixture playback into
live evidence.

A separate versioned `scoring.sqlite3` binds the canonical root, budget policy,
manifest, provider identity and scorer labels. Sample claims and results are
append-only, with at most one unfinished sample. Reopen continues only between
finished samples. A crash mid-sample or provider dispatch leaves incomplete evidence
and refuses automatic resend. Reading a completed report never dispatches or
reposts. No automatic clearing of counters or failures.

## Scoring

Keep the denominator at 20 originals plus four repeats, even on budget failure,
missing usage, revocation or early stop. Exact proposals must match frozen expected
lines/policy, entity/currency/effective date, enrolled evidence digests and the
selected input scope. Compare pre/post journal, approval and account state; agent
runs cannot post or activate accounts. Record setup postings separately. Handoffs
must match the expected semantic reason; transport faults earn no abstention credit.
Repeat semantic results must equal their corresponding originals. Capture only safe
fixed IDs, digests, exact amounts, counters, usage and durations; omit raw responses,
source text, passwords, sessions and exception details from the public report.

Successful output is **offline contract passed**, never a live accuracy pass. Freeze
one synthetic response worker; arbitrary injected workers remain labelled offline.
All live gates and real-data use stay deferred. G0 is still incomplete because its
operator/account choices and sandbox prerequisites are unselected.

## Implementation and acceptance

1. Write failing tests in `tests/test_operational_scoring.py` for full 14/14 and 6/6
   semantics, four exact repeats, zero agent postings, identity/evidence boundaries,
   restart without new attempts, exhausted/unknown budgets, missing usage, wrong
   semantic outputs, forged approval tools, revoked preparer and immutable results.
2. Extend `EvaluationBudget.dispatch` and add the offline evaluated adapter to the
   operational runtime's explicit type allowlist. Add a trusted authenticated
   evaluation entry point; untrusted HTTP JSON cannot inject an adapter.
3. Implement the focused score store, fixture setup, scorer and resumable runner.
   Use literal expected dates/source scopes from the frozen synthetic case contract.
   Keep old corpus and old run identities byte-for-byte unchanged.
4. Add `demo-operational-evaluation` and `eval-operational --directory PATH` (offline
   only). Demonstrate all 24 samples, an incomplete budget, and a completed reopen
   with identical report/no provider attempts. Add commands to docs and CI.
5. Run the focused tests, complete suite, every demo, foundation/JS/diff checks and
   independent review. Fix findings; commit, push and inspect exact-SHA GitHub CI.

Known boundary: this command is a synthetic evaluation harness, not a sandbox for
untrusted Python workers, a live experiment authorization UI, or a real-data pilot.
The worker is trusted application code; evidence and tool-call arguments remain
untrusted. No provider URL or credential is selected by this delivery.

Rollback preserves experiment files and financial evidence; use a new code revert,
never budget resets, journal deletion or reuse of a completed sample's identity.
