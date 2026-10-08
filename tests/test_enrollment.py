"""Additive enrollment, legacy identity and failure-boundary integration tests."""
import json
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch

import test_review
from accounting_harness.approval import ReviewApplication
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.runs import FakeProvider, RunLimits, SQLiteRunEngine
from accounting_harness.sources import SQLiteSourceRegistry


class EnrollmentTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp
    save = test_review.ReviewTests.save

    def register(self, identity='new'):
        return self.registry.register(dict(self.document, document_id=identity, amount='125.00'),
                                      actor_id='importer').record

    def enroll(self, identity='new', ledger=None, registry=None, actor='enroller'):
        return (ledger or self.ledger).enroll_source(registry or self.registry, identity, actor_id=actor)

    def test_listing_and_enrollment_retry_audit_and_live_connections(self):
        source = self.register()
        self.assertEqual(tuple(s.document_id for s in self.registry.list_documents()), ('new', 'rent'))
        before = self.ledger.snapshot
        with SQLiteLedger(self.path, **self.options) as other:
            first = self.enroll()
            self.assertEqual(first.state, 'enrolled')
            self.assertEqual(first.actor_id, 'enroller')
            self.assertEqual(first.content_digest, source.content_digest)
            self.assertEqual(self.enroll(ledger=other, actor='retry-operator'), first)
            self.assertEqual(other.known_source_ids(), frozenset({'rent', 'new'}))
        self.assertEqual(self.ledger.snapshot, before)
        baseline = self.enroll('rent')
        self.assertEqual(baseline.state, 'already_known')
        self.assertIsNone(baseline.actor_id)
        self.assertIsNone(baseline.recorded_at)
        self.assertEqual(self.ledger._sources, frozenset({'rent'}))
        self.assertEqual(self.ledger._connection.execute('SELECT count(*) FROM source_enrollments').fetchone(), (1,))

    def test_new_source_requires_enrollment_then_human_review_and_post(self):
        source = self.register()
        proposal = dict(self.proposal, id='new-journal', source_ids=['new'], lines=[
            dict(account='5000', side='debit', amount='125.00'),
            dict(account='1000', side='credit', amount='125.00')])
        evidence = {'new': source.content_digest}
        self.assertTrue(self.store.validate(proposal, evidence))
        self.enroll()
        self.assertEqual(self.store.validate(proposal, evidence), ())
        draft = self.save(proposal=proposal, evidence=evidence)
        app = ReviewApplication(self.store)
        approval = app.approve('draft', revision=1, confirmed_digest=draft.content_digest,
                               actor_id='human', idempotency_key='approval')
        receipt = app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(receipt.entry.source_ids, ('new',))
        self.assertEqual(self.ledger.trial_balance('2026-01-31').total_debits.cents, 12500)

    def test_legacy_post_approval_and_in_progress_run_keep_exact_bytes(self):
        receipt = self.ledger.admit(self.proposal, actor_id='legacy', idempotency_key='legacy')
        draft = self.save(proposal=dict(self.proposal, id='approved-journal'))
        app = ReviewApplication(self.store)
        approval = app.approve('draft', revision=1, confirmed_digest=draft.content_digest,
                               actor_id='human', idempotency_key='approval')
        run_path = self.path.with_name('runs.sqlite3')
        provider = FakeProvider([dict(tool='read_accounts', arguments=dict(entity_id=self.catalog.entity_id))])
        with SQLiteRunEngine(run_path, self.store) as engine:
            checkpoint = engine.start('in-progress', task_id='task', provider=provider,
                                      actor_id='agent', limits=RunLimits(2, 10000, 10, 0))
            configuration = engine.configuration('in-progress')
            scope = engine._scope
        tables = ('ledger_context', 'sources', 'journals', 'idempotency', 'approvals', 'approval_requests')
        before = {t: self.ledger._connection.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        report = self.ledger.trial_balance('2026-01-31')
        self.register()
        self.enroll()
        with SQLiteLedger(self.path, **self.options) as ledger:
            store = SQLiteReviewStore(ledger, self.registry)
            reopened_app = ReviewApplication(store)
            for table in tables:
                if table != 'sources':
                    self.assertEqual(ledger._connection.execute(f'SELECT * FROM {table}').fetchall(), before[table])
            self.assertEqual(ledger._context, self.ledger._context)
            self.assertEqual(ledger.trial_balance('2026-01-31'), report)
            self.assertEqual(ledger.admit(self.proposal, actor_id='legacy', idempotency_key='legacy'), receipt)
            with SQLiteRunEngine(run_path, store) as engine:
                self.assertEqual(engine.get('in-progress'), checkpoint)
                self.assertEqual(engine.configuration('in-progress'), configuration)
                self.assertEqual(engine._scope, scope)
            posted = reopened_app.post(approval.approval_id, actor_id='human', idempotency_key='post')
            self.assertEqual(posted.entry.id, 'approved-journal')

    def test_conflicts_wrong_entity_and_corrupt_or_unsupported_content_do_not_write(self):
        source = self.register()
        first = self.enroll()
        with SQLiteSourceRegistry(self.path.with_name('other.sqlite3'), self.catalog.entity_id) as registry:
            registry.register(dict(self.document, document_id='new', amount='126.00'), actor_id='other')
            with self.assertRaises(ValueError):
                self.enroll(registry=registry)
        with SQLiteSourceRegistry(self.path.with_name('wrong.sqlite3'), 'other') as registry:
            registry.register(dict(self.document, entity_id='other', document_id='wrong'), actor_id='other')
            with self.assertRaises(ValueError):
                self.enroll('wrong', registry=registry)
        for changed in (replace(source, content_digest='0'*64),
                        replace(source, canonical_content=source.canonical_content.replace('true', 'false'))):
            with patch.object(self.registry, 'get', return_value=changed), self.assertRaises(ValueError):
                self.enroll()
        self.assertEqual(self.enroll(), first)
        self.assertEqual(self.ledger.known_source_ids(), frozenset({'new', 'rent'}))

    def test_failure_between_audit_and_source_rolls_back_and_retry_recovers(self):
        self.register()
        self.ledger._connection.execute("CREATE TRIGGER fail_enroll BEFORE INSERT ON sources BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.enroll()
        self.assertEqual(self.ledger._connection.execute('SELECT * FROM source_enrollments').fetchall(), [])
        self.assertEqual(self.ledger.known_source_ids(), frozenset({'rent'}))
        self.ledger._connection.execute('DROP TRIGGER fail_enroll')
        self.assertEqual(self.enroll().state, 'enrolled')

    def test_concurrent_enrollment_creates_one_original_audit_receipt(self):
        self.register()
        barrier = Barrier(2)
        def enroll(actor):
            with SQLiteLedger(self.path, **self.options) as ledger:
                with SQLiteSourceRegistry(self.source_path, self.catalog.entity_id) as registry:
                    barrier.wait()
                    return self.enroll(ledger=ledger, registry=registry, actor=actor)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(enroll, ('first', 'second')))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.ledger._connection.execute('SELECT count(*) FROM source_enrollments').fetchone(), (1,))

    def test_direct_sql_unaudited_insert_and_all_replace_update_delete_are_blocked(self):
        self.register()
        self.enroll()
        db = self.ledger._connection
        row = db.execute('SELECT * FROM source_enrollments').fetchone()
        for sql, values in [("INSERT INTO sources VALUES ('unaudited')", ()),
                            ("INSERT OR REPLACE INTO sources VALUES ('rent')", ()),
                            ("INSERT OR REPLACE INTO sources VALUES ('new')", ()),
                            ('UPDATE source_enrollments SET actor_id=?', ('changed',)),
                            ('DELETE FROM source_enrollments', ()),
                            ('INSERT OR REPLACE INTO source_enrollments VALUES (?,?,?,?,?,?,?)', row)]:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                db.execute(sql, values)

    def legacy_v2(self):
        """Use the genuine pre-enrollment schema and its normal posting path."""
        path = self.path.with_name('v2.sqlite3')
        with patch.object(SQLiteLedger, '_migrate_v3', lambda ledger: None):
            with SQLiteLedger(path, **self.options) as ledger:
                receipt = ledger.admit(self.proposal, actor_id='old', idempotency_key='old')
        return path, receipt

    def test_populated_v2_migration_preserves_history_and_frozen_context(self):
        path, receipt = self.legacy_v2()
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (2,))
            dump = {t: db.execute(f'SELECT * FROM {t}').fetchall() for t in
                    ('ledger_context', 'sources', 'journals', 'lines', 'journal_sources', 'posting_events', 'idempotency')}
        with SQLiteLedger(path, **self.options) as ledger:
            self.assertEqual(ledger._connection.execute('PRAGMA user_version').fetchone(), (4,))
            for table, rows in dump.items():
                self.assertEqual(ledger._connection.execute(f'SELECT * FROM {table}').fetchall(), rows)
            self.assertEqual(ledger.admit(self.proposal, actor_id='old', idempotency_key='old'), receipt)
            self.assertEqual(ledger._connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_v3_migration_ddl_failure_rolls_back_version_triggers_and_rows(self):
        path, receipt = self.legacy_v2()
        migrate = SQLiteLedger._migrate_v3
        def fail(ledger):
            migrate(ledger)
            raise RuntimeError('injected migration failure')
        with sqlite3.connect(path) as db:
            before = tuple(db.iterdump())
        with patch.object(SQLiteLedger, '_migrate_v3', fail):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                SQLiteLedger(path, **self.options)
        with sqlite3.connect(path) as db:
            self.assertEqual(tuple(db.iterdump()), before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (2,))
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name='sources_frozen'").fetchone(),
                             ('sources_frozen',))
        with SQLiteLedger(path, **self.options) as ledger:
            self.assertEqual(ledger.receipt(receipt.entry.id), receipt)

    def test_enrolled_audit_anchor_rejects_substitute_registry_evidence(self):
        self.register()
        self.enroll()
        with SQLiteSourceRegistry(self.path.with_name('substitute.sqlite3'), self.catalog.entity_id) as registry:
            source = registry.register(dict(self.document, document_id='new', amount='126.00'), actor_id='other').record
            proposal = dict(self.proposal, source_ids=['new'], lines=[
                dict(account='5000', side='debit', amount='126.00'),
                dict(account='1000', side='credit', amount='126.00')])
            store = SQLiteReviewStore(self.ledger, registry)
            self.assertIn('conflicting_evidence', [f.code for f in store.validate(proposal, {'new': source.content_digest})])

    def test_cli_enrollment_demo(self):
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-enrollment'],
                                text=True, capture_output=True, cwd=test_review.ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('125.00', result.stdout)
        self.assertIn('zero additional journals', result.stdout)
