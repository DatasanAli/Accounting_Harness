import copy
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from pathlib import Path

from accounting_harness.domain.accounts import AccountCatalog, load_account_catalog
from accounting_harness.domain.journal import validate_journal
from accounting_harness.domain.ledger import EntryRejected, InMemoryLedger, trial_balance
from accounting_harness.domain.money import Money

FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/service-business-month.json"


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.catalog = load_account_catalog(FIXTURE)
        self.sources = {row["id"] for row in self.fixture["evidence"]}
        self.ledger = self.new_ledger()

    def new_ledger(self, catalog=None):
        return InMemoryLedger(catalog or self.catalog, "2026-01-01", "2026-01-31",
                              known_source_ids=self.sources)

    def proposal(self, entry_id="example", effective_date="2026-01-01", amount="1000.00"):
        return {
            "id": entry_id, "entity_id": self.catalog.entity_id, "currency": "USD",
            "effective_date": effective_date, "description": "Synthetic contribution",
            "source_ids": ["source-T01"],
            "lines": [
                {"account": "1000", "side": "debit", "amount": amount},
                {"account": "3000", "side": "credit", "amount": amount},
            ],
        }

    def load_ordinary_entries(self):
        for transaction in self.fixture["transactions"]:
            if transaction["kind"] == "ordinary":
                self.ledger.admit({
                    "id": transaction["id"], "entity_id": self.catalog.entity_id,
                    "currency": "USD", "effective_date": transaction["date"],
                    "description": transaction["description"],
                    "source_ids": [transaction["evidence_id"]], "lines": transaction["lines"],
                })

    def assert_rejected_unchanged(self, proposal, code):
        before = self.ledger.snapshot
        report = self.ledger.trial_balance("2026-01-31")
        with self.assertRaises(EntryRejected) as caught:
            self.ledger.admit(proposal)
        self.assertIn(code, [finding.code for finding in caught.exception.findings])
        self.assertIs(self.ledger.snapshot, before)
        self.assertEqual(self.ledger.trial_balance("2026-01-31"), report)

    def test_every_reference_account_and_independent_totals(self):
        self.load_ordinary_entries()
        report = self.ledger.trial_balance("2026-01-31")
        expected = self.fixture["expected"]["unadjusted_trial_balance"]
        self.assertEqual(
            [{"account": row.account, "debit": str(row.debit), "credit": str(row.credit)}
             for row in report.rows], expected["rows"],
        )
        self.assertEqual(str(report.total_debits), expected["total_debits"])
        self.assertEqual(str(report.total_credits), expected["total_credits"])
        self.assertEqual(report.total_debits, Money(1330000))
        self.assertEqual(report.included_entry_ids, tuple(f"T{i:02}" for i in range(1, 10)))
        self.assertEqual(len(report.snapshot.entries), 9)
        self.assertEqual(report.entity_id, "demo-service-001")
        self.assertEqual(report.currency, "USD")
        self.assertEqual(report.policy, "unadjusted-zero-opening-v1")
        self.assertEqual(report.as_of, date(2026, 1, 31))

    def test_cutoff_includes_same_day_and_excludes_later_activity(self):
        self.load_ordinary_entries()
        before_collection = self.ledger.trial_balance("2026-01-14")
        on_collection = self.ledger.trial_balance("2026-01-15")
        rows_before = {row.account: row for row in before_collection.rows}
        rows_on = {row.account: row for row in on_collection.rows}
        self.assertEqual(rows_before["1000"].debit, Money(760000))
        self.assertEqual(rows_before["1100"].debit, Money(250000))
        self.assertEqual(rows_on["1000"].debit, Money(910000))
        self.assertEqual(rows_on["1100"].debit, Money(100000))
        self.assertEqual(on_collection.included_entry_ids, ("T01", "T02", "T03", "T04", "T05"))
        self.assertEqual(before_collection.total_debits, Money(1250000))
        self.assertEqual(on_collection.total_credits, Money(1250000))

    def test_empty_ledger_lists_all_accounts_including_inactive(self):
        catalog = replace(self.catalog, accounts=[replace(a, active=False)
                                                  for a in reversed(self.catalog.accounts)])
        ledger = self.new_ledger(catalog)
        report = ledger.trial_balance("2026-01-01")
        self.assertEqual(len(report.rows), 13)
        self.assertEqual([r.account for r in report.rows], sorted(a.code for a in catalog.accounts))
        self.assertTrue(all(r.debit == r.credit == Money(0) for r in report.rows))
        self.assertEqual(report.total_debits, Money(0))
        self.assertEqual(report.total_credits, Money(0))
        self.assertEqual(report.included_entry_ids, ())
        empty = self.new_ledger(AccountCatalog(self.catalog.entity_id, "USD", []))
        self.assertEqual(empty.trial_balance("2026-01-31").rows, ())

    def test_zero_activity_before_first_entry(self):
        self.ledger.admit(self.proposal(effective_date="2026-01-02"))
        report = self.ledger.trial_balance("2026-01-01")
        self.assertEqual(report.included_entry_ids, ())
        self.assertEqual(report.total_debits, Money(0))
        self.assertEqual(len(report.snapshot.entries), 1)

    def test_duplicate_ids_fail_even_with_changed_payload(self):
        self.ledger.admit(self.proposal())
        self.assert_rejected_unchanged(self.proposal(), "duplicate_entry_id")
        self.assert_rejected_unchanged(self.proposal(amount="1500.00"), "duplicate_entry_id")

    def test_equal_amounts_with_different_ids_remain_distinct(self):
        self.ledger.admit(self.proposal("one"))
        self.ledger.admit(self.proposal("two"))
        report = self.ledger.trial_balance("2026-01-31")
        self.assertEqual(report.included_entry_ids, ("one", "two"))
        self.assertEqual(report.total_debits, Money(200000))

    def test_all_invalid_entries_preserve_existing_records_and_balances(self):
        self.ledger.admit(self.proposal("existing"))
        changes = [
            ({"entity_id": "other"}, "entity_mismatch"),
            ({"currency": "EUR"}, "unsupported_currency"),
            ({"source_ids": []}, "sources_required"),
            ({"source_ids": ["unknown"]}, "unknown_source"),
            ({"description": ""}, "invalid_text"),
            ({"effective_date": "2026-02-30"}, "invalid_date"),
        ]
        for changeset, code in changes:
            with self.subTest(changes=changeset):
                draft = self.proposal()
                draft.update(changeset)
                self.assert_rejected_unchanged(draft, code)
        for field, value, code in (("amount", "999.00", "unbalanced"),
                                   ("amount", 1000.0, "invalid_amount"),
                                   ("account", "unknown", "invalid_account"),
                                   ("side", "both", "invalid_side")):
            with self.subTest(field=field, value=value):
                draft = self.proposal()
                draft["lines"][1][field] = value
                self.assert_rejected_unchanged(draft, code)
        self.assert_rejected_unchanged([self.proposal()], "entry_type")

    def test_inactive_account_rejected_at_admission(self):
        catalog = replace(self.catalog, accounts=[
            replace(a, active=False) if a.code == "1000" else a for a in self.catalog.accounts])
        self.ledger = self.new_ledger(catalog)
        self.assert_rejected_unchanged(self.proposal(), "invalid_account")

    def test_validation_result_cannot_bypass_revalidation(self):
        draft = self.proposal()
        result = validate_journal(draft, self.catalog, known_source_ids=self.sources)
        self.assertTrue(result.accepted)
        draft["lines"][1]["amount"] = "999.00"
        self.assert_rejected_unchanged(draft, "unbalanced")
        self.assert_rejected_unchanged(result, "entry_type")
        draft = self.proposal()
        draft["validation_result"] = result
        self.assert_rejected_unchanged(draft, "unknown_fields")

    def test_entry_dates_use_inclusive_period_boundaries(self):
        self.ledger.admit(self.proposal("first", date(2026, 1, 1)))
        self.ledger.admit(self.proposal("last", "2026-01-31"))
        for value in ("2025-12-31", "2026-02-01"):
            self.assert_rejected_unchanged(self.proposal(value, value), "date_out_of_range")
        self.assertEqual(self.ledger.trial_balance("2026-01-01").included_entry_ids, ("first",))
        self.assertEqual(self.ledger.trial_balance("2026-01-31").included_entry_ids, ("first", "last"))

    def test_invalid_periods_and_report_dates(self):
        values = (None, True, 20260101, "20260101", "2026-W01-1", "2026-1-1", "2026-02-30",
                  "2026-01-01T00:00:00", datetime(2026, 1, 1), [], {})
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    InMemoryLedger(self.catalog, value, "2026-01-31", known_source_ids=self.sources)
                with self.assertRaises(ValueError):
                    InMemoryLedger(self.catalog, "2026-01-01", value, known_source_ids=self.sources)
                with self.assertRaises(ValueError):
                    self.ledger.trial_balance(value)
        with self.assertRaises(ValueError):
            InMemoryLedger(self.catalog, "2026-01-31", "2026-01-01", known_source_ids=self.sources)
        for value in ("2025-12-31", "2026-02-01"):
            with self.assertRaises(ValueError):
                self.ledger.trial_balance(value)
        single_day = InMemoryLedger(self.catalog, "2026-01-01", date(2026, 1, 1),
                                    known_source_ids=self.sources)
        single_day.admit(self.proposal())
        self.assertEqual(single_day.trial_balance(date(2026, 1, 1)).total_debits, Money(100000))

    def test_context_is_validated_and_source_set_is_snapshotted(self):
        for catalog, sources in ((None, self.sources), (self.catalog, "source-T01")):
            with self.assertRaises(TypeError):
                InMemoryLedger(catalog, "2026-01-01", "2026-01-31", known_source_ids=sources)
        with self.assertRaises(ValueError):
            InMemoryLedger(self.catalog, "2026-01-01", "2026-01-31", known_source_ids={""})
        self.sources.clear()
        self.sources.add("late-source")
        self.ledger.admit(self.proposal())
        draft = self.proposal("late")
        draft["source_ids"] = ["late-source"]
        self.assert_rejected_unchanged(draft, "unknown_source")

    def test_snapshots_preserve_entry_metadata_and_nested_values(self):
        draft = self.proposal(amount=Money(100000))
        before = copy.deepcopy(draft)
        entry = self.ledger.admit(draft)
        self.assertEqual(draft, before)
        self.assertEqual(entry.id, "example")
        self.assertEqual(entry.entity_id, self.catalog.entity_id)
        self.assertEqual(entry.currency, "USD")
        self.assertEqual(entry.effective_date, date(2026, 1, 1))
        self.assertEqual(entry.description, "Synthetic contribution")
        self.assertEqual(entry.source_ids, ("source-T01",))
        report = self.ledger.trial_balance("2026-01-31")
        draft["id"] = "changed"
        draft["description"] = "changed"
        draft["source_ids"].clear()
        draft["lines"][0]["amount"] = "2000.00"
        draft["lines"].clear()
        self.assertEqual(self.ledger.trial_balance("2026-01-31"), report)
        for obj, field, value in ((entry, "id", "changed"),
                                  (entry.lines[0], "amount", Money(1)),
                                  (self.ledger.snapshot, "entries", ()),
                                  (report, "total_debits", Money(1)),
                                  (report.rows[0], "debit", Money(1))):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, field, value)
        with self.assertRaises(AttributeError):
            self.ledger.snapshot = report.snapshot

    def test_old_snapshot_reproduces_report_after_later_admission(self):
        self.ledger.admit(self.proposal("first"))
        old_report = self.ledger.trial_balance("2026-01-31")
        self.ledger.admit(self.proposal("later", "2026-01-15"))
        self.assertEqual(trial_balance(old_report.snapshot, old_report.as_of), old_report)
        self.assertEqual(old_report.total_debits, Money(100000))
        self.assertEqual(self.ledger.trial_balance("2026-01-31").total_debits, Money(200000))
        before = self.ledger.snapshot
        self.assertEqual(self.ledger.trial_balance("2026-01-31"),
                         self.ledger.trial_balance("2026-01-31"))
        self.assertIs(self.ledger.snapshot, before)

    def test_credit_asset_balance_follows_net_sign_and_can_clear(self):
        withdrawal = self.proposal("withdrawal", amount="200.00")
        withdrawal["lines"][0]["side"] = "credit"
        withdrawal["lines"][1].update(account="3100", side="debit")
        self.ledger.admit(withdrawal)
        rows = {r.account: r for r in self.ledger.trial_balance("2026-01-31").rows}
        self.assertEqual(rows["1000"].debit, Money(0))
        self.assertEqual(rows["1000"].credit, Money(20000))
        self.assertEqual(rows["3100"].debit, Money(20000))
        self.ledger.admit(self.proposal("deposit", amount="200.00"))
        cash = self.ledger.trial_balance("2026-01-31").rows[0]
        self.assertEqual(cash.debit, Money(0))
        self.assertEqual(cash.credit, Money(0))

    def test_compound_entry_repeated_account_and_large_exact_cents(self):
        draft = self.proposal(amount="90071992547409.93")
        draft["lines"][0]["amount"] = "90071992547409.92"
        draft["lines"].append({"account": "1000", "side": "debit", "amount": "0.01"})
        self.ledger.admit(draft)
        report = self.ledger.trial_balance("2026-01-31")
        self.assertEqual(report.total_debits.cents, 9007199254740993)
        self.assertEqual(report.total_credits, report.total_debits)
        self.assertEqual(report.rows[0].debit, report.total_debits)

    def test_out_of_order_admission_reports_in_date_and_id_order(self):
        for entry_id, effective_date in (("z", "2026-01-20"), ("b", "2026-01-01"),
                                         ("a", "2026-01-01")):
            self.ledger.admit(self.proposal(entry_id, effective_date))
        self.assertEqual(self.ledger.trial_balance("2026-01-01").included_entry_ids, ("a", "b"))
        report = self.ledger.trial_balance("2026-01-31")
        self.assertEqual(report.included_entry_ids, ("a", "b", "z"))
        self.assertEqual(report.total_debits, Money(300000))


if __name__ == "__main__":
    unittest.main()
