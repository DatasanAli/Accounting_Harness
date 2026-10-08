"""Recorded settlement binds cash evidence and serializes remaining AP at posting."""
import copy
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_payables
from accounting_harness.approval import ReviewApplication
from accounting_harness.payables import PayablesService, payables_report
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.sources import SQLiteSourceRegistry
from accounting_harness.review import SQLiteReviewStore


def cash_fact(entity, event='payment-1', amount='100.00', **changes):
    return dict(dict(schema_version=2, synthetic=True, entity_id=entity, document_id=event,
        event_id=event, kind='cash_movement', document_date='2026-01-15', currency='USD',
        amount=amount, counterparty_id='vendor-1', counterparty='Fictional software vendor',
        direction='out', purpose='settlement', description='Synthetic recorded payment; sends no money'), **changes)


class PaymentTests(unittest.TestCase):
    setUp = test_payables.PayablesTests.setUp
    register = test_payables.PayablesTests.register
    propose = test_payables.PayablesTests.propose

    def setup_bill(self):
        self.service = PayablesService(self.ledger,self.registry)
        self.bill = self.propose(self.service,self.register())
        self.post(self.service.app,self.bill)
        self.bill_id = json.loads(self.bill.operation_intent_json)['bill_id']
        self.payment_store = SQLiteReviewStore(self.ledger,self.registry,policy_version='bill-payment-v1')
        self.payment_app = ReviewApplication(self.payment_store)

    def approve(self,app,draft):
        return app.approve(draft.draft_id,revision=draft.revision,confirmed_digest=draft.content_digest,
            actor_id='human',idempotency_key=draft.draft_id+str(draft.revision))

    def post(self,app,draft):
        approval=self.approve(app,draft)
        return app.post(approval.approval_id,actor_id='human',idempotency_key=draft.draft_id)

    def payment(self,event='payment-1',amount='100.00',bill_id=None,**changes):
        document=cash_fact(self.catalog.entity_id,event,amount,**changes)
        self.registry.register(document,actor_id='op')
        self.ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
        self.assertTrue(hasattr(self.service,'propose_payment'),'recorded payment proposal is required')
        return self.service.propose_payment(bill_id=bill_id or self.bill_id,cash_source_id=document['document_id'],
            expected_revision=0,actor_id='template',idempotency_key=event)

    def report(self):
        return payables_report(self.service.snapshot(),as_of='2026-01-31')

    def test_partial_payments_preserve_expense_history_and_exact_retry(self):
        self.setup_bill()
        frozen=self.service.snapshot(); before=self.report()
        draft=self.payment(); self.assertTrue(draft.reviewable,draft.current_findings)
        receipt=self.post(self.payment_app,draft)
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],
            [('2000','debit',10000),('1000','credit',10000)])
        report=self.report()
        self.assertEqual((report['ap_control_cents'],report['subledger_cents'],report['unassigned_control_cents']),
            (20000,20000,0))
        self.assertEqual(report['bills'][0]['paid_cents'],10000)
        self.post(self.payment_app,self.payment('payment-2','50.00'))
        self.assertEqual(self.report()['subledger_cents'],15000)
        self.assertEqual(sum(l.amount.cents for e in self.ledger.snapshot.entries for l in e.lines if l.account=='5100'),30000)
        self.assertTrue(self.payment_store.get(draft.draft_id).reviewable)
        self.assertTrue(self.service.store.get(self.bill.draft_id).reviewable)
        self.assertEqual(payables_report(frozen,as_of='2026-01-31'),before)
        self.assertEqual(payables_report(self.service.snapshot(),as_of='2026-01-12')['subledger_cents'],30000)
        with SQLiteLedger(self.path,**self.options) as ledger:
            reopened=PayablesService(ledger,self.registry)
            app=ReviewApplication(SQLiteReviewStore(ledger,self.registry,policy_version='bill-payment-v1'))
            approval=self.approve(app,draft)
            self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key=draft.draft_id),receipt)
            self.assertEqual(len(payables_report(reopened.snapshot(),as_of='2026-01-31')['payments']),2)

    def test_full_settlement_and_invalid_evidence(self):
        self.setup_bill()
        for i,changes in enumerate([dict(counterparty_id='wrong'),dict(document_date='2026-01-09'),
                dict(document_date='2026-02-01'),dict(direction='in'),dict(purpose='incurred_expense')]):
            try:
                draft=self.payment('invalid'+str(i),**changes)
            except ValueError:
                continue
            self.assertFalse(draft.reviewable)
            with self.assertRaises(ValueError): self.post(self.payment_app,draft)
        with self.assertRaises((ValueError,KeyError)): self.payment('missing',bill_id='unknown')
        over=self.payment('over','300.01'); self.assertFalse(over.reviewable)
        self.post(self.payment_app,self.payment('full','300.00'))
        self.assertEqual(self.report()['subledger_cents'],0)
        self.assertFalse(self.payment('after').reviewable)

    def test_approved_payments_race_without_reserving_balance(self):
        self.setup_bill()
        drafts=[self.payment('race'+str(i),'200.00') for i in range(2)]
        approvals=[self.approve(self.payment_app,d) for d in drafts]
        from threading import Barrier
        barrier=Barrier(2)
        def post(approval):
            with SQLiteLedger(self.path,**self.options) as ledger, SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry:
                PayablesService(ledger,registry)
                app=ReviewApplication(SQLiteReviewStore(ledger,registry,policy_version='bill-payment-v1'))
                barrier.wait()
                try: return app.post(approval.approval_id,actor_id='human',idempotency_key=approval.approval_id)
                except ValueError: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(post,approvals))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.report()['subledger_cents'],10000)
        self.assertEqual(self.ledger.counts()['journals'],2)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM vendor_bill_payments').fetchone()[0],1)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM approved_post_requests').fetchone()[0],2)

    def test_forged_split_intent_and_accounts_cannot_approve(self):
        self.setup_bill(); draft=self.payment()
        intent=json.loads(draft.operation_intent_json); proposal=json.loads(draft.proposal_json)
        for revision,change in enumerate([dict(allocated_cents=v) for v in (5000,True,10000.0,0)] +
                [dict(bill_id='wrong'),dict(extra=True)],2):
            changed=self.payment_store.save(draft.draft_id,proposal,evidence=json.loads(draft.evidence_json),
                operation_intent=dict(intent,**change),expected_revision=revision-1,actor_id='op',
                idempotency_key=str(revision),reason='Invalid split or intent')
            self.assertFalse(changed.reviewable)
        forged=copy.deepcopy(proposal); forged['lines'][1]['account']='3000'
        changed=self.payment_store.save(draft.draft_id,forged,evidence=json.loads(draft.evidence_json),
            operation_intent=intent,expected_revision=7,actor_id='op',idempotency_key='forged',reason='Wrong cash account')
        self.assertFalse(changed.reviewable)
        self.assertEqual(self.report()['subledger_cents'],30000)

    def test_payment_faults_orphan_immutability_and_reversal(self):
        from accounting_harness.payables import prepare_payable_post
        self.setup_bill(); draft=self.payment(); approval=self.approve(self.payment_app,draft)
        db=self.service.db
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                prepare_payable_post(self.payment_store,approval,draft,entry)
        for table in ('vendor_bill_payments','journals','lines','posting_events','review_postings','approved_post_requests'):
            db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.payment_app.post(approval.approval_id,actor_id='human',idempotency_key='payment')
            db.execute('DROP TRIGGER injected')
            self.assertEqual(self.ledger.counts()['journals'],1)
            self.assertEqual(db.execute('SELECT count(*) FROM vendor_bill_payments').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM approved_post_requests').fetchone()[0],1)
        receipt=self.payment_app.post(approval.approval_id,actor_id='human',idempotency_key='payment')
        for sql in ('UPDATE vendor_bill_payments SET allocated_cents=1', 'DELETE FROM vendor_bill_payments',
                    'INSERT OR REPLACE INTO vendor_bill_payments SELECT * FROM vendor_bill_payments'):
            with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)
        with self.assertRaisesRegex(ValueError,'operational_reversal_not_supported'):
            self.ledger.reverse(receipt.entry.id,reversal_id='reverse-payment',entity_id=self.catalog.entity_id,
                effective_date='2026-01-16',reason='Correction',source_ids=list(receipt.entry.source_ids),
                actor_id='human',idempotency_key='reverse-payment')
        self.assertEqual(self.report()['subledger_cents'],20000)

    def test_cash_claims_shared_across_bills_and_cash_policy(self):
        self.setup_bill(); draft=self.payment()
        second=self.propose(self.service,self.register('second-bill',number='B-002'),key='second-bill')
        self.post(self.service.app,second)
        second_id=json.loads(second.operation_intent_json)['bill_id']
        with self.assertRaises(ValueError):
            self.service.propose_payment(bill_id=second_id,cash_source_id='payment-1',expected_revision=0,
                actor_id='template',idempotency_key='duplicate')
        # A second cash document with the same semantic event cannot evade ownership.
        from accounting_harness.operations import cash_expense_proposal
        cash=cash_fact(self.catalog.entity_id,'cash-copy',event_id='payment-1',purpose='incurred_expense')
        incurred=dict(cash,kind='incurred_expense',document_id='cash-incurred',incurred_date='2026-01-15',expense_account='5100')
        del incurred['direction']; del incurred['purpose']
        for document in (cash,incurred):
            self.registry.register(document,actor_id='op'); self.ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
        proposal,evidence=cash_expense_proposal(self.registry,entry_id='cash-copy',cash_source_id='cash-copy',recognition_source_id='cash-incurred')
        cash_store=SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1')
        with self.assertRaisesRegex(ValueError,'economic event'):
            cash_store.save('cash-copy',proposal,evidence=evidence,expected_revision=0,actor_id='op',idempotency_key='cash-copy',reason='Duplicate')
        # Reverse policy direction on a fresh event.
        for document in (cash,incurred):
            document.update(document_id=document['document_id']+'2',event_id='cash-first')
            self.registry.register(document,actor_id='op'); self.ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
        proposal,evidence=cash_expense_proposal(self.registry,entry_id='cash-copy2',cash_source_id='cash-copy2',recognition_source_id='cash-incurred2')
        cash_store.save('cash-copy2',proposal,evidence=evidence,expected_revision=0,actor_id='op',idempotency_key='cash-copy2',reason='Cash first')
        with self.assertRaisesRegex(ValueError,'economic event'):
            self.payment('settlement-copy',event_id='cash-first')

    def test_exact_concurrent_payment_retries(self):
        from threading import Barrier
        self.setup_bill(); draft=self.payment(); approval=self.approve(self.payment_app,draft)
        barrier=Barrier(2)
        def post(_):
            with SQLiteLedger(self.path,**self.options) as ledger, SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry:
                PayablesService(ledger,registry)
                app=ReviewApplication(SQLiteReviewStore(ledger,registry,policy_version='bill-payment-v1'))
                barrier.wait()
                return app.post(approval.approval_id,actor_id='human',idempotency_key='same')
        with ThreadPoolExecutor(max_workers=2) as pool: receipts=list(pool.map(post,range(2)))
        self.assertEqual(receipts[0],receipts[1])
        self.assertEqual(self.report()['subledger_cents'],20000)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM vendor_bill_payments').fetchone()[0],1)

    def test_payment_sql_seal_rejects_missing_or_mismatched_effect(self):
        from dataclasses import replace
        from accounting_harness.domain.money import Money
        self.setup_bill(); draft=self.payment(); approval=self.approve(self.payment_app,draft)
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
                self.payment_app.post(approval.approval_id,actor_id='human',idempotency_key='mismatch')
            self.assertEqual(self.service.db.execute('SELECT count(*) FROM vendor_bill_payments').fetchone()[0],0)
            self.assertEqual(self.ledger.counts()['journals'],1)
        # The effect cannot point at a different approved journal or alter the approved amount.
        intent=json.loads(draft.operation_intent_json)
        for cents,journal in ((5000,entry.id),(10000,'other-journal')):
            with self.assertRaises(sqlite3.IntegrityError):
                self.service.db.execute('INSERT INTO vendor_bill_payments VALUES (?,?,?,?,?,?,?)',
                    (intent['payment_event_id'],self.bill_id,'payment-1',cents,'2026-01-15',approval.approval_id,journal))
        self.assertEqual(self.report()['subledger_cents'],30000)

    def test_payment_intent_sealing_correction_and_stale_approval(self):
        self.setup_bill(); draft=self.payment(); approval=self.approve(self.payment_app,draft)
        proposal=json.loads(draft.proposal_json); evidence=json.loads(draft.evidence_json)
        with self.assertRaises(sqlite3.IntegrityError):
            self.payment_store.save(draft.draft_id,proposal,evidence=evidence,expected_revision=1,
                actor_id='op',idempotency_key='no-intent',reason='Missing intent')
        # Retargeting requires the same event-owned draft and a new separately approved revision.
        second=self.propose(self.service,self.register('second',number='B-002'),key='second')
        self.post(self.service.app,second)
        second_id=json.loads(second.operation_intent_json)['bill_id']
        corrected=self.service.propose_payment(bill_id=second_id,cash_source_id='payment-1',expected_revision=1,
            actor_id='op',idempotency_key='correct-target')
        self.assertTrue(corrected.reviewable)
        self.assertEqual(corrected.draft_id,draft.draft_id)
        self.assertNotEqual(corrected.content_digest,draft.content_digest)
        with self.assertRaises(ValueError):
            self.payment_app.post(approval.approval_id,actor_id='human',idempotency_key='stale')
        rejected=self.payment_store.reject(draft.draft_id,expected_revision=2,actor_id='human',
            idempotency_key='reject',reason='Review target')
        self.assertEqual(rejected.operation_intent_json,corrected.operation_intent_json)
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                (draft.draft_id,3,draft.operation_intent_json))
        self.assertEqual(self.report()['subledger_cents'],60000)

    def test_payment_save_faults_leave_no_partial_revision_or_cash_claim(self):
        self.setup_bill()
        document=cash_fact(self.catalog.entity_id)
        self.registry.register(document,actor_id='op'); self.ledger.enroll_source(self.registry,'payment-1',actor_id='op')
        db=self.service.db
        tables=('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims')
        before={table:db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
        for table in tables:
            db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.service.propose_payment(bill_id=self.bill_id,cash_source_id='payment-1',expected_revision=0,
                    actor_id='op',idempotency_key='payment-save')
            db.execute('DROP TRIGGER injected')
            self.assertEqual({table:db.execute(f'SELECT * FROM {table}').fetchall() for table in tables},before)
        draft=self.service.propose_payment(bill_id=self.bill_id,cash_source_id='payment-1',expected_revision=0,
            actor_id='op',idempotency_key='payment-save')
        self.assertTrue(draft.reviewable)



class PaymentHTTPTests(unittest.TestCase):
    setUp = test_payables.BillHTTPTests.setUp
    start = test_payables.BillHTTPTests.start
    stop = test_payables.BillHTTPTests.stop
    tearDown = test_payables.BillHTTPTests.tearDown
    request = test_payables.BillHTTPTests.request

    def test_payment_route_derives_exact_amount_and_requires_human_confirmation(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in test_payables.facts(entity):
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.request('POST','/api/bill-proposals',dict(bill_source_id='bill-event-bill',incurrence_source_id='bill-event-incurrence'))
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest']))
        state=self.request('GET','/api/state')[1]; bill_id=state['payables']['bills'][0]['bill_id']
        self.assertEqual(self.request('POST','/api/operation-sources',dict(document=cash_fact(entity)))[0],200)
        payload=dict(bill_id=bill_id,cash_source_id='payment-1')
        status,result=self.request('POST','/api/bill-payment-proposals',payload)
        self.assertEqual(status,200,result)
        self.assertEqual(self.request('POST','/api/bill-payment-proposals',payload)[1],result)
        for extra in ({'amount':'50.00'},{'actor_id':'agent'},{'policy_version':'bill-v1'}):
            self.assertEqual(self.request('POST','/api/bill-payment-proposals',dict(payload,**extra))[0],409)
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],1)
        draft=next(d for d in state['drafts'] if d['policy_version']=='bill-payment-v1')
        self.assertEqual(len(draft['evidence']),2)
        self.assertEqual(json.loads(draft['operation_intent_json'])['allocated_cents'],10000)
        confirmation=dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest'])
        self.assertEqual(self.request('POST','/api/approve-post',dict(confirmation,confirmed_digest='wrong'))[0],409)
        self.assertEqual(self.request('POST','/api/approve-post',confirmation)[0],200)
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['payables']['subledger_amount'],'200.00')
        self.assertEqual(state['payables']['payments'][0]['allocated_amount'],'100.00')
        self.assertIn('10000',state['payables']['payments'][0]['trace_json'])
        posted=next(d for d in state['drafts'] if d['policy_version']=='bill-payment-v1')
        self.assertEqual(posted['audit']['approval']['actor_id'],'local-operator')
        self.assertEqual(self.request('POST','/api/approve-post',confirmation)[0],200)

    def test_payment_large_cents_remain_exact_in_ui_serialization(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in test_payables.facts(entity):
            document['amount']='90071992547409.94'
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.request('POST','/api/bill-proposals',dict(bill_source_id='bill-event-bill',incurrence_source_id='bill-event-incurrence'))
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest']))
        bill_id=self.request('GET','/api/state')[1]['payables']['bills'][0]['bill_id']
        self.request('POST','/api/operation-sources',dict(document=cash_fact(entity,amount='90071992547409.93')))
        self.assertEqual(self.request('POST','/api/bill-payment-proposals',dict(bill_id=bill_id,cash_source_id='payment-1'))[0],200)
        draft=next(d for d in self.request('GET','/api/state')[1]['drafts'] if d['policy_version']=='bill-payment-v1')
        self.assertIn('9007199254740993',draft['operation_intent_json'])
        self.assertEqual(draft['proposal']['lines'][0]['amount'],'90071992547409.93')
        self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],revision=1,confirmed_digest=draft['content_digest']))
        report=self.request('GET','/api/state')[1]['payables']
        self.assertEqual(report['subledger_amount'],'0.01')
        self.assertEqual(report['payments'][0]['allocated_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['payments'][0]['trace_json'])


class PaymentCLITests(unittest.TestCase):
    def test_demo_bill_payment(self):
        import subprocess
        import sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-bill-payment'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for expected in ('AP debit 100.00','Cash credit 100.00','outstanding 200.00','expense remains 300.00',
                         'residual 0.00','bill-payment-v1','zero model calls'):
            self.assertIn(expected,result.stdout)


class PaymentMigrationTests(unittest.TestCase):
    setUp = PaymentTests.setUp
    register = PaymentTests.register
    propose = PaymentTests.propose
    setup_bill = PaymentTests.setup_bill
    approve = PaymentTests.approve
    post = PaymentTests.post
    payment = PaymentTests.payment
    report = PaymentTests.report
    def test_versioned_migrations_rollback_and_preserve_historical_rows(self):
        self.setup_bill()
        db=self.service.db
        # Simulate the shipped v2 review seal and v1 payables guard with genuine posted bill rows.
        seal=db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0]
        old_seal=seal.replace("NOT IN ('bill-v1','bill-payment-v1','invoice-v1')", "!= 'bill-v1'").replace("IN ('bill-v1','bill-payment-v1','invoice-v1')", "= 'bill-v1'")
        guard=db.execute("SELECT sql FROM sqlite_master WHERE name='payables_post_guard'").fetchone()[0]
        old_guard=guard.replace('                 OR EXISTS (SELECT 1 FROM vendor_bill_payments WHERE journal_id=NEW.journal_id)\n','')
        start=old_guard.index(' ) AND NOT EXISTS (\n                    SELECT 1 FROM vendor_bill_payments')
        end=old_guard.index(" THEN RAISE(ABORT,'AP posting",start)
        old_guard=old_guard[:start]+')'+old_guard[end:]
        db.execute('DROP TRIGGER intent_required_at_seal'); db.execute(old_seal)
        db.execute('DROP TRIGGER payables_post_guard'); db.execute(old_guard)
        db.execute('DROP TABLE vendor_bill_payments')
        for table,version in (('review_schema',2),('payables_schema',1)):
            db.execute(f'DROP TRIGGER {table}_no_update'); db.execute(f'UPDATE {table} SET version=?',(version,))
            db.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
        tables=('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims',
            'approvals','approval_requests','review_postings','approved_post_requests','vendor_bills',
            'payables_context','journals','lines','posting_events','ledger_context')
        before={t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        # Denial at the final schema-version write proves the earlier DDL rolls back as one unit.
        def deny_update(table):
            return lambda action,name,*_: sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and name==table else sqlite3.SQLITE_OK
        db.set_authorizer(deny_update('review_schema'))
        try:
            with self.assertRaises(sqlite3.DatabaseError): SQLiteReviewStore(self.ledger,self.registry)
        finally: db.set_authorizer(None)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(2,)])
        self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0],old_seal)
        SQLiteReviewStore(self.ledger,self.registry)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(4,)])
        db.set_authorizer(deny_update('payables_schema'))
        try:
            with self.assertRaises(sqlite3.DatabaseError): PayablesService(self.ledger,self.registry)
        finally: db.set_authorizer(None)
        self.assertEqual(db.execute('SELECT version FROM payables_schema').fetchall(),[(1,)])
        self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='vendor_bill_payments'").fetchone())
        self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='payables_post_guard'").fetchone()[0],old_guard)
        self.service=PayablesService(self.ledger,self.registry)
        self.assertEqual(db.execute('SELECT version FROM payables_schema').fetchall(),[(2,)])
        self.assertEqual({t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
        self.assertEqual(self.post(self.service.app,self.bill).entry.id,json.loads(self.bill.proposal_json)['id'])
        self.post(self.payment_app,self.payment())
        self.assertEqual(self.report()['subledger_cents'],20000)
