# Step 12: one provider and proposal evaluation

Goal: one synthetic paid-rent/software receipt produces a validated draft or a
review handoff, with separate application-owned human approval and posting.
This implements the Step 12 brief; Step 13 remains out of scope.

## Contract

- OpenAI Responses API, pinned `gpt-4.1-mini-2025-04-14`, prompt `expense-v1`.
  One strict structured decision per receipt; no model-selected tools, actors,
  storage, policy, budgets or posting. Fixed application workflow uses existing
  account/evidence reads, validation, save and request-review tools.
- Synthetic USD receipts only. Model classifies incurred and paid rent (5000)
  or consumed software services (5100), or abstains. Missing/ambiguous/conflicting facts,
  duplicates, future benefits and unsupported workflows require review.
- Reserve at most 16384 input + 512 output tokens before network I/O; integer
  nanodollars at 400/input token and 1600/output token (uncached upper rate).
  Bound request bytes and output bytes. Record usage-derived cost separately
  from conservative reservation; missing/uncertain billing never refunds it.
- Network runs outside SQLite transactions, in a disposable child process.
  Parent enforces a 10-second absolute deadline and polls cancellation.
  No automatic network retries (including 429 and 5xx). A durable request
  reservation surviving a crash becomes an uncertain-completion review item;
  resumption never silently sends another billable request. New calls require
  a new explicit run. Existing local tool retry/recovery behavior is retained.
- Persist scope/model/prompt/request digest, usage, bounded reason codes and
  validated replay intent. Never persist API keys, raw responses, full prompt
  context or hidden reasoning. Review handoffs without drafts remain in the
  durable run trace; ordinary proposals enter the existing pending draft queue.
- Offline CI uses clearly labeled synthetic response envelopes through the real
  adapter/parser/runtime, retaining all 24 Step 10 contract cases. Freeze 20
  independently labeled proposal cases across seven categories and test that
  wrong labels, unsafe responses and empty corpora fail the gate.
- Live evaluation: at most 24 requests (20 cases plus four repeats), 300 seconds,
  $0.25 total conservative reservation. Report per-category scores, exact
  proposals, review routing, evidence, balance, unauthorized postings, usage,
  latency, failures and repeated-case nondeterminism. No credential is present
  at planning time; a blocked live gate must not advance roadmap completion.

## Implementation sequence

- [x] Add failing adapter/runtime tests for proposal/review, budgets, parsing,
  timeouts, cancellation, uncertain restart and no duplicate side effects.
- [x] Implement `accounting_harness/provider.py` and extend `runs.py` at the
  provider reservation boundary. Preserve fake-provider tests and schema v1.
- [x] Add frozen synthetic corpus and `provider_evaluation.py`; test independent
  expected outcomes, safety counts, score failure and credential-free execution.
- [x] Add offline `demo-provider` and explicit `eval-provider --live`, CLI tests,
  CI command, README, status, next-step brief and verification evidence.
- [ ] Run foundation, guarded tests, all demos, review diff, commit/push and
  inspect the exact GitHub SHA and Actions run. Stop after Step 12 work.

## Documentation checked

- [Pinned model, structured outputs and pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Responses structured output format and refusal handling](https://developers.openai.com/api/docs/guides/structured-outputs)

Live billing is estimated from returned token usage and these documented rates,
not reconciled against an account invoice. The prototype's conservative input
bound is serialized UTF-8 bytes plus framing allowance, with no attachments or
tools sent to the API. Revalidate pricing before a later live evaluation.
