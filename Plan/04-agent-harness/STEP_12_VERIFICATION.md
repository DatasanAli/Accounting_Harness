# Step 12 verification — adapter/offline work, live gate pending

Observed 2026-10-03. This record distinguishes executable offline verification
from the still-unrun live provider gate. Step 12 is not marked complete.

## Implemented behavior

One OpenAI Responses adapter pins `gpt-4.1-mini-2025-04-14` and `expense-v1`.
Registered synthetic receipt evidence, actual scoped account results and the
ledger period support a structured paid-rent/consumed-software proposal or an
abstention. Application code owns entity, actor, amounts/line construction,
validation, save/review actions and permissions. Human approval/posting remain
separate; no approval or posting capability reaches the model.

The run engine commits a conservative integer-nanodollar reservation before
network I/O, never holds a SQLite transaction across the request, and uses a
child process for a 10-second absolute request deadline and cancellation polling.
No network retry occurs on timeout, HTTP/rate-limit failure or uncertain crash
completion. Restart retains the reservation and routes uncertainty to review.
Source reuse is rechecked inside the draft write transaction. A prior save's
receipt is recovered without another draft revision or model request.

## Observed checks

- `python3 scripts/verify_foundation.py`: plan/reference arithmetic and links pass.
- `python3 scripts/run_tests.py`: 227 tests pass, including all prior 203 tests.
- All eleven documented demos pass, including unchanged 24/24 tool cases.
- `demo-provider`: 20/20 offline cases, zero model calls; separate simulated human
  approval posts rent 1200.00 USD once, and reopen/retry preserves one journal.
- Missing-key live CLI check fails explicitly before a call or live score.
- Tests reproduce and prevent expired-budget dispatch and duplicate evidence
  introduced during I/O or after intent. Real child processes are terminated on
  timeout/cancellation; these transport tests never contact the provider.
- Incorrect expected labels, unsafe responses and empty/duplicate corpora fail
  the evaluation. Tests also cover refusal/incomplete output, usage bounds,
  request size, sanitized logs, and recovery after live-adapter draft commit.

## Offline category results

Frozen corpus SHA-256: `54ae3b965703a7b4e658bbe66c6d3c4c1a637be1ad9e061482455a3b3d06abce`.

These are handwritten response-envelope contract results, **not live accuracy**.
The adapter, run engine, tools, evidence registry and review store are real.
Expected accounting labels are distinct from synthetic responses; no labels or
category names are sent to the model. Hostile document text is inert test data.

| Category | Correct / total |
| --- | --- |
| Clean supported evidence | 8 / 8 |
| Ambiguity | 2 / 2 |
| Missing facts | 2 / 2 |
| Conflicting facts | 2 / 2 |
| Duplicate receipt use | 2 / 2 |
| Unsupported requests | 2 / 2 |
| Hostile document instructions | 2 / 2 |

Exact supported proposals: 8/8. Required review handoffs: 12/12. Successful
proposals linked to registered fixture evidence: 8/8. Unauthorized postings:
0/20. Accepted unbalanced proposals: 0/8. The separate human demo's authorized
posting is outside the model evaluation and is not counted as unauthorized.

## Live gate and limitations

`OPENAI_API_KEY` was absent. Live sample count: **0**. No measured live latency,
cost, accuracy, failures or nondeterminism are available; none are inferred from
synthetic envelopes. GitHub authentication is available independently of the API.

The explicit live command is `python3 -m accounting_harness eval-provider --live`.
The defined budget is 20 cases plus four repeat requests, at most 24 requests,
300 seconds and $0.25 reserved. Each request reserves $0.007372800 from a maximum
16384 input and 512 output tokens at uncached rates. Twenty-four reservations
sum to $0.176947200. Actual returned usage is reported separately at published
rates; missing/uncertain usage does not refund a reservation. These are estimates,
not invoice reconciliation. Recheck model availability and pricing before use.

The implementation supports the existing local macOS/Linux prototype. Local
actors are labels, not authenticated roles. No general agent conversation,
network retry/backoff service or real-document processing is introduced. A
no-draft abstention is a durable awaiting-review run checkpoint; draft review
uses the existing queue. Run/ledger/source files must be restored together under
the existing recovery contract. The corpus is small and intentionally narrow.

## Delivery and rollback

The completion response must link the exact uploaded commit and that commit's
successful Actions run; a previous green run is insufficient. This document
records local results, not an unobserved upload. Revert code with a new commit;
posted journals require linked reversals. Step 13 remains gated, with its
[brief](../05-service-bookkeeping/STEP_13_PLAN.md) prepared but not implemented.
