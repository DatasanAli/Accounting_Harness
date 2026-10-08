"""Customer invoices: exact earning evidence, human approval and atomic AR enforcement."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_review
import test_web
from accounting_harness.approval import ReviewApplication
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore, digest


def facts(entity, event='invoice-event', customer='customer-1', number='I-001'):
    common = dict(schema_version=2, synthetic=True, entity_id=entity, currency='USD',
        document_date='2026-01-10', amount='2500.00', event_id=event, counterparty_id=customer,
        counterparty='Fictional service customer', description='Synthetic separately asserted fact')
    return (dict(common, document_id=event+'-invoice', kind='customer_invoice', invoice_number=number,
                 due_date='2026-01-25'),
            dict(common, document_id=event+'-completion', kind='service_completion',
                 completion_date='2026-01-10'))


class ReceivablesTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def service(self):
        from importlib.util import find_spec
        self.assertIsNotNone(find_spec('accounting_harness.receivables'), 'receivables service is required')
        from accounting_harness.receivables import ReceivablesService
        return ReceivablesService(self.ledger, self.registry)

    def register(self, event='invoice-event', customer='customer-1', number='I-001', changes=None):
        docs = facts(self.catalog.entity_id, event, customer, number)
        for i, doc in enumerate(docs):
            doc.update((changes or {}).get(i, {}))
            self.registry.register(doc, actor_id='operator')
            self.ledger.enroll_source(self.registry, doc['document_id'], actor_id='operator')
        return docs

    def propose(self, service, docs, expected=0, key='invoice'):
        return service.propose_invoice(invoice_source_id=docs[0]['document_id'],
            completion_source_id=docs[1]['document_id'], expected_revision=expected,
            actor_id='template', idempotency_key=key)

    def approve(self, service, draft):
        return service.app.approve(draft.draft_id, revision=draft.revision,
            confirmed_digest=draft.content_digest, actor_id='human', idempotency_key='approve'+str(draft.revision))

    def test_invoice_independent_balances_intent_trace_retry_and_snapshot(self):
        service = self.service()
        docs = self.register()
        draft = self.propose(service, docs)
        self.assertTrue(draft.reviewable, draft.findings + draft.current_findings)
        self.assertEqual(self.ledger.counts()['journals'], 0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0], 0)
        intent = json.loads(draft.operation_intent_json)
        self.assertEqual(intent['principal_cents'], 250000)
        self.assertEqual(intent['due_date'], '2026-01-25')
        approval = self.approve(service, draft)
        self.assertEqual(self.ledger.counts()['journals'], 0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0], 0)
        receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual([(l.account, l.side, l.amount.cents) for l in receipt.entry.lines],
                         [('1100', 'debit', 250000), ('4000', 'credit', 250000)])
        from accounting_harness.receivables import receivables_report
        frozen = service.snapshot()
        report = receivables_report(frozen, as_of='2026-01-31')
        self.assertEqual((report['ar_control_cents'], report['subledger_cents'], report['unassigned_control_cents']),
                         (250000, 250000, 0))
        self.assertEqual(report['invoices'][0]['outstanding_cents'], 250000)
        self.assertEqual(report['invoices'][0]['paid_cents'], 0)
        self.assertEqual(receivables_report(frozen, as_of='2026-01-09')['subledger_cents'], 0)
        self.assertEqual(service.app.post(approval.approval_id, actor_id='human', idempotency_key='post'), receipt)
        self.assertTrue(service.store.get(draft.draft_id).reviewable)
        self.assertEqual(len(service.app.trace(draft.draft_id)['evidence']), 2)
        with self.assertRaisesRegex(ValueError, 'operational_reversal_not_supported'):
            self.ledger.reverse(receipt.entry.id, reversal_id='reverse', entity_id=self.catalog.entity_id,
                effective_date='2026-01-11', reason='correct', source_ids=list(receipt.entry.source_ids),
                actor_id='human', idempotency_key='reverse')
        self.assertEqual(receivables_report(frozen, as_of='2026-01-31'), report)

    def test_duplicate_invoice_identity_and_shared_service_claim(self):
        service = self.service()
        self.propose(service, self.register())
        with self.assertRaises(ValueError):
            self.propose(service, self.register('other-event'), key='duplicate')
        with self.assertRaisesRegex(ValueError, 'economic event'):
            self.propose(service, self.register('other-number', number='I-002',
                changes={0: {'event_id': 'invoice-event'}, 1: {'event_id': 'invoice-event'}}), key='event')
        self.assertTrue(self.propose(service, self.register('other-customer', customer='customer-2'), key='other').reviewable)

    def test_inconsistent_facts_and_invalid_dates_refused(self):
        service = self.service()
        for i, changes in enumerate([{1: {k: v}} for k, v in
            [('amount','301.00'),('event_id','wrong'),('counterparty_id','wrong'),
             ('completion_date','2026-01-11'),('document_date','2026-01-11')]]):
            docs = self.register('bad'+str(i), changes=changes)
            with self.assertRaises(ValueError):
                self.propose(service, docs, key=str(i))
        for changes in ({'amount': True}, {'amount': 3.0}, {'due_date':'2026-01-09'},
                        {'due_date':'bad'}, {'extra':'bad'}, {'currency':'EUR'}):
            with self.assertRaises((ValueError, TypeError)):
                self.registry.register(dict(facts(self.catalog.entity_id)[0], **changes), actor_id='op')

    def test_intent_binding_rejection_missing_unexpected_and_late_insert(self):
        service = self.service()
        draft = self.propose(service, self.register())
        approval = self.approve(service, draft)
        proposal, evidence = json.loads(draft.proposal_json), json.loads(draft.evidence_json)
        intent = json.loads(draft.operation_intent_json)
        changed = dict(intent, due_date='2026-03-01')
        second = service.store.save(draft.draft_id, proposal, evidence=evidence,
            operation_intent=changed, expected_revision=1, actor_id='op', idempotency_key='change', reason='Change')
        self.assertNotEqual(second.content_digest, draft.content_digest)
        self.assertFalse(second.reviewable)
        with self.assertRaises(ValueError):
            service.app.post(approval.approval_id, actor_id='human', idempotency_key='stale')
        rejected = service.store.reject(draft.draft_id, expected_revision=2, actor_id='op',
            idempotency_key='reject', reason='Unsupported')
        self.assertEqual(rejected.operation_intent_json, second.operation_intent_json)
        self.assertEqual(service.store.reject(draft.draft_id, expected_revision=2, actor_id='op',
            idempotency_key='reject', reason='Unsupported'), rejected)
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            service.store.save('missing', proposal, evidence=evidence, expected_revision=0,
                actor_id='op', idempotency_key='missing', reason='No intent')
        old = test_review.ReviewTests.save(self)
        self.assertEqual(old.content_digest, digest([self.proposal, self.evidence, 'review-v1']))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)', ('draft',1,draft.operation_intent_json))
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            self.store.save('unexpected', self.proposal, evidence=self.evidence, operation_intent=intent,
                expected_revision=0, actor_id='op', idempotency_key='unexpected', reason='No authority')

    def test_ar_activation_guard_old_connection_and_rollback(self):
        with SQLiteLedger(self.path, **self.options) as old:
            service = self.service()
            before = self.ledger.snapshot
            activation = service.ensure_enabled(actor_id='human')
            self.assertEqual(service.ensure_enabled(actor_id='other'), activation)
            proposal = copy.deepcopy(self.proposal)
            proposal['lines'][0]['account'] = '1100'
            with self.assertRaises(sqlite3.IntegrityError):
                old.admit(proposal, actor_id='human', idempotency_key='bypass')
            self.assertEqual(self.ledger.snapshot, before)
            draft = self.store.save('generic', proposal, evidence=self.evidence, expected_revision=0,
                actor_id='op', idempotency_key='generic', reason='AR bypass')
            app = ReviewApplication(self.store)
            approval = app.approve('generic', revision=1, confirmed_digest=draft.content_digest,
                actor_id='human', idempotency_key='generic')
            with self.assertRaises(sqlite3.IntegrityError):
                app.post(approval.approval_id, actor_id='human', idempotency_key='generic')
            self.assertEqual(self.ledger.snapshot, before)

    def test_existing_ar_blocks_activation(self):
        proposal = copy.deepcopy(self.proposal)
        proposal['lines'] = [dict(account='1100',side='debit',amount='100.00'),
                             dict(account='4000',side='credit',amount='100.00')]
        self.ledger.admit(proposal, actor_id='human', idempotency_key='legacy')
        service = self.service()
        with self.assertRaisesRegex(ValueError, '10000'):
            service.ensure_enabled(actor_id='human')
        self.assertEqual(service.db.execute('SELECT count(*) FROM receivables_context').fetchone()[0], 0)
        from accounting_harness.receivables import receivables_report
        self.assertEqual(receivables_report(service.snapshot(), as_of='2026-01-31')['unassigned_control_cents'],10000)

    def test_post_faults_rollback_whole_unit_then_retry(self):
        service = self.service()
        draft = self.propose(service, self.register())
        approval = self.approve(service, draft)
        for table in ('customer_invoices','journals','lines','journal_sources','posting_events','review_postings','approved_post_requests'):
            service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
            service.db.execute('DROP TRIGGER injected')
            self.assertEqual(self.ledger.counts()['journals'],0)
            self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0],0)
        receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(receipt.entry.lines[0].amount.cents,250000)
        for table in ('receivables_schema','receivables_context','customer_invoices','draft_operation_intents'):
            for statement in (f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                    service.db.execute(statement)

    def test_shared_cash_claim_blocks_invoice_and_invoice_blocks_cash(self):
        from accounting_harness.operations import earned_cash_proposal
        service = self.service()
        docs = self.register()
        common = dict(docs[1])
        for key in ('completion_date',):
            del common[key]
        cash = dict(common, kind='cash_movement', document_id='cash', direction='in', purpose='earned_service')
        self.registry.register(cash, actor_id='op')
        self.ledger.enroll_source(self.registry, 'cash', actor_id='op')
        proposal, evidence = earned_cash_proposal(self.registry, entry_id='cash-journal',
            cash_source_id='cash', recognition_source_id=docs[1]['document_id'])
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        store.save('cash', proposal, evidence=evidence, expected_revision=0, actor_id='op',
            idempotency_key='cash', reason='Earned cash service')
        with self.assertRaisesRegex(ValueError, 'economic event'):
            self.propose(service, docs)
        other = self.register('other',number='I-002')
        self.propose(service, other, key='other')
        cash.update(document_id='cash2',event_id='other')
        self.registry.register(cash,actor_id='op')
        self.ledger.enroll_source(self.registry,'cash2',actor_id='op')
        proposal,evidence = earned_cash_proposal(self.registry,entry_id='cash2-journal',
            cash_source_id='cash2',recognition_source_id=other[1]['document_id'])
        with self.assertRaisesRegex(ValueError,'economic event'):
            store.save('cash2',proposal,evidence=evidence,expected_revision=0,actor_id='op',
                idempotency_key='cash2',reason='Duplicate service revenue')

    def test_save_faults_leave_no_revision_intent_event_claim_or_retry(self):
        service = self.service()
        docs = self.register()
        for table in ('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims'):
            service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.propose(service,docs)
            service.db.execute('DROP TRIGGER injected')
            for atomic in ('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims'):
                self.assertEqual(service.db.execute(f'SELECT count(*) FROM {atomic}').fetchone()[0],0)
        first = self.propose(service,docs)
        self.assertEqual(self.propose(service,docs),first)

    def test_direct_intent_shapes_and_forged_journals_never_approve(self):
        service = self.service()
        draft = self.propose(service,self.register())
        proposal,evidence = json.loads(draft.proposal_json),json.loads(draft.evidence_json)
        intent = json.loads(draft.operation_intent_json)
        changes = [dict(intent,**{key:value}) for key,value in [
            ('principal_cents',True),('principal_cents',250000.0),('principal_cents',0),
            ('principal_cents',2**63),('schema_version',True),('kind','customer_invoice_payment'),
            ('invoice_id','other'),('customer_id','other'),('currency','EUR'),
            ('due_date','2026-01-09'),('revenue_account','1000'),
            ('evidence_roles',dict(invoice='invoice-event-completion',completion='invoice-event-invoice'))]]
        changes += [dict(intent,extra='unsupported')]
        for index,changed in enumerate(changes,1):
            current = service.store.save(draft.draft_id,proposal,evidence=evidence,operation_intent=changed,
                expected_revision=index,actor_id='op',idempotency_key='bad'+str(index),reason='Invalid intent')
            self.assertFalse(current.reviewable,changed)
            self.assertNotEqual(current.content_digest,draft.content_digest)
            with self.assertRaises(ValueError):
                self.approve(service,current)
        forged = copy.deepcopy(proposal)
        forged['lines'][0]['account']='5000'
        current = service.store.save(draft.draft_id,forged,evidence=evidence,operation_intent=intent,
            expected_revision=len(changes)+1,actor_id='op',idempotency_key='forged',reason='Wrong account')
        self.assertFalse(current.reviewable)
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_historical_residual_and_legacy_ar_retries_after_activation(self):
        from accounting_harness.receivables import receivables_report
        proposal=copy.deepcopy(self.proposal)
        proposal['lines'][0]['account']='1100'
        original=self.ledger.admit(proposal,actor_id='human',idempotency_key='legacy-ar')
        reversed_receipt=self.ledger.reverse(original.entry.id,reversal_id='legacy-ar-reverse',
            entity_id=self.catalog.entity_id,effective_date='2026-01-20',reason='Historical AR reversal',
            source_ids=['rent'],actor_id='human',idempotency_key='legacy-ar-reverse')
        service=self.service()
        service.ensure_enabled(actor_id='human')
        frozen=service.snapshot()
        early=receivables_report(frozen,as_of='2026-01-10')
        self.assertEqual((early['ar_control_cents'],early['subledger_cents'],early['unassigned_control_cents']),
            (120000,0,120000))
        self.assertFalse(early['reconciled'])
        self.assertTrue(receivables_report(frozen,as_of='2026-01-31')['reconciled'])
        self.assertEqual(self.ledger.admit(proposal,actor_id='human',idempotency_key='legacy-ar'),original)
        self.assertEqual(self.ledger.reverse(original.entry.id,reversal_id='legacy-ar-reverse',
            entity_id=self.catalog.entity_id,effective_date='2026-01-20',reason='Historical AR reversal',
            source_ids=['rent'],actor_id='human',idempotency_key='legacy-ar-reverse'),reversed_receipt)
        self.propose(service,self.register())
        self.assertEqual(receivables_report(frozen,as_of='2026-01-10'),early)

    def test_effect_cannot_assign_historic_journal_or_commit_without_seal(self):
        from accounting_harness.receivables import prepare_receivable_post
        service=self.service()
        draft=self.propose(service,self.register())
        approval=self.approve(service,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                prepare_receivable_post(service.store,approval,draft,entry)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0],0)
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        row=service.db.execute('SELECT * FROM customer_invoices').fetchone()
        with self.assertRaises(sqlite3.IntegrityError):
            service.db.execute('INSERT INTO customer_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                ('another-invoice','another-customer','another-number','another-event',*row[4:]))
        for table,column in [('customer_invoices','due_date'),('receivables_context','actor_id'),
                             ('receivables_schema','version'),('draft_operation_intents','intent_json')]:
            with self.assertRaises(sqlite3.IntegrityError):
                service.db.execute(f'UPDATE {table} SET {column}={column}')

    def test_invoice_source_in_initial_context_does_not_disappear_from_report(self):
        # Legacy known-source IDs have no enrollment anchor; reporting must not inner-join away a invoice.
        from pathlib import Path
        from accounting_harness.receivables import ReceivablesService,receivables_report
        docs=facts(self.catalog.entity_id)
        for doc in docs:
            self.registry.register(doc,actor_id='op')
        with SQLiteLedger(Path(self.temp.name)/'initial.sqlite3',self.catalog,'2026-01-01','2026-01-31',
                known_source_ids={d['document_id'] for d in docs}) as ledger:
            service=ReceivablesService(ledger,self.registry)
            draft=self.propose(service,docs)
            approval=self.approve(service,draft)
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            frozen=service.snapshot()
            report=receivables_report(frozen,as_of='2026-01-31')
            self.assertEqual(len(report['invoices']),1)
            self.assertEqual(report['unassigned_control_cents'],0)
            self.assertEqual(report['invoices'][0]['customer_name'],'Fictional service customer')
            self.assertEqual(report['customers'],[dict(customer_id='customer-1',
                names=['Fictional service customer'],outstanding_cents=250000,
                aging_cents=dict(current=0,days_1_30=250000,days_31_60=0,days_61_90=0,days_91_plus=0))])
            later=facts(self.catalog.entity_id,event='later-invoice',number='I-002')
            for document in later:
                document['counterparty']='Fictional service customer renamed'
                self.registry.register(document,actor_id='op')
                ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
            next_draft=self.propose(service,later,key='later')
            next_approval=service.app.approve(next_draft.draft_id,revision=1,
                confirmed_digest=next_draft.content_digest,actor_id='human',idempotency_key='later')
            service.app.post(next_approval.approval_id,actor_id='human',idempotency_key='later')
            with patch.object(self.registry,'get',side_effect=AssertionError('pure reports cannot read registry')):
                self.assertEqual(receivables_report(frozen,as_of='2026-01-31'),report)
            current=receivables_report(service.snapshot(),as_of='2026-01-31')
            self.assertEqual(current['customers'],[dict(customer_id='customer-1',
                names=['Fictional service customer','Fictional service customer renamed'],outstanding_cents=500000,
                aging_cents=dict(current=0,days_1_30=500000,days_31_60=0,days_61_90=0,days_91_plus=0))])
            self.assertEqual(current['unassigned_control_cents'],0)
            # An unanchored source still has to match the immutable approval binding.
            from dataclasses import replace
            original_get=self.registry.get
            def altered_source(source_id):
                source=original_get(source_id)
                document=json.loads(source.canonical_content)
                document['counterparty']='Unapproved replacement name'
                return replace(source,canonical_content=json.dumps(document))
            with patch.object(self.registry,'get',side_effect=altered_source), self.assertRaisesRegex(ValueError,'approved evidence'):
                service.snapshot()

    def test_missing_cash_only_and_outside_period_cannot_approve(self):
        service=self.service()
        docs=self.register()
        for invoice,completion in [('missing',docs[1]['document_id']),
                              (docs[0]['document_id'],'missing'),
                              (docs[0]['document_id'],docs[0]['document_id'])]:
            with self.assertRaises((ValueError,KeyError)):
                service.propose_invoice(invoice_source_id=invoice,completion_source_id=completion,
                    expected_revision=0,actor_id='op',idempotency_key='missing')
        cash=dict(docs[1],document_id='cash-only',kind='cash_movement',direction='out',purpose='settlement')
        del cash['completion_date']
        self.registry.register(cash,actor_id='op')
        self.ledger.enroll_source(self.registry,'cash-only',actor_id='op')
        with self.assertRaises(ValueError):
            service.propose_invoice(invoice_source_id=docs[0]['document_id'],completion_source_id='cash-only',
                expected_revision=0,actor_id='op',idempotency_key='cash-only')
        later=self.register('later',number='later',changes={
            0:dict(document_date='2026-02-01',due_date='2026-03-01'),
            1:dict(document_date='2026-02-01',completion_date='2026-02-01')})
        draft=self.propose(service,later)
        self.assertFalse(draft.reviewable)
        with self.assertRaises(ValueError):
            self.approve(service,draft)

    def test_direct_sql_and_store_entry_cannot_omit_or_mismatch_effect(self):
        from dataclasses import replace
        from accounting_harness.domain.money import Money
        service=self.service()
        draft=self.propose(service,self.register())
        approval=self.approve(service,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                self.ledger._store_entry(entry,'direct')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                db=service.db
                db.execute('INSERT INTO journals VALUES (?,?,?,?,?)',
                    ('sql-ar',self.catalog.entity_id,'USD','2026-01-10','Direct SQL attempt'))
                db.execute('INSERT INTO lines VALUES (?,?,?,?,?)',('sql-ar',0,'1100','debit',250000))
                db.execute('INSERT INTO lines VALUES (?,?,?,?,?)',('sql-ar',1,'4000','credit',250000))
                db.execute('INSERT INTO posting_events VALUES (?,?,?,?)',
                    ('sql-ar','human','2026-01-10T00:00:00+00:00','post-v1'))
        original=self.ledger._store_entry
        from datetime import date
        cases=[replace(entry,effective_date=date(2026,1,11)),
               replace(entry,lines=(replace(entry.lines[0],account='5000'),entry.lines[1])),
               replace(entry,lines=tuple(replace(l,amount=Money(100)) for l in entry.lines)),
               replace(entry,source_ids=('rent',)),
               replace(entry,lines=tuple(replace(l,side='credit' if l.side=='debit' else 'debit') for l in entry.lines))]
        for changed in cases:
            with patch.object(self.ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)), self.assertRaises(sqlite3.IntegrityError):
                service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            self.assertEqual(self.ledger.counts()['journals'],0)
            self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0],0)
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')

    def test_tampered_or_missing_bound_intent_cannot_post(self):
        service=self.service()
        draft=self.propose(service,self.register())
        approval=self.approve(service,draft)
        # Deliberate database-owner corruption tests the read/approval revalidation boundary.
        service.db.execute('DROP TRIGGER draft_operation_intents_no_update')
        changed=json.loads(draft.operation_intent_json)
        changed['due_date']='2026-02-10'
        service.db.execute('UPDATE draft_operation_intents SET intent_json=?',(json.dumps(changed),))
        self.assertIn('content_digest',[f.code for f in service.store.get(draft.draft_id).current_findings])
        with self.assertRaises(ValueError):
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        service.db.execute('DROP TRIGGER draft_operation_intents_no_delete')
        service.db.execute('DELETE FROM draft_operation_intents')
        with self.assertRaises(ValueError):
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with self.assertRaises(sqlite3.IntegrityError):
            service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                (draft.draft_id,1,draft.operation_intent_json))
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_enrolled_display_name_must_match_approved_evidence(self):
        service = self.service()
        draft = self.propose(service, self.register())
        service.app.post(self.approve(service, draft).approval_id, actor_id='human', idempotency_key='post')
        db = service.db
        # Database-owner corruption cannot substitute an unapproved display name in a captured report.
        db.execute('DROP TRIGGER source_enrollments_no_update')
        content = json.loads(db.execute('SELECT canonical_content FROM source_enrollments WHERE source_id=?',
                                      ('invoice-event-invoice',)).fetchone()[0])
        content['counterparty'] = 'Unapproved customer name'
        db.execute('UPDATE source_enrollments SET canonical_content=? WHERE source_id=?',
                   (json.dumps(content), 'invoice-event-invoice'))
        with self.assertRaisesRegex(ValueError, 'approved evidence'):
            service.snapshot()

    def test_rejected_service_claim_retained_and_weak_policy_denied(self):
        service = self.service()
        draft = self.propose(service, self.register())
        service.store.reject(draft.draft_id, expected_revision=1, actor_id='human',
                             idempotency_key='reject', reason='Needs revised evidence')
        with self.assertRaisesRegex(ValueError, 'economic event'):
            self.propose(service, self.register('different-sources', number='I-002',
                changes={0: {'event_id':'invoice-event'}, 1: {'event_id':'invoice-event'}}), key='duplicate')
        proposal, evidence = json.loads(draft.proposal_json), json.loads(draft.evidence_json)
        weak = self.store.save('weak', proposal, evidence=evidence, expected_revision=0,
            actor_id='op', idempotency_key='weak', reason='Receipt policy cannot recognize typed invoice')
        self.assertFalse(weak.reviewable)
        with self.assertRaises(ValueError):
            ReviewApplication(self.store).approve('weak', revision=1, confirmed_digest=weak.content_digest,
                                                 actor_id='human', idempotency_key='weak')
        unknown = SQLiteReviewStore(self.ledger, self.registry, policy_version='invoice-v999')
        self.assertIn('unsupported_policy', [f.code for f in unknown.validate(proposal, evidence)])
        # Removing a bound source prevents an already-issued approval from posting.
        next_draft = self.propose(service, self.register('next', number='I-003'), key='next')
        approval = self.approve(service, next_draft)
        original = self.registry.get
        def missing(source_id):
            if source_id == 'next-completion':
                raise KeyError(source_id)
            return original(source_id)
        with patch.object(self.registry, 'get', side_effect=missing), self.assertRaises(ValueError):
            service.app.post(approval.approval_id, actor_id='human', idempotency_key='missing')
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_registered_but_unenrolled_invoice_is_inert(self):
        service = self.service()
        docs = facts(self.catalog.entity_id)
        for document in docs:
            self.registry.register(document, actor_id='op')
        draft = self.propose(service, docs)
        self.assertFalse(draft.reviewable)
        with self.assertRaises(ValueError):
            self.approve(service, draft)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0], 0)


    def test_concurrent_exact_post_retry_reopens_one_invoice(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.sources import SQLiteSourceRegistry
        from accounting_harness.receivables import ReceivablesService, receivables_report
        service = self.service()
        docs = self.register()
        draft = self.propose(service, docs)
        approval = self.approve(service, draft)
        def post():
            with SQLiteSourceRegistry(self.source_path, self.catalog.entity_id) as registry:
                with SQLiteLedger(self.path, **self.options) as ledger:
                    reopened = ReceivablesService(ledger, registry)
                    return reopened.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: post(), range(2)))
        self.assertEqual(results[0], results[1])
        with SQLiteLedger(self.path, **self.options) as ledger:
            reopened = ReceivablesService(ledger, self.registry)
            self.assertEqual(self.propose(reopened, docs), draft)
            self.assertEqual(self.approve(reopened, draft), approval)
            self.assertEqual(reopened.app.post(approval.approval_id, actor_id='human', idempotency_key='post'), results[0])
            report = receivables_report(reopened.snapshot(), as_of='2026-01-31')
            self.assertEqual(len(report['invoices']), 1)
            self.assertEqual(report['ar_control_cents'], 250000)
            self.assertEqual(report['unassigned_control_cents'], 0)

    def test_invoice_schema_and_activation_faults_roll_back(self):
        from accounting_harness import receivables
        original = receivables.protect_table
        def fail(db, table, conflict):
            original(db, table, conflict)
            if table == 'customer_invoices':
                raise RuntimeError('migration fault')
        with patch.object(receivables, 'protect_table', side_effect=fail), self.assertRaisesRegex(RuntimeError, 'migration fault'):
            receivables.ReceivablesService(self.ledger, self.registry)
        for table in ('receivables_schema','receivables_context','customer_invoices'):
            self.assertIsNone(self.store.db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone())
        service = self.service()
        docs = self.register()
        service.db.execute("CREATE TRIGGER injected BEFORE INSERT ON receivables_context BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.propose(service, docs)
        self.assertEqual(service.db.execute('SELECT count(*) FROM receivables_context').fetchone()[0], 0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM draft_revisions').fetchone()[0], 0)
        service.db.execute('DROP TRIGGER injected')
        self.assertTrue(self.propose(service, docs).reviewable)

    def test_forged_and_stale_direct_invoice_effects_are_denied(self):
        service = self.service()
        draft = self.propose(service, self.register())
        approval = self.approve(service, draft)
        intent = json.loads(draft.operation_intent_json)
        effect = [intent['invoice_id'], intent['customer_id'], intent['invoice_number'],
            intent['recognition_event_id'], intent['evidence_roles']['invoice'], intent['evidence_roles']['completion'],
            intent['principal_cents'], intent['revenue_account'], intent['effective_date'], intent['due_date'],
            approval.approval_id, json.loads(draft.proposal_json)['id']]
        for index, value in [(0,'forged'),(1,'other'),(2,'Other'),(3,'other-event'),(4,'rent'),
                             (5,'rent'),(6,1),(7,'5000'),(8,'2026-01-11'),(9,'2026-01-26'),
                             (10,'forged-approval'),(11,'forged-journal')]:
            changed = list(effect); changed[index] = value
            with self.subTest(index=index), self.assertRaises(sqlite3.IntegrityError):
                with self.ledger._transaction(write=True):
                    service.db.execute('INSERT INTO customer_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', changed)
        service.store.reject(draft.draft_id, expected_revision=1, actor_id='human',
                             idempotency_key='reject', reason='Reject prior approval')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'approved operation'):
            with self.ledger._transaction(write=True):
                service.db.execute('INSERT INTO customer_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', effect)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_invoices').fetchone()[0], 0)
        self.assertEqual(self.ledger.counts()['journals'], 0)


    def test_new_revision_between_invoice_effect_and_journal_seal_rolls_back(self):
        from accounting_harness.receivables import prepare_receivable_post
        service = self.service()
        draft = self.propose(service, self.register())
        approval = self.approve(service, draft)
        entry = self.ledger._validate_entry(json.loads(draft.proposal_json))
        tables = ('customer_invoices', 'journals', 'lines', 'journal_sources', 'posting_events',
                  'draft_revisions', 'draft_operation_intents', 'review_events', 'review_requests',
                  'review_postings', 'approved_post_requests')
        before = {table: service.db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
        for state, operation in [('rejected', 'reject'), ('pending', 'save')]:
            with self.subTest(state=state), self.assertRaisesRegex(sqlite3.IntegrityError, 'approved receivable effect'):
                with self.ledger._transaction(write=True):
                    prepare_receivable_post(service.store, approval, draft, entry)
                    # All guards stay enabled. The newer revision seals after the approved effect
                    # was accepted but before the journal's mandatory posting-event seal.
                    revision = list(service.db.execute('SELECT * FROM draft_revisions').fetchone())
                    revision[1], revision[6], revision[7], revision[8] = 2, state, 'A later human decision', 'human'
                    service.db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)', revision)
                    service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                                       (draft.draft_id, 2, draft.operation_intent_json))
                    service.db.execute('INSERT INTO review_events VALUES (?,?,?)', (draft.draft_id, 2, operation))
                    service.db.execute('INSERT INTO review_requests VALUES (?,?,?,?,?)',
                        (operation, 'later-decision', digest([operation, draft.draft_id, 1, 'human',
                            'A later human decision', None if operation == 'reject' else json.loads(draft.proposal_json),
                            None if operation == 'reject' else json.loads(draft.evidence_json), 'invoice-v1'] +
                            ([] if operation == 'reject' else [{'operation_intent_v1': json.loads(draft.operation_intent_json)}])),
                         draft.draft_id, 2))
                    self.ledger._store_entry(entry, 'human')
            self.assertEqual({table: service.db.execute(f'SELECT * FROM {table}').fetchall()
                              for table in tables}, before)
        # The failed unit neither consumes the approval nor leaves the draft rejected.
        receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(receipt.entry.id, entry.id)
        self.assertEqual(self.ledger.counts()['journals'], 1)



class InvoiceHTTPTests(unittest.TestCase):
    setUp = test_web.WorkspaceHTTPTests.setUp
    start = test_web.WorkspaceHTTPTests.start
    stop = test_web.WorkspaceHTTPTests.stop
    tearDown = test_web.WorkspaceHTTPTests.tearDown
    request = test_web.WorkspaceHTTPTests.request

    def test_separate_evidence_proposal_confirmation_and_report(self):
        entity = self.request('GET','/api/state')[1]['entity_id']
        for document in facts(entity):
            status, result = self.request('POST','/api/operation-sources',dict(document=document))
            self.assertEqual(status,200,result)
        payload = dict(invoice_source_id='invoice-event-invoice', completion_source_id='invoice-event-completion')
        status, result = self.request('POST','/api/invoice-proposals',payload)
        self.assertEqual(status,200,result)
        self.assertEqual(self.request('POST','/api/invoice-proposals',payload)[1],result)
        state = self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],0)
        draft = state['drafts'][0]
        self.assertEqual(draft['operation_intent']['principal_cents'],250000)
        self.assertEqual(len(draft['evidence']),2)
        for extra in ({'amount':'1.00'},{'actor_id':'agent'},{'policy_version':'review-v1'}):
            self.assertEqual(self.request('POST','/api/invoice-proposals',dict(payload,**extra))[0],409)
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],confirmed_digest=draft['content_digest'])
        self.assertEqual(self.request('POST','/api/approve-post',dict(confirmation,confirmed_digest='wrong'))[0],409)
        status, posted = self.request('POST','/api/approve-post',confirmation)
        self.assertEqual(status,200,posted)
        state = self.request('GET','/api/state')[1]
        self.assertEqual(state['receivables']['subledger_cents'],250000)
        self.assertEqual(state['receivables']['unassigned_control_cents'],0)
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'],'local-operator')

    def test_large_cents_review_and_report_have_exact_display_text(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in facts(entity):
            document['amount']='90071992547409.93'
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.assertEqual(self.request('POST','/api/invoice-proposals',dict(
            invoice_source_id='invoice-event-invoice',completion_source_id='invoice-event-completion'))[0],200)
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.assertIn('9007199254740993',draft.get('operation_intent_json',''))
        self.assertEqual(json.loads(draft['operation_intent_json'])['principal_cents'],9007199254740993)
        self.assertEqual(self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],
            revision=1,confirmed_digest=draft['content_digest']))[0],200)
        report=self.request('GET','/api/state')[1]['receivables']
        self.assertEqual(report['ar_control_amount'],'90071992547409.93')
        self.assertEqual(report['invoices'][0]['outstanding_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['invoices'][0]['trace_json'])


class InvoiceCLITests(unittest.TestCase):
    def test_demo_invoice(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-invoice'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ('AR debit 2500.00', 'Revenue credit 2500.00', 'outstanding 2500.00',
                         'residual 0.00', 'invoice-v1', 'zero model calls'):
            self.assertIn(expected, result.stdout)


class InvoiceMigrationTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def test_review_v3_upgrade_preserves_bill_payment_and_legacy_rows_and_rolls_back(self):
        import test_payables
        import test_bill_payments
        import test_operations
        from accounting_harness.operations import cash_expense_proposal
        from accounting_harness.receivables import ReceivablesService, receivables_report
        from accounting_harness.payables import PayablesService, payables_report
        # Record genuinely approved receipt, cash, bill and payment envelopes before migration.
        old = test_review.ReviewTests.save(self, require_unused_evidence=True)
        old_app = ReviewApplication(self.store)
        approval = old_app.approve('draft', revision=1, confirmed_digest=old.content_digest,
                                  actor_id='human', idempotency_key='old')
        receipt = old_app.post(approval.approval_id, actor_id='human', idempotency_key='old')
        bills = PayablesService(self.ledger, self.registry)
        docs = test_payables.facts(self.catalog.entity_id)
        for doc in docs:
            self.registry.register(doc, actor_id='op')
            self.ledger.enroll_source(self.registry, doc['document_id'], actor_id='op')
        bill = bills.propose_bill(bill_source_id=docs[0]['document_id'], incurrence_source_id=docs[1]['document_id'],
            expected_revision=0, actor_id='op', idempotency_key='bill')
        def post(app, draft, key):
            approval = app.approve(draft.draft_id, revision=1, confirmed_digest=draft.content_digest,
                                  actor_id='human', idempotency_key=key)
            return app.post(approval.approval_id, actor_id='human', idempotency_key=key)
        bill_receipt = post(bills.app, bill, 'bill')
        payment_doc = test_bill_payments.cash_fact(self.catalog.entity_id)
        self.registry.register(payment_doc, actor_id='op')
        self.ledger.enroll_source(self.registry, payment_doc['document_id'], actor_id='op')
        payment = bills.propose_payment(bill_id=json.loads(bill.operation_intent_json)['bill_id'],
            cash_source_id=payment_doc['document_id'], expected_revision=0, actor_id='op', idempotency_key='payment')
        payments = ReviewApplication(SQLiteReviewStore(self.ledger, self.registry, policy_version='bill-payment-v1'))
        payment_receipt = post(payments, payment, 'payment')
        docs = test_operations.facts(self.catalog.entity_id, 'legacy-cash')
        for doc in docs:
            self.registry.register(doc, actor_id='op')
            self.ledger.enroll_source(self.registry, doc['document_id'], actor_id='op')
        proposal, evidence = cash_expense_proposal(self.registry, entry_id='legacy-cash',
            cash_source_id=docs[0]['document_id'], recognition_source_id=docs[1]['document_id'])
        cash = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        cash_draft = cash.save('cash', proposal, evidence=evidence, expected_revision=0, actor_id='op',
            idempotency_key='cash', reason='Cash', require_unused_evidence=True)
        cash_app = ReviewApplication(cash)
        cash_receipt = post(cash_app, cash_draft, 'cash')
        db = self.store.db
        with self.ledger._transaction(write=True):
            self.store._replace_intent_seal("'bill-v1','bill-payment-v1'")
            db.execute('DROP TRIGGER review_schema_no_update')
            db.execute('UPDATE review_schema SET version=3')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        tables = ('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims',
            'approvals','approval_requests','review_postings','approved_post_requests','vendor_bills',
            'vendor_bill_payments','payables_context','journals','lines','posting_events','ledger_context','source_enrollments')
        before = {t: db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        old_seal = db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0]
        db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_UPDATE and name == 'review_schema' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                SQLiteReviewStore(self.ledger, self.registry)
        finally:
            db.set_authorizer(None)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(), [(3,)])
        self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0], old_seal)
        service = ReceivablesService(self.ledger, self.registry)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(), [(5,)])
        self.assertEqual({t: db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}, before)
        self.assertEqual(test_review.ReviewTests.save(self, require_unused_evidence=True), old)
        self.assertEqual(old_app.post(approval.approval_id, actor_id='human', idempotency_key='old'), receipt)
        self.assertEqual(post(bills.app, bill, 'bill'), bill_receipt)
        self.assertEqual(post(payments, payment, 'payment'), payment_receipt)
        self.assertEqual(post(cash_app, cash_draft, 'cash'), cash_receipt)
        self.assertEqual(cash.save('cash', proposal, evidence=evidence, expected_revision=0, actor_id='op',
            idempotency_key='cash', reason='Cash', require_unused_evidence=True), cash_draft)
        service.ensure_enabled(actor_id='human')
        self.assertEqual(receivables_report(service.snapshot(), as_of='2026-01-31')['ar_control_cents'], 0)
        self.assertEqual(payables_report(bills.snapshot(), as_of='2026-01-31')['ap_control_cents'], 20000)
        invoice_docs = facts(self.catalog.entity_id)
        for document in invoice_docs:
            self.registry.register(document, actor_id='op')
            self.ledger.enroll_source(self.registry, document['document_id'], actor_id='op')
        invoice = service.propose_invoice(invoice_source_id=invoice_docs[0]['document_id'],
            completion_source_id=invoice_docs[1]['document_id'], expected_revision=0, actor_id='op', idempotency_key='invoice')
        post(service.app, invoice, 'invoice')
        later_cash = test_bill_payments.cash_fact(self.catalog.entity_id, event='later-payment', amount='50.00')
        self.registry.register(later_cash, actor_id='op')
        self.ledger.enroll_source(self.registry, later_cash['document_id'], actor_id='op')
        later_payment = bills.propose_payment(bill_id=json.loads(bill.operation_intent_json)['bill_id'],
            cash_source_id=later_cash['document_id'], expected_revision=0, actor_id='op', idempotency_key='later-payment')
        post(payments, later_payment, 'later-payment')
        ar = receivables_report(service.snapshot(), as_of='2026-01-31')
        ap = payables_report(bills.snapshot(), as_of='2026-01-31')
        self.assertEqual((ar['ar_control_cents'], ap['ap_control_cents']), (250000, 15000))
        self.assertEqual((ar['unassigned_control_cents'], ap['unassigned_control_cents']), (0, 0))
        self.ledger.reverse(receipt.entry.id, reversal_id='ordinary-reverse', entity_id=self.catalog.entity_id,
            effective_date='2026-01-20', reason='Ordinary correction', source_ids=['rent'],
            actor_id='human', idempotency_key='ordinary-reverse')
