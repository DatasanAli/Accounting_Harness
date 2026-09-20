"""Real SQLite integration tests; all records are synthetic and temporary."""

import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from pathlib import Path

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.ledger import EntryRejected, trial_balance
from accounting_harness.domain.money import Money
from accounting_harness.persistence import SQLiteLedger, PersistenceBusy

FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/service-business-month.json"


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.SQLiteLedger = SQLiteLedger
        self.PersistenceBusy = PersistenceBusy
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.sqlite3"
        self.fixture = json.loads(FIXTURE.read_text())
        self.catalog = load_account_catalog(FIXTURE)
        self.sources = {row["id"] for row in self.fixture["evidence"]}
        self.ledger = self.open()

    def open(self, **changes):
        options = dict(catalog=self.catalog, period_start="2026-01-01",
                       period_end="2026-01-31", known_source_ids=self.sources)
        options.update(changes)
        ledger = self.SQLiteLedger(self.path, **options)
        self.addCleanup(ledger.close)
        return ledger

    def sql(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(connection.close)
        return connection

    def proposal(self, entry_id="example", amount="1000.00", **changes):
        draft = dict(id=entry_id, entity_id=self.catalog.entity_id, currency="USD",
                     effective_date="2026-01-01", description="Synthetic contribution",
                     source_ids=["source-T01"], lines=[
                         dict(account="1000", side="debit", amount=amount),
                         dict(account="3000", side="credit", amount=amount)])
        draft.update(changes)
        return draft

    def post(self, draft=None, key="key", actor="local-operator", ledger=None):
        return (ledger or self.ledger).admit(self.proposal() if draft is None else draft,
                                           idempotency_key=key, actor_id=actor)

    def assert_counts(self, journals, lines, sources, events, retries):
        expected = dict(journals=journals, lines=lines, journal_sources=sources,
                        posting_events=events, idempotency=retries, reversals=0)
        self.assertEqual(self.ledger.counts(), expected)
        # A separate connection observes only committed rows.
        sql = self.sql()
        for table, count in expected.items():
            self.assertEqual(sql.execute(f"SELECT count(*) FROM {table}").fetchone()[0], count)

    def test_reference_month_survives_reopen_with_every_row_and_metadata(self):
        for row in self.fixture["transactions"]:
            if row["kind"] == "ordinary":
                self.post(self.proposal(row["id"], effective_date=row["date"],
                          description=row["description"], source_ids=[row["evidence_id"]],
                          lines=row["lines"]), key=row["id"])
        before = self.ledger.trial_balance("2026-01-31")
        self.ledger.close()
        self.ledger = self.open()
        report = self.ledger.trial_balance("2026-01-31")
        self.assertEqual(report, before)
        self.assertEqual([dict(account=r.account, debit=str(r.debit), credit=str(r.credit))
                          for r in report.rows],
                         self.fixture["expected"]["unadjusted_trial_balance"]["rows"])
        self.assertEqual(report.total_debits, Money(1330000))
        self.assertEqual(report.total_credits, Money(1330000))
        self.assertEqual(report.rows[0].debit, Money(940000))
        self.assertEqual(report.policy, "unadjusted-zero-opening-v1")
        self.assertEqual(report.included_entry_ids, tuple(f"T{i:02}" for i in range(1, 10)))
        self.assert_counts(9, 18, 9, 9, 9)

    def test_retry_returns_original_receipt_after_restart_without_side_effects(self):
        start = datetime.now(timezone.utc)
        original = self.post()
        self.assertEqual(original.actor_id, "local-operator")
        self.assertEqual(original.entry.source_ids, ("source-T01",))
        self.assertEqual(original.entry.effective_date, date(2026, 1, 1))
        self.assertLessEqual(start, original.recorded_at)
        self.assertLessEqual(original.recorded_at, datetime.now(timezone.utc))
        self.assertEqual(original.recorded_at.utcoffset().total_seconds(), 0)
        self.ledger.close()
        self.ledger = self.open()
        self.assertEqual(self.post(), original)
        self.assert_counts(1, 2, 1, 1, 1)
        with self.assertRaises(FrozenInstanceError):
            original.actor_id = "changed"

    def test_equivalent_amount_date_and_container_representations_retry(self):
        original = self.post()
        draft = self.proposal(amount=Money(100000), effective_date=date(2026, 1, 1))
        draft["source_ids"] = tuple(draft["source_ids"])
        draft["lines"][1]["amount"] = "001000.00"
        draft["lines"][1]["currency"] = "USD"
        draft["lines"] = tuple(draft["lines"])
        self.assertEqual(self.post(draft), original)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_changed_payload_or_actor_conflicts_without_mutation(self):
        self.post()
        before = self.ledger.trial_balance("2026-01-31")
        changes = [dict(description="changed"), dict(effective_date="2026-01-02"),
                   dict(source_ids=["source-T02"]), dict(id="another"),
                   dict(source_ids=["source-T01", "source-T01"])]
        drafts = [self.proposal(**c) for c in changes]
        drafts += [self.proposal(amount="999.00"),
                   self.proposal(lines=list(reversed(self.proposal()["lines"])))]
        for draft in drafts:
            with self.subTest(draft=draft), self.assertRaisesRegex(ValueError, "idempotency"):
                self.post(draft)
        with self.assertRaisesRegex(ValueError, "idempotency"):
            self.post(actor="another-operator")
        self.assertEqual(self.ledger.trial_balance("2026-01-31"), before)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_duplicate_id_other_key_rejected_but_equal_amount_new_id_is_distinct(self):
        self.post()
        with self.assertRaisesRegex(EntryRejected, "duplicate_entry_id"):
            self.post(key="another-key")
        self.post(self.proposal("another"), key="another-key")
        self.assertEqual(self.ledger.trial_balance("2026-01-31").total_debits, Money(200000))
        self.assert_counts(2, 4, 2, 2, 2)

    def test_failure_after_first_line_rolls_back_every_table_then_retry_succeeds(self):
        sql = self.sql()
        sql.execute("""CREATE TRIGGER inject_failure BEFORE INSERT ON lines
            WHEN NEW.position = 1 AND EXISTS (
                SELECT 1 FROM lines WHERE journal_id = NEW.journal_id AND position = 0)
            BEGIN SELECT RAISE(ABORT, 'injected after first line'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected after first line"):
            self.post()
        self.assert_counts(0, 0, 0, 0, 0)
        self.assertEqual(self.open().snapshot.entries, ())
        sql.execute("DROP TRIGGER inject_failure")
        original = self.post()
        self.assertEqual(self.post(), original)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_failure_after_event_before_retry_record_also_rolls_back(self):
        sql = self.sql()
        sql.execute("""CREATE TRIGGER inject_failure BEFORE INSERT ON idempotency
            WHEN EXISTS (SELECT 1 FROM posting_events)
            BEGIN SELECT RAISE(ABORT, 'injected after event'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected after event"):
            self.post()
        self.assert_counts(0, 0, 0, 0, 0)
        sql.execute("DROP TRIGGER inject_failure")
        self.post()
        self.assert_counts(1, 2, 1, 1, 1)

    def test_concurrent_connections_same_key_commit_once(self):
        barrier = threading.Barrier(2)
        def attempt():
            with self.SQLiteLedger(self.path, self.catalog, "2026-01-01", "2026-01-31",
                                   known_source_ids=self.sources) as ledger:
                barrier.wait(timeout=5)
                return self.post(ledger=ledger)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(first, second)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_busy_exhaustion_is_explicit_and_retry_after_unlock_succeeds(self):
        ledger = self.open(busy_timeout_ms=20)
        sql = self.sql()
        sql.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaisesRegex(self.PersistenceBusy, "busy.*20 ms"):
                self.post(ledger=ledger)
        finally:
            sql.rollback()
        self.assert_counts(0, 0, 0, 0, 0)
        self.post(ledger=ledger)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_invalid_proposals_leave_existing_reports_and_counts_unchanged(self):
        self.post(self.proposal("existing"))
        before = self.ledger.trial_balance("2026-01-31")
        drafts = [self.proposal(entity_id="other"), self.proposal(currency="EUR"),
                  self.proposal(source_ids=[]), self.proposal(source_ids=["unknown"]),
                  self.proposal(description=""), self.proposal(effective_date="2026-02-30"),
                  self.proposal(effective_date="2025-12-31"),
                  self.proposal(effective_date="2026-02-01"),
                  self.proposal(amount=Money(2**63)), [self.proposal()]]
        for field, value in (("account", "unknown"), ("amount", "999.00"),
                             ("amount", 1.0), ("amount", "0.00"), ("side", "both")):
            draft = self.proposal()
            draft["lines"][1][field] = value
            drafts.append(draft)
        for draft in drafts:
            with self.subTest(draft=draft), self.assertRaises(EntryRejected):
                self.post(draft, key="new-key")
            self.assertEqual(self.ledger.trial_balance("2026-01-31"), before)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_inactive_account_is_rejected_through_persistence(self):
        self.ledger.close()
        self.path = self.path.with_name("inactive.sqlite3")
        catalog = replace(self.catalog, accounts=[replace(a, active=False) if a.code == "1000"
                                                  else a for a in self.catalog.accounts])
        self.ledger = self.open(catalog=catalog)
        with self.assertRaisesRegex(EntryRejected, "invalid_account"):
            self.post()
        self.assert_counts(0, 0, 0, 0, 0)

    def test_storage_limit_and_unbounded_python_report_totals(self):
        for entry_id in ("one", "two"):
            self.post(self.proposal(entry_id, Money(2**63 - 1)), key=entry_id)
        self.ledger.close()
        self.ledger = self.open()
        report = self.ledger.trial_balance("2026-01-31")
        self.assertEqual(report.total_debits.cents, 2 * (2**63 - 1))
        self.assertEqual(report.total_credits, report.total_debits)
        stored = self.sql().execute("SELECT DISTINCT typeof(cents), cents FROM lines").fetchall()
        self.assertEqual(stored, [("integer", 2**63 - 1)])

    def test_snapshot_reproduction_and_inclusive_cutoff(self):
        self.post()
        report = self.ledger.trial_balance("2026-01-01")
        draft = self.proposal("later", effective_date="2026-01-31")
        original = copy.deepcopy(draft)
        receipt = self.post(draft, key="later")
        self.assertEqual(draft, original)
        draft["source_ids"].clear()
        draft["lines"].clear()
        self.assertEqual(len(receipt.entry.lines), 2)
        self.assertEqual(trial_balance(report.snapshot, report.as_of), report)
        self.assertEqual(self.ledger.trial_balance("2026-01-01").total_debits, Money(100000))
        self.assertEqual(self.ledger.trial_balance("2026-01-31").total_debits, Money(200000))
        with self.assertRaises(ValueError):
            self.ledger.trial_balance("2026-02-01")

    def test_invalid_actor_and_key_are_rejected(self):
        for invalid in (None, "", " ", " padded", "\t", 1, True):
            with self.subTest(value=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.post(key=invalid)
                with self.assertRaises((TypeError, ValueError)):
                    self.post(actor=invalid)
        self.assert_counts(0, 0, 0, 0, 0)

    def test_context_reopen_must_match_but_set_and_catalog_order_do_not_matter(self):
        self.post()
        equivalent = self.open(catalog=replace(self.catalog, accounts=self.catalog.accounts[::-1]),
                               period_start=date(2026, 1, 1), known_source_ids=frozenset(self.sources))
        self.assertEqual(equivalent.snapshot, self.ledger.snapshot)
        changes = [dict(period_start="2026-01-02"), dict(period_end="2026-02-01"),
                   dict(catalog=replace(self.catalog, entity_id="other")),
                   dict(catalog=replace(self.catalog, accounts=self.catalog.accounts[:-1])),
                   dict(catalog=replace(self.catalog, accounts=[replace(a, name="Changed")
                                                               for a in self.catalog.accounts])),
                   dict(known_source_ids=self.sources | {"new"})]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "context"):
                self.open(**change)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_schema_version_and_unknown_version_refusal_preserve_data(self):
        self.post()
        sql = self.sql()
        self.assertEqual(sql.execute("PRAGMA user_version").fetchone()[0], 2)
        sql.execute("PRAGMA user_version = 999")
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.open()
        self.assertEqual(sql.execute("PRAGMA user_version").fetchone()[0], 999)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_unversioned_nonempty_database_is_not_adopted(self):
        self.path = self.path.with_name("unrelated.sqlite3")
        sql = self.sql()
        sql.execute("CREATE TABLE unrelated (value TEXT)")
        with self.assertRaisesRegex(ValueError, "unversioned"):
            self.open()
        self.assertEqual(sql.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(sql.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                         [("unrelated",)])

    def test_direct_sql_constraints_and_append_only_records(self):
        self.post()
        sql = self.sql()
        # Exercise field constraints before sealing; otherwise a seal trigger
        # could mask a missing type, side, reference or primary-key constraint.
        sql.execute("BEGIN")
        sql.execute("INSERT INTO journals SELECT 'unposted', entity_id, currency, effective_date, "
                    "description FROM journals WHERE id='example'")
        sql.execute("INSERT INTO lines VALUES ('unposted', 0, '1000', 'debit', 100)")
        invalid_lines = [("example", 2, "1000", "debit", 0),
                         ("example", 2, "1000", "debit", -1),
                         ("example", 2, "1000", "debit", 1.5),
                         ("example", 2, "1000", "debit", "bad"),
                         ("example", 2, "1000", "both", 100),
                         ("example", 2, "unknown", "debit", 100),
                         ("missing", 2, "1000", "debit", 100),
                         ("example", -1, "1000", "debit", 100),
                         ("example", 0, "1000", "debit", 100)]
        for row in invalid_lines:
            row = ("unposted" if row[0] == "example" else row[0], *row[1:])
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                sql.execute("INSERT INTO lines VALUES (?, ?, ?, ?, ?)", row)
        with self.assertRaises(sqlite3.IntegrityError):
            sql.execute("INSERT INTO journal_sources VALUES ('unposted', 0, 'unknown')")
        sql.rollback()
        for table in ("journals", "lines", "journal_sources", "posting_events", "idempotency",
                      "ledger_context", "accounts", "sources"):
            with self.subTest(table=table):
                with self.assertRaises(sqlite3.IntegrityError):
                    sql.execute(f"DELETE FROM {table}")
        for statement in (
            "UPDATE journals SET description = 'changed'",
            "UPDATE lines SET cents = 200000",
            "INSERT INTO journals SELECT * FROM journals",
            "INSERT INTO posting_events SELECT * FROM posting_events",
            "INSERT INTO idempotency SELECT * FROM idempotency",
            "INSERT INTO journal_sources VALUES ('example', 1, 'unknown')",
        ):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                sql.execute(statement)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_posted_journal_cannot_gain_extra_lines_or_evidence_through_sql(self):
        self.post()
        sql = self.sql()
        before = self.ledger.trial_balance("2026-01-31")
        for statement in (
            "INSERT INTO lines VALUES ('example', 2, '1000', 'debit', 100)",
            "INSERT INTO journal_sources VALUES ('example', 1, 'source-T02')",
        ):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                sql.execute(statement)
        self.assertEqual(self.ledger.trial_balance("2026-01-31"), before)

    def test_sql_replace_cannot_rewrite_posted_records_or_context(self):
        receipt = self.post()
        sql = self.sql()
        # REPLACE's implicit delete does not fire delete triggers by default.
        self.assertEqual(sql.execute("PRAGMA recursive_triggers").fetchone()[0], 0)
        for table in ("journals", "lines", "journal_sources", "posting_events", "idempotency",
                      "ledger_context", "accounts", "sources"):
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                sql.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
        self.assertEqual(self.post(), receipt)
        self.assert_counts(1, 2, 1, 1, 1)

    def test_sql_rowid_replace_cannot_move_a_posted_line_to_another_journal(self):
        receipt = self.post()
        sql = self.sql()
        sql.execute("BEGIN")
        sql.execute("INSERT INTO journals SELECT 'unposted', entity_id, currency, effective_date, "
                    "description FROM journals WHERE id='example'")
        for alias in ("rowid", "_rowid_", "oid"):
            with self.subTest(alias=alias), self.assertRaises(sqlite3.Error):
                sql.execute(f"INSERT OR REPLACE INTO lines "
                            f"({alias}, journal_id, position, account, side, cents) "
                            "VALUES (1, 'unposted', 0, '1000', 'debit', 100000)")
        sql.rollback()
        self.assertEqual(self.post(), receipt)


if __name__ == "__main__":
    unittest.main()
