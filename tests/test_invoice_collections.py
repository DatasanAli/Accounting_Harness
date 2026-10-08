"""Recorded settlement binds cash evidence and serializes remaining AR at posting."""
import copy
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_receivables
from accounting_harness.approval import ReviewApplication
from accounting_harness.receivables import ReceivablesService, receivables_report
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.sources import SQLiteSourceRegistry
from accounting_harness.review import SQLiteReviewStore, digest


def cash_fact(entity, event='collection-1', amount='1500.00', **changes):
    return dict(dict(schema_version=2, synthetic=True, entity_id=entity, document_id=event,
        event_id=event, kind='cash_movement', document_date='2026-01-15', currency='USD',
        amount=amount, counterparty_id='customer-1', counterparty='Fictional software customer',
        direction='in', purpose='settlement', description='Synthetic recorded collection; sends no money'), **changes)


class CollectionTests(unittest.TestCase):
    setUp = test_receivables.ReceivablesTests.setUp
    register = test_receivables.ReceivablesTests.register
    propose = test_receivables.ReceivablesTests.propose

    def setup_invoice(self):
        self.service = ReceivablesService(self.ledger,self.registry)
        self.invoice = self.propose(self.service,self.register())
        self.post(self.service.app,self.invoice)
        self.invoice_id = json.loads(self.invoice.operation_intent_json)['invoice_id']
        self.collection_store = SQLiteReviewStore(self.ledger,self.registry,policy_version='invoice-collection-v1')
        self.collection_app = ReviewApplication(self.collection_store)

    def approve(self,app,draft):
        return app.approve(draft.draft_id,revision=draft.revision,confirmed_digest=draft.content_digest,
            actor_id='human',idempotency_key=draft.draft_id+str(draft.revision))

    def post(self,app,draft):
        approval=self.approve(app,draft)
        return app.post(approval.approval_id,actor_id='human',idempotency_key=draft.draft_id)

    def collection(self,event='collection-1',amount='1500.00',invoice_id=None,**changes):
        document=cash_fact(self.catalog.entity_id,event,amount,**changes)
        self.registry.register(document,actor_id='op')
        self.ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
        self.assertTrue(hasattr(self.service,'propose_collection'),'recorded collection proposal is required')
        return self.service.propose_collection(invoice_id=invoice_id or self.invoice_id,cash_source_id=document['document_id'],
            expected_revision=0,actor_id='template',idempotency_key=event)

    def report(self):
        return receivables_report(self.service.snapshot(),as_of='2026-01-31')

    def test_partial_collections_preserve_revenue_history_and_exact_retry(self):
        self.setup_invoice()
        frozen=self.service.snapshot(); before=self.report()
        draft=self.collection(); self.assertTrue(draft.reviewable,draft.current_findings)
        receipt=self.post(self.collection_app,draft)
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],
            [('1000','debit',150000),('1100','credit',150000)])
        report=self.report()
        self.assertEqual((report['ar_control_cents'],report['subledger_cents'],report['unassigned_control_cents']),
            (100000,100000,0))
        self.assertEqual(report['invoices'][0]['paid_cents'],150000)
        self.assertEqual(report['invoices'][0]['days_past_due'],6)
        self.assertEqual(report['aging_cents'],dict(current=0,days_1_30=100000,days_31_60=0,days_61_90=0,days_91_plus=0))
        self.assertEqual(report['customers'][0]['aging_cents'],report['aging_cents'])
        self.post(self.collection_app,self.collection('collection-2','500.00'))
        self.assertEqual(self.report()['subledger_cents'],50000)
        self.assertEqual(sum(l.amount.cents for e in self.ledger.snapshot.entries for l in e.lines if l.account=='4000'),250000)
        self.assertTrue(self.collection_store.get(draft.draft_id).reviewable)
        self.assertTrue(self.service.store.get(self.invoice.draft_id).reviewable)
        self.assertEqual(receivables_report(frozen,as_of='2026-01-31'),before)
        self.assertEqual(receivables_report(self.service.snapshot(),as_of='2026-01-12')['subledger_cents'],250000)
        with SQLiteLedger(self.path,**self.options) as ledger:
            reopened=ReceivablesService(ledger,self.registry)
            app=ReviewApplication(SQLiteReviewStore(ledger,self.registry,policy_version='invoice-collection-v1'))
            approval=self.approve(app,draft)
            self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key=draft.draft_id),receipt)
            self.assertEqual(len(receivables_report(reopened.snapshot(),as_of='2026-01-31')['collections']),2)

    def test_full_settlement_and_invalid_evidence(self):
        self.setup_invoice()
        for i,changes in enumerate([dict(counterparty_id='wrong'),dict(document_date='2026-01-09'),
                dict(document_date='2026-02-01'),dict(direction='out'),dict(purpose='earned_service')]):
            try:
                draft=self.collection('invalid'+str(i),**changes)
            except ValueError:
                continue
            self.assertFalse(draft.reviewable)
            with self.assertRaises(ValueError): self.post(self.collection_app,draft)
        with self.assertRaises((ValueError,KeyError)): self.collection('missing',invoice_id='unknown')
        over=self.collection('over','2500.01'); self.assertFalse(over.reviewable)
        self.post(self.collection_app,self.collection('full','2500.00'))
        self.assertEqual(self.report()['subledger_cents'],0)
        self.assertFalse(self.collection('after').reviewable)

    def test_approved_collections_race_without_reserving_balance(self):
        self.setup_invoice()
        drafts=[self.collection('race'+str(i),'1500.00') for i in range(2)]
        approvals=[self.approve(self.collection_app,d) for d in drafts]
        from threading import Barrier
        barrier=Barrier(2)
        def post(approval):
            with SQLiteLedger(self.path,**self.options) as ledger, SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry:
                ReceivablesService(ledger,registry)
                app=ReviewApplication(SQLiteReviewStore(ledger,registry,policy_version='invoice-collection-v1'))
                barrier.wait()
                try: return app.post(approval.approval_id,actor_id='human',idempotency_key=approval.approval_id)
                except ValueError: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(post,approvals))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.report()['subledger_cents'],100000)
        self.assertEqual(self.ledger.counts()['journals'],2)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM customer_invoice_collections').fetchone()[0],1)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM approved_post_requests').fetchone()[0],2)

    def test_forged_split_intent_and_accounts_cannot_approve(self):
        self.setup_invoice(); draft=self.collection()
        intent=json.loads(draft.operation_intent_json); proposal=json.loads(draft.proposal_json)
        for revision,change in enumerate([dict(allocated_cents=v) for v in (5000,True,150000.0,0)] +
                [dict(invoice_id='wrong'),dict(extra=True)],2):
            changed=self.collection_store.save(draft.draft_id,proposal,evidence=json.loads(draft.evidence_json),
                operation_intent=dict(intent,**change),expected_revision=revision-1,actor_id='op',
                idempotency_key=str(revision),reason='Invalid split or intent')
            self.assertFalse(changed.reviewable)
        forged=copy.deepcopy(proposal); forged['lines'][1]['account']='3000'
        changed=self.collection_store.save(draft.draft_id,forged,evidence=json.loads(draft.evidence_json),
            operation_intent=intent,expected_revision=7,actor_id='op',idempotency_key='forged',reason='Wrong cash account')
        self.assertFalse(changed.reviewable)
        self.assertEqual(self.report()['subledger_cents'],250000)

    def test_collection_faults_orphan_immutability_and_reversal(self):
        from accounting_harness.receivables import prepare_receivable_post
        self.setup_invoice(); draft=self.collection(); approval=self.approve(self.collection_app,draft)
        db=self.service.db
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                prepare_receivable_post(self.collection_store,approval,draft,entry)
        for table in ('customer_invoice_collections','journals','lines','journal_sources','posting_events','review_postings','approved_post_requests'):
            db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.collection_app.post(approval.approval_id,actor_id='human',idempotency_key='collection')
            db.execute('DROP TRIGGER injected')
            self.assertEqual(self.ledger.counts()['journals'],1)
            self.assertEqual(db.execute('SELECT count(*) FROM customer_invoice_collections').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM approved_post_requests').fetchone()[0],1)
        receipt=self.collection_app.post(approval.approval_id,actor_id='human',idempotency_key='collection')
        for sql in ('UPDATE customer_invoice_collections SET allocated_cents=1', 'DELETE FROM customer_invoice_collections',
                    'INSERT OR REPLACE INTO customer_invoice_collections SELECT * FROM customer_invoice_collections'):
            with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)
        with self.assertRaisesRegex(ValueError,'operational_reversal_not_supported'):
            self.ledger.reverse(receipt.entry.id,reversal_id='reverse-collection',entity_id=self.catalog.entity_id,
                effective_date='2026-01-16',reason='Correction',source_ids=list(receipt.entry.source_ids),
                actor_id='human',idempotency_key='reverse-collection')
        self.assertEqual(self.report()['subledger_cents'],100000)

    def test_cash_claims_shared_across_invoices_and_cash_policy(self):
        self.setup_invoice(); draft=self.collection()
        second=self.propose(self.service,self.register('second-invoice',number='I-002'),key='second-invoice')
        self.post(self.service.app,second)
        second_id=json.loads(second.operation_intent_json)['invoice_id']
        with self.assertRaises(ValueError):
            self.service.propose_collection(invoice_id=second_id,cash_source_id='collection-1',expected_revision=0,
                actor_id='template',idempotency_key='duplicate')
        # A second cash document with the same semantic event cannot evade ownership.
        from accounting_harness.operations import earned_cash_proposal
        cash=cash_fact(self.catalog.entity_id,'cash-copy',event_id='collection-1',purpose='earned_service')
        incurred=dict(cash,kind='service_completion',document_id='cash-incurred',completion_date='2026-01-15')
        del incurred['direction']; del incurred['purpose']
        for document in (cash,incurred):
            self.registry.register(document,actor_id='op'); self.ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
        proposal,evidence=earned_cash_proposal(self.registry,entry_id='cash-copy',cash_source_id='cash-copy',recognition_source_id='cash-incurred')
        cash_store=SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1')
        with self.assertRaisesRegex(ValueError,'economic event'):
            cash_store.save('cash-copy',proposal,evidence=evidence,expected_revision=0,actor_id='op',idempotency_key='cash-copy',reason='Duplicate')
        # Reverse policy direction on a fresh event.
        for document in (cash,incurred):
            document.update(document_id=document['document_id']+'2',event_id='cash-first')
            self.registry.register(document,actor_id='op'); self.ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
        proposal,evidence=earned_cash_proposal(self.registry,entry_id='cash-copy2',cash_source_id='cash-copy2',recognition_source_id='cash-incurred2')
        cash_store.save('cash-copy2',proposal,evidence=evidence,expected_revision=0,actor_id='op',idempotency_key='cash-copy2',reason='Cash first')
        with self.assertRaisesRegex(ValueError,'economic event'):
            self.collection('settlement-copy',event_id='cash-first')

    def test_exact_concurrent_collection_retries(self):
        from threading import Barrier
        self.setup_invoice(); draft=self.collection(); approval=self.approve(self.collection_app,draft)
        barrier=Barrier(2)
        def post(_):
            with SQLiteLedger(self.path,**self.options) as ledger, SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry:
                ReceivablesService(ledger,registry)
                app=ReviewApplication(SQLiteReviewStore(ledger,registry,policy_version='invoice-collection-v1'))
                barrier.wait()
                return app.post(approval.approval_id,actor_id='human',idempotency_key='same')
        with ThreadPoolExecutor(max_workers=2) as pool: receipts=list(pool.map(post,range(2)))
        self.assertEqual(receipts[0],receipts[1])
        self.assertEqual(self.report()['subledger_cents'],100000)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM customer_invoice_collections').fetchone()[0],1)

    def test_collection_sql_seal_rejects_missing_or_mismatched_effect(self):
        from dataclasses import replace
        from accounting_harness.domain.money import Money
        self.setup_invoice(); draft=self.collection(); approval=self.approve(self.collection_app,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True): self.ledger._store_entry(entry,'direct')
        original=self.ledger._store_entry
        mismatches=[replace(entry,source_ids=('rent',)),
            replace(entry,lines=(entry.lines[0],replace(entry.lines[1],account='3000'))),
            replace(entry,lines=tuple(replace(line,amount=Money(5000)) for line in entry.lines)),
            replace(entry,lines=tuple(replace(line,side='credit' if line.side=='debit' else 'debit') for line in entry.lines))]
        for changed in mismatches:
            with patch.object(self.ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)), self.assertRaises(sqlite3.IntegrityError):
                self.collection_app.post(approval.approval_id,actor_id='human',idempotency_key='mismatch')
            self.assertEqual(self.service.db.execute('SELECT count(*) FROM customer_invoice_collections').fetchone()[0],0)
            self.assertEqual(self.ledger.counts()['journals'],1)
        # The effect cannot point at a different approved journal or alter the approved amount.
        intent=json.loads(draft.operation_intent_json)
        for cents,journal in ((5000,entry.id),(150000,'other-journal')):
            with self.assertRaises(sqlite3.IntegrityError):
                self.service.db.execute('INSERT INTO customer_invoice_collections VALUES (?,?,?,?,?,?,?)',
                    (intent['receipt_event_id'],self.invoice_id,'collection-1',cents,'2026-01-15',approval.approval_id,journal))
        self.assertEqual(self.report()['subledger_cents'],250000)

    def test_collection_intent_sealing_correction_and_stale_approval(self):
        self.setup_invoice(); draft=self.collection(); approval=self.approve(self.collection_app,draft)
        proposal=json.loads(draft.proposal_json); evidence=json.loads(draft.evidence_json)
        with self.assertRaises(sqlite3.IntegrityError):
            self.collection_store.save(draft.draft_id,proposal,evidence=evidence,expected_revision=1,
                actor_id='op',idempotency_key='no-intent',reason='Missing intent')
        # Retargeting requires the same event-owned draft and a new separately approved revision.
        second=self.propose(self.service,self.register('second',number='I-002'),key='second')
        self.post(self.service.app,second)
        second_id=json.loads(second.operation_intent_json)['invoice_id']
        corrected=self.service.propose_collection(invoice_id=second_id,cash_source_id='collection-1',expected_revision=1,
            actor_id='op',idempotency_key='correct-target')
        self.assertTrue(corrected.reviewable)
        self.assertEqual(corrected.draft_id,draft.draft_id)
        self.assertNotEqual(corrected.content_digest,draft.content_digest)
        with self.assertRaises(ValueError):
            self.collection_app.post(approval.approval_id,actor_id='human',idempotency_key='stale')
        rejected=self.collection_store.reject(draft.draft_id,expected_revision=2,actor_id='human',
            idempotency_key='reject',reason='Review target')
        self.assertEqual(rejected.operation_intent_json,corrected.operation_intent_json)
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                (draft.draft_id,3,draft.operation_intent_json))
        self.assertEqual(self.report()['subledger_cents'],500000)

    def test_collection_save_faults_leave_no_partial_revision_or_cash_claim(self):
        self.setup_invoice()
        document=cash_fact(self.catalog.entity_id)
        self.registry.register(document,actor_id='op'); self.ledger.enroll_source(self.registry,'collection-1',actor_id='op')
        db=self.service.db
        tables=('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims')
        before={table:db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
        for table in tables:
            db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.service.propose_collection(invoice_id=self.invoice_id,cash_source_id='collection-1',expected_revision=0,
                    actor_id='op',idempotency_key='collection-save')
            db.execute('DROP TRIGGER injected')
            self.assertEqual({table:db.execute(f'SELECT * FROM {table}').fetchall() for table in tables},before)
        draft=self.service.propose_collection(invoice_id=self.invoice_id,cash_source_id='collection-1',expected_revision=0,
            actor_id='op',idempotency_key='collection-save')
        self.assertTrue(draft.reviewable)


    def test_collection_requires_distinct_cash_event_and_enrolled_evidence(self):
        self.setup_invoice()
        with self.assertRaisesRegex(ValueError, 'distinct'):
            self.collection('same-event', event_id='invoice-event')
        document = cash_fact(self.catalog.entity_id, 'unenrolled')
        self.registry.register(document, actor_id='op')
        draft = self.service.propose_collection(invoice_id=self.invoice_id, cash_source_id='unenrolled',
            expected_revision=0, actor_id='op', idempotency_key='unenrolled')
        self.assertFalse(draft.reviewable)
        with self.assertRaises(ValueError): self.approve(self.collection_app, draft)
        self.assertEqual(self.report()['subledger_cents'],250000)

    def test_aging_cutoffs_due_today_and_all_bucket_boundaries_are_pure(self):
        from dataclasses import replace
        from datetime import date, timedelta
        self.setup_invoice()
        frozen = self.service.snapshot()
        self.assertEqual(receivables_report(frozen, as_of='2026-01-25')['aging_cents']['current'],250000)
        self.assertEqual(receivables_report(frozen, as_of='2026-01-26')['aging_cents']['days_1_30'],250000)
        before = receivables_report(frozen, as_of='2026-01-31')
        self.post(self.collection_app, self.collection(document_date='2026-01-20'))
        captured = self.service.snapshot()
        for cutoff, expected in [('2026-01-19',250000),('2026-01-20',100000),('2026-01-31',100000)]:
            report = receivables_report(captured,as_of=cutoff)
            self.assertEqual(report['subledger_cents'],expected)
            self.assertEqual(sum(report['aging_cents'].values()),expected)
        self.assertEqual(receivables_report(frozen,as_of='2026-01-31'),before)
        # Pure synthetic report fixtures exercise older buckets; live posting stays January-only.
        for days,bucket in [(0,'current'),(-1,'current'),(1,'days_1_30'),(30,'days_1_30'),
                (31,'days_31_60'),(60,'days_31_60'),(61,'days_61_90'),(90,'days_61_90'),(91,'days_91_plus')]:
            cutoff = date(2026,1,31)
            invoice = replace(frozen.invoices[0], due_date=(cutoff-timedelta(days=days)).isoformat())
            fixture = replace(frozen,invoices=(invoice,))
            with patch.object(self.registry,'get',side_effect=AssertionError('report must be pure')):
                report = receivables_report(fixture,as_of=cutoff)
            self.assertEqual(report['aging_cents'][bucket],250000)
            self.assertEqual(sum(report['aging_cents'].values()),250000)
            self.assertEqual(report['invoices'][0]['days_past_due'],max(days,0))
        with self.assertRaises(ValueError): receivables_report(frozen,as_of='2026-02-01')

    def test_new_revision_between_collection_effect_and_journal_seal_rolls_back(self):
        from accounting_harness.receivables import prepare_receivable_post
        self.setup_invoice()
        service = self.service
        draft = self.collection()
        approval = self.approve(self.collection_app, draft)
        entry = self.ledger._validate_entry(json.loads(draft.proposal_json))
        tables = ('customer_invoice_collections', 'journals', 'lines', 'journal_sources', 'posting_events',
                  'draft_revisions', 'draft_operation_intents', 'review_events', 'review_requests',
                  'review_postings', 'approved_post_requests')
        before = {table: service.db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
        for state, operation in [('rejected', 'reject'), ('pending', 'save')]:
            with self.subTest(state=state), self.assertRaisesRegex(sqlite3.IntegrityError, 'approved receivable effect'):
                with self.ledger._transaction(write=True):
                    prepare_receivable_post(self.collection_store, approval, draft, entry)
                    # All guards stay enabled. The newer revision seals after the approved effect
                    # was accepted but before the journal's mandatory posting-event seal.
                    revision = list(service.db.execute('SELECT * FROM draft_revisions WHERE draft_id=?', (draft.draft_id,)).fetchone())
                    revision[1], revision[6], revision[7], revision[8] = 2, state, 'A later human decision', 'human'
                    service.db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)', revision)
                    service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                                       (draft.draft_id, 2, draft.operation_intent_json))
                    service.db.execute('INSERT INTO review_events VALUES (?,?,?)', (draft.draft_id, 2, operation))
                    service.db.execute('INSERT INTO review_requests VALUES (?,?,?,?,?)',
                        (operation, 'later-decision', digest([operation, draft.draft_id, 1, 'human',
                            'A later human decision', None if operation == 'reject' else json.loads(draft.proposal_json),
                            None if operation == 'reject' else json.loads(draft.evidence_json), 'invoice-collection-v1'] +
                            ([] if operation == 'reject' else [{'operation_intent_v1': json.loads(draft.operation_intent_json)}])),
                         draft.draft_id, 2))
                    self.ledger._store_entry(entry, 'human')
            self.assertEqual({table: service.db.execute(f'SELECT * FROM {table}').fetchall()
                              for table in tables}, before)
        # The failed unit neither consumes the approval nor leaves the draft rejected.
        receipt = self.collection_app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(receipt.entry.id, entry.id)
        self.assertEqual(self.ledger.counts()['journals'], 2)


