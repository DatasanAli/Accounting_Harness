#!/usr/bin/env python3
"""Check plan integrity and an original accounting fixture, not application behavior."""

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
AMOUNT = re.compile(r"[0-9]+\.[0-9]{2}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def cents(value, signed=False):
    require(isinstance(value, str), f"Amount must be a string: {value!r}")
    negative = signed and value.startswith("-")
    unsigned = value[1:] if negative else value
    require(AMOUNT.fullmatch(unsigned), f"Invalid amount: {value!r}")
    whole, fraction = unsigned.split(".")
    amount = int(whole) * 100 + int(fraction)
    return -amount if negative else amount


def check_plan():
    files = [ROOT / "README.md", ROOT / "AGENTS.md"]
    files += sorted((ROOT / "Plan").rglob("*.md"))
    files += sorted((ROOT / "data").rglob("*.md"))
    checked = 0
    for path in files:
        content = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"\[[^\]]+\]\(([^\n)]+)\)", content):
            target = target.strip("<>")
            url = urlsplit(target)
            if url.scheme or not url.path:
                continue
            resolved = (path.parent / unquote(url.path)).resolve()
            require(resolved.is_relative_to(ROOT), f"Link escapes project: {target}")
            require(resolved.exists(), f"Broken link in {path.relative_to(ROOT)}: {target}")
            checked += 1

    roadmap = read_json(ROOT / "Plan/roadmap.json")
    steps = []
    for index, phase in enumerate(roadmap["phases"], 1):
        require(phase["id"] == f"{index:02}", "Phases must be ordered")
        path = ROOT / phase["path"]
        require(path.is_file(), f"Missing phase file: {path}")
        actual_ids = re.findall(r"^### Step (\d{2}):", path.read_text(), re.M)
        require(actual_ids == [s["id"] for s in phase["steps"]], f"Step mismatch in {path}")
        steps.extend(phase["steps"])
    require([s["id"] for s in steps] == [f"{i:02}" for i in range(1, len(steps) + 1)],
            "Roadmap steps must be unique, ordered and contiguous")
    current = int(roadmap["current_step"])
    require(1 <= current <= len(steps), "Current step is outside roadmap")
    next_id = f"{current + 1:02}" if current < len(steps) else None
    require(roadmap["next_step"] == next_id, "Next step must follow completed work")
    for index, step in enumerate(steps, 1):
        expected = "complete" if index <= current else "ready" if index == current + 1 else "planned"
        require(step["status"] == expected, f"Unexpected status for Step {step['id']}")
    print(f"PASS: {len(files)} Markdown files, {checked} local links, {len(steps)} ordered steps")


def check_sources(check_local):
    sources = read_json(ROOT / "Plan/references/sources.json")
    require(sources["reading_order"] == ["V1", "V2"], "Source reading order changed")
    require([s["id"] for s in sources["sources"]] == ["V1", "V2"], "Missing volume")
    for source in sources["sources"]:
        require(re.fullmatch(r"[0-9a-f]{64}", source["sha256"]), "Invalid source SHA-256")
        if check_local:
            path = ROOT / source["filename"]
            require(path.stat().st_size == source["bytes"], f"Source size mismatch: {path.name}")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            require(digest == source["sha256"], f"Source digest mismatch: {path.name}")
    print("PASS: source references" + (" and both local PDF fingerprints" if check_local else " (PDFs not required)"))


