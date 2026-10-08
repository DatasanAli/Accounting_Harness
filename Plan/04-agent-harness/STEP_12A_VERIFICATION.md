# Step 12a verification: persistent localhost workspace

Observed 2026-10-08. Live provider connections are explicitly deferred by the
user. This record describes offline implementation and observed synthetic checks.

## Delivered behavior

`python3 -m accounting_harness serve` starts a loopback-only browser workspace,
with records persisted in ignored `.local/workspace/`. Five registered fictional
January 2026 receipts support the evidence → proposal → human review → posting
flow. Review, rejection, journal/evidence/approval audit, run checkpoints and a
snapshot/policy-bound trial balance use the existing application services.

Provider choices include fixed offline fixture playback, local Ollama and the
existing pinned OpenAI adapter. Provider requests require explicit startup opt-in
and a UI action. There are no automatic connections, health checks or model
downloads. Ollama uses local nonstreaming schema output, bounded response size,
a hard process deadline and cancellation; uncertain completion never repeats a
request. The same atomic duplicate-source guard applies to every expense adapter.

## Observed verification

- Foundation verification: Markdown links, 34 ordered steps and reference
  accounting identities pass. Roadmap schema v2 records an explicitly reasoned
  deferred external gate without treating it as a completed gate.
- Guarded application suite: **243 tests pass**. Zero-test discovery still fails.
- All twelve documented demos pass. `demo-web` proposes rent, performs separate
  simulated human approval, reopens/retries and retains one journal with **1200.00
  USD per trial-balance column**, with zero model calls.
- New HTTP integration checks exercise real loopback sockets/SQLite: stale and
  rejected approvals, duplicate run requests/evidence, persistent reopen,
  exact posted-line decimal strings, invalid JSON/size/type, Host/Origin/CSRF,
  static-path allowlisting and provider-disabled refusal before creating a run.
- Ollama runs all 20 frozen synthetic response cases through real parsing,
  validation, draft/review and runtime services. Malformed/truncated/foreign
  output fails; local usage is recorded with zero provider billing. This is
  protocol-contract evidence, not model accuracy.
- Retained regression tests reproduce saved-draft crash recovery for both new
  adapters without a repeated request/revision, and cancellation winning over
  a late Ollama response with no SQLite transaction spanning model I/O.
- Independent backend review passed accounting, authority, transport, retry and
  uncertainty boundaries. It independently reproduced recovery and cancellation.

## Browser checks

Real Chromium at desktop and 390px mobile widths: evidence, review, ledger, runs
and provider views render without horizontal document overflow. Rent proposal
initially leaves zero journals. Approve/post is disabled until the exact-revision
human confirmation checkbox is checked. Posting retains one journal, exact
1200.00 amounts and the evidence/policy/revision/actor audit trail after reload.

The hostile fixture remains visible as source data and routes to review with
zero postings. An injected HTML-looking description renders literally without
an image element or script execution. Software rejection records the reason and
leaves posted journal count unchanged. An aborted browser request retains the
original run identity through reload and explicit recovery. No provider request
or external request occurs on initial page load.

Browser inspection caught a posted-line serialization mismatch (internal cents
instead of decimal strings); the API now exposes canonical strings, with an HTTP
regression assertion. UI review also exercised recovery after a definitive
provider denial and browser timeout reporting before delivery.

## Limits and continuation

No live Ollama/OpenAI call was made. No live model accuracy, latency or billing
result is claimed. Local inference's zero provider charge excludes hardware and
energy costs. This is one local fictional operator, not authenticated multi-user
access. It uses fixed fictional receipts; arbitrary evidence enrollment is next.
Cash starts at zero, so the isolated rent posting produces a credit Cash balance.
The trial balance is not a completed financial-statement or reconciliation suite.

Step 12's live gate is recorded as deferred. The user explicitly authorized the
wider roadmap, so work continues with Step 13a after Step 12a commit/CI evidence.
The delivery message and subsequent status update name the exact uploaded commit
and its observed Actions result. No previous green run substitutes for that gate.

Rollback uses a new revert commit. Preserve ledger, registry and run files
together; corrections to posted entries still require linked reversals.
