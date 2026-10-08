# Step 14a verification: reviewed vendor bill recognition

Observed on 2026-10-08 with synthetic January 2026 data. Live connections remain
deferred. Bill payment recording follows separately in Step 14b.

## Behavior and accounting boundary

Two typed facts establish recognition: a vendor bill and a separately asserted
incurred expense. They must agree on economic event, vendor identity, currency,
amount and recognition date. Due date is retained and may fall after January.
The fixed journal debits the evidenced expense account and credits Accounts
Payable. Registration and draft preparation do not post or create a payable.

The exact bill intent is included in the revision digest. Additive review schema
v2 stores immutable intents before the review event seals the revision; old
receipt/cash hashes and retry envelopes retain their original shape. Approval
continues to bind the exact revision, evidence and policy. Source text and the
browser cannot choose permissions or arbitrary posting policy.

Payables activate only at zero unexplained AP balance. Bill effects, journals,
posting audit and retry receipts share one SQLite write transaction. Once
activated, the AP posting guard requires a matching approved bill effect even
through an older connection or direct ledger admission. Shared expense-event
claims prevent recognizing the same incurrence as both a cash expense and bill.

Captured payables reports retain their own ledger snapshot, bills, activation
context, cutoff and policy. They show principal, paid, outstanding, vendor totals,
AP control and any unassigned residual. Initial-context source IDs remain in the report even without an enrollment
anchor. Their original recorded vendor names are captured after verifying source
bytes against approval evidence; later reports never replace a frozen report's names.

## Observed browser results

A fresh localhost workspace registered bill B-14A-001 for 300.00 and separate
software-incurrence evidence dated January 10, due February 9. The draft showed
zero posted journals, both documents, the exact intent and these proposed lines:

| Account | Debit USD | Credit USD |
| --- | ---: | ---: |
| Software expense | 300.00 | 0.00 |
| Accounts Payable | 0.00 | 300.00 |

The operator checked the exact-revision confirmation and selected Approve & post.
The Vendor bills screen then showed one posted journal, principal/outstanding
300.00, paid 0.00, AP control 300.00 and unassigned residual 0.00. The report,
due date, approval and evidence trail remained available after server restart.

A separate browser draft used 90071992547409.93, exceeding JavaScript's exact
integer-cent range. Review rendered the exact amount and canonical
9007199254740993-cent intent, with no rounded 9007199254740992 value. This draft
remained pending and did not change the ledger. Review and vendor views had no
horizontal page overflow at the actual 500px browser viewport. The finding was
fixed by rendering server-produced intent/trace text and decimal amount strings;
stored accounting integers and approval bytes did not change.

## Verification commands

The guarded application suite passed **287 tests**, including 19 focused bill tests. Foundation verification, all **15 demonstrations**, JavaScript syntax and diff checks passed. The implementation report records initial failing tests for missing behavior and regressions before their fixes. Task review identified and corrected the original vendor-name edge case; all 19 focused tests and `demo-bill` passed after that isolated snapshot correction. Final scoped review approved spec compliance and code quality, with no remaining findings.

```sh
python3 scripts/verify_foundation.py
python3 scripts/run_tests.py
python3 -m accounting_harness demo-bill
node --check accounting_harness/static/app.js
```

All earlier documented demos passed alongside `demo-bill`. Meaningful checks include invalid
facts, shared duplicate claims, intent/rejection binding, legacy revision and
approval compatibility, migration rollback, AP activation residual, posting from
an old connection, direct SQL mismatch denial, transaction fault boundaries,
immutable tables, historical residuals and managed-reversal denial.

## Limits and rollback

Only whole-principal USD software/rent expense bills are supported here. Splits,
tax, credit notes and bill/payment corrections are outside this slice. A managed
bill cannot use the generic reversal method: changing only the journal would
leave the payable wrong. Ordinary non-AP reversal and historical exact retries
retain their existing behavior. Step 14b records partial settlements separately.

This is a single fictional local operator, not production authentication. The
SQL guard prevents missing/mismatched subledger effects through ordinary
services and constrained inserts; a database owner able to remove guards is not
an authenticated application user.

Keep all workspace databases together. Revert published software with a new
commit; do not delete bill/journal history or restore over valid postings to
perform accounting corrections.

## Delivery evidence

The exact reviewed commit, remote SHA comparison and GitHub Actions result are
recorded after upload; local passes are not substituted for GitHub verification.
