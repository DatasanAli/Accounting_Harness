"""Nonnegative USD values; journal sides will supply direction in Step 03."""

import re
from dataclasses import dataclass

_AMOUNT = re.compile(r"[0-9]+\.[0-9]{2}")


def validate_currency(currency: str) -> None:
    """Require the currency supported by this initial implementation."""
    if not isinstance(currency, str):
        raise TypeError("currency must be a string")
    if currency != "USD":
        raise ValueError("only USD is supported")


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable exact amount, with validation on every construction path."""

    cents: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if type(self.cents) is not int:
            raise TypeError("cents must be an integer, not a boolean or float")
        if self.cents < 0:
            raise ValueError("cents must be nonnegative")
        validate_currency(self.currency)

    @classmethod
    def parse(cls, amount: str, currency: str = "USD") -> "Money":
        """Parse an unsigned amount with exactly two fractional digits."""
        if not isinstance(amount, str):
            raise TypeError("amount must be a decimal string, such as '1200.00'")
        if _AMOUNT.fullmatch(amount) is None:
            raise ValueError("amount must be unsigned with exactly two decimal places")
        whole, fraction = amount.split(".")
        return cls(cents=int(whole) * 100 + int(fraction), currency=currency)

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError("cannot add amounts with different currencies")
        return Money(self.cents + other.cents, self.currency)

    def __str__(self) -> str:
        whole, fraction = divmod(self.cents, 100)
        return f"{whole}.{fraction:02d}"
