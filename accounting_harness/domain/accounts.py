"""Validated accounts and an immutable catalog for one entity and currency."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from accounting_harness.domain.money import validate_currency

Classification = Literal["asset", "liability", "equity", "revenue", "expense"]
Side = Literal["debit", "credit"]


def _validate_text(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be nonblank without surrounding whitespace")


@dataclass(frozen=True, slots=True)
class Account:
    """Account identity and metadata; normal side does not constrain balances."""

    code: str
    name: str
    classification: Classification
    normal_side: Side
    active: bool = True
    temporary: bool = False

    def __post_init__(self) -> None:
        _validate_text(self.code, "account code")
        _validate_text(self.name, "account name")
        if self.classification not in ("asset", "liability", "equity", "revenue", "expense"):
            raise ValueError("invalid account classification")
        if self.normal_side not in ("debit", "credit"):
            raise ValueError("normal side must be debit or credit")
        if type(self.active) is not bool or type(self.temporary) is not bool:
            raise TypeError("active and temporary must be boolean flags")


@dataclass(frozen=True, slots=True)
class AccountCatalog:
    """Entity-scoped account codes; snapshot inputs to prevent later mutation."""

    entity_id: str
    currency: str
    accounts: Sequence[Account]

    def __post_init__(self) -> None:
        _validate_text(self.entity_id, "entity ID")
        validate_currency(self.currency)
        if not isinstance(self.accounts, (list, tuple)):
            raise TypeError("accounts must be a list or tuple of Account values")
        codes = set()
        for account in self.accounts:
            if not isinstance(account, Account):
                raise TypeError("catalog entries must be validated Account values")
            if account.code in codes:
                raise ValueError(f"duplicate account code: {account.code}")
            codes.add(account.code)
        object.__setattr__(self, "accounts", tuple(self.accounts))

    def list_accounts(self) -> tuple[Account, ...]:
        """List active and inactive accounts, sorted by stable account code."""
        return tuple(sorted(self.accounts, key=lambda account: account.code))

    def get_for_posting(self, code: str) -> Account:
        """Resolve an active account; this method does not post a transaction."""
        _validate_text(code, "account code")
        for account in self.accounts:
            if account.code == code:
                if not account.active:
                    raise ValueError(f"account is inactive: {code}")
                return account
        raise ValueError(f"unknown account code: {code}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_account_catalog(path: str | Path) -> AccountCatalog:
    """Load the entity/accounts portion of JSON, including the reference fixture.

    Other top-level fixture data is ignored; journal/evidence validation belongs
    to later steps. Required account metadata must be present and valid.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or not isinstance(data.get("entity"), dict):
        raise ValueError("catalog JSON must contain an entity object")
    entity = data["entity"]
    if not {"id", "currency"}.issubset(entity):
        raise ValueError("entity requires id and currency")
    if not isinstance(data.get("accounts"), list):
        raise ValueError("catalog JSON must contain an accounts list")

    required = {"code", "name", "classification", "normal_side", "active"}
    allowed = required | {"temporary"}
    accounts = []
    for index, row in enumerate(data["accounts"]):
        if not isinstance(row, dict):
            raise ValueError(f"account at index {index} must be an object")
        if not required.issubset(row):
            raise ValueError(f"account at index {index} is missing required fields")
        if set(row) - allowed:
            raise ValueError(f"account at index {index} contains unknown fields")
        accounts.append(Account(**row))
    return AccountCatalog(entity_id=entity["id"], currency=entity["currency"], accounts=accounts)
