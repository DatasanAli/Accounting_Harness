# Step 20d: reproducible adjusted operational month

> **For agentic workers:** Use subagent-driven-development or executing-plans after verified Step 20c.

**Goal:** Assemble the reference month through delivered accounting services and
prove its exact adjusted balances before financial reports build on it.

**Architecture:** One reusable synthetic fixture builder registers/enrolls evidence,
prepares supported operations and makes explicit simulated human approval/post
calls. It returns stable source/draft/approval/journal references for later report
and close demonstrations. This is fixture assembly, not a new accounting policy.

**Tech stack:** Existing Python/SQLite operations, review and approval services.
**Spec:** [Step 20](STEP_20_PLAN.md), [reference month](../../data/fixtures/service-business-month.json).

## Global constraints

- Exact cents, synthetic USD/January and immutable source/actor/effective-date
  history. Use the published reference's independent month-end expected values.
- All active subsidiary guards remain enabled. Never INSERT fabricated effects,
  alter posted entries, disable triggers or post directly to managed controls.
- No new production source kind, review policy, account or schema merely to make
  a fixture work. No bank fee or separate unbilled-accrual example enters this month.
- Original published fixture/context/report bytes remain unchanged. Document the
  operational variant below explicitly; never backdate an existing posted purchase.

## Explicit date variant

The original reference T03 pays insurance on January 3 for January–December
coverage. Step 20a's delivered bounded policy requires an original purchase on or
before coverage starts. The operational fixture therefore records a **new synthetic
purchase on January 1**, with coverage January 1–December 31 and a distinct
versioned fixture/source identity. All amounts and other dates remain as published.

This is an explicit fixture variant, not a correction to an actual journal or a
relaxation of the policy. Its January 31 totals match the independent reference;
its January 1–2 cutoff results intentionally differ and must use variant-specific
expected values. Do not claim date-by-date equivalence with the old fixture.

## Fixture assembly contract

Use a new isolated workspace with zero journals and no preexisting operational
fixture identity. Reject an unrelated populated ledger rather than mixing its
actuals into acceptance totals. Register exact synthetic facts, retain their
canonical digests and perform normal recoverable enrollment before preparation.

Create owner capital 10,000.00 on Jan1, rent 1,200.00 on Jan2, the explicit prepaid
purchase 1,200.00 on Jan1, invoice 2,500.00 on Jan10, collection 1,500.00 on Jan15,
software bill 300.00 on Jan18, payment 100.00 on Jan20, customer advance 600.00 on
Jan22 and drawings 200.00 on Jan25. Use existing reviewed cash/bill/payment/invoice/
collection/advance policies. Owner/drawing/purchase may use the existing trusted
core fixture primitive in this slice because their dedicated UI policy arrives
in 31a; label that fixture boundary and do not imply it is an authenticated input.

Then register anchored annual coverage and prepare/approve/post the 100.00 January
consumption, plus supported completion 200.00 on Jan31 and existing advance earning.
The builder invokes separate approval and post calls with named synthetic actors;
no effect is constructed directly. Export its source/draft/approval/journal map
so later tests can follow real posted traces instead of assuming IDs equal T01.

The adjusted month has 11 journals and trial-balance totals 13,300.00 per side.
Cash 9,400.00; AR 1,000.00; Prepaid 1,100.00; AP 200.00; advances 400.00; Capital 10,000.00;
Drawings 200.00; Revenue 2,700.00; Rent 1,200.00; Software 300.00; Insurance 100.00.
All other baseline balances are zero. AP/AR/advance/prepaid control residuals are
zero. Separate accrual extension accounts may exist at zero but cannot change
these totals. No close is performed in this builder.

Use deterministic scoped source/event/draft/retry identities. Exact rerun/reopen
returns the same records and references without extra journals or approvals.
Interrupted enrollment or a completed post before the builder's next operation
can resume via existing receipts; a changed fixture identity/payload fails clearly.
Do not add a generic workflow framework for this one synthetic sequence.

## Task 1: supported adjusted-month fixture and demonstration

**Files:** A focused reusable reference-month fixture helper, tests and CLI;
synthetic fixture metadata if needed. Root owns docs/CI and delivery.

- [ ] RED: independently assert every balance above, 11 journals, 13,300.00 totals,
  unchanged cash during both adjustments and zero subsidiary/control residuals.
- [ ] Assemble registered evidence and delivered supported service operations with
  explicit separate approvals; retain a complete input→approval→journal map.
- [ ] Assert the variant's prepaid purchase date Jan1 and original fixture bytes
  unchanged; add Jan1/Jan2 cutoff expectations so the difference is not hidden.
- [ ] Exercise rerun/reopen and an interrupted operation without duplicate source,
  effect, approval or journal; refuse unrelated populated workspace/changed inputs.
- [ ] Verify no direct managed-control writes or trigger bypass and full existing
  reversal/approval guards still apply to this assembled month.
- [ ] Add `demo-adjusted-month` with exact expected balances and trace references,
  explicitly labeling the date variant and trusted owner/purchase fixture setup.
- [ ] Run focused then guarded suite/foundation/all demos/diff, independent review,
  commit/push/exact CI before Step 21 statements. No new browser action is needed
  for this fixture-only slice; later report/browser demonstrations consume it.
