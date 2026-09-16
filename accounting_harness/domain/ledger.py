"""Synthetic, single-threaded in-memory ledger; no durable or authorized posting."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date

from accounting_harness.domain.accounts import AccountCatalog, Side
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import Finding, validate_journal
from accounting_harness.domain.money import Money


class EntryRejected(ValueError):
    """Admission failed without changing the ledger; exposes structured reasons."""

    def __init__(self, findings: tuple[Finding, ...]):
        self.findings = findings
        super().__init__("; ".join(f"{f.code} at {f.path}: {f.message}" for f in findings))


@dataclass(frozen=True, slots=True)
class LedgerLine:
    account: str
    side: Side
    amount: Money


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: str
    entity_id: str
    currency: str
    effective_date: date
    description: str
    source_ids: tuple[str, ...]
    lines: tuple[LedgerLine, ...]


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    """Ledger-produced immutable records retained for report reproduction."""

    catalog: AccountCatalog
    period_start: date
    period_end: date
    entries: tuple[LedgerEntry, ...]


@dataclass(frozen=True, slots=True)
class TrialBalanceRow:
    account: str
    name: str
    debit: Money
    credit: Money


@dataclass(frozen=True, slots=True)
class TrialBalance:
    snapshot: LedgerSnapshot
    as_of: date
    included_entry_ids: tuple[str, ...]
    rows: tuple[TrialBalanceRow, ...]
    total_debits: Money
    total_credits: Money
    policy: str = field(default="unadjusted-zero-opening-v1", init=False)

    @property
    def entity_id(self) -> str:
        return self.snapshot.catalog.entity_id

    @property
    def currency(self) -> str:
        return self.snapshot.catalog.currency


def trial_balance(snapshot: LedgerSnapshot, as_of: date | str) -> TrialBalance:
    """Derive net balances from a ledger-produced snapshot and inclusive cutoff.

    Policy v1 assumes zero opening balances and caller-selected ordinary entries.
    Entry kind/recognition is not inferred from descriptions. Snapshot record
    constructors are data containers, not alternative entry admission APIs.
    """
    if not isinstance(snapshot, LedgerSnapshot):
        raise TypeError("snapshot must be a LedgerSnapshot")
    cutoff = accounting_date(as_of)
    if not snapshot.period_start <= cutoff <= snapshot.period_end:
        raise ValueError("report date must fall within the inclusive ledger period")
    accounts = snapshot.catalog.list_accounts()
    balances = {account.code: 0 for account in accounts}
    included = tuple(sorted(
        (entry for entry in snapshot.entries if entry.effective_date <= cutoff),
        key=lambda entry: (entry.effective_date, entry.id),
    ))
    for entry in included:
        for line in entry.lines:
            direction = 1 if line.side == "debit" else -1
            balances[line.account] += direction * line.amount.cents
    rows = tuple(
        TrialBalanceRow(account.code, account.name,
                        Money(max(balances[account.code], 0)),
                        Money(max(-balances[account.code], 0)))
        for account in accounts
    )
    return TrialBalance(
        snapshot, cutoff, tuple(entry.id for entry in included), rows,
        Money(sum(row.debit.cents for row in rows)),
        Money(sum(row.credit.cents for row in rows)),
    )


class InMemoryLedger:
    """Admit one proposal at a time, revalidating before replacing the snapshot.

    Only admission mutates state. No batch import, approval, persistence or
    concurrency support is provided. Keep old snapshots to reproduce reports.
    """

    def __init__(
        self, catalog: AccountCatalog, period_start: date | str, period_end: date | str,
        *, known_source_ids: set[str] | frozenset[str],
    ):
        # Reuse the validator's trusted-context checks; draft findings are unused.
        validate_journal({}, catalog, known_source_ids=known_source_ids)
        start, end = accounting_date(period_start), accounting_date(period_end)
        if start > end:
            raise ValueError("ledger period start must not follow its end")
        self._known_source_ids = frozenset(known_source_ids)
        self._snapshot = LedgerSnapshot(catalog, start, end, ())

    @property
    def snapshot(self) -> LedgerSnapshot:
        return self._snapshot

    def admit(self, proposal: object) -> LedgerEntry:
        """Validate a private copy and retain immutable records, or raise EntryRejected."""
        draft = deepcopy(proposal)
        current = self._snapshot
        result = validate_journal(draft, current.catalog, known_source_ids=self._known_source_ids)
        if not result.accepted:
            raise EntryRejected(result.findings)
        effective_date = accounting_date(draft["effective_date"])
        findings = []
        if any(entry.id == draft["id"] for entry in current.entries):
            findings.append(Finding("duplicate_entry_id", "id", "entry ID already exists in this ledger"))
        if not current.period_start <= effective_date <= current.period_end:
            findings.append(Finding("date_out_of_range", "effective_date",
                                    "entry date must fall within the inclusive ledger period"))
        if findings:
            raise EntryRejected(tuple(findings))
        entry = LedgerEntry(
            draft["id"], draft["entity_id"], draft["currency"], effective_date,
            draft["description"], tuple(draft["source_ids"]),
            tuple(LedgerLine(line["account"], line["side"],
                             line["amount"] if isinstance(line["amount"], Money)
                             else Money.parse(line["amount"])) for line in draft["lines"]),
        )
        self._snapshot = replace(current, entries=current.entries + (entry,))
        return entry

    def trial_balance(self, as_of: date | str) -> TrialBalance:
        return trial_balance(self._snapshot, as_of)
