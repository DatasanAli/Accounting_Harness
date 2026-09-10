"""Small local demonstrations of the currently implemented behavior."""

import argparse
from pathlib import Path

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.money import Money

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo-accounts", help="show the fictional account catalog and exact arithmetic")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo-accounts":
            demo_accounts()
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
