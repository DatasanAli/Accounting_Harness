"""Vendor bills: independent accounting, exact intent and atomic AP enforcement."""
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


def facts(entity, event='bill-event', vendor='vendor-1', number='B-001'):
    common = dict(schema_version=2, synthetic=True, entity_id=entity, currency='USD',
        document_date='2026-01-10', amount='300.00', event_id=event, counterparty_id=vendor,
        counterparty='Fictional software vendor', description='Synthetic separately asserted fact')
    return (dict(common, document_id=event+'-bill', kind='vendor_bill', bill_number=number,
                 due_date='2026-02-09'),
            dict(common, document_id=event+'-incurrence', kind='incurred_expense',
                 incurred_date='2026-01-10', expense_account='5100'))


class PayablesTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def service(self):
        import accounting_harness
        from importlib.util import find_spec
        self.assertIsNotNone(find_spec('accounting_harness.payables'), 'payables service is required')
        from accounting_harness.payables import PayablesService
        return PayablesService(self.ledger, self.registry)

    def register(self, event='bill-event', vendor='vendor-1', number='B-001', changes=None):
        docs = facts(self.catalog.entity_id, event, vendor, number)
        for i, doc in enumerate(docs):
            doc.update((changes or {}).get(i, {}))
            self.registry.register(doc, actor_id='operator')
            self.ledger.enroll_source(self.registry, doc['document_id'], actor_id='operator')
        return docs

    def propose(self, service, docs, expected=0, key='bill'):
        return service.propose_bill(bill_source_id=docs[0]['document_id'],
            incurrence_source_id=docs[1]['document_id'], expected_revision=expected,
            actor_id='template', idempotency_key=key)

    def approve(self, service, draft):
        return service.app.approve(draft.draft_id, revision=draft.revision,
            confirmed_digest=draft.content_digest, actor_id='human', idempotency_key='approve'+str(draft.revision))

    def test_bill_independent_balances_intent_trace_retry_and_snapshot(self):
        service = self.service()
        docs = self.register()
        draft = self.propose(service, docs)
        self.assertTrue(draft.reviewable, draft.findings + draft.current_findings)
        self.assertEqual(self.ledger.counts()['journals'], 0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM vendor_bills').fetchone()[0], 0)
        intent = json.loads(draft.operation_intent_json)
        self.assertEqual(intent['principal_cents'], 30000)
        self.assertEqual(intent['due_date'], '2026-02-09')
        approval = self.approve(service, draft)
        receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual([(l.account, l.side, l.amount.cents) for l in receipt.entry.lines],
                         [('5100', 'debit', 30000), ('2000', 'credit', 30000)])
        from accounting_harness.payables import payables_report
        frozen = service.snapshot()
        report = payables_report(frozen, as_of='2026-01-31')
        self.assertEqual((report['ap_control_cents'], report['subledger_cents'], report['unassigned_control_cents']),
                         (30000, 30000, 0))
        self.assertEqual(report['bills'][0]['outstanding_cents'], 30000)
        self.assertEqual(report['bills'][0]['paid_cents'], 0)
        self.assertEqual(payables_report(frozen, as_of='2026-01-09')['subledger_cents'], 0)
        self.assertEqual(service.app.post(approval.approval_id, actor_id='human', idempotency_key='post'), receipt)
        self.assertTrue(service.store.get(draft.draft_id).reviewable)
        self.assertEqual(len(service.app.trace(draft.draft_id)['evidence']), 2)
        with self.assertRaisesRegex(ValueError, 'operational_reversal_not_supported'):
            self.ledger.reverse(receipt.entry.id, reversal_id='reverse', entity_id=self.catalog.entity_id,
                effective_date='2026-01-11', reason='correct', source_ids=list(receipt.entry.source_ids),
                actor_id='human', idempotency_key='reverse')
        self.assertEqual(payables_report(frozen, as_of='2026-01-31'), report)

    def test_duplicate_bill_identity_and_shared_expense_claim(self):
        service = self.service()
        self.propose(service, self.register())
        with self.assertRaises(ValueError):
            self.propose(service, self.register('other-event'), key='duplicate')
        with self.assertRaisesRegex(ValueError, 'economic event'):
            self.propose(service, self.register('other-number', number='B-002',
                changes={0: {'event_id': 'bill-event'}, 1: {'event_id': 'bill-event'}}), key='event')
        self.assertTrue(self.propose(service, self.register('other-vendor', vendor='vendor-2'), key='other').reviewable)

    def test_inconsistent_facts_and_invalid_dates_refused(self):
        service = self.service()
        for i, changes in enumerate([{1: {k: v}} for k, v in
            [('amount','301.00'),('event_id','wrong'),('counterparty_id','wrong'),
             ('incurred_date','2026-01-11'),('document_date','2026-01-11')]]):
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

    def test_ap_activation_guard_old_connection_and_rollback(self):
        with SQLiteLedger(self.path, **self.options) as old:
            service = self.service()
            before = self.ledger.snapshot
            activation = service.ensure_enabled(actor_id='human')
            self.assertEqual(service.ensure_enabled(actor_id='other'), activation)
            proposal = copy.deepcopy(self.proposal)
            proposal['lines'][1]['account'] = '2000'
            with self.assertRaises(sqlite3.IntegrityError):
                old.admit(proposal, actor_id='human', idempotency_key='bypass')
            self.assertEqual(self.ledger.snapshot, before)
            draft = self.store.save('generic', proposal, evidence=self.evidence, expected_revision=0,
                actor_id='op', idempotency_key='generic', reason='AP bypass')
            app = ReviewApplication(self.store)
            approval = app.approve('generic', revision=1, confirmed_digest=draft.content_digest,
                actor_id='human', idempotency_key='generic')
            with self.assertRaises(sqlite3.IntegrityError):
                app.post(approval.approval_id, actor_id='human', idempotency_key='generic')
            self.assertEqual(self.ledger.snapshot, before)

    def test_existing_ap_blocks_activation(self):
        proposal = copy.deepcopy(self.proposal)
        proposal['lines'] = [dict(account='5100',side='debit',amount='100.00'),
                             dict(account='2000',side='credit',amount='100.00')]
        self.ledger.admit(proposal, actor_id='human', idempotency_key='legacy')
        service = self.service()
        with self.assertRaisesRegex(ValueError, '10000'):
            service.ensure_enabled(actor_id='human')
        self.assertEqual(service.db.execute('SELECT count(*) FROM payables_context').fetchone()[0], 0)
        from accounting_harness.payables import payables_report
        self.assertEqual(payables_report(service.snapshot(), as_of='2026-01-31')['unassigned_control_cents'],10000)

    def test_post_faults_rollback_whole_unit_then_retry(self):
        service = self.service()
        draft = self.propose(service, self.register())
        approval = self.approve(service, draft)
        for table in ('vendor_bills','journals','lines','posting_events','review_postings','approved_post_requests'):
            service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
            service.db.execute('DROP TRIGGER injected')
            self.assertEqual(self.ledger.counts()['journals'],0)
            self.assertEqual(service.db.execute('SELECT count(*) FROM vendor_bills').fetchone()[0],0)
        receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(receipt.entry.lines[0].amount.cents,30000)
        for table in ('payables_schema','payables_context','vendor_bills','draft_operation_intents'):
            for statement in (f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                    service.db.execute(statement)

    def test_shared_cash_claim_blocks_bill_and_bill_blocks_cash(self):
        from accounting_harness.operations import cash_expense_proposal
        service = self.service()
        docs = self.register()
        common = dict(docs[1])
        for key in ('incurred_date','expense_account'):
            del common[key]
        cash = dict(common, kind='cash_movement', document_id='cash', direction='out', purpose='incurred_expense')
        self.registry.register(cash, actor_id='op')
        self.ledger.enroll_source(self.registry, 'cash', actor_id='op')
        proposal, evidence = cash_expense_proposal(self.registry, entry_id='cash-journal',
            cash_source_id='cash', recognition_source_id=docs[1]['document_id'])
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='cash-v1')
        store.save('cash', proposal, evidence=evidence, expected_revision=0, actor_id='op',
            idempotency_key='cash', reason='Cash expense')
        with self.assertRaisesRegex(ValueError, 'economic event'):
            self.propose(service, docs)
        other = self.register('other',number='B-002')
        self.propose(service, other, key='other')
        cash.update(document_id='cash2',event_id='other')
        self.registry.register(cash,actor_id='op')
        self.ledger.enroll_source(self.registry,'cash2',actor_id='op')
        proposal,evidence = cash_expense_proposal(self.registry,entry_id='cash2-journal',
            cash_source_id='cash2',recognition_source_id=other[1]['document_id'])
        with self.assertRaisesRegex(ValueError,'economic event'):
            store.save('cash2',proposal,evidence=evidence,expected_revision=0,actor_id='op',
                idempotency_key='cash2',reason='Duplicate expense')

    def test_save_faults_leave_no_revision_intent_event_claim_or_retry(self):
        service = self.service()
        docs = self.register()
        for table in ('draft_operation_intents','review_events','review_requests','operation_claims'):
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
            ('principal_cents',True),('principal_cents',30000.0),('principal_cents',0),
            ('principal_cents',2**63),('schema_version',True),('kind','vendor_bill_payment'),
            ('bill_id','other'),('vendor_id','other'),('currency','EUR'),
            ('due_date','2026-01-09'),('expense_account','1000'),
            ('evidence_roles',dict(bill='bill-event-incurrence',incurrence='bill-event-bill'))]]
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

    def test_migration_preserves_legacy_bytes_and_rolls_back_on_failure(self):
        # Recreate the v1 schema boundary after recording genuine legacy-envelope rows.
        from accounting_harness import review
        from accounting_harness.operations import cash_expense_proposal
        import test_operations
        old = test_review.ReviewTests.save(self,require_unused_evidence=True)
        app = ReviewApplication(self.store)
        approval = app.approve('draft',revision=1,confirmed_digest=old.content_digest,
            actor_id='human',idempotency_key='old')
        receipt = app.post(approval.approval_id,actor_id='human',idempotency_key='old')
        docs = test_operations.facts(self.catalog.entity_id,'cash-legacy')
        for doc in docs:
            self.registry.register(doc,actor_id='op')
            self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='op')
        cash = SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1')
        proposal,evidence = cash_expense_proposal(self.registry,entry_id='legacy-cash',
            cash_source_id=docs[0]['document_id'],recognition_source_id=docs[1]['document_id'])
        cash_draft = cash.save('cash',proposal,evidence=evidence,expected_revision=0,actor_id='op',
            idempotency_key='cash',reason='Cash',require_unused_evidence=True)
        cash_app = ReviewApplication(cash)
        cash_approval = cash_app.approve('cash',revision=1,confirmed_digest=cash_draft.content_digest,
            actor_id='human',idempotency_key='cash')
        db = self.store.db
        tables = ('draft_revisions','review_events','review_requests','operation_claims',
            'approvals','approval_requests','review_postings','approved_post_requests',
            'journals','lines','posting_events','ledger_context','source_enrollments')
        before = {t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        context = self.ledger._context
        db.execute('DROP TRIGGER intent_required_at_seal')
        db.execute('DROP TABLE draft_operation_intents')
        db.execute('DROP TRIGGER review_schema_no_update')
        db.execute('UPDATE review_schema SET version=1')
        db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        original = review.protect_table
        def fail(db,table,conflict):
            original(db,table,conflict)
            if table == 'draft_operation_intents':
                raise RuntimeError('migration fault')
        with patch.object(review,'protect_table',side_effect=fail), self.assertRaisesRegex(RuntimeError,'migration fault'):
            SQLiteReviewStore(self.ledger,self.registry)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(1,)])
        self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='draft_operation_intents'").fetchone())
        service = self.service()
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(2,)])
        self.assertEqual({t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
        self.assertEqual(self.ledger._context,context)
        self.assertEqual(test_review.ReviewTests.save(self,require_unused_evidence=True),old)
        self.assertEqual(app.approve('draft',revision=1,confirmed_digest=old.content_digest,
            actor_id='human',idempotency_key='old'),approval)
        self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key='old'),receipt)
        self.assertEqual(cash.save('cash',proposal,evidence=evidence,expected_revision=0,actor_id='op',
            idempotency_key='cash',reason='Cash',require_unused_evidence=True),cash_draft)
        cash_app.post(cash_approval.approval_id,actor_id='human',idempotency_key='cash')
        service.ensure_enabled(actor_id='human')
        reversed_receipt=self.ledger.reverse(receipt.entry.id,reversal_id='ordinary-reverse',
            entity_id=self.catalog.entity_id,effective_date='2026-01-20',reason='Ordinary correction',
            source_ids=['rent'],actor_id='human',idempotency_key='ordinary-reverse')
        self.assertEqual(reversed_receipt.original_entry_id,receipt.entry.id)

    def test_historical_residual_and_legacy_ap_retries_after_activation(self):
        from accounting_harness.payables import payables_report
        proposal=copy.deepcopy(self.proposal)
        proposal['lines'][1]['account']='2000'
        original=self.ledger.admit(proposal,actor_id='human',idempotency_key='legacy-ap')
        reversed_receipt=self.ledger.reverse(original.entry.id,reversal_id='legacy-ap-reverse',
            entity_id=self.catalog.entity_id,effective_date='2026-01-20',reason='Historical AP reversal',
            source_ids=['rent'],actor_id='human',idempotency_key='legacy-ap-reverse')
        service=self.service()
        service.ensure_enabled(actor_id='human')
        frozen=service.snapshot()
        early=payables_report(frozen,as_of='2026-01-10')
        self.assertEqual((early['ap_control_cents'],early['subledger_cents'],early['unassigned_control_cents']),
            (120000,0,120000))
        self.assertFalse(early['reconciled'])
        self.assertTrue(payables_report(frozen,as_of='2026-01-31')['reconciled'])
        self.assertEqual(self.ledger.admit(proposal,actor_id='human',idempotency_key='legacy-ap'),original)
        self.assertEqual(self.ledger.reverse(original.entry.id,reversal_id='legacy-ap-reverse',
            entity_id=self.catalog.entity_id,effective_date='2026-01-20',reason='Historical AP reversal',
            source_ids=['rent'],actor_id='human',idempotency_key='legacy-ap-reverse'),reversed_receipt)
        self.propose(service,self.register())
        self.assertEqual(payables_report(frozen,as_of='2026-01-10'),early)

    def test_effect_cannot_assign_historic_journal_or_commit_without_seal(self):
        from accounting_harness.payables import prepare_payable_post
        service=self.service()
        draft=self.propose(service,self.register())
        approval=self.approve(service,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                prepare_payable_post(service.store,approval,draft,entry)
        self.assertEqual(service.db.execute('SELECT count(*) FROM vendor_bills').fetchone()[0],0)
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        row=service.db.execute('SELECT * FROM vendor_bills').fetchone()
        with self.assertRaises(sqlite3.IntegrityError):
            service.db.execute('INSERT INTO vendor_bills VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                ('another-bill','another-vendor','another-number','another-event',*row[4:]))
        for table,column in [('vendor_bills','due_date'),('payables_context','actor_id'),
                             ('payables_schema','version'),('draft_operation_intents','intent_json')]:
            with self.assertRaises(sqlite3.IntegrityError):
                service.db.execute(f'UPDATE {table} SET {column}={column}')

    def test_bill_source_in_initial_context_does_not_disappear_from_report(self):
        # Legacy known-source IDs have no enrollment anchor; reporting must not inner-join away a bill.
        from pathlib import Path
        from accounting_harness.payables import PayablesService,payables_report
        docs=facts(self.catalog.entity_id)
        for doc in docs:
            self.registry.register(doc,actor_id='op')
        with SQLiteLedger(Path(self.temp.name)/'initial.sqlite3',self.catalog,'2026-01-01','2026-01-31',
                known_source_ids={d['document_id'] for d in docs}) as ledger:
            service=PayablesService(ledger,self.registry)
            draft=self.propose(service,docs)
            approval=self.approve(service,draft)
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            frozen=service.snapshot()
            report=payables_report(frozen,as_of='2026-01-31')
            self.assertEqual(len(report['bills']),1)
            self.assertEqual(report['unassigned_control_cents'],0)
            self.assertEqual(report['bills'][0]['vendor_name'],'Fictional software vendor')
            self.assertEqual(report['vendors'],[dict(vendor_id='vendor-1',
                names=['Fictional software vendor'],outstanding_cents=30000)])
            later=facts(self.catalog.entity_id,event='later-bill',number='B-002')
            for document in later:
                document['counterparty']='Fictional software vendor renamed'
                self.registry.register(document,actor_id='op')
                ledger.enroll_source(self.registry,document['document_id'],actor_id='op')
            next_draft=self.propose(service,later,key='later')
            next_approval=service.app.approve(next_draft.draft_id,revision=1,
                confirmed_digest=next_draft.content_digest,actor_id='human',idempotency_key='later')
            service.app.post(next_approval.approval_id,actor_id='human',idempotency_key='later')
            with patch.object(self.registry,'get',side_effect=AssertionError('pure reports cannot read registry')):
                self.assertEqual(payables_report(frozen,as_of='2026-01-31'),report)
            current=payables_report(service.snapshot(),as_of='2026-01-31')
            self.assertEqual(current['vendors'],[dict(vendor_id='vendor-1',
                names=['Fictional software vendor','Fictional software vendor renamed'],outstanding_cents=60000)])
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
        for bill,incurred in [('missing',docs[1]['document_id']),
                              (docs[0]['document_id'],'missing'),
                              (docs[0]['document_id'],docs[0]['document_id'])]:
            with self.assertRaises((ValueError,KeyError)):
                service.propose_bill(bill_source_id=bill,incurrence_source_id=incurred,
                    expected_revision=0,actor_id='op',idempotency_key='missing')
        cash=dict(docs[1],document_id='cash-only',kind='cash_movement',direction='out',purpose='settlement')
        del cash['incurred_date'];del cash['expense_account']
        self.registry.register(cash,actor_id='op')
        self.ledger.enroll_source(self.registry,'cash-only',actor_id='op')
        with self.assertRaises(ValueError):
            service.propose_bill(bill_source_id=docs[0]['document_id'],incurrence_source_id='cash-only',
                expected_revision=0,actor_id='op',idempotency_key='cash-only')
        later=self.register('later',number='later',changes={
            0:dict(document_date='2026-02-01',due_date='2026-03-01'),
            1:dict(document_date='2026-02-01',incurred_date='2026-02-01')})
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
                    ('sql-ap',self.catalog.entity_id,'USD','2026-01-10','Direct SQL attempt'))
                db.execute('INSERT INTO lines VALUES (?,?,?,?,?)',('sql-ap',0,'5100','debit',30000))
                db.execute('INSERT INTO lines VALUES (?,?,?,?,?)',('sql-ap',1,'2000','credit',30000))
                db.execute('INSERT INTO posting_events VALUES (?,?,?,?)',
                    ('sql-ap','human','2026-01-10T00:00:00+00:00','post-v1'))
        original=self.ledger._store_entry
        cases=[replace(entry,lines=(replace(entry.lines[0],account='5000'),entry.lines[1])),
               replace(entry,lines=tuple(replace(l,amount=Money(100)) for l in entry.lines)),
               replace(entry,source_ids=('rent',)),
               replace(entry,lines=tuple(replace(l,side='credit' if l.side=='debit' else 'debit') for l in entry.lines))]
        for changed in cases:
            with patch.object(self.ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)), self.assertRaises(sqlite3.IntegrityError):
                service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            self.assertEqual(self.ledger.counts()['journals'],0)
            self.assertEqual(service.db.execute('SELECT count(*) FROM vendor_bills').fetchone()[0],0)
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


