import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.persistence import SQLiteLedger, PersistenceBusy
from accounting_harness.sources import SQLiteSourceRegistry
from accounting_harness.review import SQLiteReviewStore

ROOT = Path(__file__).resolve().parents[1]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.sqlite3'
        self.source_path = Path(self.temp.name) / 'sources.sqlite3'
        self.catalog = load_account_catalog(ROOT / 'data/fixtures/service-business-month.json')
        self.document = json.loads((ROOT / 'data/fixtures/source-receipt.json').read_text())
        self.document.update(document_id='rent', amount='1200.00', description='Fictional rent')
        self.registry = SQLiteSourceRegistry(self.source_path, self.catalog.entity_id)
        self.addCleanup(self.registry.close)
        self.source = self.registry.register(self.document, actor_id='importer').record
        self.options = dict(catalog=self.catalog, period_start='2026-01-01',
                            period_end='2026-01-31', known_source_ids={'rent'})
        self.ledger = SQLiteLedger(self.path, **self.options)
        self.addCleanup(self.ledger.close)
        self.store = SQLiteReviewStore(self.ledger, self.registry)
        self.proposal = dict(id='rent-journal', entity_id=self.catalog.entity_id, currency='USD',
                             effective_date='2026-01-05', description='Fictional rent',
                             source_ids=['rent'], lines=[
                                 dict(account='5000', side='debit', amount='1200.00'),
                                 dict(account='1000', side='credit', amount='1200.00')])
        self.evidence = {'rent': self.source.content_digest}

    def save(self, **changes):
        args = dict(draft_id='draft', proposal=self.proposal, evidence=self.evidence,
                    expected_revision=0, actor_id='proposer', idempotency_key='create', reason='Rent proposal')
        args.update(changes)
        return self.store.save(**args)

    def reject(self, **changes):
        args = dict(draft_id='draft', expected_revision=1, actor_id='reviewer',
                    idempotency_key='reject', reason='Wrong amount')
        args.update(changes)
        return self.store.reject(**args)

    def test_edit_history_reopen_and_input_snapshot(self):
        first = self.save()
        self.assertTrue(first.reviewable)
        self.proposal['lines'][0]['amount'] = '1100.00'
        second = self.save(expected_revision=1, idempotency_key='edit')
        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 2)
        self.assertIn('unbalanced', [f.code for f in second.findings])
        self.assertIn('1200.00', first.proposal_json)
        self.assertEqual(self.store.history('draft'), (first, second))
        with SQLiteLedger(self.path, **self.options) as reopened:
            review = SQLiteReviewStore(reopened, self.registry)
            self.assertEqual(review.history('draft'), (first, second))
            self.assertEqual(review.queue(), (second,))
            self.assertEqual(reopened.counts()['journals'], 0)

    def test_rejection_is_revision_and_edit_returns_pending(self):
        first = self.save()
        rejected = self.reject()
        self.assertEqual(rejected.state, 'rejected')
        self.assertFalse(rejected.reviewable)
        self.assertEqual(rejected.reason, 'Wrong amount')
        self.assertEqual(self.store.get('draft', 1), first)
        with self.assertRaises(ValueError):
            self.reject(expected_revision=2, idempotency_key='again')
        edited = self.save(expected_revision=2, idempotency_key='edit')
        self.assertEqual(edited.state, 'pending')
        self.assertEqual(self.store.queue('rejected'), ())

    def test_retries_preserve_original_and_changed_requests_conflict(self):
        first = self.save()
        self.assertEqual(self.save(), first)
        self.reject()
        self.assertEqual(self.save(), first)
        for changes in ({'actor_id': 'other'}, {'reason': 'other'}, {'evidence': {'rent': '0'*64}},
                        {'expected_revision': 1}, {'proposal': dict(self.proposal, description='other')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.save(**changes)
        self.assertEqual(len(self.store.history('draft')), 2)

    def test_stale_edits_bad_metadata_and_unknown_state(self):
        self.save()
        for changes in ({'expected_revision': 0}, {'expected_revision': True},
                        {'actor_id': ''}, {'draft_id': ' bad'}, {'reason': ''}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.save(idempotency_key='bad', **changes)
        with self.assertRaises(ValueError):
            self.store.queue('approved')
        with self.assertRaises(KeyError):
            self.store.get('missing')

    def test_missing_conflicting_and_unbound_sources_remain_findings(self):
        for index, evidence in enumerate(({}, {'rent': '0'*64}, {'missing': '0'*64})):
            record = self.save(draft_id=f'draft-{index}', idempotency_key=str(index), evidence=evidence)
            self.assertFalse(record.reviewable)
            self.assertTrue(record.findings)
        changed = dict(self.proposal, source_ids=['missing'])
        record = self.save(draft_id='missing', idempotency_key='missing', proposal=changed,
                           evidence={'missing': '0'*64})
        self.assertIn('missing_evidence', [f.code for f in record.findings])
        self.assertEqual(len(self.store.queue()), 4)

    def test_amount_period_overflow_and_entity_checks(self):
        cases = [dict(self.proposal, entity_id='other'),
                 dict(self.proposal, effective_date='2026-02-01'),
                 dict(self.proposal, lines=[dict(l, amount='1100.00') for l in self.proposal['lines']]),
                 dict(self.proposal, lines=[dict(l, amount='999999999999999999.00') for l in self.proposal['lines']])]
        for index, proposal in enumerate(cases):
            r = self.save(draft_id=str(index), idempotency_key=str(index), proposal=proposal)
            self.assertFalse(r.reviewable)
        with SQLiteSourceRegistry(Path(self.temp.name)/'other.sqlite3', 'other') as registry:
            with self.assertRaises(ValueError):
                SQLiteReviewStore(self.ledger, registry)

    def test_current_evidence_rechecked_without_overwriting_historical_findings(self):
        first = self.save()
        with SQLiteSourceRegistry(Path(self.temp.name)/'empty.sqlite3', self.catalog.entity_id) as empty:
            store = SQLiteReviewStore(self.ledger, empty)
            record = store.get('draft')
            self.assertEqual(record.findings, first.findings)
            self.assertFalse(record.reviewable)
            self.assertIn('missing_evidence', [f.code for f in record.current_findings])

    def test_atomic_event_failure_rolls_back_revision_and_retry(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_review BEFORE INSERT ON review_events BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save()
        self.assertEqual(self.store.queue(), ())
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER fail_review')
        self.assertEqual(self.save().revision, 1)

    def test_immutability_and_unsupported_version(self):
        first = self.save()
        with sqlite3.connect(self.path) as db:
            for table in ('draft_revisions', 'review_events', 'review_requests', 'review_schema'):
                for sql in (f'DELETE FROM {table}', f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                    with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql)
            db.execute('DROP TRIGGER review_schema_no_update')
            db.execute('UPDATE review_schema SET version=99')
        with self.assertRaises(ValueError):
            SQLiteReviewStore(self.ledger, self.registry)
        self.assertEqual(self.store.get('draft'), first)

    def test_concurrent_edits_have_one_winner(self):
        self.save()
        barrier = Barrier(2)
        def worker(i):
            with SQLiteLedger(self.path, **self.options) as ledger, SQLiteSourceRegistry(self.source_path, self.catalog.entity_id) as registry:
                store = SQLiteReviewStore(ledger, registry)
                barrier.wait(timeout=5)
                try:
                    return store.save('draft', self.proposal, evidence=self.evidence, expected_revision=1,
                                      actor_id='op', idempotency_key=str(i), reason='edit')
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.store.history('draft')), 2)

    def test_bounded_lock_failure_and_unchanged_ledger(self):
        before = self.ledger.snapshot
        with SQLiteLedger(self.path, **self.options, busy_timeout_ms=0) as ledger:
            review = SQLiteReviewStore(ledger, self.registry)
            with sqlite3.connect(self.path) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                with self.assertRaises(PersistenceBusy):
                    review.save('draft', self.proposal, evidence=self.evidence, expected_revision=0,
                                actor_id='op', idempotency_key='key', reason='rent')
        self.assertEqual(self.ledger.snapshot, before)
        self.assertEqual(self.store.queue(), ())

    def test_reject_retry_and_retry_write_failure_are_atomic(self):
        self.save()
        rejected = self.reject()
        self.assertEqual(self.reject(), rejected)
        with self.assertRaises(ValueError):
            self.reject(reason='changed')
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_retry BEFORE INSERT ON review_requests BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save(expected_revision=2, idempotency_key='edit')
        self.assertEqual(self.store.get('draft'), rejected)

    def test_initialization_rolls_back_and_legacy_ledger_reopens(self):
        path = Path(self.temp.name) / 'legacy.sqlite3'
        class FailingReview(SQLiteReviewStore):
            def _initialize(self):
                super()._initialize()
                raise RuntimeError('injected initialization failure')
        with SQLiteLedger(path, **self.options) as ledger:
            receipt = ledger.admit(self.proposal, actor_id='operator', idempotency_key='original')
            before = ledger.snapshot
            with self.assertRaises(RuntimeError):
                FailingReview(ledger, self.registry)
            self.assertIsNone(ledger._connection.execute("SELECT 1 FROM sqlite_master WHERE name='review_schema'").fetchone())
            SQLiteReviewStore(ledger, self.registry)
        with SQLiteLedger(path, **self.options) as reopened:
            self.assertEqual(reopened.snapshot, before)
            self.assertEqual(reopened.admit(self.proposal, actor_id='operator', idempotency_key='original'), receipt)
