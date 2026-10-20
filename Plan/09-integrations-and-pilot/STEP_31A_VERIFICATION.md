# Step 31a verification: reviewed owner and prepaid-purchase cash entries

Date: 2026-10-20. Scope: Step 31a only, with temporary synthetic workspaces and
fictional evidence. No model calls, live connections or real financial data.

## Delivered behavior

`accounting_harness/nonoperating_cash.py` implements `nonoperating-cash-v1`. A typed
schema-v2 `cash_movement` and a separate schema-v2 `nonoperating_cash_basis` fact
(`event_id`, `counterparty_id`, `classification`) reconstruct a fixed two-line journal:

| Classification | Cash direction / purpose | Debit | Credit |
| --- | --- | --- | --- |
| owner_contribution | in / owner_contribution | 1000 Cash | 3000 Owner Capital |
| owner_draw | out / owner_draw | 3100 Owner Drawings | 1000 Cash |
| prepaid_insurance | out / prepaid_insurance | 1200 Prepaid Insurance | 1000 Cash |

- **Evidence.** Both facts must be registered and enrolled unchanged, be distinct,
  and match currency, economic event, counterparty, full amount and January date.
  The explicit classification fact selects the accounts; descriptions never do.
  `prepaid_insurance` is a new schema-v2 cash purpose; old documents and the older
  expense/service policies are unchanged.
- **Strict reconstruction.** Save, review and the final posting seal rebuild the
  draft identity, strict operation intent (classification, event, counterparty,
  integer cents, accounts and evidence roles) and journal from evidence. They
  compare canonical JSON, so forged amounts, control accounts, bool-for-int or a
  classification swap never validate. A missing intent is refused by the SQL seal.
- **Identity and claims.** One deterministic draft per entity/event. The existing
  `cash_movement` claim is shared, and a new `nonoperating_cash_recognition` claim
  is added for the basis. Renamed sources and cross-policy reuse of an event (for example
  `cash-v1`) are refused. A first preparation requires unused evidence. Rejection
  retains claims; correction uses the current revision and needs fresh exact approval.
- **Prepaid hand-off.** The purchase journal is exactly one principal 1200 debit and
  one Cash credit and retains its registered cash source. It is a valid Step 20a
  original purchase. Coverage and consumption remain separate reviewed actions;
  the purchase starts no schedule and records no expense. The existing reversal
  dependency refuses reversing a purchase with consumption.
- **Storage.** Review schema 12 adds the policy to the operation-intent seal in one
  atomic migration; earlier policies keep their seals and records. No subsidiary
  guard or posting trigger was broadened.
- **UI and CLI.** Native forms register both facts with direction and purpose
  derived from the selected classification. They prepare the draft (with revision
  correction) for separate reviewer approval. The prepaid coverage form suggests
  posted purchase journals and fills the retained cash source; the server still
  validates. The new demo is `demo-owner-prepaid-cash`.

## Automated evidence

Final observed results: **833 application tests passed in 106.004 seconds**
(824 prior + 9 new) and **all 43 CLI demonstrations passed**. Foundation
links/reference accounting, JavaScript syntax and diff whitespace checks passed.
Twelve existing migration assertions now expect review schema 12, and the 26
authentication-boundary tests pass with the new mapping.

```sh
python3 -m unittest discover -s tests -p test_nonoperating_cash.py -v
python3 scripts/run_tests.py
python3 scripts/verify_foundation.py
node --check accounting_harness/static/app.js
git diff --check
python3 -m accounting_harness demo-owner-prepaid-cash
```

The tests cover:
- the reference table after three separate approvals, with zero journals beforehand;
- refusals for direction, purpose, amount, date, event and counterparty mismatches,
  unsupported classifications, the same document in both roles, a wrong cash kind,
  and five storage-level forgeries;
- renamed-source and cross-policy (`cash-v1`) event reuse;
- corrections that cannot attach used or unenrolled evidence;
- a rejected revision corrected at its current revision, an exact retry returning
  its historical result, three concurrent approve-post calls producing one journal,
  and an injected posting fault rolling back;
- closed-period refusal, and an atomic, fault-injected schema 11→12 migration
  that preserves drafts and a pre-migration approval;
- the prepaid consumption hand-off with reversal-dependency refusal, statement,
  equity and cash-flow classification (operating -1,200.00, financing 9,800.00),
  HTTP strict fields, the native forms and the demo.

Red/green observations: the new suite failed before the policy existed. My first
assertions wrongly expected exact retries after rejection to fail, a reversal
`DatabaseError` (it is a `ValueError`) and empty revenue rows. The first migration
test migrated through `storage()` before its injected denial. These were test
corrections. The first full run exposed 12 latest-version assertions pinned at
review schema 11, updated as earlier policy steps did. The M1 regression test
failed with the fix disabled and passed with it.

## Browser demonstration

A temporary workspace (`alpha`) with separate preparer and reviewer users was
served on 127.0.0.1:8798. Headless Google Chrome was driven over the DevTools
protocol by a throwaway script outside the repository.

The preparer used the new native forms to register and prepare an owner
contribution (10,000.00), drawing (200.00) and prepaid purchase (1,200.00).
Result: three drafts awaiting approval, **0 posted journals**, and no
approve/post control for the preparer. The review card showed the exact 1000/3000
journal, the bound intent and both facts.

After logout, the reviewer confirmed and approved each draft separately. Result:
Cash 8,600.00 debit, Owner Capital 10,000.00 credit, Drawings 200.00 debit and
Prepaid 1,200.00 debit.

The preparer then opened Prepaid insurance. The coverage form suggested the
purchase journal and filled `insurance-cash` as the original source. The preparer
registered January–December coverage and prepared the January consumption. The
reviewer approved it, giving Insurance Expense 100.00, Prepaid 1,100.00, and Cash
8,600.00 unchanged across four journals. No JavaScript exception or console error
occurred. The server was stopped; no real accounts or files were used.

## Review, delivery and rollback

Independent review covered every changed hook. Its probes tried forged
journals and intents, mismatches, duplicates, cross-policy reuse in both
directions, the lifecycle, a real schema-11 workspace migrated to 12 with
retries, the prepaid hand-off, and statement/close/cash-flow classification. It
found **no Critical or Important issues**. Minor M1: a correction (revision > 0)
skipped the unused-evidence check, so it could attach a cash document already held
by a journal posted through the trusted fixture path (not reachable through HTTP).
It is fixed: a correction may keep only its own draft's evidence. A regression
test fails without the fix. Minor M2 (recorded, not changed): Step 20a coverage
accepts any source the purchase journal retains, including the classification
fact, as `original_source_id`. There is no money impact (one coverage per purchase;
principal checked). The UI fills the cash source; tightening it belongs to a
future prepaid change.

Implementation commit, push and exact-SHA CI evidence: pending (recorded after upload).

Rollback uses a new revert commit. Opening a workspace with this version migrates
its review schema to 12. Older code rejects schema 12, so reverting the code
requires the verified restore/relocation procedure planned in Step 33a, not file
edits. Correct posted entries with linked reversals; prepaid-dependent purchases
need a future linked correction policy.
