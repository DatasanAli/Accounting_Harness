"""Unbilled service revenue, exact authorization and frozen accrued assets."""
import copy
import json
import sqlite3
import unittest
from importlib.util import find_spec
from unittest.mock import patch
import test_review


class RevenueAccrualTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def service(self):
        self.assertIsNotNone(find_spec('accounting_harness.revenue_accrual'), 'revenue accrual service required')
        from accounting_harness.revenue_accrual import RevenueAccrualService
        return RevenueAccrualService(self.ledger, self.registry)

    def facts(self, suffix='', amount='250.00', completion=None, basis=None, enroll=True):
        common=dict(self.document,schema_version=2,event_id='service-january',counterparty_id='service-customer',amount=amount)
        expense=dict(common,document_id='completion'+suffix,kind='service_completion',document_date='2026-01-28',completion_date='2026-01-28')
        support=dict(common,document_id='basis'+suffix,kind='revenue_accrual_basis',document_date='2026-01-31',cutoff_date='2026-01-31',status='unbilled_uncollected')
        expense.update(completion or {});support.update(basis or {})
        for doc in (expense,support):
            self.registry.register(doc,actor_id='operator')
            if enroll:self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='operator')
        return expense,support

    def propose(self, service, suffix='', expected=0, key='prepare'):
        return service.propose(completion_source_id='completion'+suffix,basis_source_id='basis'+suffix,
            expected_revision=expected,actor_id='template',idempotency_key=key)

    def approve(self, service, draft):
        return service.app.approve(draft.draft_id,revision=draft.revision,confirmed_digest=draft.content_digest,
            actor_id='human',idempotency_key='approval'+str(draft.revision))

    def post(self,service,draft):
        return service.app.post(self.approve(service,draft).approval_id,actor_id='human',idempotency_key='post')

    def test_supported_250_requires_human_confirmation_and_has_zero_residual(self):
        service=self.service();self.facts();draft=self.propose(service)
        self.assertTrue(draft.reviewable,draft.current_findings)
        self.assertEqual(self.ledger.counts()['journals'],0)
        receipt=self.post(service,draft)
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],[('1150','debit',25000),('4000','credit',25000)])
        from accounting_harness.revenue_accrual import revenue_accrual_report
        report=revenue_accrual_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual([report[k] for k in ('principal_cents','control_cents','unassigned_control_cents')],[25000,25000,0])
        self.assertEqual(report['assets'][0]['completion_source_id'],'completion')
        self.assertEqual(self.propose(service),draft)
        self.assertEqual(self.post(service,draft),receipt)
        self.assertEqual(service.db.execute('SELECT count(*) FROM revenue_accrual_effects').fetchone(),(1,))

    def test_conflicting_facts_dates_status_roles_and_accounts_are_refused(self):
        service=self.service()
        changes=[({},dict(counterparty_id='other')),({},dict(event_id='other')),({},dict(amount='249.99')),
            ({},dict(cutoff_date='2026-01-30')),({},dict(document_date='2026-01-30')),
            (dict(completion_date='2026-02-01',document_date='2026-02-01'),{}),
            (dict(completion_date='2026-01-27'),{}),({},dict(status='paid')),
            (dict(expense_account='5300'),{}),(dict(expense_account='2000'),{}),
            ({},dict(status=True)),(dict(document_date='2025-12-31',completion_date='2025-12-31'),{}),
            (dict(currency='EUR'),{}),({},dict(extra='unsupported')),(dict(kind='receipt',schema_version=1),{}),
            (dict(amount='0.00'),{}),({},dict(event_id=True)),({},dict(counterparty_id=''))]
        for index,(completion,basis) in enumerate(changes):
            with self.subTest(index=index),self.assertRaises((ValueError,TypeError)):
                self.facts(str(index),completion=completion,basis=basis)
                self.propose(service,str(index),key='bad'+str(index))
        self.facts()
        with self.assertRaises(ValueError):service.propose(completion_source_id='completion',basis_source_id='completion',expected_revision=0,actor_id='template',idempotency_key='roles')
        self.assertEqual(self.ledger.counts()['journals'],0)
        self.assertIsNone(self.ledger.revenue_accrual_account_activation())

    def test_missing_anchor_and_missing_source_are_refused(self):
        service=self.service();self.facts(enroll=False)
        with self.assertRaisesRegex(ValueError,'anchored'):self.propose(service)
        with self.assertRaises(KeyError):self.propose(service,'absent')
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_forged_intents_and_lines_never_become_reviewable(self):
        service=self.service();self.facts();draft=self.propose(service)
        intent=json.loads(draft.operation_intent_json);proposal=json.loads(draft.proposal_json)
        attempts=[]
        for field,value in [('principal_cents',True),('principal_cents',25000.0),('principal_cents',24999),('customer_id','forged'),('schema_version',True),('extra','unsupported'),('currency','EUR'),
                ('kind','customer_invoice'),('effective_date','2026-01-30'),('revenue_account','1100'),
                ('evidence_roles',{'completion':'basis','basis':'completion'})]:
            attempts.append((proposal,intent|{field:value}))
        for account in ('1000','2000','1100','2100','1200'):
            forged=copy.deepcopy(proposal);forged['lines'][1]['account']=account;attempts.append((forged,intent))
        for n,(journal,op) in enumerate(attempts):
            forged=service.store.save(draft.draft_id,journal,evidence=json.loads(draft.evidence_json),operation_intent=op,
                expected_revision=n+1,actor_id='forger',idempotency_key='forged'+str(n),reason='test')
            self.assertFalse(forged.reviewable)
            with self.assertRaises(ValueError):self.approve(service,forged)
        self.assertEqual(service.db.execute('SELECT count(*) FROM revenue_accrual_preparations').fetchone(),(1,))

    def test_revised_evidence_keeps_event_identity_and_requires_fresh_approval(self):
        service=self.service();self.facts();draft=self.propose(service);old=self.approve(service,draft)
        self.facts('revised',amount='251.00')
        revised=self.propose(service,'revised',expected=1,key='revision')
        self.assertEqual(revised.draft_id,draft.draft_id)
        with self.assertRaisesRegex(ValueError,'stale'):service.app.post(old.approval_id,actor_id='human',idempotency_key='stale')
        receipt=self.post(service,revised)
        self.assertEqual(receipt.entry.lines[0].amount.cents,25100)
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
            self.assertEqual(service.db.execute('SELECT count(*) FROM revenue_accrual_effects').fetchone(),(0,))
            self.assertEqual(service.store.get(draft.draft_id).revision,1)
            self.assertEqual(self.ledger.counts()['journals'],0)

    def test_final_seal_rejects_changed_shape_after_effect(self):
        from dataclasses import replace
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        from datetime import date
        from accounting_harness.domain.money import Money
        original=self.ledger._store_entry
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        for changed in (replace(entry,id='other'),replace(entry,effective_date=date(2026,1,30)),replace(entry,source_ids=('rent',)),
                replace(entry,lines=(replace(entry.lines[0],account='1100'),entry.lines[1])),
                replace(entry,lines=tuple(replace(line,amount=Money(100)) for line in entry.lines))):
            with patch.object(self.ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)),self.assertRaises(sqlite3.IntegrityError):
                service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        self.assertEqual(self.ledger.counts()['journals'],0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM revenue_accrual_effects').fetchone(),(0,))

    def test_write_faults_rollback_effect_journal_posting_and_retry(self):
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        for table in ('revenue_accrual_effects','journals','posting_events','review_postings','approved_post_requests'):
            service.db.execute(f"CREATE TRIGGER fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'write fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            for name in ('revenue_accrual_effects','journals','posting_events','review_postings','approved_post_requests'):
                self.assertEqual(service.db.execute('SELECT count(*) FROM '+name).fetchone(),(0,))
            service.db.execute('DROP TRIGGER fault')
        self.post(service,draft)

    def test_activation_and_preparation_are_atomic_audited_and_idempotent(self):
        from dataclasses import asdict
        service=self.service();self.facts();context=self.ledger._context
        self.assertIsNone(self.ledger.revenue_accrual_account_activation())
        for table in ('accounts','revenue_accrual_preparations','review_requests'):
            service.db.execute(f"CREATE TRIGGER fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'write fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):self.propose(service)
            self.assertIsNone(self.ledger.revenue_accrual_account_activation())
            self.assertEqual(service.db.execute('SELECT count(*) FROM operation_claims').fetchone(),(0,))
            service.db.execute('DROP TRIGGER fault')
        self.propose(service);activation=self.ledger.revenue_accrual_account_activation()
        self.assertEqual(activation.actor_id,'template')
        self.assertEqual(json.loads(activation.canonical_metadata),dict(code='1150',name='Accrued Service Revenue',classification='asset',normal_side='debit',active=True,temporary=False))
        self.assertEqual(self.ledger._context,context)
        self.propose(service);self.assertEqual(self.ledger.revenue_accrual_account_activation(),activation)
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_immutable_effect_context_and_schema_and_deferred_posting_link(self):
        service=self.service();self.facts();draft=self.propose(service);approval=self.approve(service,draft)
        from accounting_harness.revenue_accrual import prepare_revenue_accrual_post
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):prepare_revenue_accrual_post(service.store,approval,draft,self.ledger._validate_entry(json.loads(draft.proposal_json)))
        self.post(service,draft)
        for table in ('revenue_accrual_schema','revenue_accrual_preparations','revenue_accrual_effects','account_extensions','ledger_context'):
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
                old.reverse(receipt.entry.id,reversal_id='reverse',entity_id=self.catalog.entity_id,effective_date='2026-01-31',reason='test',source_ids=['completion'],actor_id='human',idempotency_key='reverse')

    def test_frozen_report_cutoff_and_exact_large_server_decimals(self):
        from accounting_harness.revenue_accrual import revenue_accrual_report
        service=self.service();self.facts(amount='90071992547409.93');draft=self.propose(service)
        frozen=service.snapshot();before=json.dumps(revenue_accrual_report(frozen,as_of='2026-01-31'),sort_keys=True)
        self.post(service,draft)
        with patch.object(self.registry,'get',side_effect=AssertionError('pure report')):
            self.assertEqual(json.dumps(revenue_accrual_report(frozen,as_of='2026-01-31'),sort_keys=True),before)
        report=revenue_accrual_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual(report['principal_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['assets'][0]['trace_json'])
        self.assertEqual(report['assets'][0]['customer_name'],self.document['counterparty'])
        self.assertEqual(revenue_accrual_report(service.snapshot(),as_of='2026-01-30')['principal_cents'],0)
        captured=service.snapshot();encoded=json.dumps(revenue_accrual_report(captured,as_of='2026-01-31'),sort_keys=True)
        self.facts('other',completion={'event_id':'other'},basis={'event_id':'other'})
        other=self.propose(service,'other',key='other')
        approval=service.app.approve(other.draft_id,revision=1,confirmed_digest=other.content_digest,actor_id='human',idempotency_key='other-a')
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='other-p')
        self.assertEqual(json.dumps(revenue_accrual_report(captured,as_of='2026-01-31'),sort_keys=True),encoded)

    def test_concurrent_exact_prepare_and_post_retry(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.sources import SQLiteSourceRegistry
        from accounting_harness.revenue_accrual import RevenueAccrualService
        service=self.service();self.facts()
        def prepare(_):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry,SQLiteLedger(self.path,**self.options) as ledger:
                return self.propose(RevenueAccrualService(ledger,registry))
        with ThreadPoolExecutor(2) as executor:drafts=list(executor.map(prepare,range(2)))
        self.assertEqual(drafts[0],drafts[1]);approval=self.approve(service,drafts[0])
        def post(_):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry,SQLiteLedger(self.path,**self.options) as ledger:
                return RevenueAccrualService(ledger,registry).app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with ThreadPoolExecutor(2) as executor:receipts=list(executor.map(post,range(2)))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(self.ledger.counts()['journals'],1)


    def recognition_draft(self,kind,suffix='',key='other'):
        from accounting_harness.operations import earned_cash_proposal
        from accounting_harness.review import SQLiteReviewStore
        from accounting_harness.receivables import ReceivablesService
        from accounting_harness.advances import AdvancesService
        from accounting_harness.approval import ReviewApplication
        common=dict(self.document,schema_version=2,event_id='service-january',counterparty_id='service-customer',amount='250.00',document_date='2026-01-28')
        if kind=='advance':
            # Receipt belongs to a distinct cash event; only its earning claims completion.
            advance=AdvancesService(self.ledger,self.registry)
            prepayment=dict(common,document_id='prepayment'+suffix,event_id='prepayment'+suffix,kind='customer_prepayment',contract_id='contract')
            cash=dict(common,document_id='prepay-cash'+suffix,event_id='prepayment'+suffix,kind='cash_movement',direction='in',purpose='customer_advance')
            completion=dict(common,document_id='advance-completion'+suffix,kind='advance_completion',completion_date='2026-01-28',contract_id='contract')
            for doc in (prepayment,cash,completion):
                self.registry.register(doc,actor_id='operator');self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='operator')
            draft=advance.propose_advance(prepayment_source_id=prepayment['document_id'],cash_source_id=cash['document_id'],expected_revision=0,actor_id='operator',idempotency_key='advance'+suffix)
            approval=advance.app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='advance'+suffix)
            advance.app.post(approval.approval_id,actor_id='human',idempotency_key='advance'+suffix)
            store=SQLiteReviewStore(self.ledger,self.registry,policy_version='advance-earning-v1')
            return store,advance.propose_earning(advance_id=json.loads(draft.operation_intent_json)['advance_id'],completion_source_id=completion['document_id'],expected_revision=0,actor_id='operator',idempotency_key=key)
        doc=(dict(common,document_id='cash'+suffix,kind='cash_movement',direction='in',purpose='earned_service') if kind=='cash' else
             dict(common,document_id='invoice'+suffix,kind='customer_invoice',invoice_number='I'+suffix,due_date='2026-01-31'))
        self.registry.register(doc,actor_id='operator');self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='operator')
        if kind=='cash':
            store=SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1')
            proposal,evidence=earned_cash_proposal(self.registry,entry_id='cash-journal'+suffix,cash_source_id=doc['document_id'],recognition_source_id='completion'+suffix)
            return store,store.save('cash-draft'+suffix,proposal,evidence=evidence,expected_revision=0,actor_id='operator',idempotency_key=key,reason='test')
        service=ReceivablesService(self.ledger,self.registry)
        return service.store,service.propose_invoice(invoice_source_id=doc['document_id'],completion_source_id='completion'+suffix,expected_revision=0,actor_id='operator',idempotency_key=key)

    def test_cash_invoice_and_advance_shared_claim_collisions_both_directions(self):
        from accounting_harness.approval import ReviewApplication
        for first in ('cash','invoice','advance','accrual'):
            for state in ('rejected','posted'):
                others=('cash','invoice','advance') if first=='accrual' else ('accrual',)
                for second in others:
                    with self.subTest(first=first,state=state,second=second):
                        case=RevenueAccrualTests();case.setUp()
                        try:
                            service=case.service();case.facts()
                            if first=='accrual':store,draft=service.store,case.propose(service)
                            else:store,draft=case.recognition_draft(first)
                            if state=='rejected':store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key='reject',reason='test')
                            else:
                                app=ReviewApplication(store)
                                approval=app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='first')
                                app.post(approval.approval_id,actor_id='human',idempotency_key='first')
                            case.facts('new')
                            with self.assertRaisesRegex(ValueError,'duplicate economic event'):
                                if second=='accrual':case.propose(service,'new')
                                else:case.recognition_draft(second,'new')
                            if second=='accrual':self.assertIsNone(case.ledger.revenue_accrual_account_activation())
                        finally:case.doCleanups()

    def test_combined_v2_reports_separate_controls_and_preserve_old_captures(self):
        from accounting_harness.expense_accrual import expense_accrual_report, ExpenseAccrualSnapshot
        from accounting_harness.revenue_accrual import accrual_report
        import test_expense_accrual
        old=test_expense_accrual.ExpenseAccrualTests()
        old.ledger,old.registry,old.document=self.ledger,self.registry,self.document
        expenses=old.service();old.facts();old.post(expenses,old.propose(expenses))
        # Literal legacy capture shape is independent of the new combined snapshot type.
        legacy=ExpenseAccrualSnapshot(self.ledger.snapshot,tuple(expenses.db.execute('SELECT * FROM expense_accrual_effects')),
            tuple(expenses.db.execute("SELECT source_id,canonical_content,content_digest FROM source_enrollments WHERE source_id IN ('incurrence','basis') ORDER BY source_id")),self.ledger._context)
        before=json.dumps(expense_accrual_report(legacy,as_of='2026-01-31'),sort_keys=True)
        service=self.service();empty=service.combined_snapshot()
        report=accrual_report(empty,as_of='2026-01-31')
        self.assertEqual((report['schema_version'],report['report_policy']),(2,'outstanding-accruals-v2'))
        self.assertEqual(report['expenses']['principal_amount'],'150.00');self.assertEqual(report['revenue']['assets'],[])
        frozen=json.dumps(report,sort_keys=True)
        self.facts('revenue');draft=self.propose(service,'revenue',key='revenue')
        approval=service.app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='revenue-approval')
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='revenue-post')
        current=accrual_report(service.combined_snapshot(),as_of='2026-01-31')
        self.assertEqual([current[category][field] for category in ('expenses','revenue') for field in ('principal_amount','control_amount','unassigned_control_amount')],
            ['150.00','150.00','0.00','250.00','250.00','0.00'])
        self.assertEqual(json.dumps(accrual_report(empty,as_of='2026-01-31'),sort_keys=True),frozen)
        self.assertEqual(json.dumps(expense_accrual_report(legacy,as_of='2026-01-31'),sort_keys=True),before)
        self.assertEqual(accrual_report(service.combined_snapshot(),as_of='2026-01-30')['revenue']['control_cents'],0)
        self.assertEqual({l.account for e in self.ledger.snapshot.entries for l in e.lines},{'5100','2050','1150','4000'})

    def test_20b_workspace_migration_faults_restore_all_schema_rows_and_exact_retries(self):
        from contextlib import closing
        from pathlib import Path
        from accounting_harness.workspace import Workspace
        from accounting_harness.expense_accrual import ExpenseAccrualService, expense_accrual_report, protect_table
        for entrypoint in ('storage','state','restart','register','prepare'):
            with self.subTest(entrypoint=entrypoint):
                directory=Path(self.temp.name)/entrypoint
                # Construct delivered ledger5/review10/expense1, including its posted history.
                with patch('accounting_harness.workspace.RevenueAccrualService',side_effect=ExpenseAccrualService):
                    workspace=Workspace(directory)
                    with workspace.storage() as (registry,ledger,_,_,_):
                        import test_expense_accrual
                        old=test_expense_accrual.ExpenseAccrualTests();old.ledger,old.registry,old.document=ledger,registry,self.document
                        service=old.service();old.facts();draft=old.propose(service);receipt=old.post(service,draft)
                        frozen=service.snapshot();old_report=json.dumps(expense_accrual_report(frozen,as_of='2026-01-31'),sort_keys=True)
                        with ledger._transaction(write=True):
                            service.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1','bank-fee-v1','prepaid-consumption-v1','expense-accrual-v1'")
                            ledger._connection.execute('DROP TRIGGER review_schema_no_update')
                            ledger._connection.execute('UPDATE review_schema SET version=10')
                            ledger._connection.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'review schema is immutable'); END")
                def capture():
                    with closing(sqlite3.connect(directory/'ledger.sqlite3')) as db:
                        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                        return db.execute('PRAGMA user_version').fetchone(),db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall(),{t:sorted(db.execute('SELECT * FROM '+t).fetchall()) for t in tables}
                before=capture();self.assertEqual(before[0],(5,));self.assertEqual(before[2]['review_schema'],[(10,)])
                self.assertNotIn('revenue_accrual_schema',before[2])
                def fail(db,table,conflict):
                    if table=='revenue_accrual_preparations':raise sqlite3.OperationalError('revenue setup fault')
                    return protect_table(db,table,conflict)
                with patch('accounting_harness.expense_accrual.protect_table',side_effect=fail),self.assertRaisesRegex(sqlite3.OperationalError,'revenue setup fault'):
                    if entrypoint=='storage':
                        with workspace.storage():pass
                    elif entrypoint=='state':workspace.state()
                    elif entrypoint=='restart':Workspace(directory)
                    elif entrypoint=='prepare':workspace.prepare_revenue_accrual(dict(completion_source_id='absent',basis_source_id='absent',expected_revision=0))
                    else:workspace.register_operation_source(dict(document=dict(self.document,schema_version=2,document_id='new',kind='revenue_accrual_basis',document_date='2026-01-31',event_id='new',counterparty_id='customer',cutoff_date='2026-01-31',status='unbilled_uncollected')))
                self.assertEqual(capture(),before)
                state=workspace.state();after=capture()
                self.assertEqual(after[0],(6,));self.assertEqual(after[2]['review_schema'],[(11,)])
                for table,rows in before[2].items():
                    if table!='review_schema':self.assertEqual(after[2][table],rows,table)
                with workspace.storage() as (registry,ledger,_,_,_):
                    self.assertIsNone(ledger.revenue_accrual_account_activation())
                    old.ledger,old.registry=ledger,registry;service=old.service()
                    self.assertEqual(old.propose(service),draft)
                    self.assertEqual(old.post(service,draft),receipt)
                    self.assertEqual(json.dumps(expense_accrual_report(service.snapshot(),as_of='2026-01-31'),sort_keys=True),old_report)
                self.assertEqual(state['accruals']['schema_version'],2)
                self.assertEqual(json.dumps(expense_accrual_report(frozen,as_of='2026-01-31'),sort_keys=True),old_report)

    def test_demo_revenue_accrual(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from accounting_harness.revenue_accrual import demo_revenue_accrual
        output=StringIO()
        with redirect_stdout(output):demo_revenue_accrual()
        self.assertIn('1150 control: 250.00; residual: 0.00',output.getvalue())
        self.assertIn('Duplicate invoice recognition refused',output.getvalue())



class RevenueAccrualHTTPTests(unittest.TestCase):
    from test_web import WorkspaceHTTPTests as _HTTP
    setUp=_HTTP.setUp
    tearDown=_HTTP.tearDown
    start=_HTTP.start
    stop=_HTTP.stop
    request=_HTTP.request

    def test_native_http_prepare_review_exact_values_and_restart(self):
        common=dict(schema_version=2,synthetic=True,entity_id=self.server.workspace.catalog.entity_id,currency='USD',
            event_id='unbilled',counterparty_id='vendor',amount='90071992547409.93',counterparty='Original vendor name',description='Synthetic support')
        expense=dict(common,document_id='completion',kind='service_completion',document_date='2026-01-28',completion_date='2026-01-28')
        basis=dict(common,document_id='basis',kind='revenue_accrual_basis',document_date='2026-01-31',cutoff_date='2026-01-31',status='unbilled_uncollected')
        for document in (expense,basis):self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        with self.server.workspace.storage() as (_,ledger,_,_,_):self.assertIsNone(ledger.revenue_accrual_account_activation())
        payload=dict(completion_source_id='completion',basis_source_id='basis',expected_revision=0)
        self.assertEqual(self.request('POST','/api/revenue-accrual-proposals',payload,headers={'X-CSRF-Token':'bad'})[0],403)
        for extra in ({'amount':'1.00'},{'actor_id':'forged'},{'expected_revision':True}):
            self.assertEqual(self.request('POST','/api/revenue-accrual-proposals',payload|extra)[0],409)
        status,draft=self.request('POST','/api/revenue-accrual-proposals',payload);self.assertEqual(status,200,draft)
        self.assertEqual(self.request('GET','/api/state')[1]['journal_count'],0)
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        status,receipt=self.request('POST','/api/approve-post',confirmation);self.assertEqual(status,200,receipt)
        self.stop();self.start()
        self.assertEqual(self.request('POST','/api/approve-post',confirmation),(200,receipt))
        state=self.request('GET','/api/state')[1];report=state['revenue_accruals']
        self.assertEqual(report['principal_amount'],'90071992547409.93')
        self.assertEqual(report['unassigned_control_amount'],'0.00')
        self.assertIn('9007199254740993',report['assets'][0]['trace_json'])
        for name in ('revenue-accrual-facts-form','revenue-accrual-proposal-form','revenue-accrual-report'):
            self.assertIn(name,self.request('GET','/')[1])
