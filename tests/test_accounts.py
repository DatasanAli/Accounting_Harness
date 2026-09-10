import copy
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from accounting_harness.domain.accounts import Account, AccountCatalog, load_account_catalog

FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/service-business-month.json"


def cash_account(**overrides):
    fields = dict(code="1000", name="Cash", classification="asset", normal_side="debit", active=True)
    fields.update(overrides)
    return Account(**fields)


class AccountTests(unittest.TestCase):
    def test_invalid_text_metadata_is_rejected(self):
        for field in ("code", "name"):
            for value in ["", " ", "\t", " Cash", "Cash ", 1000, None, True]:
                with self.subTest(field=field, value=value), self.assertRaises((TypeError, ValueError)):
                    cash_account(**{field: value})

    def test_invalid_classification_and_normal_side_are_rejected(self):
        for field, invalid in [("classification", ["income", "Asset", "", None, True, []]),
                               ("normal_side", ["Debit", "both", "", None, True, []])]:
            for value in invalid:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    cash_account(**{field: value})

    def test_flags_require_booleans(self):
        for field in ("active", "temporary"):
            for value in [0, 1, "true", "false", None]:
                with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                    cash_account(**{field: value})

    def test_account_identity_and_metadata_are_immutable(self):
        account = cash_account()
        for field, value in [("code", "2000"), ("active", False), ("normal_side", "credit")]:
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(account, field, value)


class CatalogTests(unittest.TestCase):
    def test_reference_catalog_has_expected_accounts_and_entity(self):
        catalog = load_account_catalog(FIXTURE)
        self.assertEqual((catalog.entity_id, catalog.currency), ("demo-service-001", "USD"))
        expected = {
            "1000": ("Cash", "asset", "debit", False),
            "1100": ("Accounts Receivable", "asset", "debit", False),
            "1200": ("Prepaid Insurance", "asset", "debit", False),
            "1500": ("Equipment", "asset", "debit", False),
            "1590": ("Accumulated Depreciation", "asset", "credit", False),
            "2000": ("Accounts Payable", "liability", "credit", False),
            "2100": ("Unearned Service Revenue", "liability", "credit", False),
            "3000": ("Owner Capital", "equity", "credit", False),
            "3100": ("Owner Drawings", "equity", "debit", True),
            "4000": ("Service Revenue", "revenue", "credit", True),
            "5000": ("Rent Expense", "expense", "debit", True),
            "5100": ("Software Expense", "expense", "debit", True),
            "5200": ("Insurance Expense", "expense", "debit", True),
        }
        actual = {a.code: (a.name, a.classification, a.normal_side, a.temporary) for a in catalog.list_accounts()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(catalog.accounts), 13)
        for code in expected:
            self.assertTrue(catalog.get_for_posting(code).active)

    def test_duplicate_codes_are_rejected_by_direct_construction(self):
        with self.assertRaisesRegex(ValueError, "duplicate account code"):
            AccountCatalog("demo", "USD", [cash_account(), cash_account(name="Other cash")])

    def test_catalog_validates_entity_currency_and_account_values(self):
        for entity in ["", " ", " demo", "demo ", None, 1]:
            with self.subTest(entity=entity), self.assertRaises((TypeError, ValueError)):
                AccountCatalog(entity, "USD", [])
        for currency in ["EUR", "usd", None, True]:
            with self.subTest(currency=currency), self.assertRaises((TypeError, ValueError)):
                AccountCatalog("demo", currency, [])
        for accounts in [[{"code": "1000"}], [None], "1000", None, {"1000": cash_account()}]:
            with self.subTest(accounts=accounts), self.assertRaises(TypeError):
                AccountCatalog("demo", "USD", accounts)

    def test_input_list_and_output_listing_cannot_mutate_catalog(self):
        source = [cash_account(code="2000"), cash_account()]
        catalog = AccountCatalog("demo", "USD", source)
        source.clear()
        self.assertEqual([a.code for a in catalog.list_accounts()], ["1000", "2000"])
        self.assertIsInstance(catalog.accounts, tuple)
        with self.assertRaises(FrozenInstanceError):
            catalog.entity_id = "another-entity"
        with self.assertRaises(FrozenInstanceError):
            catalog.accounts = ()

    def test_inactive_account_is_listed_but_not_available_for_posting(self):
        account = cash_account(active=False)
        catalog = AccountCatalog("demo", "USD", [account])
        self.assertEqual(catalog.list_accounts(), (account,))
        with self.assertRaisesRegex(ValueError, "inactive"):
            catalog.get_for_posting("1000")

    def test_unknown_or_malformed_lookup_is_rejected(self):
        catalog = AccountCatalog("demo", "USD", [cash_account()])
        with self.assertRaisesRegex(ValueError, "unknown account"):
            catalog.get_for_posting("9999")
        for code in ["", " 1000", 1000, None]:
            with self.subTest(code=code), self.assertRaises((TypeError, ValueError)):
                catalog.get_for_posting(code)

    def test_same_code_can_belong_to_distinct_entity_catalogs(self):
        first = AccountCatalog("first", "USD", [cash_account()])
        second = AccountCatalog("second", "USD", [cash_account(name="Petty cash")])
        self.assertEqual(first.get_for_posting("1000").name, "Cash")
        self.assertEqual(second.get_for_posting("1000").name, "Petty cash")

    def test_empty_catalog_is_valid_but_has_no_postable_accounts(self):
        catalog = AccountCatalog("demo", "USD", [])
        self.assertEqual(catalog.list_accounts(), ())
        with self.assertRaisesRegex(ValueError, "unknown account"):
            catalog.get_for_posting("1000")


class CatalogLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "catalog.json"
        self.fixture = json.loads(FIXTURE.read_text())

    def load(self, data):
        self.path.write_text(json.dumps(data))
        return load_account_catalog(self.path)

    def test_bad_envelope_and_account_structure_fail_clearly(self):
        for data in [None, [], {}, {"entity": None}, {"entity": {}},
                     {"entity": {"id": "demo"}}, {"entity": {"id": "demo", "currency": "USD"}},
                     {"entity": {"id": "demo", "currency": "USD"}, "accounts": {}},
                     {"entity": {"id": "demo", "currency": "USD"}, "accounts": [None]}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_missing_or_unknown_account_fields_are_rejected(self):
        for field in ("code", "name", "classification", "normal_side", "active"):
            data = copy.deepcopy(self.fixture)
            del data["accounts"][0][field]
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, "missing required"):
                self.load(data)
        data = copy.deepcopy(self.fixture)
        data["accounts"][0]["norml_side"] = "debit"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            self.load(data)

    def test_loader_applies_account_and_catalog_validation(self):
        for field, value in [("code", ""), ("name", ""), ("classification", "income"),
                             ("normal_side", "both"), ("active", "false"), ("temporary", 1)]:
            data = copy.deepcopy(self.fixture)
            data["accounts"][0][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                self.load(data)
        data = copy.deepcopy(self.fixture)
        data["accounts"].append(copy.deepcopy(data["accounts"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate account code"):
            self.load(data)
        for field, value in [("id", ""), ("currency", "EUR")]:
            data = copy.deepcopy(self.fixture)
            data["entity"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(data)

    def test_duplicate_json_keys_and_invalid_json_are_rejected(self):
        self.path.write_text('{"entity": {}, "entity": {}}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            load_account_catalog(self.path)
        self.path.write_text("{invalid}")
        with self.assertRaises(ValueError):
            load_account_catalog(self.path)


if __name__ == "__main__":
    unittest.main()
