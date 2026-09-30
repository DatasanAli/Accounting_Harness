import json
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import test_review
ROOT = test_review.ROOT
from accounting_harness.approval import ReviewApplication
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.sources import SQLiteSourceRegistry


class ApprovalTests(unittest.TestCase):
    save = test_review.ReviewTests.save
    reject = test_review.ReviewTests.reject
    def setUp(self):
        test_review.ReviewTests.setUp(self)
        self.application = ReviewApplication(self.store)

    def approve(self, **changes):
        current = self.store.get('draft')
        args = dict(draft_id='draft', revision=current.revision, confirmed_digest=current.content_digest,
                    actor_id='human', idempotency_key='approve')
        args.update(changes)
        return self.application.approve(**args)

    def post(self, approval, **changes):
        args = dict(actor_id='human', idempotency_key='post')
        args.update(changes)
        return self.application.post(approval.approval_id, **args)

    def test_approval_post_reopen_retry_trace_and_snapshot(self):
        first = self.save()
        before = self.ledger.snapshot
        approval = self.approve()
        self.assertEqual(self.approve(), approval)
        receipt = self.post(approval)
        self.assertEqual(receipt.entry.id, 'rent-journal')
        self.assertEqual(receipt.entry.lines[0].amount.cents, 120000)
        self.assertEqual(before.entries, ())
        with SQLiteLedger(self.path, **self.options) as ledger:
            app = ReviewApplication(SQLiteReviewStore(ledger, self.registry))
            self.assertEqual(app.post(approval.approval_id, actor_id='human', idempotency_key='post'), receipt)
            trail = app.trace('draft')
            self.assertEqual(trail['revisions'], (first,))
            self.assertEqual(trail['approval'], approval)
            self.assertEqual(trail['receipt'], receipt)
            self.assertEqual(trail['evidence'], (self.source,))
        self.assertEqual(self.ledger.counts()['journals'], 1)
        self.assertEqual(self.application.status('draft'), 'posted')
        self.assertEqual(self.store.queue(), ())

    def test_no_approval_rejected_invalid_or_wrong_confirmation_cannot_post(self):
        with self.assertRaises(KeyError):
            self.application.post('fabricated', actor_id='human', idempotency_key='none')
        self.save()
        with self.assertRaises(ValueError):
            self.approve(confirmed_digest='0'*64)
        self.reject()
        with self.assertRaises(ValueError):
            self.approve()
        self.save(expected_revision=2, idempotency_key='edit', evidence={})
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_changed_draft_rejection_and_policy_invalidate_approval(self):
        self.save()
        approval = self.approve()
        self.reject()
        with self.assertRaises(ValueError):
            self.post(approval)
        self.save(expected_revision=2, idempotency_key='edit')
        second = self.approve(idempotency_key='approve-again')
        other = ReviewApplication(SQLiteReviewStore(self.ledger, self.registry, policy_version='review-v2'))
        with self.assertRaises(ValueError):
            other.post(second.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_changed_registry_evidence_prevents_post(self):
        self.save()
        approval = self.approve()
        path = self.source_path.with_name('replacement.sqlite3')
        with SQLiteSourceRegistry(path, self.catalog.entity_id) as registry:
            registry.register(dict(self.document, amount='1100.00'), actor_id='op')
            app = ReviewApplication(SQLiteReviewStore(self.ledger, registry))
            with self.assertRaises(ValueError):
                app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_posted_draft_immutable_and_repeated_new_key_refused(self):
        self.save()
        approval = self.approve()
        receipt = self.post(approval)
        for action in (lambda: self.post(approval, idempotency_key='other'),
                       lambda: self.post(approval, actor_id='other'),
                       lambda: self.save(expected_revision=1, idempotency_key='edit'),
                       lambda: self.reject()):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.post(approval), receipt)
        with sqlite3.connect(self.path) as db:
            row = list(db.execute('SELECT * FROM draft_revisions').fetchone())
            row[1] = 2
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)', row)
        self.assertEqual(len(self.store.history('draft')), 1)

    def test_approval_and_posting_failures_roll_back(self):
        self.save()
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_approval BEFORE INSERT ON approval_requests BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve()
        self.assertEqual(self.application.status('draft'), 'awaiting_approval')
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER fail_approval')
        approval = self.approve()
        for table in ('review_postings', 'approved_post_requests'):
            with sqlite3.connect(self.path) as db:
                db.execute(f"CREATE TRIGGER fail_post BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.post(approval)
            self.assertEqual(self.ledger.counts()['journals'], 0)
            self.assertEqual(self.application.status('draft'), 'approved')
            with sqlite3.connect(self.path) as db:
                db.execute('DROP TRIGGER fail_post')
        self.post(approval)

    def test_concurrent_post_requests_only_one_journal(self):
        self.save()
        approval = self.approve()
        barrier = Barrier(2)
        def worker(i):
            with SQLiteLedger(self.path, **self.options) as ledger, SQLiteSourceRegistry(self.source_path, self.catalog.entity_id) as registry:
                app = ReviewApplication(SQLiteReviewStore(ledger, registry))
                barrier.wait(timeout=5)
                return app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(worker, range(2)))
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(self.ledger.counts()['journals'], 1)

    def test_approval_schema_records_are_immutable(self):
        self.save()
        approval = self.approve()
        self.post(approval)
        with sqlite3.connect(self.path) as db:
            for table in ('approval_schema', 'approvals', 'approval_requests', 'review_postings', 'approved_post_requests'):
                for query in (f'DELETE FROM {table}', f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(query)
            db.execute('DROP TRIGGER approval_schema_no_update')
            db.execute('UPDATE approval_schema SET version=99')
        with self.assertRaises(ValueError):
            ReviewApplication(self.store)

    def test_cli_cancel_then_explicit_confirmation_posts(self):
        draft = self.save()
        command = [sys.executable, '-m', 'accounting_harness', 'review-post', '--ledger', str(self.path),
                   '--registry', str(self.source_path), '--draft', 'draft', '--actor', 'human']
        for answer in ('', 'yes\n'):
            result = subprocess.run(command, input=answer, capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Cancelled', result.stdout)
            self.assertEqual(self.ledger.counts()['journals'], 0)
        result = subprocess.run(command, input=f'approve {draft.content_digest}\n', capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Posted rent-journal', result.stdout)
        self.assertEqual(self.ledger.counts()['journals'], 1)

    def test_bad_decision_metadata_and_changed_approval_retry(self):
        self.save()
        for changes in ({'actor_id': ''}, {'revision': True}, {'revision': 0},
                        {'idempotency_key': ''}, {'confirmed_digest': ''}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.approve(**changes)
        approval = self.approve()
        with self.assertRaises(ValueError):
            self.approve(actor_id='other')
        with self.assertRaises(ValueError):
            self.approve(idempotency_key='other')
        self.assertEqual(self.application.status('draft'), 'approved')
        self.assertEqual(self.post(approval).entry.id, 'rent-journal')

    def test_additive_initialization_rolls_back_and_preserves_revision(self):
        path = self.path.with_name('pre-approval.sqlite3')
        class FailingApplication(ReviewApplication):
            def _initialize(self):
                super()._initialize()
                raise RuntimeError('injected')
        with SQLiteLedger(path, **self.options) as ledger:
            store = SQLiteReviewStore(ledger, self.registry)
            draft = store.save('draft', self.proposal, evidence=self.evidence, expected_revision=0,
                               actor_id='op', idempotency_key='create', reason='rent')
            with self.assertRaises(RuntimeError):
                FailingApplication(store)
            self.assertIsNone(ledger._connection.execute("SELECT 1 FROM sqlite_master WHERE name='approval_schema'").fetchone())
            self.assertEqual(store.get('draft'), draft)
            self.assertEqual(ReviewApplication(store).status('draft'), 'awaiting_approval')

    def test_posted_draft_sealed_by_sql_and_duplicate_journal_rolls_back(self):
        self.save()
        approval = self.approve()
        self.ledger.admit(self.proposal, actor_id='legacy', idempotency_key='legacy')
        before = self.ledger.snapshot
        with self.assertRaises(ValueError):
            self.post(approval)
        self.assertEqual(self.ledger.snapshot, before)
        self.assertEqual(self.application.status('draft'), 'approved')

    def test_trace_includes_superseded_human_decisions(self):
        self.save()
        first = self.approve()
        self.reject()
        self.save(expected_revision=2, idempotency_key='edit')
        second = self.approve(idempotency_key='approve-second')
        self.post(second)
        trail = self.application.trace('draft')
        self.assertEqual(trail['approvals'], (first, second))
        self.assertEqual([r.state for r in trail['revisions']], ['pending', 'rejected', 'pending'])
