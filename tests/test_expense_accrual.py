"""Unbilled expense recognition, exact authorization and frozen obligations."""
import copy
import json
import sqlite3
import unittest
from importlib.util import find_spec
from unittest.mock import patch
import test_review


class ExpenseAccrualTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def service(self):
        self.assertIsNotNone(find_spec('accounting_harness.expense_accrual'), 'expense accrual service required')
        from accounting_harness.expense_accrual import ExpenseAccrualService
        return ExpenseAccrualService(self.ledger, self.registry)

    def facts(self, suffix='', amount='150.00', incurrence=None, basis=None, enroll=True):
        common=dict(self.document,schema_version=2,event_id='software-january',counterparty_id='software-vendor',amount=amount)
        expense=dict(common,document_id='incurrence'+suffix,kind='incurred_expense',document_date='2026-01-28',incurred_date='2026-01-28',expense_account='5100')
        support=dict(common,document_id='basis'+suffix,kind='expense_accrual_basis',document_date='2026-01-31',cutoff_date='2026-01-31',status='unbilled_unpaid')
        expense.update(incurrence or {});support.update(basis or {})
        for doc in (expense,support):
            self.registry.register(doc,actor_id='operator')
            if enroll:self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='operator')
        return expense,support

    def propose(self, service, suffix='', expected=0, key='prepare'):
        return service.propose(incurrence_source_id='incurrence'+suffix,basis_source_id='basis'+suffix,
            expected_revision=expected,actor_id='template',idempotency_key=key)

    def approve(self, service, draft):
        return service.app.approve(draft.draft_id,revision=draft.revision,confirmed_digest=draft.content_digest,
            actor_id='human',idempotency_key='approval'+str(draft.revision))

    def post(self,service,draft):
        return service.app.post(self.approve(service,draft).approval_id,actor_id='human',idempotency_key='post')

    def test_supported_150_requires_human_confirmation_and_has_zero_residual(self):
        service=self.service();self.facts();draft=self.propose(service)
        self.assertTrue(draft.reviewable,draft.current_findings)
        self.assertEqual(self.ledger.counts()['journals'],0)
        receipt=self.post(service,draft)
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],[('5100','debit',15000),('2050','credit',15000)])
        from accounting_harness.expense_accrual import expense_accrual_report
        report=expense_accrual_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual([report[k] for k in ('principal_cents','control_cents','unassigned_control_cents')],[15000,15000,0])
        self.assertEqual(report['obligations'][0]['incurrence_source_id'],'incurrence')
        self.assertEqual(self.propose(service),draft)
        self.assertEqual(self.post(service,draft),receipt)
        self.assertEqual(service.db.execute('SELECT count(*) FROM expense_accrual_effects').fetchone(),(1,))

    def test_conflicting_facts_dates_status_roles_and_accounts_are_refused(self):
        service=self.service()
        changes=[({},dict(counterparty_id='other')),({},dict(event_id='other')),({},dict(amount='149.99')),
            ({},dict(cutoff_date='2026-01-30')),({},dict(document_date='2026-01-30')),
            (dict(incurred_date='2026-02-01',document_date='2026-02-01'),{}),
            (dict(incurred_date='2026-01-27'),{}),({},dict(status='paid')),
            (dict(expense_account='5300'),{}),(dict(expense_account='2000'),{}),
            ({},dict(status=True)),(dict(document_date='2025-12-31',incurred_date='2025-12-31'),{})]
        for index,(incurrence,basis) in enumerate(changes):
            with self.subTest(index=index),self.assertRaises((ValueError,TypeError)):
                self.facts(str(index),incurrence=incurrence,basis=basis)
                self.propose(service,str(index),key='bad'+str(index))
        self.facts()
        with self.assertRaises(ValueError):service.propose(incurrence_source_id='incurrence',basis_source_id='incurrence',expected_revision=0,actor_id='template',idempotency_key='roles')
        self.assertEqual(self.ledger.counts()['journals'],0)
        self.assertIsNone(self.ledger.expense_accrual_account_activation())

    def test_missing_anchor_and_missing_source_are_refused(self):
        service=self.service();self.facts(enroll=False)
        with self.assertRaisesRegex(ValueError,'anchored'):self.propose(service)
        with self.assertRaises(KeyError):self.propose(service,'absent')
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_forged_intents_and_lines_never_become_reviewable(self):
        service=self.service();self.facts();draft=self.propose(service)
        intent=json.loads(draft.operation_intent_json);proposal=json.loads(draft.proposal_json)
        attempts=[]
        for field,value in [('principal_cents',True),('principal_cents',15000.0),('principal_cents',14999),('vendor_id','forged'),('schema_version',True),('extra','unsupported')]:
            attempts.append((proposal,intent|{field:value}))
        for account in ('1000','2000','1100','2100','1200'):
            forged=copy.deepcopy(proposal);forged['lines'][1]['account']=account;attempts.append((forged,intent))
        for n,(journal,op) in enumerate(attempts):
            forged=service.store.save(draft.draft_id,journal,evidence=json.loads(draft.evidence_json),operation_intent=op,
                expected_revision=n+1,actor_id='forger',idempotency_key='forged'+str(n),reason='test')
            self.assertFalse(forged.reviewable)
            with self.assertRaises(ValueError):self.approve(service,forged)
        self.assertEqual(service.db.execute('SELECT count(*) FROM expense_accrual_preparations').fetchone(),(1,))

    def test_revised_evidence_keeps_event_identity_and_requires_fresh_approval(self):
        service=self.service();self.facts();draft=self.propose(service);old=self.approve(service,draft)
        self.facts('revised',amount='151.00')
        revised=self.propose(service,'revised',expected=1,key='revision')
        self.assertEqual(revised.draft_id,draft.draft_id)
        with self.assertRaisesRegex(ValueError,'stale'):service.app.post(old.approval_id,actor_id='human',idempotency_key='stale')
        receipt=self.post(service,revised)
        self.assertEqual(receipt.entry.lines[0].amount.cents,15100)
        self.assertEqual(service.db.execute('SELECT count(*) FROM operation_claims').fetchone(),(1,))

    def test_final_seal_rejects_intervening_pending_and_rejected_revisions(self):
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        original=self.ledger._store_entry
        for state in ('pending','rejected'):
            def supersede(entry,actor):
                service.db.execute('''INSERT INTO draft_revisions SELECT draft_id,2,proposal_json,evidence_json,policy_version,
                    content_digest,?,reason,actor_id,recorded_at,findings_json FROM draft_revisions WHERE draft_id=?''',(state,draft.draft_id))
                return original(entry,actor)
            with patch.object(self.ledger,'_store_entry',side_effect=supersede),self.assertRaises(sqlite3.IntegrityError):
                service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            self.assertEqual(service.db.execute('SELECT count(*) FROM expense_accrual_effects').fetchone(),(0,))
            self.assertEqual(service.store.get(draft.draft_id).revision,1)
            self.assertEqual(self.ledger.counts()['journals'],0)

    def test_final_seal_rejects_changed_shape_after_effect(self):
        from dataclasses import replace
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        original=self.ledger._store_entry
        def forge(entry,actor):return original(replace(entry,lines=(replace(entry.lines[0],account='5000'),entry.lines[1])),actor)
        with patch.object(self.ledger,'_store_entry',side_effect=forge),self.assertRaises(sqlite3.IntegrityError):
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        self.assertEqual(self.ledger.counts()['journals'],0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM expense_accrual_effects').fetchone(),(0,))

    def test_write_faults_rollback_effect_journal_posting_and_retry(self):
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        for table in ('expense_accrual_effects','journals','posting_events','review_postings','approved_post_requests'):
            service.db.execute(f"CREATE TRIGGER fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'write fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            for name in ('expense_accrual_effects','journals','posting_events','review_postings','approved_post_requests'):
                self.assertEqual(service.db.execute('SELECT count(*) FROM '+name).fetchone(),(0,))
            service.db.execute('DROP TRIGGER fault')
        self.post(service,draft)

    def test_activation_and_preparation_are_atomic_audited_and_idempotent(self):
        from dataclasses import asdict
        service=self.service();self.facts();context=self.ledger._context
        self.assertIsNone(self.ledger.expense_accrual_account_activation())
        for table in ('accounts','expense_accrual_preparations','review_requests'):
            service.db.execute(f"CREATE TRIGGER fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'write fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):self.propose(service)
            self.assertIsNone(self.ledger.expense_accrual_account_activation())
            self.assertEqual(service.db.execute('SELECT count(*) FROM operation_claims').fetchone(),(0,))
            service.db.execute('DROP TRIGGER fault')
        self.propose(service);activation=self.ledger.expense_accrual_account_activation()
        self.assertEqual(activation.actor_id,'template')
        self.assertEqual(json.loads(activation.canonical_metadata),dict(code='2050',name='Accrued Expenses',classification='liability',normal_side='credit',active=True,temporary=False))
        self.assertEqual(self.ledger._context,context)
        self.propose(service);self.assertEqual(self.ledger.expense_accrual_account_activation(),activation)
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_service_migration_failure_restores_ledger4_review9_and_old_audit_bytes(self):
        from accounting_harness.expense_accrual import ExpenseAccrualService,protect_table
        from accounting_harness.approval import ReviewApplication
        db=self.ledger._connection
        self.ledger.ensure_bank_fee_account(actor_id='fee-human')
        draft=self.store.save('old',self.proposal,evidence=self.evidence,expected_revision=0,actor_id='old',idempotency_key='old',reason='old')
        app=ReviewApplication(self.store)
        approval=app.approve('old',revision=1,confirmed_digest=draft.content_digest,actor_id='old',idempotency_key='old')
        receipt=app.post(approval.approval_id,actor_id='old',idempotency_key='old')
        with self.ledger._transaction(write=True):
            self.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1','bank-fee-v1','prepaid-consumption-v1'")
            db.execute('DROP TRIGGER review_schema_no_update');db.execute('UPDATE review_schema SET version=9')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before={t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in tables}
        schema=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()
        def fail(db,table,conflict):
            if table=='expense_accrual_preparations':raise sqlite3.OperationalError('initialization fault')
            return protect_table(db,table,conflict)
        with patch('accounting_harness.expense_accrual.protect_table',side_effect=fail),self.assertRaises(sqlite3.OperationalError):ExpenseAccrualService(self.ledger,self.registry)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone(),(4,))
        self.assertEqual(db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall(),schema)
        self.assertEqual({t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in tables},before)
        self.service()
        self.assertEqual(db.execute('PRAGMA user_version').fetchone(),(5,))
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchone(),(10,))
        for t in tables:
            if t!='review_schema':self.assertEqual(db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall(),before[t])
        self.assertEqual(app.post(approval.approval_id,actor_id='old',idempotency_key='old'),receipt)

    def test_immutable_effect_context_and_schema_and_deferred_posting_link(self):
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        from accounting_harness.expense_accrual import prepare_expense_accrual_post
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):prepare_expense_accrual_post(service.store,approval,draft,self.ledger._validate_entry(json.loads(draft.proposal_json)))
        self.post(service,draft)
        for table in ('expense_accrual_schema','expense_accrual_preparations','expense_accrual_effects','account_extensions','ledger_context'):
            columns=[r[1] for r in service.db.execute('PRAGMA table_info('+table+')')]
            for sql in ('DELETE FROM '+table,'UPDATE '+table+' SET '+columns[0]+'='+columns[0],
                'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError):service.db.execute(sql)

    def test_old_connection_direct_other_policy_and_reversal_guards(self):
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.review import SQLiteReviewStore
        with SQLiteLedger(self.path,**self.options) as old:
            service=self.service();self.facts();draft=self.propose(service)
            proposal=json.loads(draft.proposal_json)
            for source_ids in (proposal['source_ids'],['rent']):
                with self.assertRaises(sqlite3.IntegrityError):old.admit(dict(proposal,source_ids=source_ids),actor_id='bypass',idempotency_key='bypass')
            generic=SQLiteReviewStore(old,self.registry)
            forged=generic.save('generic',dict(proposal,source_ids=['rent']),evidence=self.evidence,expected_revision=0,actor_id='operator',idempotency_key='generic',reason='test')
            self.assertFalse(forged.reviewable)
            receipt=self.post(service,draft)
            with self.assertRaisesRegex(ValueError,'linked correction'):
                old.reverse(receipt.entry.id,reversal_id='reverse',entity_id=self.catalog.entity_id,effective_date='2026-01-31',reason='test',source_ids=['incurrence'],actor_id='human',idempotency_key='reverse')

    def recognition_draft(self,kind,suffix='',key='other'):
        from accounting_harness.operations import cash_expense_proposal
        from accounting_harness.review import SQLiteReviewStore
        from accounting_harness.payables import PayablesService
        common=dict(self.document,schema_version=2,event_id='software-january',counterparty_id='software-vendor',amount='150.00',document_date='2026-01-28')
        if kind=='cash':
            doc=dict(common,document_id='cash'+suffix,kind='cash_movement',direction='out',purpose='incurred_expense')
        else:doc=dict(common,document_id='bill'+suffix,kind='vendor_bill',bill_number='B'+suffix,due_date='2026-01-31')
        self.registry.register(doc,actor_id='operator');self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='operator')
        if kind=='cash':
            store=SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1')
            proposal,evidence=cash_expense_proposal(self.registry,entry_id='cash-journal'+suffix,cash_source_id=doc['document_id'],recognition_source_id='incurrence'+suffix)
            return store,store.save('cash-draft'+suffix,proposal,evidence=evidence,expected_revision=0,actor_id='operator',idempotency_key=key,reason='test')
        service=PayablesService(self.ledger,self.registry)
        return service.store,service.propose_bill(bill_source_id=doc['document_id'],incurrence_source_id='incurrence'+suffix,expected_revision=0,actor_id='operator',idempotency_key=key)

    def test_cash_and_bill_claims_refuse_accrual_even_after_rejection(self):
        for kind in ('cash','bill'):
            # Independent ledger per direction and policy, preserving real shared-claim behavior.
            with self.subTest(kind=kind):
                case=ExpenseAccrualTests();case.setUp()
                try:
                    service=case.service();case.facts();store,draft=case.recognition_draft(kind)
                    store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key='reject',reason='test')
                    case.facts('new')
                    with self.assertRaisesRegex(ValueError,'duplicate economic event'):case.propose(service,'new')
                    self.assertIsNone(case.ledger.expense_accrual_account_activation())
                finally:case.doCleanups()

    def test_accrual_claim_refuses_later_cash_and_bill_after_rejection_or_posting(self):
        for state in ('rejected','posted'):
            case=ExpenseAccrualTests();case.setUp()
            try:
                service=case.service();case.facts();draft=case.propose(service)
                if state=='posted':case.post(service,draft)
                else:service.store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key='reject',reason='test')
                case.facts('new')
                for kind in ('cash','bill'):
                    with self.subTest(state=state,kind=kind),self.assertRaisesRegex(ValueError,'duplicate economic event'):
                        case.recognition_draft(kind,'new',key=kind)
                self.assertEqual(service.db.execute('SELECT count(*) FROM operation_claims').fetchone(),(1,))
            finally:case.doCleanups()

    def test_posted_cash_and_bill_recognition_prevents_accrual(self):
        from accounting_harness.approval import ReviewApplication
        for kind in ('cash','bill'):
            case=ExpenseAccrualTests();case.setUp()
            try:
                service=case.service();case.facts();store,draft=case.recognition_draft(kind)
                app=ReviewApplication(store)
                approval=app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='approved')
                app.post(approval.approval_id,actor_id='human',idempotency_key='posted')
                case.facts('new')
                with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'duplicate economic event'):
                    case.propose(service,'new')
                self.assertEqual(case.ledger.counts()['journals'],1)
                self.assertEqual(service.db.execute('SELECT count(*) FROM expense_accrual_effects').fetchone(),(0,))
            finally:case.doCleanups()

    def test_rejected_accrual_retains_claim_and_resumes_only_same_draft(self):
        service=self.service();self.facts();draft=self.propose(service)
        rejected=service.store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key='reject',reason='Review the evidence')
        self.facts('new')
        revised=self.propose(service,'new',expected=rejected.revision,key='revise')
        self.assertEqual(revised.draft_id,draft.draft_id)
        self.assertEqual(revised.revision,3)
        self.assertTrue(revised.reviewable)
        self.post(service,revised)
        self.assertEqual(service.db.execute('SELECT count(*) FROM operation_claims').fetchone(),(1,))

    def test_frozen_report_cutoff_and_exact_large_server_decimals(self):
        from accounting_harness.expense_accrual import expense_accrual_report
        service=self.service();self.facts(amount='90071992547409.93');draft=self.propose(service)
        frozen=service.snapshot();before=json.dumps(expense_accrual_report(frozen,as_of='2026-01-31'),sort_keys=True)
        self.post(service,draft)
        with patch.object(self.registry,'get',side_effect=AssertionError('pure report')):
            self.assertEqual(json.dumps(expense_accrual_report(frozen,as_of='2026-01-31'),sort_keys=True),before)
        report=expense_accrual_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual(report['principal_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['obligations'][0]['trace_json'])
        self.assertEqual(report['obligations'][0]['vendor_name'],self.document['counterparty'])
        self.assertEqual(expense_accrual_report(service.snapshot(),as_of='2026-01-30')['principal_cents'],0)
        captured=service.snapshot();encoded=json.dumps(expense_accrual_report(captured,as_of='2026-01-31'),sort_keys=True)
        self.facts('other',incurrence={'event_id':'other'},basis={'event_id':'other'})
        other=self.propose(service,'other',key='other')
        approval=service.app.approve(other.draft_id,revision=1,confirmed_digest=other.content_digest,actor_id='human',idempotency_key='other-a')
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='other-p')
        self.assertEqual(json.dumps(expense_accrual_report(captured,as_of='2026-01-31'),sort_keys=True),encoded)

    def test_concurrent_exact_prepare_and_post_retry(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.sources import SQLiteSourceRegistry
        from accounting_harness.expense_accrual import ExpenseAccrualService
        service=self.service();self.facts()
        def prepare(_):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry,SQLiteLedger(self.path,**self.options) as ledger:
                return self.propose(ExpenseAccrualService(ledger,registry))
        with ThreadPoolExecutor(2) as executor:drafts=list(executor.map(prepare,range(2)))
        self.assertEqual(drafts[0],drafts[1]);approval=self.approve(service,drafts[0])
        def post(_):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry,SQLiteLedger(self.path,**self.options) as ledger:
                return ExpenseAccrualService(ledger,registry).app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with ThreadPoolExecutor(2) as executor:receipts=list(executor.map(post,range(2)))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(self.ledger.counts()['journals'],1)

    def test_legacy_workspace_initialization_is_atomic_across_storage_entry_paths(self):
        from pathlib import Path
        from contextlib import closing
        from accounting_harness.workspace import Workspace
        from accounting_harness.expense_accrual import protect_table
        for entrypoint in ('storage','prepare','state','restart','register-source','register-basis'):
            with self.subTest(entrypoint=entrypoint):
                directory=Path(self.temp.name)/entrypoint
                # Reproduce the delivered pre-accrual workspace: ledger4/review9,
                # ordinary receipt approval/history, no accrual service installed.
                with patch('accounting_harness.workspace.ExpenseAccrualService'):
                    workspace=Workspace(directory)
                    with workspace.storage() as (registry,ledger,store,app,_):
                        registry.register(self.document,actor_id='old-importer')
                        ledger.enroll_source(registry,self.document['document_id'],actor_id='old-importer')
                        draft=store.save('legacy-draft',self.proposal,evidence=self.evidence,expected_revision=0,
                            actor_id='legacy-template',idempotency_key='legacy-prepare',reason='Preserve original history')
                        approval=app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,
                            actor_id='legacy-human',idempotency_key='legacy-approve')
                        receipt=app.post(approval.approval_id,actor_id='legacy-human',idempotency_key='legacy-post')
                        with ledger._transaction(write=True):
                            store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1','bank-fee-v1','prepaid-consumption-v1'")
                            store.db.execute('DROP TRIGGER review_schema_no_update')
                            store.db.execute('UPDATE review_schema SET version=9')
                            store.db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
                # Some schema tables have one column, so capture immutable rows canonically.
                def captured():
                    with closing(sqlite3.connect(directory/'ledger.sqlite3')) as db:
                        schema=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()
                        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                        return db.execute('PRAGMA user_version').fetchone(),schema,{t:sorted(db.execute('SELECT * FROM '+t).fetchall()) for t in tables}
                before=captured()
                self.assertEqual(before[0],(4,));self.assertEqual(before[2]['review_schema'],[(9,)])
                self.assertNotIn('expense_accrual_schema',before[2])
                def fail(db,table,conflict):
                    if table=='expense_accrual_preparations':raise sqlite3.OperationalError('injected workspace initialization fault')
                    return protect_table(db,table,conflict)
                with patch('accounting_harness.expense_accrual.protect_table',side_effect=fail):
                    with self.assertRaisesRegex(sqlite3.OperationalError,'injected workspace initialization fault'):
                        if entrypoint=='storage':
                            with workspace.storage():pass
                        elif entrypoint=='prepare':
                            workspace.prepare_expense_accrual(dict(incurrence_source_id='not-yet-registered',basis_source_id='basis',expected_revision=0))
                        elif entrypoint=='state':workspace.state()
                        elif entrypoint=='restart':Workspace(directory)
                        elif entrypoint=='register-basis':
                            workspace.register_operation_source(dict(document=dict(self.document,schema_version=2,
                                document_id='new-basis',kind='expense_accrual_basis',document_date='2026-01-31',
                                event_id='new-accrual',counterparty_id='vendor',cutoff_date='2026-01-31',status='unbilled_unpaid')))
                        else:
                            workspace.register_source(dict(document_id='new-receipt',document_date='2026-01-31',amount='1.00',counterparty='Vendor',description='Synthetic receipt'))
                self.assertEqual(captured(),before)
                # A successful read migrates all schemas together without activating 2050.
                state=workspace.state();self.assertEqual(state['journal_count'],1)
                after=captured();self.assertEqual(after[0],(5,));self.assertEqual(after[2]['review_schema'],[(10,)])
                for table,rows in before[2].items():
                    if table!='review_schema':self.assertEqual(after[2][table],rows,table)
                with workspace.storage() as (_,ledger,store,app,_):
                    self.assertIsNone(ledger.expense_accrual_account_activation())
                    self.assertEqual(store.get('legacy-draft'),draft)
                    self.assertEqual(app.post(approval.approval_id,actor_id='legacy-human',idempotency_key='legacy-post'),receipt)
                common=dict(self.document,schema_version=2,amount='150.00',event_id='new-accrual',counterparty_id='vendor')
                for document in (dict(common,document_id='incurrence',kind='incurred_expense',document_date='2026-01-28',incurred_date='2026-01-28',expense_account='5100'),
                    dict(common,document_id='basis',kind='expense_accrual_basis',document_date='2026-01-31',cutoff_date='2026-01-31',status='unbilled_unpaid')):
                    workspace.register_operation_source(dict(document=document))
                current=workspace.prepare_expense_accrual(dict(incurrence_source_id='incurrence',basis_source_id='basis',expected_revision=0))
                self.assertEqual(workspace.state()['journal_count'],1)
                workspace.action('approve-post',{key:current[key] for key in ('draft_id','revision')}|dict(confirmed_digest=current['content_digest']))
                self.assertEqual(workspace.state()['expense_accruals']['principal_amount'],'150.00')


class ExpenseAccrualHTTPTests(unittest.TestCase):
    from test_web import WorkspaceHTTPTests as _HTTP
    setUp=_HTTP.setUp
    tearDown=_HTTP.tearDown
    start=_HTTP.start
    stop=_HTTP.stop
    request=_HTTP.request

    def test_native_http_prepare_review_exact_values_and_restart(self):
        common=dict(schema_version=2,synthetic=True,entity_id=self.server.workspace.catalog.entity_id,currency='USD',
            event_id='unbilled',counterparty_id='vendor',amount='90071992547409.93',counterparty='Original vendor name',description='Synthetic support')
        expense=dict(common,document_id='incurrence',kind='incurred_expense',document_date='2026-01-28',incurred_date='2026-01-28',expense_account='5100')
        basis=dict(common,document_id='basis',kind='expense_accrual_basis',document_date='2026-01-31',cutoff_date='2026-01-31',status='unbilled_unpaid')
        for document in (expense,basis):self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        with self.server.workspace.storage() as (_,ledger,_,_,_):self.assertIsNone(ledger.expense_accrual_account_activation())
        payload=dict(incurrence_source_id='incurrence',basis_source_id='basis',expected_revision=0)
        self.assertEqual(self.request('POST','/api/expense-accrual-proposals',payload,headers={'X-CSRF-Token':'bad'})[0],403)
        for extra in ({'amount':'1.00'},{'actor_id':'forged'},{'expected_revision':True}):
            self.assertEqual(self.request('POST','/api/expense-accrual-proposals',payload|extra)[0],409)
        status,draft=self.request('POST','/api/expense-accrual-proposals',payload);self.assertEqual(status,200,draft)
        self.assertEqual(self.request('GET','/api/state')[1]['journal_count'],0)
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        status,receipt=self.request('POST','/api/approve-post',confirmation);self.assertEqual(status,200,receipt)
        self.stop();self.start()
        self.assertEqual(self.request('POST','/api/approve-post',confirmation),(200,receipt))
        state=self.request('GET','/api/state')[1];report=state['expense_accruals']
        self.assertEqual(report['principal_amount'],'90071992547409.93')
        self.assertEqual(report['unassigned_control_amount'],'0.00')
        self.assertIn('9007199254740993',report['obligations'][0]['trace_json'])
        for name in ('expense-accrual-facts-form','expense-accrual-proposal-form','expense-accrual-report'):
            self.assertIn(name,self.request('GET','/')[1])
