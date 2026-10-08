"""Independent cash recognition, policy, duplicate and HTTP acceptance checks."""
import copy
import json
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import test_review
import test_web
from accounting_harness.approval import ReviewApplication
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.sources import SQLiteSourceRegistry


def facts(entity, event='rent', earned=False):
    common = dict(schema_version=2, synthetic=True, entity_id=entity, currency='USD',
                  document_date='2026-01-05', amount='800.00' if earned else '1200.00',
                  counterparty='Fictional counterparty', counterparty_id='party-1', event_id=event,
                  description='Fictional evidence assertion')
    cash = dict(common, document_id=event + '-cash', kind='cash_movement',
                direction='in' if earned else 'out', purpose='earned_service' if earned else 'incurred_expense')
    recognition = dict(common, document_id=event + '-fact', kind='service_completion' if earned else 'incurred_expense')
    recognition.update(dict(completion_date='2026-01-05') if earned else
                       dict(incurred_date='2026-01-05', expense_account='5000'))
    return cash, recognition


class CashTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def register_pair(self, event='rent-event', earned=False, changes=None):
        documents = facts(self.catalog.entity_id, event, earned)
        for i, document in enumerate(documents):
            document.update((changes or {}).get(i, {}))
            self.registry.register(document, actor_id='fact-operator')
            self.ledger.enroll_source(self.registry, document['document_id'], actor_id='fact-operator')
        return documents

    def cash_proposal(self, documents, earned=False):
        from accounting_harness.operations import cash_expense_proposal, earned_cash_proposal
        return (earned_cash_proposal if earned else cash_expense_proposal)(self.registry,
            entry_id=documents[0]['event_id'] + '-journal', cash_source_id=documents[0]['document_id'],
            recognition_source_id=documents[1]['document_id'])

    def save_cash(self, documents, *, draft='cash-draft', earned=False, store=None, proposal=None, evidence=None):
        p, e = self.cash_proposal(documents, earned)
        return (store or SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')).save(
            draft, p if proposal is None else proposal, evidence=e if evidence is None else evidence,
            expected_revision=0, actor_id='template', idempotency_key=draft, reason='Synthetic cash',
            require_unused_evidence=True)

    def test_cash_demo(self):
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-cash'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ('Pending drafts: 2; posted journals: 0', 'Cash credit 400.00',
                         'Rent debit 1200.00', 'Revenue credit 800.00',
                         'Trial balance: 1200.00 / 1200.00', '2 journals after reopen/retry',
                         'Zero opening cash', 'cash-v1', 'zero model calls'):
            self.assertIn(expected, result.stdout)

    def test_typed_schema_exact_fields_and_v1_digest_unchanged(self):
        before = self.source
        self.register_pair()
        self.assertEqual(self.registry.get('rent'), before)
        for changes in ({'purpose': 'unknown'}, {'direction': 'sideways'}, {'amount': 1.2},
                        {'amount': True}, {'currency': 'EUR'}, {'schema_version': True},
                        {'extra': 'text'}, {'event_id': ''}, {'synthetic': False}):
            bad = dict(facts(self.catalog.entity_id)[0], **changes)
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.registry.register(bad, actor_id='op')
        bad = facts(self.catalog.entity_id)[1]
        bad['expense_account'] = '1000'
        with self.assertRaises(ValueError):
            self.registry.register(bad, actor_id='op')

    def test_rent_and_earned_cash_require_human_and_produce_exact_balances_and_trace(self):
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        app = ReviewApplication(store)
        for event, earned in [('rent-event', False), ('service-event', True)]:
            docs = self.register_pair(event, earned)
            draft = self.save_cash(docs, draft=event, earned=earned, store=store)
            self.assertTrue(draft.reviewable, draft.findings)
            self.assertEqual(app.status(event), 'awaiting_approval')
            approval = app.approve(event, revision=1, confirmed_digest=draft.content_digest,
                                   actor_id='human', idempotency_key=event)
            posted = app.post(approval.approval_id, actor_id='human', idempotency_key=event)
            self.assertEqual(app.post(approval.approval_id, actor_id='human', idempotency_key=event), posted)
            trace = app.trace(event)
            self.assertEqual(len(trace['evidence']), 2)
            binding = json.loads(approval.binding_json)
            self.assertEqual(binding['policy_version'], 'cash-v1')
            self.assertEqual(binding['revision'], 1)
            self.assertEqual(approval.actor_id, 'human')
            self.assertEqual(str(posted.entry.effective_date), '2026-01-05')
        report = self.ledger.trial_balance('2026-01-31')
        rows = {r.account: (r.debit.cents, r.credit.cents) for r in report.rows}
        self.assertEqual(rows['1000'], (0, 40000))
        self.assertEqual(rows['5000'], (120000, 0))
        self.assertEqual(rows['4000'], (0, 80000))
        self.assertEqual((report.total_debits.cents, report.total_credits.cents), (120000, 120000))
        self.assertEqual(self.ledger.counts()['journals'], 2)

    def test_unsupported_cash_purposes_and_mismatched_facts_never_prepare(self):
        changes = [{0: {'purpose': p}} for p in ('owner_contribution', 'owner_draw', 'transfer',
                   'customer_advance', 'settlement', 'unclassified')]
        changes += [{1: {field: value}} for field, value in [('event_id', 'other'),
                    ('counterparty_id', 'other'), ('amount', '1.00'), ('incurred_date', '2026-01-06'),
                    ('document_date', '2026-01-06')]]
        for index, change in enumerate(changes):
            docs = self.register_pair('invalid-' + str(index), changes=change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.cash_proposal(docs)
        from accounting_harness.operations import earned_cash_proposal
        for source in ('rent', 'missing'):
            with self.assertRaises((ValueError, KeyError)):
                earned_cash_proposal(self.registry, entry_id='bad', cash_source_id=source, recognition_source_id=source)
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_forged_accounts_dates_amounts_missing_and_unbound_evidence_cannot_approve(self):
        docs = self.register_pair()
        proposal, evidence = self.cash_proposal(docs)
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        app = ReviewApplication(store)
        cases = []
        for field, value in [('account', '5100'), ('amount', '100.00')]:
            changed = copy.deepcopy(proposal)
            changed['lines'][0][field] = value
            if field == 'amount':
                changed['lines'][1][field] = value  # Balanced, but unsupported by the facts.
            cases.append((changed, evidence))
        cases += [(dict(proposal, effective_date='2026-01-06'), evidence),
                  (dict(proposal, source_ids=[docs[0]['document_id']]), evidence),
                  (proposal, {docs[0]['document_id']: evidence[docs[0]['document_id']]}),
                  (proposal, dict(evidence, rent=self.source.content_digest))]
        for index, (changed, binding) in enumerate(cases):
            draft = store.save('forged', changed, evidence=binding, expected_revision=index,
                               actor_id='op', idempotency_key=str(index), reason='Untrusted direct proposal')
            self.assertFalse(draft.reviewable)
            with self.assertRaises(ValueError):
                app.approve('forged', revision=draft.revision, confirmed_digest=draft.content_digest,
                            actor_id='human', idempotency_key=str(index))
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_v2_facts_cannot_pass_review_v1_or_unknown_policy(self):
        docs = self.register_pair()
        for source_id in [d['document_id'] for d in docs]:
            proposal = dict(self.cash_proposal(docs)[0], source_ids=[source_id])
            evidence = {source_id: self.registry.get(source_id).content_digest}
            self.assertIn('unsupported_evidence', [f.code for f in self.store.validate(proposal, evidence)])
            draft = self.store.save(source_id, proposal, evidence=evidence, expected_revision=0,
                actor_id='untrusted', idempotency_key=source_id, reason='Attempt weaker receipt policy')
            with self.assertRaises(ValueError):
                ReviewApplication(self.store).approve(source_id, revision=1,
                    confirmed_digest=draft.content_digest, actor_id='human', idempotency_key=source_id)
        unknown = SQLiteReviewStore(self.ledger, self.registry, policy_version='made-up')
        self.assertTrue(unknown.validate(self.cash_proposal(docs)[0], self.cash_proposal(docs)[1]))

    def test_original_approval_remains_postable_with_cash_policy_and_context_unchanged(self):
        old = test_review.ReviewTests.save(self)
        app = ReviewApplication(self.store)
        approval = app.approve('draft', revision=1, confirmed_digest=old.content_digest,
                               actor_id='human', idempotency_key='old')
        context = self.ledger._context
        self.save_cash(self.register_pair())
        self.assertEqual(self.ledger._context, context)
        self.assertEqual(app.post(approval.approval_id, actor_id='human', idempotency_key='old').entry.id, 'rent-journal')

    def test_atomic_claim_retry_different_source_same_event_and_rejected_evidence(self):
        docs = self.register_pair()
        first = self.save_cash(docs)
        self.assertEqual(self.save_cash(docs), first)
        duplicates = self.register_pair(changes={0: {'document_id': 'copy-cash'}, 1: {'document_id': 'copy-fact'}})
        with self.assertRaisesRegex(ValueError, 'event|duplicate'):
            self.save_cash(duplicates, draft='copy')
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        store.reject(first.draft_id, expected_revision=1, actor_id='human', idempotency_key='reject', reason='Wrong facts')
        with self.assertRaises(ValueError):
            self.save_cash(docs, draft='new')
        self.save_cash(self.register_pair('distinct-event'), draft='distinct')
        claims = self.ledger._connection.execute('SELECT event_id, role FROM operation_claims').fetchall()
        self.assertIn(('rent-event', 'expense_recognition'), claims)

    def test_claims_guard_direct_saves_without_optional_source_guard_and_are_immutable(self):
        docs = self.register_pair()
        self.save_cash(docs)
        copies = self.register_pair(changes={0: {'document_id': 'other-cash'}, 1: {'document_id': 'other-fact'}})
        proposal, evidence = self.cash_proposal(copies)
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        with self.assertRaisesRegex(ValueError, 'economic event'):
            store.save('direct-copy', proposal, evidence=evidence, expected_revision=0,
                       actor_id='direct', idempotency_key='direct', reason='No optional source guard')
        self.assertEqual(len(store.queue()), 1)
        for sql in ('DELETE FROM operation_claims', 'UPDATE operation_claims SET role=role',
                    'INSERT OR REPLACE INTO operation_claims SELECT * FROM operation_claims'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                store.db.execute(sql)

    def test_concurrent_duplicate_drafts_and_claim_rollback(self):
        docs = self.register_pair()
        p, e = self.cash_proposal(docs)
        barrier = Barrier(2)
        def save(i):
            with SQLiteLedger(self.path, **self.options) as ledger, SQLiteSourceRegistry(self.source_path, self.catalog.entity_id) as registry:
                store = SQLiteReviewStore(ledger, registry, policy_version='cash-v1')
                barrier.wait(timeout=5)
                try:
                    return store.save(str(i), p, evidence=e, expected_revision=0, actor_id='op',
                                      idempotency_key=str(i), reason='Cash', require_unused_evidence=True)
                except ValueError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.ledger._connection.execute('SELECT count(*) FROM operation_claims').fetchone(), (2,))
        fresh = self.register_pair('rollback')
        self.ledger._connection.execute("CREATE TRIGGER fail_cash BEFORE INSERT ON review_events BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save_cash(fresh, draft='rollback')
        self.assertEqual(self.ledger._connection.execute("SELECT count(*) FROM operation_claims WHERE event_id='rollback'").fetchone(), (0,))


class CashHTTPTests(unittest.TestCase):
    setUp = test_web.WorkspaceHTTPTests.setUp
    tearDown = test_web.WorkspaceHTTPTests.tearDown
    start = test_web.WorkspaceHTTPTests.start
    stop = test_web.WorkspaceHTTPTests.stop
    request = test_web.WorkspaceHTTPTests.request
    confirmation = test_web.WorkspaceHTTPTests.confirmation

    def test_cash_http(self):
        entity = self.server.workspace.catalog.entity_id
        for document in facts(entity):
            status, result = self.request('POST', '/api/operation-sources', dict(document=document))
            self.assertEqual(status, 200, result)
        payload = dict(operation='cash_expense', cash_source_id='rent-cash', recognition_source_id='rent-fact')
        status, result = self.request('POST', '/api/cash-proposals', payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(self.request('POST', '/api/cash-proposals', payload), (status, result))
        state = self.request('GET', '/api/state')[1]
        self.assertEqual(state['journal_count'], 0)
        draft = state['drafts'][0]
        self.assertEqual(draft['policy_version'], 'cash-v1')
        self.assertEqual(len(draft['evidence']), 2)
        self.assertEqual(self.request('POST', '/api/approve-post', dict(self.confirmation(draft), policy_version='review-v1'))[0], 409)
        self.assertEqual(self.request('POST', '/api/approve-post', self.confirmation(draft))[0], 200)
        self.assertEqual(self.request('GET', '/api/state')[1]['journal_count'], 1)
        self.assertEqual(self.request('POST', '/api/cash-proposals', dict(payload, amount='1.00'))[0], 409)
        self.assertEqual(self.request('POST', '/api/run', dict(source_id='rent-cash', provider='offline', run_id='wrong'))[0], 409)
