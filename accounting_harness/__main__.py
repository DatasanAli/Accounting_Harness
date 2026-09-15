"""Small local demonstrations of the currently implemented behavior."""

import argparse
import json
from pathlib import Path

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.money import Money
from accounting_harness.domain.journal import validate_journal

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo-accounts", help="show the fictional account catalog and exact arithmetic")
    commands.add_parser("demo-journal", help="validate balanced and unbalanced fictional entries")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo-accounts":
            demo_accounts()
        elif args.command == "demo-journal":
            demo_journal()
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