def check_fixture(path):
    fixture = read_json(path)
    require(fixture["schema_version"] == 1 and fixture["fictional"] is True, "Expected fictional fixture v1")
    require(fixture["entity"]["currency"] == "USD", "Fixture currency must be USD")
    require(fixture["entity"]["basis"] == "accrual", "Fixture basis must be accrual")
    require(fixture["opening_balances"] == "all_zero", "Checker assumes zero opening balances")
    start, end = date.fromisoformat(fixture["period"]["start"]), date.fromisoformat(fixture["period"]["end"])
    require(start <= end, "Invalid period")
    accounts = {}
    for account in fixture["accounts"]:
        code = account["code"]
        require(isinstance(code, str) and code.strip() and code not in accounts, "Invalid/duplicate account code")
        require(isinstance(account["name"], str) and account["name"].strip(), "Missing account name")
        require(account["classification"] in {"asset", "liability", "equity", "revenue", "expense"}, "Invalid classification")
        require(account["normal_side"] in {"debit", "credit"}, "Invalid normal side")
        require(type(account["active"]) is bool and type(account["temporary"]) is bool, "Account flags must be boolean")
        accounts[code] = account
    evidence = fixture["evidence"]
    evidence_ids = {item["id"] for item in evidence}
    require(len(evidence_ids) == len(evidence), "Duplicate evidence ID")
    require(all(item["synthetic"] is True for item in evidence), "Evidence must be synthetic")
    balances = dict.fromkeys(accounts, 0)
    seen = set()
    flows = dict.fromkeys(("operating", "investing", "financing"), 0)

    def apply(entries, allowed_kinds):
        for entry in entries:
            require(entry["id"] not in seen, f"Duplicate entry: {entry['id']}")
            seen.add(entry["id"])
            require(entry["kind"] in allowed_kinds, "Unexpected entry kind")
            require(start <= date.fromisoformat(entry["date"]) <= end, "Entry outside period")
            require(entry["evidence_id"] in evidence_ids, "Entry missing evidence")
            require(len(entry["lines"]) >= 2, "Entry needs at least two lines")
            net, cash = 0, 0
            for line in entry["lines"]:
                account = line["account"]
                require(account in accounts and accounts[account]["active"], "Unknown/inactive account")
                require(line["side"] in {"debit", "credit"}, "Invalid line side")
                amount = cents(line["amount"])
                require(amount > 0, "Line amount must be positive")
                signed = amount if line["side"] == "debit" else -amount
                net += signed
                balances[account] += signed
                if account == "1000":
                    cash += signed
            require(net == 0, f"Unbalanced entry: {entry['id']}")
            category = entry["cash_flow_category"]
            if cash:
                require(category in flows, "Cash movement needs a supported category")
                flows[category] += cash
            else:
                require(category is None, "Noncash entry must not claim a cash-flow category")

    def compare_report(label, actual):
        expected = {key: cents(value, signed=True) for key, value in fixture["expected"][label].items()}
        require(actual == expected, f"{label} differs: actual cents {actual}, expected {expected}")

    def compare_trial(label):
        expected = fixture["expected"][label]
        expected_balances = {}
        for row in expected["rows"]:
            require(row["account"] not in expected_balances, "Duplicate trial-balance row")
            debit, credit = cents(row["debit"]), cents(row["credit"])
            require(not (debit and credit), "Trial-balance row has two nonzero sides")
            expected_balances[row["account"]] = debit - credit
        require(balances == expected_balances, f"{label}: account balances differ")
        debits = sum(max(0, balance) for balance in balances.values())
        credits = sum(max(0, -balance) for balance in balances.values())
        require(debits == credits == cents(expected["total_debits"]) == cents(expected["total_credits"]),
                f"{label}: totals differ")

    transactions = fixture["transactions"]
    require(all(entry["kind"] in {"ordinary", "adjustment"} for entry in transactions), "Unexpected transaction kind")
    apply([entry for entry in transactions if entry["kind"] == "ordinary"], {"ordinary"})
    compare_trial("unadjusted_trial_balance")
    apply([entry for entry in transactions if entry["kind"] == "adjustment"], {"adjustment"})
    compare_trial("adjusted_trial_balance")

    def category_total(category):
        return sum(balances[code] for code, account in accounts.items() if account["classification"] == category)

    revenue, expenses = -category_total("revenue"), category_total("expense")
    net_income = revenue - expenses
    equity = -category_total("equity") + net_income
    compare_report("income_statement", {"revenue": revenue, "expenses": expenses, "net_income": net_income})
    compare_report("owners_equity", {"opening_capital": 0, "contributions": -balances["3000"],
                   "net_income": net_income, "drawings": balances["3100"], "ending_equity": equity})
    assets, liabilities = category_total("asset"), -category_total("liability")
    require(assets == liabilities + equity, "Accounting equation does not balance")
    compare_report("balance_sheet", {"assets": assets, "liabilities": liabilities, "equity": equity})
    require(sum(flows.values()) == balances["1000"], "Cash flows do not reconcile")
    compare_report("cash_flows", {"opening_cash": 0, **flows, "net_change": sum(flows.values()), "ending_cash": balances["1000"]})

    before_close = balances.copy()
    apply(fixture["closing_entries"], {"closing"})
    compare_trial("post_closing_trial_balance")
    for code, account in accounts.items():
        if account["temporary"]:
            require(balances[code] == 0, f"Temporary account not closed: {code}")
        elif code != "3000":
            require(balances[code] == before_close[code], "Close changed another permanent account")
    require(-balances["3000"] == equity, "Post-close capital differs from ending equity")
    print(f"PASS: {len(accounts)} accounts, {len(transactions)} transactions, {len(fixture['closing_entries'])} closing entries")
    print("PASS: all trial balances, statements, equity, cash flows and closing identities")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "data/fixtures/service-business-month.json")
    parser.add_argument("--check-sources", action="store_true", help="Also verify the two local PDF fingerprints")
    args = parser.parse_args()
    try:
        check_plan()
        check_sources(args.check_sources)
        check_fixture(args.fixture)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("Foundation verification passed. Application behavior is not implemented or tested yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
