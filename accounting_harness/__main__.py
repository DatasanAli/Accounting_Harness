"""Small local demonstrations of the currently implemented behavior."""

import argparse
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.money import Money
from accounting_harness.domain.journal import validate_journal
from accounting_harness.domain.ledger import InMemoryLedger
from accounting_harness.persistence import SQLiteLedger, PersistenceBusy

FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/service-business-month.json"


def demo_accounts() -> None:
    catalog = load_account_catalog(FIXTURE)
    print(f"Entity: {catalog.entity_id} | Currency: {catalog.currency}")
    print(f"{'Code':<6} {'Account':<28} {'Classification':<15} {'Normal side':<12} Active")
    for account in catalog.list_accounts():
        active = "yes" if account.active else "no"
        print(f"{account.code:<6} {account.name:<28} {account.classification:<15} "
              f"{account.normal_side:<12} {active}")
    print(f"\n{len(catalog.accounts)} validated accounts.")
    left, right = Money.parse("0.10"), Money.parse("0.20")
    result = left + right
    print(f"Exact addition: {left} + {right} = {result} {result.currency} ({result.cents} cents)")
    try:
        Money.parse("1.005")
    except ValueError as error:
        print(f"Rejected excess precision '1.005': {error}")


def demo_journal() -> None:
    catalog = load_account_catalog(FIXTURE)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    known_sources = {row["id"] for row in fixture["evidence"]}
    for credit in ("1000.00", "999.00"):
        proposal = {
            "id": f"demo-contribution-{credit}", "entity_id": catalog.entity_id,
            "currency": "USD", "effective_date": "2026-01-01",
            "description": "Synthetic owner contribution validation example",
            "source_ids": ["source-T01"],
            "lines": [
                {"account": "1000", "side": "debit", "amount": Money.parse("1000.00")},
                {"account": "3000", "side": "credit", "amount": Money.parse(credit)},
            ],
        }
        result = validate_journal(proposal, catalog, known_source_ids=known_sources)
        status = "ACCEPTED" if result.accepted else "REJECTED"
        print(f"{status}: debits {result.total_debits} / credits {result.total_credits} USD")
        if result.difference_cents is not None:
            print(f"Difference: {Money(abs(result.difference_cents))} USD")
        for finding in result.findings:
            print(f"  {finding.code} at {finding.path}: {finding.message}")
    print("Validation only; known source IDs do not establish correct accounting or approval.")


def demo_ledger() -> None:
    catalog = load_account_catalog(FIXTURE)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ledger = InMemoryLedger(
        catalog, fixture["period"]["start"], fixture["period"]["end"],
        known_source_ids={row["id"] for row in fixture["evidence"]},
    )
    # This explicit fixture adapter includes ordinary transactions only.
    for transaction in fixture["transactions"]:
        if transaction["kind"] == "ordinary":
            ledger.admit({
                "id": transaction["id"], "entity_id": catalog.entity_id,
                "currency": catalog.currency, "effective_date": transaction["date"],
                "description": transaction["description"],
                "source_ids": [transaction["evidence_id"]], "lines": transaction["lines"],
            })
    report = ledger.trial_balance(fixture["period"]["end"])
    print(f"Unadjusted trial balance as of {report.as_of}")
    print(f"Entity: {report.entity_id} | Currency: {report.currency}")
    print(f"Period: {report.snapshot.period_start} through {report.snapshot.period_end}")
    print(f"Policy: {report.policy}")
    print(f"Included entries: {', '.join(report.included_entry_ids)}")
    print(f"{'Code':<6} {'Account':<28} {'Debit':>12} {'Credit':>12}")
    for row in report.rows:
        print(f"{row.account:<6} {row.name:<28} {str(row.debit):>12} {str(row.credit):>12}")
    print(f"{'TOTAL':<35} {str(report.total_debits):>12} {str(report.total_credits):>12}")
    print("Synthetic in-memory demonstration; balances are not saved after exit.")


def demo_persistence() -> None:
    catalog = load_account_catalog(FIXTURE)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    proposals = [
        dict(id=row["id"], entity_id=catalog.entity_id, currency=catalog.currency,
             effective_date=row["date"], description=row["description"],
             source_ids=[row["evidence_id"]], lines=row["lines"])
        for row in fixture["transactions"] if row["kind"] == "ordinary"
    ]

    def show(stage, ledger):
        counts = ledger.counts()
        report = ledger.trial_balance(fixture["period"]["end"])
        print(f"{stage}: {counts['journals']} journals, {counts['lines']} lines, "
              f"{counts['posting_events']} events, {counts['idempotency']} retry records")
        print(f"Debits {report.total_debits} / credits {report.total_credits} USD; "
              f"Cash {report.rows[0].debit} USD")
        return counts, report

    with TemporaryDirectory(prefix="accounting-harness-") as directory:
        path = Path(directory) / "synthetic.sqlite3"
        options = dict(catalog=catalog, period_start=fixture["period"]["start"],
                       period_end=fixture["period"]["end"],
                       known_source_ids={row["id"] for row in fixture["evidence"]})
        with SQLiteLedger(path, **options) as ledger:
            receipts = [ledger.admit(p, idempotency_key=p["id"], actor_id="synthetic-local-operator")
                        for p in proposals]
            original = show("Persisted", ledger)
        with SQLiteLedger(path, **options) as ledger:
            reopened = show("Reopened", ledger)
            retried = [ledger.admit(p, idempotency_key=p["id"], actor_id="synthetic-local-operator")
                       for p in proposals]
            after_retry = show("Retried", ledger)
            if reopened != original or after_retry != original or retried != receipts:
                raise ValueError("persistence/retry demonstration changed original records")
            print("Original receipt preserved for every entry, including operator and UTC timestamp.")
    print("Temporary synthetic database removed; authenticated approval remains a later step.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo-accounts", help="show the fictional account catalog and exact arithmetic")
    commands.add_parser("demo-journal", help="validate balanced and unbalanced fictional entries")
    commands.add_parser("demo-ledger", help="show the fictional unadjusted trial balance")
    commands.add_parser("demo-persistence", help="persist, reopen and safely retry fictional entries")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo-accounts":
            demo_accounts()
        elif args.command == "demo-journal":
            demo_journal()
        elif args.command == "demo-ledger":
            demo_ledger()
        elif args.command == "demo-persistence":
            demo_persistence()
    except (OSError, ValueError, TypeError, sqlite3.Error, PersistenceBusy) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
