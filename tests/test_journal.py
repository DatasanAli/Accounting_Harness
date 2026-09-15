import copy
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.journal import validate_journal
from accounting_harness.domain.money import Money

FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/service-business-month.json"


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_account_catalog(FIXTURE)
        self.sources = {"source-T01"}
        self.proposal = {
            "id": "draft-1", "entity_id": "demo-service-001", "currency": "USD",
            "effective_date": "2026-01-01", "description": "Owner contribution",
            "source_ids": ["source-T01"],
            "lines": [
                {"account": "1000", "side": "debit", "amount": Money(100000)},
                {"account": "3000", "side": "credit", "amount": "1000.00"},
            ],
        }

    def validate(self):
        return validate_journal(self.proposal, self.catalog, known_source_ids=self.sources)

    def assert_finding(self, code, path):
        result = self.validate()
        self.assertFalse(result.accepted)
        self.assertIn((code, path), [(f.code, f.path) for f in result.findings])
        return result

    def test_balanced_contribution(self):
        result = self.validate()
        self.assertTrue(result.accepted)
        self.assertEqual(result.findings, ())
        self.assertEqual(result.total_debits, Money(100000))
        self.assertEqual(result.total_credits, Money(100000))
        self.assertEqual(result.difference_cents, 0)

    def test_unbalanced_totals_and_signed_difference(self):
        for amount, difference in (("999.00", 100), ("1001.00", -100)):
            with self.subTest(amount=amount):
                self.proposal["lines"][1]["amount"] = amount
                result = self.assert_finding("unbalanced", "lines")
                self.assertEqual(result.total_debits, Money(100000))
                self.assertEqual(result.difference_cents, difference)

    def test_compound_entry_and_line_order(self):
        self.proposal["lines"] = [
            {"account": "1000", "side": "debit", "amount": "700.00"},
            {"account": "1100", "side": "debit", "amount": "300.00"},
            {"account": "4000", "side": "credit", "amount": "1000.00"},
        ]
        result = self.validate()
        self.assertTrue(result.accepted)
        self.assertEqual(result.total_debits, Money(100000))
        self.proposal["lines"].reverse()
        self.assertEqual(self.validate(), result)

    def test_large_amounts_and_exact_cent_addition(self):
        for amounts, total in ((("0.10", "0.20", "0.30"), 30),
                               (("90071992547409.92", "0.01", "90071992547409.93"), 9007199254740993)):
            with self.subTest(amounts=amounts):
                self.proposal["lines"] = [
                    {"account": "1000", "side": "debit", "amount": amounts[0]},
                    {"account": "1100", "side": "debit", "amount": amounts[1]},
                    {"account": "3000", "side": "credit", "amount": amounts[2]},
                ]
                self.assertTrue(self.validate().accepted)
                self.assertEqual(self.validate().total_debits.cents, total)

    def test_invalid_amounts_never_produce_partial_totals(self):
        for value in (None, True, 1000, 1000.0, -1, "-1.00", "1.005", "1e3", "NaN",
                      "Infinity", " 1000.00", "1000.0", Decimal("1000.00"), {}, []):
            with self.subTest(value=value):
                self.proposal["lines"][1]["amount"] = value
                result = self.assert_finding("invalid_amount", "lines[1].amount")
                self.assertIsNone(result.total_debits)
                self.assertIsNone(result.total_credits)
                self.assertIsNone(result.difference_cents)

    def test_zero_lines_cannot_balance_into_acceptance(self):
        for line in self.proposal["lines"]:
            line["amount"] = "0.00"
        result = self.assert_finding("nonpositive_amount", "lines[0].amount")
        self.assertEqual(result.total_debits, Money(0))
        self.assertIn("lines[1].amount", [f.path for f in result.findings])

    def test_line_count_and_container_types(self):
        original = self.proposal["lines"]
        for lines in ([], original[:1]):
            self.proposal["lines"] = lines
            self.assert_finding("too_few_lines", "lines")
        for lines in (None, {}, "lines", iter(original)):
            self.proposal["lines"] = lines
            self.assert_finding("lines_type", "lines")
        self.proposal["lines"] = tuple(original)
        self.assertTrue(self.validate().accepted)

    def test_malformed_lines_and_sides(self):
        for side in (None, True, [], {}, "Debit", "", "debit credit"):
            self.proposal["lines"][0]["side"] = side
            self.assert_finding("invalid_side", "lines[0].side")
        self.proposal["lines"][0]["side"] = "debit"
        self.proposal["lines"].append({"account": "1000", "side": "debit", "amount": "bad"})
        result = self.assert_finding("invalid_amount", "lines[2].amount")
        self.assertIsNone(result.total_debits)
        self.proposal["lines"] = [None, {}, "invalid"]
        result = self.assert_finding("line_type", "lines[0]")
        self.assertIn("lines[2]", [f.path for f in result.findings])
        self.assertIn("lines[1].amount", [f.path for f in result.findings])

    def test_missing_line_fields(self):
        for field, code in (("account", "invalid_account"), ("side", "invalid_side"),
                            ("amount", "invalid_amount")):
            with self.subTest(field=field):
                value = self.proposal["lines"][0].pop(field)
                self.assert_finding(code, f"lines[0].{field}")
                self.proposal["lines"][0][field] = value

    def test_extra_fields_and_dual_sided_inputs_are_rejected(self):
        for extra in ({"debit": "1000.00", "credit": "0.00"}, {"memo": "ignored?"}):
            proposal = copy.deepcopy(self.proposal)
            self.proposal["lines"][0].update(extra)
            result = self.assert_finding("unknown_fields", "lines[0]")
            self.assertIsNone(result.total_debits)
            self.proposal = proposal
        self.proposal["approved"] = True
        self.assert_finding("unknown_fields", "$")

    def test_invalid_and_inactive_accounts(self):
        for account in ("9999", "", " 1000", None, 1000, [], {}):
            self.proposal["lines"][0]["account"] = account
            result = self.assert_finding("invalid_account", "lines[0].account")
            self.assertEqual(result.total_debits, Money(100000))
        self.proposal["lines"][0]["account"] = "1000"
        self.catalog = replace(self.catalog, accounts=[
            replace(a, active=False) if a.code == "1000" else a for a in self.catalog.accounts])
        self.assert_finding("invalid_account", "lines[0].account")

    def test_metadata_text_and_missing_fields(self):
        for field in ("id", "entity_id", "description"):
            original = self.proposal[field]
            for value in (None, "", "  ", " padded ", True, [], {}):
                with self.subTest(field=field, value=value):
                    self.proposal[field] = value
                    self.assert_finding("invalid_text", field)
            del self.proposal[field]
            self.assert_finding("invalid_text", field)
            self.proposal[field] = original

    def test_entity_and_currency_scope(self):
        self.proposal["entity_id"] = "another-entity"
        self.assert_finding("entity_mismatch", "entity_id")
        for currency in ("EUR", "usd", None, 1, [], {}):
            self.proposal["currency"] = currency
            self.assert_finding("unsupported_currency", "currency")
        self.proposal["currency"] = "USD"
        self.proposal["lines"][0]["currency"] = "EUR"
        self.assert_finding("currency_mismatch", "lines[0].currency")

    def test_money_currency_must_match_entry(self):
        self.proposal["currency"] = "EUR"
        self.assert_finding("currency_mismatch", "lines[0].amount")

    def test_dates_are_calendar_dates_only(self):
        for value in ("2026-02-30", "2026-02-29", "20260101", "2026-W01-1", "2026-1-1",
                      "2026-01-01T00:00:00", "2026-01-01 00:00:00", "0000-01-01",
                      datetime(2026, 1, 1), None, 20260101, [], {}):
            with self.subTest(value=value):
                self.proposal["effective_date"] = value
                self.assert_finding("invalid_date", "effective_date")
        for value in (date(2026, 1, 1), "2024-02-29"):
            self.proposal["effective_date"] = value
            self.assertTrue(self.validate().accepted)

    def test_sources_required_and_all_checked(self):
        for sources in (None, [], (), "source-T01", {"source-T01"}):
            self.proposal["source_ids"] = sources
            self.assert_finding("sources_required", "source_ids")
        self.proposal["source_ids"] = ["source-T01", "", "unknown", [], " source-T01"]
        self.assert_finding("invalid_source", "source_ids[1]")
        self.assert_finding("unknown_source", "source_ids[2]")
        self.assert_finding("invalid_source", "source_ids[3]")
        self.assert_finding("invalid_source", "source_ids[4]")
        self.proposal["source_ids"] = ("source-T01",)
        self.sources = set()
        self.assert_finding("unknown_source", "source_ids[0]")

    def test_invalid_entry_and_trusted_context(self):
        for proposal in (None, [], "entry", 1):
            self.proposal = proposal
            self.assert_finding("entry_type", "$")
        with self.assertRaises(TypeError):
            validate_journal({}, None, known_source_ids=set())
        with self.assertRaises(TypeError):
            validate_journal({}, self.catalog, known_source_ids="source-T01")
        with self.assertRaises(ValueError):
            validate_journal({}, self.catalog, known_source_ids={""})

    def test_repeat_validation_is_pure_and_results_immutable(self):
        for rejected in (False, True):
            if rejected:
                self.proposal["lines"][1]["amount"] = "999.00"
            before = copy.deepcopy((self.proposal, self.catalog, self.sources))
            result = self.validate()
            self.assertEqual(self.validate(), result)
            self.assertEqual((self.proposal, self.catalog, self.sources), before)
            with self.assertRaises(FrozenInstanceError):
                result.total_debits = Money(1)
            if result.findings:
                with self.assertRaises(FrozenInstanceError):
                    result.findings[0].code = "changed"

    def test_balanced_misclassification_is_outside_validation_scope(self):
        self.proposal["lines"][1]["account"] = "4000"
        self.assertTrue(self.validate().accepted)  # Equity mislabeled revenue still balances.


if __name__ == "__main__":
    unittest.main()
