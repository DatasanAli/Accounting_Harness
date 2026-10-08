"""Supported monthly insurance allocation and immutable purchase dependencies."""
import copy
import json
import sqlite3
import unittest
from importlib.util import find_spec
from unittest.mock import patch
import test_review


class PrepaidTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def service(self):
        self.assertIsNotNone(find_spec('accounting_harness.prepaid'), 'prepaid service required')
        from accounting_harness.prepaid import PrepaidService
        return PrepaidService(self.ledger, self.registry)

    def purchase(self, amount='1200.00', **changes):
        document = dict(self.document, document_id='insurance-purchase', amount=amount, document_date='2026-01-01')
        self.registry.register(document, actor_id='operator')
        self.ledger.enroll_source(self.registry, document['document_id'], actor_id='operator')
        proposal = dict(self.proposal, id='purchase', effective_date='2026-01-01',source_ids=[document['document_id']],
            lines=[dict(account='1200',side='debit',amount=amount),dict(account='1000',side='credit',amount=amount)])
        proposal.update(changes)
        return self.ledger.admit(proposal, actor_id='operator', idempotency_key='purchase')

    def coverage(self, **changes):
        doc = dict(self.document, schema_version=2, document_id='coverage',kind='prepaid_coverage',
            document_date='2026-01-01',original_journal_id='purchase',original_source_id='insurance-purchase',
            coverage_start='2026-01-01',coverage_end='2026-12-31',allocation_policy='equal-months-cents-v1')
        doc.update(changes)
        self.registry.register(doc,actor_id='operator')
        self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='operator')
        return doc['document_id']

    def propose(self, service, source='coverage', month='2026-01', expected=0, key='prepare'):
        return service.propose(coverage_source_id=source,allocation_month=month,expected_revision=expected,
            actor_id='template',idempotency_key=key)

    def approve(self, service, draft):
        return service.app.approve(draft.draft_id,revision=draft.revision,confirmed_digest=draft.content_digest,
            actor_id='human',idempotency_key='approval'+str(draft.revision))

    def test_reference_consumption_is_separately_approved_and_cash_unchanged(self):
        service=self.service(); self.purchase(); self.coverage()
        draft=self.propose(service); self.assertTrue(draft.reviewable,draft.current_findings)
        approval=self.approve(service,draft)
        self.assertEqual(self.ledger.counts()['journals'],1)
        receipt=service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],
            [('5200','debit',10000),('1200','credit',10000)])
        from accounting_harness.prepaid import prepaid_report
        report=prepaid_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual([report[k] for k in ('principal_cents','consumed_cents','remaining_cents','control_cents','unassigned_control_cents')],
            [120000,10000,110000,110000,0])
        self.assertEqual(sum(l.amount.cents for e in self.ledger.snapshot.entries for l in e.lines if l.account=='1000'),120000)
        self.assertEqual(service.app.post(approval.approval_id,actor_id='human',idempotency_key='post'),receipt)
        self.assertEqual(self.propose(service),draft)

    def test_allocation_full_months_remainders_leap_and_zero(self):
        service=self.service()
        from accounting_harness.prepaid import allocation,coverage_months
        self.assertEqual([allocation(100,'2024-01-01','2024-03-31','2024-'+m)[0] for m in ('01','02','03')],[34,33,33])
        self.assertEqual(allocation(1,'2024-01-01','2024-03-31','2024-02'),(0,'2024-02-29'))
        self.assertEqual(allocation(120000,'2026-01-01','2026-12-31','2026-12'),(10000,'2026-12-31'))
        for start,end in [('2026-01-02','2026-12-31'),('2026-01-01','2026-12-30'),('2026-02-01','2026-01-31'),('2026-01-01','2036-01-31')]:
            with self.assertRaises(ValueError):coverage_months(start,end)
        for month in ['2025-12','2027-01','2026-1','2026-01-01','2026-13']:
            with self.assertRaises(ValueError):allocation(100,'2026-01-01','2026-12-31',month)
        for cents in [True,1.0,0,-1]:
            with self.assertRaises(ValueError):allocation(cents,'2026-01-01','2026-12-31','2026-01')

    def test_zero_has_no_draft_claim_effect_or_journal(self):
        service=self.service();self.purchase('0.01');self.coverage(amount='0.01',coverage_end='2026-03-31')
        result=self.propose(service,month='2026-02')
        self.assertEqual(result['state'],'no_journal_required')
        self.assertEqual(self.ledger.counts()['journals'],1)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_effects').fetchone(),(0,))
        self.assertEqual(service.db.execute('SELECT count(*) FROM draft_revisions').fetchone(),(0,))
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_policies').fetchone(),(1,))
        self.coverage(document_id='zero-redefinition',amount='0.01',coverage_end='2026-06-30')
        with self.assertRaisesRegex(ValueError,'different coverage'):
            self.propose(service,source='zero-redefinition',month='2026-02',key='second')

    def test_missing_and_wrong_original_fail_without_anchor(self):
        service=self.service();self.coverage()
        with self.assertRaises((KeyError,ValueError)):self.propose(service)
        self.purchase(lines=[dict(account='5000',side='debit',amount='1200.00'),dict(account='1000',side='credit',amount='1200.00')])
        with self.assertRaisesRegex(ValueError,'exactly'):self.propose(service)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_policies').fetchone(),(0,))

    def test_original_evidence_amount_and_effective_date_are_required(self):
        service=self.service();self.purchase(effective_date='2026-01-02');self.coverage()
        with self.assertRaisesRegex(ValueError,'on or before'):self.propose(service)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_policies').fetchone(),(0,))

    def test_coverage_strict_source_fields_policy_and_partial_months(self):
        self.service();self.purchase()
        for changes in [dict(allocation_policy='guess'),dict(coverage_start='2026-01-02'),dict(extra='instructions'),dict(original_journal_id=3)]:
            with self.subTest(changes=changes),self.assertRaises((ValueError,TypeError)):self.coverage(**changes)

    def test_changed_principal_and_unretained_original_evidence_fail(self):
        service=self.service();self.purchase();self.coverage(amount='1300.00')
        with self.assertRaisesRegex(ValueError,'original evidence'):self.propose(service)
        self.registry.register(dict(self.document,document_id='unretained'),actor_id='operator')
        self.ledger.enroll_source(self.registry,'unretained',actor_id='operator')
        self.coverage(document_id='other',original_source_id='unretained')
        with self.assertRaisesRegex(ValueError,'retain'):self.propose(service,source='other')

    def test_month_outside_ledger_is_invalid_and_does_not_anchor(self):
        service=self.service();self.purchase();self.coverage()
        draft=self.propose(service,month='2026-02')
        self.assertFalse(draft.reviewable)
        with self.assertRaises(ValueError):self.approve(service,draft)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_policies').fetchone(),(0,))

    def test_first_valid_policy_rejection_and_month_claim_survive(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service)
        rejected=service.store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key='reject',reason='Recheck')
        self.coverage(document_id='relabelled')
        with self.assertRaisesRegex(ValueError,'different coverage'):self.propose(service,source='relabelled',key='duplicate')
        changed=copy.deepcopy(json.loads(draft.proposal_json));changed['id']='different'
        forged=service.store.save('different-draft',changed,evidence=json.loads(draft.evidence_json),
            operation_intent=json.loads(draft.operation_intent_json),expected_revision=0,actor_id='evil',idempotency_key='forged',reason='duplicate')
        self.assertFalse(forged.reviewable)
        revision=self.propose(service,expected=rejected.revision,key='correct')
        self.assertTrue(revision.reviewable)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_claims').fetchone(),(1,))
        service.app.post(self.approve(service,revision).approval_id,actor_id='human',idempotency_key='post')

    def reverse(self, journal='purchase', ledger=None):
        return (ledger or self.ledger).reverse(journal,reversal_id='reverse-'+journal,entity_id=self.catalog.entity_id,
            effective_date='2026-01-31',reason='Synthetic correction',source_ids=['insurance-purchase'],actor_id='human',idempotency_key='reverse-'+journal)

    def test_intervening_purchase_reversal_invalidates_approval(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service)
        approval=self.approve(service,draft);self.reverse()
        before=self.ledger.snapshot
        with self.assertRaisesRegex(ValueError,'stale'):service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        self.assertEqual(self.ledger.snapshot,before)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_effects').fetchone(),(0,))

    def test_dependency_refusal_old_connection_and_direct_reversal_link(self):
        from accounting_harness.persistence import SQLiteLedger
        with SQLiteLedger(self.path,**self.options) as old:
            service=self.service();self.purchase();self.coverage();draft=self.propose(service)
            receipt=service.app.post(self.approve(service,draft).approval_id,actor_id='human',idempotency_key='post')
            for journal in ('purchase',receipt.entry.id):
                with self.assertRaisesRegex(ValueError,'prepaid dependency'):self.reverse(journal,old)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'prepaid dependency'):
                service.db.execute('INSERT INTO reversals VALUES(?,?,?,?,?,?)',('purchase',receipt.entry.id,self.catalog.entity_id,'reverse-v1','forged','a'*64))

    def test_forged_intent_shape_boolean_and_float_are_not_reviewable(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service)
        for n,value in enumerate([True,10000.0,10001]):
            intent=json.loads(draft.operation_intent_json);intent['allocated_cents']=value
            forged=service.store.save(draft.draft_id,json.loads(draft.proposal_json),evidence=json.loads(draft.evidence_json),
                operation_intent=intent,expected_revision=n+1,actor_id='evil',idempotency_key='forged'+str(n),reason='test')
            self.assertFalse(forged.reviewable)
        proposal=json.loads(draft.proposal_json);proposal['lines'][0]['account']='5000'
        forged=service.store.save(draft.draft_id,proposal,evidence=json.loads(draft.evidence_json),operation_intent=json.loads(draft.operation_intent_json),
            expected_revision=4,actor_id='evil',idempotency_key='shape',reason='test')
        self.assertFalse(forged.reviewable)
        with self.assertRaises(ValueError):self.approve(service,forged)

    def test_write_failure_rolls_back_all_effect_journal_and_retry(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service);approval=self.approve(service,draft)
        before=self.ledger.snapshot
        service.db.execute("CREATE TRIGGER fault BEFORE INSERT ON review_postings BEGIN SELECT RAISE(ABORT,'write fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        self.assertEqual(self.ledger.snapshot,before)
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_effects').fetchone(),(0,))
        service.db.execute('DROP TRIGGER fault')
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')

    def test_final_seal_revalidates_revision_and_actual_shape(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service);approval=self.approve(service,draft)
        original=self.ledger._store_entry
        def supersede(entry,actor):
            service.db.execute('''INSERT INTO draft_revisions SELECT draft_id,2,proposal_json,evidence_json,policy_version,
                content_digest,state,reason,actor_id,recorded_at,findings_json FROM draft_revisions WHERE draft_id=?''',(draft.draft_id,))
            return original(entry,actor)
        with patch.object(self.ledger,'_store_entry',side_effect=supersede),self.assertRaises(sqlite3.IntegrityError):
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        from dataclasses import replace
        def forge(entry,actor):
            return original(replace(entry,lines=(replace(entry.lines[0],account='5000'),entry.lines[1])),actor)
        with patch.object(self.ledger,'_store_entry',side_effect=forge),self.assertRaises(sqlite3.IntegrityError):
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        self.assertEqual(service.db.execute('SELECT count(*) FROM prepaid_effects').fetchone(),(0,))
        self.assertEqual(service.store.get(draft.draft_id).revision,1)

    def test_direct_coverage_citation_requires_effect_and_unrelated_residual_is_honest(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service)
        from accounting_harness.prepaid import prepaid_report
        frozen=service.snapshot();before=prepaid_report(frozen,as_of='2026-01-31')
        proposal=json.loads(draft.proposal_json)
        with self.assertRaises(sqlite3.IntegrityError):self.ledger.admit(proposal,actor_id='bypass',idempotency_key='bypass')
        proposal['id']='unrelated';proposal['source_ids']=['rent']
        self.ledger.admit(proposal,actor_id='operator',idempotency_key='unrelated')
        report=prepaid_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual((report['remaining_cents'],report['control_cents'],report['unassigned_control_cents']),(120000,110000,-10000))
        service.app.post(self.approve(service,draft).approval_id,actor_id='human',idempotency_key='post')
        report=prepaid_report(service.snapshot(),as_of='2026-01-31')
        self.assertEqual((report['remaining_cents'],report['control_cents'],report['unassigned_control_cents']),(110000,100000,-10000))
        with patch.object(self.registry,'get',side_effect=AssertionError('pure capture')):
            self.assertEqual(prepaid_report(frozen,as_of='2026-01-31'),before)
        self.assertNotEqual(before['snapshot_digest'],report['snapshot_digest'])
        self.assertEqual(prepaid_report(service.snapshot(),as_of='2026-01-30')['consumed_cents'],0)

    def test_records_immutable_and_effect_without_journal_cannot_commit(self):
        service=self.service();self.purchase();self.coverage();draft=self.propose(service);approval=self.approve(service,draft)
        intent=json.loads(draft.operation_intent_json)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):
                service.db.execute('INSERT INTO prepaid_effects VALUES(?,?,?,?,?,?)',('purchase','2026-01',10000,'2026-01-31',approval.approval_id,json.loads(draft.proposal_json)['id']))
        for table in ('prepaid_policies','prepaid_claims','prepaid_schema'):
            with self.assertRaises(sqlite3.IntegrityError):service.db.execute('DELETE FROM '+table)
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with self.assertRaises(sqlite3.IntegrityError):service.db.execute('UPDATE prepaid_effects SET allocated_cents=1')

    def test_enrollment_activates_typed_citation_guard(self):
        self.purchase();self.coverage()
        proposal=dict(self.proposal,id='bypass',source_ids=['coverage'])
        with self.assertRaises(sqlite3.IntegrityError):self.ledger.admit(proposal,actor_id='bypass',idempotency_key='bypass')

    def test_workspace_preparation_exact_strings_and_restart(self):
        from accounting_harness.workspace import Workspace
        workspace=Workspace(self.temp.name+'/workspace')
        with workspace.storage() as (registry,ledger,_,_,_):
            document=dict(self.document,document_id='insurance-purchase',document_date='2026-01-01')
            registry.register(document,actor_id='operator');ledger.enroll_source(registry,document['document_id'],actor_id='operator')
            ledger.admit(dict(self.proposal,id='purchase',effective_date='2026-01-01',source_ids=[document['document_id']],
                lines=[dict(account='1200',side='debit',amount='1200.00'),dict(account='1000',side='credit',amount='1200.00')]),actor_id='operator',idempotency_key='purchase')
        coverage=dict(self.document,schema_version=2,document_id='coverage',kind='prepaid_coverage',document_date='2026-01-01',
            original_journal_id='purchase',original_source_id='insurance-purchase',coverage_start='2026-01-01',coverage_end='2026-12-31',allocation_policy='equal-months-cents-v1')
        workspace.action('operation-sources',dict(document=coverage))
        request=dict(coverage_source_id='coverage',allocation_month='2026-01',expected_revision=0)
        draft=workspace.action('prepaid-proposals',request)
        self.assertEqual(workspace.state()['journal_count'],1)
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        result=workspace.action('approve-post',confirmation)
        workspace=Workspace(self.temp.name+'/workspace')
        self.assertEqual(workspace.action('prepaid-proposals',request),draft)
        self.assertEqual(workspace.action('approve-post',confirmation),result)
        report=workspace.state()['prepaid']
        self.assertEqual(report['remaining_amount'],'1100.00')
        self.assertIn('120000',report['policies'][0]['trace_json'])

    def test_concurrent_exact_preparation_and_post_retries(self):
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.sources import SQLiteSourceRegistry
        from accounting_harness.prepaid import PrepaidService
        service=self.service();self.purchase();self.coverage()
        def prepare(_):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry,SQLiteLedger(self.path,**self.options) as ledger:
                return self.propose(PrepaidService(ledger,registry))
        with ThreadPoolExecutor(max_workers=2) as executor: drafts=list(executor.map(prepare,range(2)))
        self.assertEqual(drafts[0],drafts[1])
        approval=self.approve(service,drafts[0])
        def post(_):
            with SQLiteSourceRegistry(self.source_path,self.catalog.entity_id) as registry,SQLiteLedger(self.path,**self.options) as ledger:
                return PrepaidService(ledger,registry).app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with ThreadPoolExecutor(max_workers=2) as executor: receipts=list(executor.map(post,range(2)))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(self.ledger.counts()['journals'],2)
        with self.assertRaisesRegex(ValueError,'posted drafts'):self.propose(service,key='competing')

    def test_uneven_full_year_exhaustion_and_frozen_prior_month(self):
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.prepaid import prepaid_report
        self.ledger.close();self.ledger=SQLiteLedger(self.path.with_name('year.sqlite3'),**dict(self.options,period_end='2026-12-31'))
        self.addCleanup(self.ledger.close)
        service=self.service();self.purchase('1200.01');self.coverage(amount='1200.01')
        amounts=[]
        for n in range(1,13):
            draft=self.propose(service,month='2026-'+str(n).zfill(2),key='month'+str(n))
            approval=service.app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='a'+str(n))
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='p'+str(n))
            amounts.append(json.loads(draft.operation_intent_json)['allocated_cents'])
            if n==1:
                frozen=service.snapshot();before=prepaid_report(frozen,as_of='2026-01-31')
        self.assertEqual(amounts,[10001]+[10000]*11)
        report=prepaid_report(service.snapshot(),as_of='2026-12-31')
        self.assertEqual((report['remaining_cents'],report['control_cents'],report['unassigned_control_cents']),(0,0,0))
        self.assertEqual(prepaid_report(frozen,as_of='2026-01-31'),before)
        with self.assertRaises(ValueError):self.propose(service,month='2027-01',key='excess')

    def test_atomic_initialization_preserves_historical_approval_and_review_version(self):
        from accounting_harness.approval import ReviewApplication
        from accounting_harness.prepaid import PrepaidService,protect_table
        draft=self.store.save('old',self.proposal,evidence=self.evidence,expected_revision=0,actor_id='old',idempotency_key='old',reason='old')
        app=ReviewApplication(self.store)
        approval=app.approve('old',revision=1,confirmed_digest=draft.content_digest,actor_id='old',idempotency_key='old')
        receipt=app.post(approval.approval_id,actor_id='old',idempotency_key='old')
        db=self.ledger._connection
        with self.ledger._transaction(write=True):
            self.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1','bank-fee-v1'")
            db.execute('DROP TRIGGER review_schema_no_update');db.execute('UPDATE review_schema SET version=8')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='review_schema'")]
        before={name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names}
        seal=db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()
        def fail(db,table,conflict):
            if table=='prepaid_claims':raise sqlite3.OperationalError('injected initialization fault')
            return protect_table(db,table,conflict)
        with patch('accounting_harness.prepaid.protect_table',side_effect=fail),self.assertRaises(sqlite3.OperationalError):PrepaidService(self.ledger,self.registry)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(8,)])
        self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone(),seal)
        self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='prepaid_schema'").fetchone())
        service=self.service()
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(11,)])
        self.assertEqual({name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names},before)
        self.assertEqual(app.post(approval.approval_id,actor_id='old',idempotency_key='old'),receipt)

    def test_preparation_failure_does_not_fix_coverage_or_claim(self):
        service=self.service();self.purchase();self.coverage()
        service.db.execute("CREATE TRIGGER fault BEFORE INSERT ON review_events BEGIN SELECT RAISE(ABORT,'prepare fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.propose(service)
        for table in ('prepaid_claims','prepaid_policies','draft_revisions','review_requests'):
            self.assertEqual(service.db.execute('SELECT count(*) FROM '+table).fetchone(),(0,))
        service.db.execute('DROP TRIGGER fault')
        self.coverage(document_id='replacement',coverage_end='2026-06-30')
        self.assertTrue(self.propose(service,source='replacement').reviewable)


class PrepaidHTTPTests(unittest.TestCase):
    from test_web import WorkspaceHTTPTests as _HTTP
    setUp=_HTTP.setUp
    tearDown=_HTTP.tearDown
    start=_HTTP.start
    stop=_HTTP.stop
    request=_HTTP.request

    def test_native_http_exact_large_amounts_and_denied_extra_inputs(self):
        workspace=self.server.workspace
        amount='90071992547409.93'
        document=dict(schema_version=1,synthetic=True,entity_id=workspace.catalog.entity_id,document_id='purchase-source',
            kind='receipt',document_date='2026-01-01',amount=amount,currency='USD',counterparty='Synthetic insurer',description='Original purchase')
        with workspace.storage() as (registry,ledger,_,_,_):
            registry.register(document,actor_id='fixture');ledger.enroll_source(registry,'purchase-source',actor_id='fixture')
            ledger.admit(dict(id='purchase',entity_id=workspace.catalog.entity_id,currency='USD',effective_date='2026-01-01',
                description='Purchase',source_ids=['purchase-source'],lines=[dict(account='1200',side='debit',amount=amount),dict(account='1000',side='credit',amount=amount)]),actor_id='fixture',idempotency_key='purchase')
        coverage=dict(document,schema_version=2,kind='prepaid_coverage',document_id='coverage',original_journal_id='purchase',
            original_source_id='purchase-source',coverage_start='2026-01-01',coverage_end='2026-12-31',allocation_policy='equal-months-cents-v1')
        self.assertEqual(self.request('POST','/api/operation-sources',dict(document=coverage))[0],200)
        payload=dict(coverage_source_id='coverage',allocation_month='2026-01',expected_revision=0)
        self.assertEqual(self.request('POST','/api/prepaid-proposals',payload,headers={'X-CSRF-Token':'bad'})[0],403)
        for change in [dict(amount='1.00'),dict(actor_id='forged'),dict(expected_revision=True)]:
            self.assertEqual(self.request('POST','/api/prepaid-proposals',payload|change)[0],409)
        status,draft=self.request('POST','/api/prepaid-proposals',payload);self.assertEqual(status,200,draft)
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],1)
        self.assertEqual(state['prepaid']['principal_amount'],amount)
        self.assertIn('9007199254740993',state['prepaid']['policies'][0]['trace_json'])
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        status,receipt=self.request('POST','/api/approve-post',confirmation);self.assertEqual(status,200,receipt)
        self.stop();self.start()
        self.assertEqual(self.request('POST','/api/approve-post',confirmation),(200,receipt))
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['prepaid']['consumed_amount'],'7505999378950.83')
        self.assertEqual(state['prepaid']['remaining_amount'],'82565993168459.10')
        page=self.request('GET','/')[1]
        for name in ('prepaid-coverage-form','prepaid-proposal-form','prepaid-report'):
            self.assertIn(name,page)
