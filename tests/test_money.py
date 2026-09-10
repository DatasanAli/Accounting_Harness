import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal

from accounting_harness.domain.money import Money


class MoneyTests(unittest.TestCase):
    def test_parse_and_format_exact_cents(self):
        examples = [("0.00", 0, "0.00"), ("0.01", 1, "0.01"),
                    ("1200.00", 120000, "1200.00"), ("001.20", 120, "1.20"),
                    ("90071992547409.93", 9007199254740993, "90071992547409.93")]
        for text, expected_cents, rendered in examples:
            with self.subTest(amount=text):
                value = Money.parse(text)
                self.assertEqual(value.cents, expected_cents)
                self.assertEqual(value.currency, "USD")
                self.assertEqual(str(value), rendered)
                self.assertEqual(Money.parse(str(value)), value)

    def test_addition_is_exact_and_preserves_operands(self):
        left, right = Money.parse("0.10"), Money.parse("0.20")
        result = left + right
        self.assertEqual(result, Money(30, "USD"))
        self.assertEqual(str(result), "0.30")
        self.assertEqual((left.cents, right.cents), (10, 20))
        self.assertEqual(Money.parse("0.99") + Money.parse("0.01"), Money(100))
        self.assertEqual(result + Money(0), result)

    def test_parse_rejects_non_string_inputs(self):
        for value in [0.1, 100, True, False, None, b"1.00", Decimal("1.00"), float("nan"), float("inf")]:
            with self.subTest(value=repr(value)), self.assertRaises(TypeError):
                Money.parse(value)

    def test_parse_rejects_invalid_formats_without_rounding(self):
        for value in ["", "1", "1.0", "1.005", "-1.00", "-0.00", "+1.00", "NaN", "Infinity",
                      "1e2", "1_000.00", "1,000.00", " 1.00", "1.00 ", "1.00\n", "\t1.00",
                      ".50", "1.", "１.００", "$1.00"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Money.parse(value)

    def test_direct_construction_rejects_non_integer_cents(self):
        for value in [True, False, 1.0, 0.1, "100", None, Decimal(100), float("nan"), float("inf")]:
            with self.subTest(value=repr(value)), self.assertRaises(TypeError):
                Money(value)

    def test_direct_construction_rejects_negative_cents(self):
        with self.assertRaises(ValueError):
            Money(-1)

    def test_currency_validated_by_constructor_and_parser(self):
        for currency in ["EUR", "usd", " USD", "USD ", ""]:
            with self.subTest(currency=currency):
                with self.assertRaises(ValueError):
                    Money(100, currency)
                with self.assertRaises(ValueError):
                    Money.parse("1.00", currency)
        for currency in [None, True, 1, ["USD"]]:
            with self.subTest(currency=currency):
                with self.assertRaises(TypeError):
                    Money(100, currency)
                with self.assertRaises(TypeError):
                    Money.parse("1.00", currency)

    def test_addition_rejects_values_that_are_not_money(self):
        for value in [1, 0.1, True, "0.10", None]:
            with self.subTest(value=value), self.assertRaises(TypeError):
                Money(10) + value

    def test_amount_and_currency_are_immutable(self):
        value = Money(100)
        for field, replacement in [("cents", -1), ("currency", "EUR")]:
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(value, field, replacement)


if __name__ == "__main__":
    unittest.main()
