"""Full correction, crash recovery and migration tests with synthetic SQLite files."""

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.ledger import EntryRejected, trial_balance
from accounting_harness.domain.money import Money
from accounting_harness.persistence import SQLiteLedger

FIXTURE = Path(__file__).resolve().parents[1] / 'data/fixtures/service-business-month.json'
V1 = Path(__file__).parent / 'fixtures/step05-v1.sql'


class ReversalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'ledger.sqlite3'
        self.catalog = load_account_catalog(FIXTURE)
        self.options = dict(catalog=self.catalog, period_start='2026-01-01',
                            period_end='2026-01-31', known_source_ids={
                                s['id'] for s in json.loads(FIXTURE.read_text())['evidence']})
        self.ledger = self.open()
        self.proposal = dict(id='expense', entity_id=self.catalog.entity_id, currency='USD',
                             effective_date='2026-01-05', description='Fictional erroneous expense',
                             source_ids=['source-T01'], lines=[
                                 dict(account='5100', side='debit', amount='125.00'),
                                 dict(account='1000', side='credit', amount='125.00')])
        self.original = self.ledger.admit(self.proposal, idempotency_key='original-key',
                                          actor_id='local-operator')

    def open(self):
        ledger = SQLiteLedger(self.path, **self.options)
        self.addCleanup(ledger.close)
        return ledger

    def sql(self):
        sql = sqlite3.connect(self.path, isolation_level=None)
        sql.execute('PRAGMA foreign_keys = ON')
        self.addCleanup(sql.close)
        return sql

    def reverse(self, ledger=None, **changes):
        options = dict(original_id='expense', reversal_id='reversal',
                       entity_id=self.catalog.entity_id, effective_date='2026-01-10',
                       reason='Expense entered in error', source_ids=['source-T02'],
                       actor_id='local-operator', idempotency_key='correction-key')
        options.update(changes)
        return (ledger or self.ledger).reverse(**options)

    def state(self):
        sql = self.sql()
        return {table: sql.execute(f'SELECT * FROM {table}').fetchall() for table in (
            'journals', 'lines', 'journal_sources', 'posting_events', 'idempotency', 'reversals')}

    def test_schema_supports_durable_reversal_links(self):
        self.assertEqual(self.sql().execute('PRAGMA user_version').fetchone()[0], 2)

    def test_full_reversal_preserves_original_and_snapshot_across_restart(self):
        before = self.ledger.trial_balance('2026-01-31')
        original_rows = self.state()
        receipt = self.reverse()
        after_rows = self.state()
        for table, rows in original_rows.items():
            for row in rows:
                self.assertIn(row, after_rows[table])
        self.assertEqual(receipt.original_entry_id, 'expense')
        self.assertEqual(receipt.entry.description, 'Expense entered in error')
        self.assertEqual(receipt.entry.source_ids, ('source-T02',))
        self.assertEqual([(l.account, l.side, l.amount.cents) for l in receipt.entry.lines],
                         [('5100', 'credit', 12500), ('1000', 'debit', 12500)])
        self.assertEqual(receipt.recorded_at.utcoffset().total_seconds(), 0)
        self.assertEqual(self.ledger.receipt('expense'), self.original)
        self.assertEqual(self.ledger.trial_balance('2026-01-09').total_debits, Money(12500))
        report = self.ledger.trial_balance('2026-01-10')
        self.assertEqual(report.included_entry_ids, ('expense', 'reversal'))
        self.assertTrue(all(r.debit == Money(0) and r.credit == Money(0) for r in report.rows))
        self.assertEqual(trial_balance(before.snapshot, before.as_of), before)
        self.ledger.close()
        self.ledger = self.open()
        self.assertEqual(self.ledger.receipt('expense'), self.original)
        self.assertEqual(self.ledger.receipt('reversal'), receipt)
        self.assertEqual(self.reverse(), receipt)
        self.assertEqual(self.ledger.admit(self.proposal, idempotency_key='original-key',
                                         actor_id='local-operator'), self.original)
        self.assertEqual(self.ledger.trial_balance('2026-01-10'), report)

    def test_retry_canonicalization_and_action_scope(self):
        receipt = self.reverse(idempotency_key='original-key')
        before = self.state()
        self.assertEqual(self.reverse(idempotency_key='original-key',
                                      effective_date=date(2026, 1, 10),
                                      source_ids=('source-T02',)), receipt)
        self.assertEqual(self.state(), before)

    def test_changed_retry_payload_rejected_without_mutation(self):
        self.ledger.admit(dict(self.proposal, id='other'), idempotency_key='other', actor_id='operator')
        self.reverse()
        before = self.state()
        for change in (dict(reversal_id='new'), dict(original_id='other'),
                       dict(effective_date='2026-01-11'), dict(reason='Different reason'),
                       dict(source_ids=['source-T03']), dict(actor_id='another'),
                       dict(source_ids=['source-T02', 'source-T02'])):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'idempotency'):
                self.reverse(**change)
            self.assertEqual(self.state(), before)

    def test_duplicate_id_and_second_reversal_rejected(self):
        before = self.state()
        with self.assertRaisesRegex(EntryRejected, 'duplicate_entry_id'):
            self.reverse(reversal_id='expense')
        self.assertEqual(self.state(), before)
        self.reverse()
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'already reversed'):
            self.reverse(idempotency_key='another', reversal_id='another')
        with self.assertRaisesRegex(ValueError, 'reversal of a reversal'):
            self.reverse(original_id='reversal', reversal_id='another', idempotency_key='another')
        self.assertEqual(self.state(), before)

    def test_invalid_requests_do_not_change_any_records_or_balances(self):
        before = self.state()
        report = self.ledger.trial_balance('2026-01-31')
        for change in (dict(original_id='missing'), dict(entity_id='another'),
                       dict(source_ids=[]), dict(source_ids=['unknown']), dict(source_ids='source-T02'),
                       dict(reason=''), dict(reversal_id=''), dict(effective_date='2026-02-30'),
                       dict(effective_date='2025-12-31'), dict(effective_date='2026-02-01'),
                       dict(actor_id=''), dict(idempotency_key=''), dict(original_id=None)):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                self.reverse(**change)
            self.assertEqual(self.state(), before)
            self.assertEqual(self.ledger.trial_balance('2026-01-31'), report)
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.ledger.receipt('missing')

    def test_revalidates_current_accounts_sources_and_period_inside_transaction(self):
        # Context is frozen in this version. Substitute the service's trusted
        # context to exercise future policy changes without editing posted rows.
        empty, sources = self.ledger._empty, self.ledger._sources
        before = self.state()
        for catalog in (
            replace(self.catalog, accounts=tuple(a for a in self.catalog.accounts if a.code != '5100')),
            replace(self.catalog, accounts=tuple(replace(a, active=False) if a.code == '5100'
                                                 else a for a in self.catalog.accounts)),
        ):
            self.ledger._empty = replace(empty, catalog=catalog)
            with self.assertRaisesRegex(EntryRejected, 'invalid_account'):
                self.reverse()
        self.ledger._empty = replace(empty, period_start=date(2026, 1, 11))
        with self.assertRaisesRegex(EntryRejected, 'date_out_of_range'):
            self.reverse()
        self.ledger._empty = empty
        self.ledger._sources = frozenset()
        with self.assertRaises(EntryRejected):
            self.reverse()
        self.ledger._sources = sources
        self.assertEqual(self.state(), before)

    def test_mid_write_and_after_event_failures_rollback_then_retry_once(self):
        before = self.state()
        sql = self.sql()
        for table, condition in (('lines', 'NEW.position = 1'), ('reversals', '1')):
            sql.execute(f"""CREATE TRIGGER inject_failure BEFORE INSERT ON {table}
                WHEN {condition} BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected failure'):
                self.reverse()
            self.assertEqual(self.state(), before)
            self.assertEqual(self.open().snapshot.entries, (self.original.entry,))
            sql.execute('DROP TRIGGER inject_failure')
        receipt = self.reverse()
        self.assertEqual(self.reverse(), receipt)
        self.assertEqual(self.ledger.counts(), dict(journals=2, lines=4, journal_sources=2,
                                                  posting_events=2, idempotency=1, reversals=1))

    def test_concurrent_same_key_returns_same_receipt(self):
        results = self.concurrent(False)
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.ledger.counts()['reversals'], 1)
        self.assertEqual(self.ledger.counts()['journals'], 2)

    def test_concurrent_different_keys_reverse_original_at_most_once(self):
        results = self.concurrent(True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(self.ledger.counts()['reversals'], 1)
        self.assertEqual(self.ledger.counts()['journals'], 2)

    def concurrent(self, different):
        barrier = threading.Barrier(2)
        def attempt(index):
            with SQLiteLedger(self.path, **self.options) as ledger:
                barrier.wait(timeout=5)
                try:
                    return self.reverse(ledger, idempotency_key=str(index) if different else 'key',
                                        reversal_id=str(index) if different else 'reversal')
                except ValueError as error:
                    return error
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, range(2)))

    def test_maximum_integer_cents_reverse_exactly(self):
        draft = dict(self.proposal, id='large', lines=[
            dict(account='5100', side='debit', amount=Money(2**63 - 1)),
            dict(account='1000', side='credit', amount=Money(2**63 - 1))])
        self.ledger.admit(draft, idempotency_key='large', actor_id='operator')
        result = self.reverse(original_id='large')
        self.assertEqual(result.entry.lines[0].amount.cents, 2**63 - 1)
        self.assertEqual(self.ledger.trial_balance('2026-01-31').total_debits, Money(12500))

    def load_v1(self):
        self.ledger.close()
        self.path = self.path.with_name('legacy.sqlite3')
        sql = self.sql()
        sql.execute('PRAGMA foreign_keys = OFF')
        sql.executescript(V1.read_text())
        sql.execute('PRAGMA foreign_keys = ON')
        return sql

    def test_v1_migration_preserves_all_rows_original_receipt_and_retries(self):
        sql = self.load_v1()
        tables = ('journals', 'lines', 'journal_sources', 'posting_events', 'idempotency')
        before = {t: sql.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        self.ledger = self.open()
        self.assertEqual(sql.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual({t: sql.execute(f'SELECT * FROM {t}').fetchall() for t in tables}, before)
        original = self.ledger.receipt('expense')
        self.assertEqual(self.ledger.admit(self.proposal, idempotency_key='original-key',
                                         actor_id='local-operator'), original)
        self.reverse()
        self.assertEqual(self.open().receipt('expense'), original)
        self.assertEqual(self.ledger.trial_balance('2026-01-31').total_debits, Money(0))
        self.assertEqual(sql.execute('PRAGMA foreign_key_check').fetchall(), [])
        for statement in ("UPDATE journals SET description='changed'", 'DELETE FROM posting_events'):
            with self.assertRaises(sqlite3.IntegrityError):
                sql.execute(statement)

    def test_context_mismatch_does_not_migrate_v1(self):
        sql = self.load_v1()
        self.options['period_end'] = '2026-02-01'
        with self.assertRaisesRegex(ValueError, 'context'):
            self.open()
        self.assertEqual(sql.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertIsNone(sql.execute("SELECT name FROM sqlite_master WHERE name='reversals'").fetchone())

    def test_migration_failure_rolls_back_schema_and_keeps_version(self):
        sql = self.load_v1()
        sql.execute('CREATE TABLE reversals (sentinel TEXT)')
        before = sql.execute('SELECT * FROM journals').fetchall()
        with self.assertRaises(sqlite3.OperationalError):
            self.open()
        self.assertEqual(sql.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(sql.execute('SELECT * FROM journals').fetchall(), before)
        sql.execute('DROP TABLE reversals')
        self.ledger = self.open()
        self.reverse()
        self.assertEqual(self.ledger.counts()['reversals'], 1)

    def test_link_constraints_and_immutability(self):
        self.reverse()
        sql = self.sql()
        before = self.state()
        for statement in ('DELETE FROM reversals', "UPDATE reversals SET key='changed'",
                          'INSERT OR REPLACE INTO reversals SELECT * FROM reversals'):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                sql.execute(statement)
        self.assertEqual(self.state(), before)

    def test_existing_reversal_id_cannot_be_used_for_another_original(self):
        self.reverse()
        self.ledger.admit(dict(self.proposal, id='other'), idempotency_key='other', actor_id='operator')
        before = self.state()
        with self.assertRaisesRegex(EntryRejected, 'duplicate_entry_id'):
            self.reverse(original_id='other', idempotency_key='another-key')
        self.assertEqual(self.state(), before)

    def test_sql_link_rejects_invalid_references_scope_digest_and_chains(self):
        for name in ('other', 'third'):
            self.ledger.admit(dict(self.proposal, id=name), idempotency_key=name, actor_id='operator')
        sql = self.sql()
        valid = ['expense', 'other', self.catalog.entity_id, 'reverse-v1', 'key', 'a' * 64]
        # Independent, unoccupied keys ensure each constraint is exercised.
        for index, value in ((0, 'missing'), (1, 'missing'), (1, 'expense'), (2, 'wrong-entity'),
                             (3, 'post-v1'), (4, ''), (4, ' padded'), (5, 'bad'), (5, 'z' * 64)):
            row = valid.copy()
            row[index] = value
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                sql.execute('INSERT INTO reversals VALUES (?, ?, ?, ?, ?, ?)', row)
        sql.execute('INSERT INTO reversals VALUES (?, ?, ?, ?, ?, ?)', valid)
        for original, reversal in (('expense', 'third'), ('third', 'other'),
                                   ('other', 'third'), ('third', 'expense')):
            with self.subTest(original=original, reversal=reversal), self.assertRaises(sqlite3.IntegrityError):
                sql.execute('INSERT INTO reversals VALUES (?, ?, ?, ?, ?, ?)',
                            (original, reversal, self.catalog.entity_id, 'reverse-v1', 'new', 'b' * 64))
        self.assertEqual(sql.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_failure_after_migration_ddl_rolls_back_all_new_schema(self):
        sql = self.load_v1()
        schema = sql.execute('SELECT * FROM sqlite_master').fetchall()
        migrate = SQLiteLedger._migrate_v2
        def fail_after_ddl(ledger):
            migrate(ledger)
            raise RuntimeError('injected migration failure')
        with patch.object(SQLiteLedger, '_migrate_v2', fail_after_ddl):
            with self.assertRaisesRegex(RuntimeError, 'injected migration failure'):
                self.open()
        self.assertEqual(sql.execute('SELECT * FROM sqlite_master').fetchall(), schema)
        self.assertEqual(sql.execute('PRAGMA user_version').fetchone()[0], 1)
        self.ledger = self.open()
        self.reverse()
        self.assertEqual(self.ledger.counts()['reversals'], 1)
