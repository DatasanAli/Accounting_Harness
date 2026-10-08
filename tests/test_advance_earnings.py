"""Supported earning: exact completion evidence, shared claims and atomic control."""
import json
import sqlite3
import unittest
from unittest.mock import patch
import test_advances
from accounting_harness.approval import ReviewApplication
from accounting_harness.review import SQLiteReviewStore


class AdvanceEarningTests(unittest.TestCase):
    setUp = test_advances.AdvancesTests.setUp
    service = test_advances.AdvancesTests.service
    register = test_advances.AdvancesTests.register
    propose = test_advances.AdvancesTests.propose
    approve = test_advances.AdvancesTests.approve

    def advance(self):
        service = self.service()
        draft = self.propose(service, self.register())
        service.app.post(self.approve(service, draft).approval_id, actor_id='human', idempotency_key='receipt')
        return service, json.loads(draft.operation_intent_json)['advance_id']

    def completion(self, event='completion-1', amount='200.00', **changes):
        document = dict(schema_version=2, synthetic=True, entity_id=self.catalog.entity_id,
            document_id=event+'-source', kind='advance_completion', event_id=event,
            counterparty_id='customer-1', contract_id='contract-1', counterparty='Later display name',
            currency='USD', amount=amount, document_date='2026-01-31', completion_date='2026-01-31',
            description='Synthetic service completion')
        document.update(changes)
        self.registry.register(document, actor_id='operator')
        self.ledger.enroll_source(self.registry, document['document_id'], actor_id='operator')
        return document

    def earning(self, service, target, document, expected=0):
        return service.propose_earning(advance_id=target, completion_source_id=document['document_id'],
            expected_revision=expected, actor_id='template', idempotency_key=document['document_id']+str(expected))

    def earning_app(self):
        return ReviewApplication(SQLiteReviewStore(self.ledger, self.registry, policy_version='advance-earning-v1'))

    def earning_approval(self, app, draft):
        return app.approve(draft.draft_id, revision=draft.revision, confirmed_digest=draft.content_digest,
            actor_id='human', idempotency_key='approve:'+draft.draft_id+str(draft.revision))

    def test_supported_200_earning_leaves_400_and_cash_unchanged(self):
        from accounting_harness.advances import advances_report, AdvancesSnapshot
        service, target = self.advance()
        frozen = service.snapshot()
        legacy = AdvancesSnapshot(frozen.ledger, frozen.advances, frozen.activation_json, frozen.ledger_context)
        before = advances_report(frozen, as_of='2026-01-31')
        old = advances_report(legacy, as_of='2026-01-31')
        self.assertEqual(old['schema_version'], 1)
        self.assertNotIn('earnings', old)
        self.assertEqual(before['schema_version'], 2)
        self.assertEqual(before['earnings'], [])
        self.assertTrue(callable(getattr(service, 'propose_earning', None)), 'earning proposal service required')
        draft = self.earning(service, target, self.completion())
        self.assertTrue(draft.reviewable, draft.current_findings)
        app = self.earning_app()
        approval = self.earning_approval(app, draft)
        self.assertEqual(self.ledger.counts()['journals'], 1)
        receipt = app.post(approval.approval_id, actor_id='human', idempotency_key='earn')
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],
                         [('2100','debit',20000),('4000','credit',20000)])
        report = advances_report(service.snapshot(), as_of='2026-01-31')
        self.assertEqual([report[k] for k in ('principal_cents','earned_cents','remaining_cents','unearned_control_cents','unassigned_control_cents')],
                         [60000,20000,40000,40000,0])
        self.assertEqual(sum(l.amount.cents for e in self.ledger.snapshot.entries for l in e.lines if l.account=='1000'),60000)
        self.assertEqual(report['advances'][0]['customer_name'],'Fictional customer')
        self.assertEqual(advances_report(service.snapshot(),as_of='2026-01-30')['earned_cents'],0)
        with patch.object(self.registry, 'get', side_effect=AssertionError('pure report')):
            self.assertEqual(advances_report(frozen,as_of='2026-01-31'),before)
            self.assertEqual(advances_report(legacy,as_of='2026-01-31'),old)
        self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key='earn'),receipt)

    def test_two_approved_400_completions_reserve_nothing_and_only_one_posts(self):
        from accounting_harness.advances import advances_report
        service,target=self.advance()
        self.assertTrue(callable(getattr(service, 'propose_earning', None)), 'earning proposal service required')
        drafts=[self.earning(service,target,self.completion('event-'+str(n),'400.00')) for n in range(2)]
        app=self.earning_app()
        approvals=[self.earning_approval(app,d) for d in drafts]
        app.post(approvals[0].approval_id,actor_id='human',idempotency_key='first')
        with self.assertRaises(ValueError):app.post(approvals[1].approval_id,actor_id='human',idempotency_key='second')
        report=advances_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual(report['remaining_cents'],20000)
        self.assertEqual(len(report['earnings']),1)
        self.assertTrue(app.store.get(drafts[0].draft_id).reviewable)

    def test_full_earning_historical_readability_overearning_and_reversal_refusal(self):
        from accounting_harness.advances import advances_report
        service,target=self.advance();app=self.earning_app()
        first=self.earning(service,target,self.completion())
        approval=self.earning_approval(app,first)
        receipt=app.post(approval.approval_id,actor_id='human',idempotency_key='first')
        second=self.earning(service,target,self.completion('second','400.00'))
        app.post(self.earning_approval(app,second).approval_id,actor_id='human',idempotency_key='second')
        self.assertTrue(app.store.get(first.draft_id).reviewable)
        self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key='first'),receipt)
        self.assertEqual(advances_report(service.snapshot(),as_of='2026-01-31')['remaining_cents'],0)
        excess=self.earning(service,target,self.completion('excess','0.01'))
        self.assertFalse(excess.reviewable)
        with self.assertRaises(ValueError):self.earning_approval(app,excess)
        with self.assertRaisesRegex(ValueError,'operational_reversal_not_supported'):
            self.ledger.reverse(receipt.entry.id,reversal_id='reverse',entity_id=self.catalog.entity_id,
                effective_date='2026-01-31',reason='correct',source_ids=list(receipt.entry.source_ids),actor_id='human',idempotency_key='reverse')

    def test_strict_completion_wrong_customer_contract_date_and_unposted_target(self):
        service,target=self.advance()
        for n,changes in enumerate((dict(counterparty_id='other'),dict(contract_id='other'),
                dict(document_date='2026-01-21',completion_date='2026-01-21'))):
            document=self.completion('bad'+str(n),**changes)
            with self.assertRaises(ValueError):self.earning(service,target,document)
        outside=self.earning(service,target,self.completion('outside',document_date='2026-02-01',completion_date='2026-02-01'))
        self.assertFalse(outside.reviewable)
        with self.assertRaises(ValueError):self.earning(service,'unposted',self.completion('unposted'))
        for n,changes in enumerate((dict(amount=True),dict(amount=200.0),dict(amount='0.00'),
                dict(amount='200.001'),dict(currency='EUR'),dict(extra='invalid'),dict(contract_id=''),
                dict(document_date='2026-01-30'),dict(schema_version=1),dict(completion_date='2026-02-30'))):
            with self.subTest(changes=changes),self.assertRaises((ValueError,TypeError)):
                self.completion('invalid'+str(n),**changes)

    def test_exact_intent_and_journal_no_split_and_stale_approval(self):
        service,target=self.advance();app=self.earning_app()
        draft=self.earning(service,target,self.completion())
        approval=self.earning_approval(app,draft)
        intent=json.loads(draft.operation_intent_json);proposal=json.loads(draft.proposal_json)
        evidence=json.loads(draft.evidence_json)
        for field,value in [('schema_version',True),('earned_cents',True),('earned_cents',20000.0),
                ('earned_cents',10000),('advance_id','wrong'),('customer_id','wrong'),('contract_id','wrong'),
                ('completion_event_id','wrong'),('effective_date','2026-01-30'),('currency','EUR'),
                ('kind','customer_advance'),('extra',1),('evidence_roles',dict(prepayment='rent',completion='completion-1-source'))]:
            self.assertTrue(app.store.validate(proposal,evidence,operation_intent=dict(intent,**{field:value}),draft_id=draft.draft_id))
        for field,value in [('id','other'),('effective_date','2026-01-30'),('source_ids',['rent']),
                ('lines',[dict(account='1000',side='debit',amount='200.00'),dict(account='4000',side='credit',amount='200.00')])]:
            self.assertTrue(app.store.validate(dict(proposal,**{field:value}),evidence,operation_intent=intent,draft_id=draft.draft_id))
        newer=app.store.save(draft.draft_id,proposal,evidence=evidence,operation_intent=intent,expected_revision=1,
            actor_id='human',idempotency_key='newer',reason='Reconfirm completion')
        with self.assertRaises(ValueError):app.post(approval.approval_id,actor_id='human',idempotency_key='old')
        app.post(self.earning_approval(app,newer).approval_id,actor_id='human',idempotency_key='new')

    def test_completion_event_identity_independent_of_target_and_correction_needs_approval(self):
        from accounting_harness.review import digest
        service,target=self.advance();app=self.earning_app()
        document=self.completion()
        draft=self.earning(service,target,document)
        self.assertEqual(draft.draft_id,'draft:advance-earning:'+digest([self.catalog.entity_id,'completion-1']))
        # Invalid target is retained for explicit correction on the same economic event.
        intent=json.loads(draft.operation_intent_json)
        invalid=app.store.save(draft.draft_id,json.loads(draft.proposal_json),evidence=json.loads(draft.evidence_json),
            operation_intent=dict(intent,advance_id='wrong'),expected_revision=1,actor_id='human',idempotency_key='wrong',reason='Invalid target')
        self.assertFalse(invalid.reviewable)
        corrected=self.earning(service,target,document,expected=2)
        self.assertEqual(corrected.draft_id,draft.draft_id)
        self.assertTrue(corrected.reviewable)
        self.assertEqual(corrected.revision,3)
        self.assertEqual(self.ledger.counts()['journals'],1)

    def test_save_and_every_post_write_fault_roll_back_then_retry(self):
        service,target=self.advance();app=self.earning_app();document=self.completion()
        tables=('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims',
                'customer_advance_earnings','journals','lines','journal_sources','posting_events','review_postings','approved_post_requests')
        snapshot=lambda:{t:service.db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        before=snapshot()
        for table in tables[:5]:
            service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):self.earning(service,target,document)
            service.db.execute('DROP TRIGGER injected');self.assertEqual(snapshot(),before)
        draft=self.earning(service,target,document);approval=self.earning_approval(app,draft);before=snapshot()
        for table in tables[5:]:
            service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            service.db.execute('DROP TRIGGER injected');self.assertEqual(snapshot(),before)
        app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        for action in ('UPDATE customer_advance_earnings SET earned_cents=1','DELETE FROM customer_advance_earnings',
                       'INSERT OR REPLACE INTO customer_advance_earnings SELECT * FROM customer_advance_earnings'):
            with self.assertRaises(sqlite3.IntegrityError):service.db.execute(action)

    def test_final_seal_rechecks_current_approval_after_effect_for_reject_and_pending(self):
        from accounting_harness.advances import prepare_advance_post
        service,target=self.advance();app=self.earning_app()
        draft=self.earning(service,target,self.completion());approval=self.earning_approval(app,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        tables=('customer_advance_earnings','journals','lines','journal_sources','posting_events',
                'draft_revisions','draft_operation_intents','review_events','review_requests','review_postings','approved_post_requests')
        before={t:service.db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        for state,operation in [('rejected','reject'),('pending','save')]:
            with self.subTest(state=state),self.assertRaisesRegex(sqlite3.IntegrityError,'approved advance effect'):
                with self.ledger._transaction(write=True):
                    prepare_advance_post(app.store,approval,draft,entry)
                    row=list(service.db.execute('SELECT * FROM draft_revisions WHERE draft_id=?',(draft.draft_id,)).fetchone())
                    row[1],row[6]=2,state
                    service.db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)',row)
                    service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',(draft.draft_id,2,draft.operation_intent_json))
                    service.db.execute('INSERT INTO review_events VALUES (?,?,?)',(draft.draft_id,2,operation))
                    service.db.execute('INSERT INTO review_requests VALUES (?,?,?,?,?)',(operation,'intervene','d'*64,draft.draft_id,2))
                    self.ledger._store_entry(entry,'human')
            self.assertEqual({t:service.db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
        app.post(approval.approval_id,actor_id='human',idempotency_key='post')

    def test_orphan_forged_effect_and_mismatching_journal_are_denied(self):
        from dataclasses import replace
        from datetime import date
        from accounting_harness.advances import prepare_advance_post
        from accounting_harness.domain.money import Money
        service,target=self.advance();app=self.earning_app()
        draft=self.earning(service,target,self.completion());approval=self.earning_approval(app,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):prepare_advance_post(app.store,approval,draft,entry)
        effect=['completion-1',target,'completion-1-source',20000,'2026-01-31',approval.approval_id,entry.id]
        for index,value in [(0,'other'),(1,'other'),(2,'rent'),(3,10000),(4,'2026-01-30'),(5,'other'),(6,'other')]:
            changed=effect.copy();changed[index]=value
            with self.assertRaises(sqlite3.IntegrityError):
                with self.ledger._transaction(write=True):service.db.execute('INSERT INTO customer_advance_earnings VALUES (?,?,?,?,?,?,?)',changed)
        original=self.ledger._store_entry
        for changed in [replace(entry,effective_date=date(2026,1,30)),replace(entry,source_ids=('rent',)),
                replace(entry,lines=(replace(entry.lines[0],account='1000'),entry.lines[1])),
                replace(entry,lines=tuple(replace(l,amount=Money(10000)) for l in entry.lines))]:
            with patch.object(self.ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)),self.assertRaises(sqlite3.IntegrityError):
                app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):self.ledger._store_entry(entry,'bypass')
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advance_earnings').fetchone()[0],0)

    def test_shared_service_claim_cash_invoice_and_advance_both_directions(self):
        from accounting_harness.operations import earned_cash_proposal
        from accounting_harness.receivables import ReceivablesService
        service,target=self.advance();app=self.earning_app()
        def other(event,policy):
            base=dict(schema_version=2,synthetic=True,entity_id=self.catalog.entity_id,currency='USD',amount='200.00',
                document_date='2026-01-31',event_id=event,counterparty_id='customer-1',counterparty='Fictional customer',description='Synthetic service')
            completion=dict(base,document_id=event+'-ordinary-completion',kind='service_completion',completion_date='2026-01-31')
            source=(dict(base,document_id=event+'-cash',kind='cash_movement',direction='in',purpose='earned_service') if policy=='cash'
                else dict(base,document_id=event+'-invoice',kind='customer_invoice',invoice_number=event,due_date='2026-02-15'))
            for document in (source,completion):
                self.registry.register(document,actor_id='human');self.ledger.enroll_source(self.registry,document['document_id'],actor_id='human')
            if policy=='invoice':
                return ReceivablesService(self.ledger,self.registry).propose_invoice(invoice_source_id=source['document_id'],
                    completion_source_id=completion['document_id'],expected_revision=0,actor_id='template',idempotency_key=event)
            proposal,evidence=earned_cash_proposal(self.registry,entry_id=event,cash_source_id=source['document_id'],recognition_source_id=completion['document_id'])
            return SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1').save(event,proposal,evidence=evidence,
                expected_revision=0,actor_id='template',idempotency_key=event,reason='Earned service')
        for policy in ('cash','invoice'):
            for first in (True,False):
                event=policy+str(first)
                if first:
                    draft=self.earning(service,target,self.completion(event))
                    app.store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key=event,reason='Rejected but claim retained')
                    with self.assertRaisesRegex(ValueError,'economic event'):other(event,policy)
                else:
                    other(event,policy)
                    with self.assertRaisesRegex(ValueError,'economic event'):self.earning(service,target,self.completion(event))
        self.assertEqual(self.ledger.counts()['journals'],1)

    def test_concurrent_exact_retry_and_restart_keep_one_effect(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.sources import SQLiteSourceRegistry
        from accounting_harness.advances import AdvancesService,advances_report
        service,target=self.advance();app=self.earning_app();document=self.completion()
        draft=self.earning(service,target,document);approval=self.earning_approval(app,draft)
        def post():
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry:
                with SQLiteLedger(self.path,**self.options) as ledger:
                    AdvancesService(ledger,registry)
                    reopened=ReviewApplication(SQLiteReviewStore(ledger,registry,policy_version='advance-earning-v1'))
                    return reopened.post(approval.approval_id,actor_id='human',idempotency_key='concurrent')
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:post(),range(2)))
        self.assertEqual(results[0],results[1])
        with SQLiteLedger(self.path,**self.options) as ledger:
            reopened=AdvancesService(ledger,self.registry)
            self.assertEqual(self.earning(reopened,target,document),draft)
            report=advances_report(reopened.snapshot(),as_of='2026-01-31')
            self.assertEqual(report['remaining_cents'],40000)
            self.assertEqual(len(report['earnings']),1)
            self.assertEqual(len(ledger.snapshot.entries),2)

    def test_competing_posts_recheck_balance_under_write_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.sources import SQLiteSourceRegistry
        from accounting_harness.advances import AdvancesService,advances_report
        service,target=self.advance();app=self.earning_app()
        approvals=[self.earning_approval(app,self.earning(service,target,self.completion('race'+str(n),'400.00'))) for n in range(2)]
        def post(n):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry:
                with SQLiteLedger(self.path,**self.options) as ledger:
                    AdvancesService(ledger,registry)
                    reopened=ReviewApplication(SQLiteReviewStore(ledger,registry,policy_version='advance-earning-v1'))
                    try:return reopened.post(approvals[n].approval_id,actor_id='human',idempotency_key='race'+str(n))
                    except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(post,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        report=advances_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual((report['remaining_cents'],report['unassigned_control_cents']),(20000,0))

    def test_v6_v1_migration_failure_restores_exact_schema_and_legacy_approval_bytes(self):
        from accounting_harness import advances
        service,target=self.advance();db=service.db
        draft=service.store.get('draft:'+target)
        approval=service.db.execute('SELECT approval_id FROM customer_advances').fetchone()[0]
        receipt=service.app.post(approval,actor_id='human',idempotency_key='receipt')
        # Reconstruct the delivered v6/v1 schema using explicit predecessor definitions.
        with self.ledger._transaction(write=True):
            db.execute('DROP TRIGGER advances_post_guard')
            db.execute('DROP TABLE customer_advance_earnings')
            service._create_post_guard()
            db.execute('DROP TRIGGER advances_schema_no_update');db.execute('UPDATE advances_schema SET version=1')
            db.execute("CREATE TRIGGER advances_schema_no_update BEFORE UPDATE ON advances_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
            service.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1'")
            db.execute('DROP TRIGGER review_schema_no_update');db.execute('UPDATE review_schema SET version=6')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        schema=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables=('customer_advances','advances_context','draft_revisions','draft_operation_intents','review_events','review_requests',
                'operation_claims','approvals','approval_requests','review_postings','approved_post_requests','ledger_context',
                'journals','lines','journal_sources','posting_events','source_enrollments')
        before={t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        sources=self.registry.list_documents()
        original=advances.protect_table
        def fail(db,table,conflict):
            original(db,table,conflict)
            if table=='customer_advance_earnings':raise RuntimeError('earning migration fault')
        with patch.object(advances,'protect_table',side_effect=fail),self.assertRaises(RuntimeError):self.service()
        self.assertEqual(db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),schema)
        db.set_authorizer(lambda action,name,*_:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and name=='advances_schema' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):self.service()
        finally:db.set_authorizer(None)
        self.assertEqual(db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),schema)
        migrated=self.service()
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(7,)])
        self.assertEqual(db.execute('SELECT version FROM advances_schema').fetchall(),[(2,)])
        self.assertEqual({t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
        self.assertEqual(self.registry.list_documents(),sources)
        self.assertEqual(migrated.store.get(draft.draft_id),draft)
        self.assertEqual(migrated.app.post(approval,actor_id='human',idempotency_key='receipt'),receipt)

    def test_legacy_four_field_capture_keeps_exact_schema1_shape_and_digests(self):
        from dataclasses import asdict
        from accounting_harness.advances import AdvancesSnapshot,advances_report,REPORT_POLICY
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.review import digest
        service,target=self.advance();snapshot=service.snapshot()
        legacy=AdvancesSnapshot(snapshot.ledger,snapshot.advances,snapshot.activation_json,snapshot.ledger_context)
        expected=dict(schema_version=1,policy=REPORT_POLICY,as_of='2026-01-31',
            snapshot_digest=digest([legacy.ledger_context,[SQLiteLedger._entry_payload(e) for e in legacy.ledger.entries],
                [asdict(a) for a in legacy.advances],legacy.activation_json]),
            included_journal_ids=[e.id for e in legacy.ledger.entries],enabled=True,activation=json.loads(legacy.activation_json),
            advances=[dict(asdict(legacy.advances[0]),earned_cents=0,remaining_cents=60000)],
            customers=[dict(customer_id='customer-1',names=['Fictional customer'],principal_cents=60000,earned_cents=0,remaining_cents=60000)],
            principal_cents=60000,earned_cents=0,remaining_cents=60000,unearned_control_cents=60000,subledger_cents=60000,
            unassigned_control_cents=0,reconciled=True)
        expected['report_digest']=digest(expected)
        self.assertEqual(advances_report(legacy,as_of='2026-01-31'),expected)

    def test_registered_unenrolled_completion_and_tampered_intent_cannot_post(self):
        service,target=self.advance();app=self.earning_app()
        with patch.object(self.ledger,'enroll_source'):
            document=self.completion()
        draft=self.earning(service,target,document)
        self.assertFalse(draft.reviewable)
        with self.assertRaises(ValueError):self.earning_approval(app,draft)
        self.ledger.enroll_source(self.registry,document['document_id'],actor_id='human')
        draft=self.earning(service,target,document,expected=1);approval=self.earning_approval(app,draft)
        service.db.execute('DROP TRIGGER draft_operation_intents_no_update')
        intent=json.loads(draft.operation_intent_json);intent['earned_cents']=10000
        service.db.execute('UPDATE draft_operation_intents SET intent_json=? WHERE draft_id=? AND revision=2',
            (json.dumps(intent),draft.draft_id))
        self.assertIn('content_digest',[f.code for f in app.store.get(draft.draft_id).current_findings])
        with self.assertRaises(ValueError):app.post(approval.approval_id,actor_id='human',idempotency_key='post')


class AdvanceEarningHTTPTests(unittest.TestCase):
    setUp = test_advances.AdvanceHTTPTests.setUp
    start = test_advances.AdvanceHTTPTests.start
    stop = test_advances.AdvanceHTTPTests.stop
    tearDown = test_advances.AdvanceHTTPTests.tearDown
    request = test_advances.AdvanceHTTPTests.request

    def test_completion_enrollment_review_confirmation_exact_display_and_history(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in test_advances.facts(entity):
            document['amount']='90071992547409.95'
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        draft=self.request('POST','/api/advance-proposals',dict(prepayment_source_id='advance-event-prepayment',cash_source_id='advance-event-cash'))[1]
        confirmation=lambda d:dict(draft_id=d['draft_id'],revision=d['revision'],confirmed_digest=d['content_digest'])
        self.assertEqual(self.request('POST','/api/approve-post',confirmation(draft))[0],200)
        target=self.request('GET','/api/state')[1]['advances']['advances'][0]['advance_id']
        document=dict(test_advances.facts(entity)[0],kind='advance_completion',document_id='completion-source',
            event_id='completion',document_date='2026-01-31',completion_date='2026-01-31',amount='90071992547409.93')
        self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        payload=dict(advance_id=target,completion_source_id='completion-source')
        # Exercise the route actually shipped in the native form, including the HTTP boundary.
        import re
        from pathlib import Path
        script=(Path(__file__).resolve().parents[1]/'accounting_harness/static/app.js').read_text()
        handler=script.split("$('earning-proposal-form').addEventListener",1)[1].split("$('advance-evidence-form')",1)[0]
        route=re.search(r"await request\('([^']+)'",handler).group(1)
        status,draft=self.request('POST',route,payload)
        self.assertEqual(status,200,draft)
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],1)
        self.assertEqual(state['advances']['earnings'],[])
        earning=next(d for d in state['drafts'] if d['policy_version']=='advance-earning-v1')
        self.assertIn('9007199254740993',earning['operation_intent_json'])
        for extra in ({'earned_cents':1},{'actor_id':'agent'},{'policy_version':'review-v1'}):
            self.assertEqual(self.request('POST','/api/advance-earning-proposals',dict(payload,**extra))[0],409)
        self.assertEqual(self.request('POST','/api/approve-post',dict(confirmation(draft),confirmed_digest='wrong'))[0],409)
        status,posted=self.request('POST','/api/approve-post',confirmation(draft));self.assertEqual(status,200,posted)
        report=self.request('GET','/api/state')[1]['advances']
        self.assertEqual(report['earned_amount'],'90071992547409.93')
        self.assertEqual(report['remaining_amount'],'0.02')
        self.assertEqual(report['earnings'][0]['earned_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['earnings'][0]['trace_json'])
        self.assertEqual(self.request('POST','/api/advance-earning-proposals',payload)[1],draft)
        self.assertEqual(self.request('POST','/api/approve-post',confirmation(draft))[1],posted)

class AdvanceEarningCLITests(unittest.TestCase):
    def test_demo(self):
        import subprocess
        import sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-advance-earning'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for expected in ('Cash unchanged 600.00','earned 200.00','remaining 400.00','residual 0.00','advance-earning-v1','zero model calls'):
            self.assertIn(expected,result.stdout)