class BillHTTPTests(unittest.TestCase):
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
        payload = dict(bill_source_id='bill-event-bill', incurrence_source_id='bill-event-incurrence')
        status, result = self.request('POST','/api/bill-proposals',payload)
        self.assertEqual(status,200,result)
        self.assertEqual(self.request('POST','/api/bill-proposals',payload)[1],result)
        state = self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],0)
        draft = state['drafts'][0]
        self.assertEqual(draft['operation_intent']['principal_cents'],30000)
        self.assertEqual(len(draft['evidence']),2)
        for extra in ({'amount':'1.00'},{'actor_id':'agent'},{'policy_version':'review-v1'}):
            self.assertEqual(self.request('POST','/api/bill-proposals',dict(payload,**extra))[0],409)
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],confirmed_digest=draft['content_digest'])
        self.assertEqual(self.request('POST','/api/approve-post',dict(confirmation,confirmed_digest='wrong'))[0],409)
        status, posted = self.request('POST','/api/approve-post',confirmation)
        self.assertEqual(status,200,posted)
        state = self.request('GET','/api/state')[1]
        self.assertEqual(state['payables']['subledger_cents'],30000)
        self.assertEqual(state['payables']['unassigned_control_cents'],0)
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'],'local-operator')

    def test_large_cents_review_and_report_have_exact_display_text(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in facts(entity):
            document['amount']='90071992547409.93'
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.assertEqual(self.request('POST','/api/bill-proposals',dict(
            bill_source_id='bill-event-bill',incurrence_source_id='bill-event-incurrence'))[0],200)
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.assertIn('9007199254740993',draft.get('operation_intent_json',''))
        self.assertEqual(json.loads(draft['operation_intent_json'])['principal_cents'],9007199254740993)
        self.assertEqual(self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],
            revision=1,confirmed_digest=draft['content_digest']))[0],200)
        report=self.request('GET','/api/state')[1]['payables']
        self.assertEqual(report['ap_control_amount'],'90071992547409.93')
        self.assertEqual(report['bills'][0]['outstanding_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['bills'][0]['trace_json'])
