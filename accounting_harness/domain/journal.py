"""Pure draft validation. Acceptance is neither approval nor posting authority."""

import re
from dataclasses import dataclass
from datetime import date

from accounting_harness.domain.accounts import AccountCatalog
from accounting_harness.domain.money import Money


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    findings: tuple[Finding, ...]
    total_debits: Money | None
    total_credits: Money | None

    @property
    def accepted(self) -> bool:
        return not self.findings

    @property
    def difference_cents(self) -> int | None:
        """Signed debits minus credits; unavailable if totals are incomplete."""
        if self.total_debits is None or self.total_credits is None:
            return None
        return self.total_debits.cents - self.total_credits.cents


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def validate_journal(
    proposal: object, catalog: AccountCatalog, *, known_source_ids: set[str] | frozenset[str]
) -> ValidationResult:
    """Check a dict draft without changing it or the supplied catalog.

    Amounts accept Money or canonical decimal strings. Serialized line currency
    is optional and defaults to the entry currency. Unknown fields are rejected.
    Both totals are unavailable if any line's arithmetic is ambiguous/invalid;
    metadata/account errors can coexist with complete totals. Invalid caller
    context raises TypeError/ValueError; draft errors return structured findings.
    """
    if not isinstance(catalog, AccountCatalog):
        raise TypeError("catalog must be an AccountCatalog")
    if not isinstance(known_source_ids, (set, frozenset)):
        raise TypeError("known_source_ids must be an explicit set of source IDs")
    if any(not _text(source) for source in known_source_ids):
        raise ValueError("known source IDs must be nonblank unpadded strings")

    findings = []

    def add(code: str, path: str, message: str) -> None:
        findings.append(Finding(code, path, message))

    if not isinstance(proposal, dict):
        add("entry_type", "$", "entry must be an object")
        return ValidationResult(tuple(findings), None, None)

    fields = {"id", "entity_id", "currency", "effective_date", "description", "source_ids", "lines"}
    if set(proposal) - fields:
        add("unknown_fields", "$", "entry contains unsupported fields")
    for field in ("id", "entity_id", "description"):
        if not _text(proposal.get(field)):
            add("invalid_text", field, "must be a nonblank string without surrounding whitespace")
    if proposal.get("entity_id") != catalog.entity_id:
        add("entity_mismatch", "entity_id", "entry entity must match the catalog")
    currency = proposal.get("currency")
    if currency != "USD":
        add("unsupported_currency", "currency", "only USD is supported")
    if currency != catalog.currency:
        add("currency_mismatch", "currency", "entry currency must match the catalog")

    effective_date = proposal.get("effective_date")
    valid_date = type(effective_date) is date
    if isinstance(effective_date, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", effective_date):
        try:
            date.fromisoformat(effective_date)
            valid_date = True
        except ValueError:
            pass
    if not valid_date:
        add("invalid_date", "effective_date", "must be a calendar date or YYYY-MM-DD string")

    sources = proposal.get("source_ids")
    if not isinstance(sources, (list, tuple)) or not sources:
        add("sources_required", "source_ids", "at least one source ID is required in a list or tuple")
    else:
        for index, source in enumerate(sources):
            path = f"source_ids[{index}]"
            if not _text(source):
                add("invalid_source", path, "source ID must be a nonblank unpadded string")
            elif source not in known_source_ids:
                add("unknown_source", path, "source ID is not in the supplied known sources")

    lines = proposal.get("lines")
    if not isinstance(lines, (list, tuple)):
        add("lines_type", "lines", "lines must be a list or tuple")
        return ValidationResult(tuple(findings), None, None)
    if len(lines) < 2:
        add("too_few_lines", "lines", "at least two lines are required")

    totals = {"debit": 0, "credit": 0}
    computable = currency == "USD"
    for index, line in enumerate(lines):
        path = f"lines[{index}]"
        if not isinstance(line, dict):
            add("line_type", path, "line must be an object")
            computable = False
            continue
        if set(line) - {"account", "side", "amount", "currency"}:
            add("unknown_fields", path, "line supports only account, side, amount and optional currency")
            computable = False
        try:
            catalog.get_for_posting(line.get("account"))
        except (TypeError, ValueError) as error:
            add("invalid_account", f"{path}.account", str(error))

        side = line.get("side")
        valid_side = isinstance(side, str) and side in ("debit", "credit")
        if not valid_side:
            add("invalid_side", f"{path}.side", "side must be debit or credit")
            computable = False

        amount = line.get("amount")
        line_currency = line.get("currency", currency)
        if line_currency != currency:
            add("currency_mismatch", f"{path}.currency", "line currency must match the entry")
            computable = False
        if line_currency != "USD":
            add("unsupported_currency", f"{path}.currency", "only USD is supported")
            computable = False
        try:
            if not isinstance(amount, Money):
                amount = Money.parse(amount)
        except (TypeError, ValueError) as error:
            add("invalid_amount", f"{path}.amount", str(error))
            computable = False
            continue
        if amount.currency != currency or amount.currency != line_currency:
            add("currency_mismatch", f"{path}.amount", "amount currency must match the entry and line")
            computable = False
        if amount.cents == 0:
            add("nonpositive_amount", f"{path}.amount", "journal amounts must be positive")
        if valid_side:
            totals[side] += amount.cents

    debits = Money(totals["debit"]) if computable else None
    credits = Money(totals["credit"]) if computable else None
    if computable and debits != credits:
        add("unbalanced", "lines", "total debits must equal total credits")
    return ValidationResult(tuple(findings), debits, credits)