class CollectionHTTPTests(unittest.TestCase):
    setUp = test_receivables.InvoiceHTTPTests.setUp
    start = test_receivables.InvoiceHTTPTests.start
    stop = test_receivables.InvoiceHTTPTests.stop
    tearDown = test_receivables.InvoiceHTTPTests.tearDown
    request = test_receivables.InvoiceHTTPTests.request

    def test_collection_route_derives_exact_amount_and_requires_human_confirmation(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in test_receivables.facts(entity):
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.request('POST','/api/invoice-proposals',dict(invoice_source_id='invoice-event-invoice',completion_source_id='invoice-event-completion'))
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest']))
        state=self.request('GET','/api/state')[1]; invoice_id=state['receivables']['invoices'][0]['invoice_id']
        self.assertEqual(self.request('POST','/api/operation-sources',dict(document=cash_fact(entity)))[0],200)
        payload=dict(invoice_id=invoice_id,cash_source_id='collection-1')
        status,result=self.request('POST','/api/invoice-collection-proposals',payload)
        self.assertEqual(status,200,result)
        self.assertEqual(self.request('POST','/api/invoice-collection-proposals',payload)[1],result)
        for extra in ({'amount':'50.00'},{'actor_id':'agent'},{'policy_version':'invoice-v1'}):
            self.assertEqual(self.request('POST','/api/invoice-collection-proposals',dict(payload,**extra))[0],409)
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],1)
        draft=next(d for d in state['drafts'] if d['policy_version']=='invoice-collection-v1')
        self.assertEqual(len(draft['evidence']),2)
        self.assertEqual(json.loads(draft['operation_intent_json'])['allocated_cents'],150000)
        confirmation=dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest'])
        self.assertEqual(self.request('POST','/api/approve-post',dict(confirmation,confirmed_digest='wrong'))[0],409)
        self.assertEqual(self.request('POST','/api/approve-post',confirmation)[0],200)
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['receivables']['subledger_amount'],'1000.00')
        self.assertEqual(state['receivables']['collections'][0]['allocated_amount'],'1500.00')
        self.assertIn('150000',state['receivables']['collections'][0]['trace_json'])
        posted=next(d for d in state['drafts'] if d['policy_version']=='invoice-collection-v1')
        self.assertEqual(posted['audit']['approval']['actor_id'],'local-operator')
        self.assertEqual(self.request('POST','/api/approve-post',confirmation)[0],200)

    def test_collection_large_cents_remain_exact_in_ui_serialization(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in test_receivables.facts(entity):
            document['amount']='90071992547409.94'
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.request('POST','/api/invoice-proposals',dict(invoice_source_id='invoice-event-invoice',completion_source_id='invoice-event-completion'))
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest']))
        invoice_id=self.request('GET','/api/state')[1]['receivables']['invoices'][0]['invoice_id']
        self.request('POST','/api/operation-sources',dict(document=cash_fact(entity,amount='90071992547409.93')))
        self.assertEqual(self.request('POST','/api/invoice-collection-proposals',dict(invoice_id=invoice_id,cash_source_id='collection-1'))[0],200)
        draft=next(d for d in self.request('GET','/api/state')[1]['drafts'] if d['policy_version']=='invoice-collection-v1')
        self.assertIn('9007199254740993',draft['operation_intent_json'])
        self.assertEqual(draft['proposal']['lines'][0]['amount'],'90071992547409.93')
        self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest']))
        report=self.request('GET','/api/state')[1]['receivables']
        self.assertEqual(report['subledger_amount'],'0.01')
        self.assertEqual(report['collections'][0]['allocated_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['collections'][0]['trace_json'])


class CollectionCLITests(unittest.TestCase):
    def test_demo_invoice_collection(self):
        import subprocess
        import sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-collection'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for expected in ('AR credit 1500.00','Cash debit 1500.00','outstanding 1000.00','revenue remains 2500.00',
                         'residual 0.00','invoice-collection-v1','zero model calls'):
            self.assertIn(expected,result.stdout)


class CollectionMigrationTests(unittest.TestCase):
    setUp = CollectionTests.setUp
    register = CollectionTests.register
    propose = CollectionTests.propose
    setup_invoice = CollectionTests.setup_invoice
    approve = CollectionTests.approve
    post = CollectionTests.post
    collection = CollectionTests.collection
    report = CollectionTests.report

    def test_v4_review_v1_receivables_migrations_rollback_and_preserve_history(self):
        self.setup_invoice()
        db = self.service.db
        # Restore precisely the preceding seals/version while retaining genuine invoice history.
        with self.ledger._transaction(write=True):
            self.service.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1'")
            db.execute('DROP TRIGGER receivables_post_guard')
            self.service._create_post_guard()
            db.execute('DROP TABLE customer_invoice_collections')
            for table,version in [('review_schema',4),('receivables_schema',1)]:
                db.execute(f'DROP TRIGGER {table}_no_update')
                db.execute(f'UPDATE {table} SET version=?',(version,))
                db.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
        tables = ('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims',
            'approvals','approval_requests','review_postings','approved_post_requests','customer_invoices',
            'receivables_context','journals','lines','journal_sources','posting_events','ledger_context','source_enrollments')
        before = {t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        source_before = self.registry.list_documents()
        for schema,version,guard in [('review_schema',4,'intent_required_at_seal'),('receivables_schema',1,'receivables_post_guard')]:
            old_guard = db.execute('SELECT sql FROM sqlite_master WHERE name=?',(guard,)).fetchone()[0]
            db.set_authorizer(lambda action,name,*_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_UPDATE and name == schema else sqlite3.SQLITE_OK)
            try:
                with self.assertRaises(sqlite3.DatabaseError): ReceivablesService(self.ledger,self.registry)
            finally: db.set_authorizer(None)
            self.assertEqual(db.execute(f'SELECT version FROM {schema}').fetchall(),[(version,)])
            self.assertEqual(db.execute('SELECT sql FROM sqlite_master WHERE name=?',(guard,)).fetchone()[0],old_guard)
            self.assertEqual({t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='customer_invoice_collections'").fetchone())
            if schema == 'review_schema': SQLiteReviewStore(self.ledger,self.registry)
        self.service = ReceivablesService(self.ledger,self.registry)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(5,)])
        self.assertEqual(db.execute('SELECT version FROM receivables_schema').fetchall(),[(2,)])
        self.assertEqual({t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
        self.assertEqual(self.registry.list_documents(),source_before)
        self.assertEqual(self.post(self.service.app,self.invoice).entry.id,json.loads(self.invoice.proposal_json)['id'])
        self.post(self.collection_app,self.collection())
        self.assertEqual(self.report()['subledger_cents'],100000)
