"""Independent direct cash-flow expectations and captured read-only boundaries."""
import dataclasses
import http.client
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from accounting_harness.adjusted_month import build_adjusted_month
from accounting_harness.financial_reports import capture_financials, financial_statements
from accounting_harness.workspace import Workspace
from accounting_harness.web import make_server

ROOT = Path(__file__).resolve().parents[1]


class CashFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.cash_flow'),
                             'captured direct cash flow must be implemented')
        from accounting_harness import cash_flow
        return cash_flow

    def capture(self, cutoff='2026-01-31'):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return self.module().capture_cash_flow(ledger, cutoff)

    def render(self, capture=None):
        return self.module().cash_flow_statement(capture or self.capture())

    def post(self, identity, debit='1000', credit='3000', amount='10.00', day='2026-01-20', lines=None):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return ledger.admit(dict(id=identity, entity_id=self.workspace.catalog.entity_id,
                currency='USD', effective_date=day, description='Do not infer from this text: financing',
                source_ids=[next(iter(self.workspace.sources))], lines=lines or [
                    dict(account=debit, side='debit', amount=amount),
                    dict(account=credit, side='credit', amount=amount)]),
                actor_id='test-human', idempotency_key=identity)

    def check_bridge(self, report):
        total = sum(int(report[k + '_cents']) for k in ('operating','investing','financing','unresolved'))
        self.assertEqual(total, int(report['net_change_cents']))
        self.assertEqual(sum(int(row['cash_cents']) for row in report['rows']), total)
        self.assertEqual(report['residual_amount'], '0.00')
        self.assertTrue(report['reconciled'])
        for row in report['rows']:
            self.assertTrue(row['source_ids']); self.assertTrue(row['actor_id'])
            self.assertTrue(row['cash_lines']); self.assertTrue(row['effective_date'])
            self.assertIsInstance(row['cash_amount'], str)

    def test_reference_receipts_payments_categories_bridge_and_sources(self):
        build_adjusted_month(self.workspace)
        before = self.workspace.state()
        report = self.render()
        self.assertEqual([report[k + '_amount'] for k in ('operating_receipts','operating_payments',
            'operating','investing','financing','opening_cash','net_change','ending_cash','residual')],
            ['2100.00','-2500.00','-400.00','0.00','9800.00','0.00','9400.00','9400.00','0.00'])
        self.assertTrue(report['classification_complete'])
        self.assertEqual(report['exceptions'], [])
        self.assertEqual(sorted(row['cash_amount'] for row in report['rows']),
                         sorted(['10000.00','-1200.00','-1200.00','1500.00','-100.00','600.00','-200.00']))
        ap = next(row for row in report['rows'] if row['counterparts'][0]['account'] == '2000')
        self.assertEqual(ap['category'],'operating')
        self.assertEqual(ap['payable_trace']['bill']['expense_account'],'5100')
        self.assertTrue(ap['payable_trace']['payment_approval']['actor_id'])
        self.assertTrue(ap['payable_trace']['bill_approval']['actor_id'])
        self.check_bridge(report)
        self.assertEqual(self.workspace.state(),before)

    def test_empty_capture_is_versioned_immutable_and_distinct_from_statements(self):
        capture = self.capture(); report = self.render(capture)
        self.assertEqual(report, self.render(self.capture()))
        self.assertEqual(report['rows'],[])
        self.assertEqual(report['capture']['schema_version'],1)
        self.assertEqual(report['capture']['kind'],'direct_cash_flow')
        self.assertTrue(report['classification_complete'])
        with self.assertRaises(dataclasses.FrozenInstanceError): capture.policy = None
        self.check_bridge(report)

    def test_noncash_loss_does_not_create_cash_flow(self):
        self.post('loss','5000','2000','100.00')
        report=self.render()
        self.assertEqual(report['rows'],[])
        self.assertEqual(report['ending_cash_amount'],'0.00')
        self.check_bridge(report)

    def test_supported_equipment_fee_revenue_and_owner_opposite_signs(self):
        with self.workspace.storage() as (_,ledger,_,_,_): ledger.ensure_bank_fee_account(actor_id='test')
        for args in [('equipment','1500','1000','75.00'),('fee','5300','1000','2.00'),
                     ('service','1000','4000','7.00'),('withdraw','3000','1000','12.00'),
                     ('return','1000','3100','3.00')]: self.post(*args)
        report=self.render()
        self.assertEqual([report[k+'_amount'] for k in ('operating','investing','financing','ending_cash')],
                         ['5.00','-75.00','-9.00','-79.00'])
        self.check_bridge(report)

    def test_reversal_keeps_original_category_and_cutoff_is_inclusive(self):
        self.post('equipment','1500','1000','75.00',day='2026-01-02')
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.reverse('equipment',reversal_id='undo',entity_id=self.workspace.catalog.entity_id,
                effective_date='2026-01-03',reason='Correction',source_ids=[next(iter(self.workspace.sources))],
                actor_id='reverser',idempotency_key='undo')
        early=self.render(self.capture('2026-01-02')); report=self.render(self.capture('2026-01-03'))
        self.assertEqual(early['investing_amount'],'-75.00')
        self.assertEqual(report['investing_amount'],'0.00')
        self.assertEqual([r['cash_amount'] for r in report['rows']],['-75.00','75.00'])
        self.assertEqual(report['rows'][1]['original_entry_id'],'equipment')
        self.assertTrue(all(r['category']=='investing' for r in report['rows']))
        self.check_bridge(report)

    def test_reference_early_cutoff_starts_january_first(self):
        build_adjusted_month(self.workspace)
        for day, ending, operating in [('2026-01-01','8800.00','-1200.00'),('2026-01-02','7600.00','-2400.00')]:
            report=self.render(self.capture(day))
            self.assertEqual(report['period_start'],'2026-01-01')
            self.assertEqual(report['opening_cash_amount'],'0.00')
            self.assertEqual(report['ending_cash_amount'],ending)
            self.assertEqual(report['operating_amount'],operating)
            self.check_bridge(report)
        for day in ('2025-12-31','2026-02-01','2026-1-1','',True):
            with self.subTest(day=day),self.assertRaises((ValueError,TypeError)): self.capture(day)

    def test_untraced_payable_unknown_and_compound_remain_unresolved(self):
        self.post('legacy-payment','2000','1000','20.00')
        self.post('unknown','1000','1590','20.00')
        self.post('compound',lines=[dict(account='1000',side='debit',amount='30.00'),
            dict(account='4000',side='credit',amount='20.00'),dict(account='3000',side='credit',amount='10.00')])
        report=self.render()
        self.assertFalse(report['classification_complete'])
        self.assertEqual(report['unresolved_amount'],'30.00')
        self.assertEqual(len(report['exceptions']),3)
        self.assertTrue(all(r['category']=='unresolved' for r in report['rows']))
        self.check_bridge(report)

    def test_multiple_cash_lines_zero_net_remain_blocking(self):
        self.post('transfer',lines=[dict(account='1000',side='debit',amount='10.00'),
                                   dict(account='1000',side='credit',amount='10.00')])
        report=self.render()
        self.assertEqual(report['rows'][0]['cash_amount'],'0.00')
        self.assertFalse(report['classification_complete'])
        self.assertEqual(len(report['exceptions']),1)
        self.check_bridge(report)

    def test_offsetting_unsupported_flows_do_not_hide_exceptions(self):
        self.post('unknown-in','1000','1590','20.00');self.post('unknown-out','1590','1000','20.00')
        report=self.render()
        self.assertEqual(report['unresolved_amount'],'0.00')
        self.assertFalse(report['classification_complete'])
        self.assertEqual(len(report['exceptions']),2)
        self.check_bridge(report)

    def test_contradictory_or_unsupported_payable_capture_is_unresolved(self):
        build_adjusted_month(self.workspace); capture=self.capture()
        for field,value in [('expense_account','1500'),('principal_cents','1'),('effective_date','2026-01-31')]:
            trace=json.loads(capture.payables_json);trace['bills'][0][field]=value
            changed=dataclasses.replace(capture,payables_json=json.dumps(trace,sort_keys=True))
            report=self.render(changed)
            self.assertFalse(report['classification_complete'])
            self.assertEqual(report['unresolved_amount'],'-100.00')
            self.check_bridge(report)
        trace=json.loads(capture.payables_json);trace['approvals']=[]
        self.assertFalse(self.render(dataclasses.replace(capture,payables_json=json.dumps(trace)))['classification_complete'])

    def test_payable_approval_evidence_and_revision_must_match_capture(self):
        build_adjusted_month(self.workspace); capture=self.capture()
        for field,value in [('evidence',{}),('draft_id','unrelated'),('revision',999)]:
            with self.subTest(field=field):
                trace=json.loads(capture.payables_json)
                approval=trace['approvals'][0];binding=json.loads(approval['binding_json']);binding[field]=value
                approval['binding_json']=json.dumps(binding)
                report=self.render(dataclasses.replace(capture,payables_json=json.dumps(trace)))
                self.assertFalse(report['classification_complete'])
                self.assertEqual(report['unresolved_amount'],'-100.00')
                self.check_bridge(report)

    def test_payable_approval_identity_binds_exact_evidence_revision_and_actor(self):
        build_adjusted_month(self.workspace); capture=self.capture()
        for fact_type in ('bills','payments'):
            for mutation in ('evidence_digest','revision_digest','actor_id','approval_id'):
                with self.subTest(fact_type=fact_type,mutation=mutation):
                    trace=json.loads(capture.payables_json)
                    fact=trace[fact_type][0]
                    approval=next(a for a in trace['approvals'] if a['approval_id']==fact['approval_id'])
                    if mutation in ('evidence_digest','revision_digest'):
                        binding=json.loads(approval['binding_json'])
                        if mutation=='evidence_digest':
                            source=next(iter(binding['evidence']))
                            binding['evidence'][source]='0'*64
                        else:
                            binding['revision_digest']='0'*64
                        approval['binding_json']=json.dumps(binding,sort_keys=True,separators=(',',':'))
                    elif mutation=='actor_id':
                        approval['actor_id']='contradictory-human'
                    else:
                        # Keep the fact/approval reference intact so a missing join
                        # cannot mask absence of the content-identity check.
                        fact['approval_id']=approval['approval_id']='0'*64
                    report=self.render(dataclasses.replace(capture,payables_json=json.dumps(trace)))
                    self.assertFalse(report['classification_complete'])
                    self.assertEqual(report['unresolved_amount'],'-100.00')
                    self.assertEqual(report['ending_cash_amount'],'9400.00')
                    self.assertEqual(report['exceptions'][0]['code'],'unsupported_payable')
                    self.check_bridge(report)

    def test_multiple_cash_lines_with_nonzero_net_are_not_allocated(self):
        self.post('multiple',lines=[dict(account='1000',side='debit',amount='30.00'),
            dict(account='1000',side='credit',amount='10.00'),dict(account='4000',side='credit',amount='20.00')])
        report=self.render()
        self.assertEqual(report['unresolved_amount'],'20.00')
        self.assertEqual(report['operating_amount'],'0.00')
        self.assertFalse(report['classification_complete'])
        self.check_bridge(report)

    def test_approved_noncash_accruals_invoice_and_earning_leave_cash_unchanged(self):
        from accounting_harness.expense_accrual import ExpenseAccrualService
        from accounting_harness.revenue_accrual import RevenueAccrualService
        fixture=build_adjusted_month(self.workspace)
        before=self.render()
        noncash=[fixture['transactions'][label]['journal_id'] for label in ('T04','T06','A01','A02')]
        self.assertTrue(set(noncash).isdisjoint(r['journal_id'] for r in before['rows']))
        with self.workspace.storage() as (registry,ledger,_,_,_):
            common=dict(next(iter(self.workspace.sources.values()))['document'],schema_version=2,
                        event_id='cash-flow-expense',counterparty_id='cash-flow-vendor',amount='150.00')
            incurred=dict(common,document_id='cf-incurred',kind='incurred_expense',document_date='2026-01-28',
                          incurred_date='2026-01-28',expense_account='5100')
            basis=dict(common,document_id='cf-expense-basis',kind='expense_accrual_basis',document_date='2026-01-31',
                       cutoff_date='2026-01-31',status='unbilled_unpaid')
            completed=dict(common,document_id='cf-completed',event_id='cash-flow-revenue',kind='service_completion',
                           document_date='2026-01-28',completion_date='2026-01-28',amount='250.00')
            revenue_basis=dict(completed,document_id='cf-revenue-basis',kind='revenue_accrual_basis',
                               document_date='2026-01-31',cutoff_date='2026-01-31',status='unbilled_uncollected')
            del revenue_basis['completion_date']
            for document in (incurred,basis,completed,revenue_basis):
                registry.register(document,actor_id='test');ledger.enroll_source(registry,document['document_id'],actor_id='test')
            for service,args in [(ExpenseAccrualService(ledger,registry),dict(incurrence_source_id='cf-incurred',basis_source_id='cf-expense-basis')),
                                 (RevenueAccrualService(ledger,registry),dict(completion_source_id='cf-completed',basis_source_id='cf-revenue-basis'))]:
                key=args['basis_source_id']
                draft=service.propose(**args,expected_revision=0,actor_id='test-template',idempotency_key=key)
                approval=service.app.approve(draft.draft_id,revision=draft.revision,confirmed_digest=draft.content_digest,
                                             actor_id='test-human',idempotency_key=key)
                service.app.post(approval.approval_id,actor_id='test-human',idempotency_key=key)
        after=self.render()
        self.assertEqual(after['rows'],before['rows'])
        self.assertEqual(after['ending_cash_amount'],'9400.00')
        self.check_bridge(after)

    def test_cash_in_closing_journal_is_blocking_and_bridge_retains_it(self):
        self.post('bad-close','1000','3000','5.00')
        capture=self.capture()
        journals=tuple(dataclasses.replace(j,classification='closing') for j in capture.financial.journals)
        changed=dataclasses.replace(capture,financial=dataclasses.replace(capture.financial,journals=journals))
        report=self.render(changed)
        self.assertEqual(report['financing_amount'],'0.00')
        self.assertEqual(report['unresolved_amount'],'5.00')
        self.assertEqual(report['exceptions'][0]['code'],'closing_cash')
        self.assertFalse(report['classification_complete'])
        self.check_bridge(report)

    def test_capture_old_statements_and_report_survive_posts_enrollment_and_close(self):
        build_adjusted_month(self.workspace)
        capture=self.capture(); old=json.dumps(self.render(capture),sort_keys=True)
        with self.workspace.storage() as (_,ledger,_,_,_): old_fin=capture_financials(ledger,'2026-01-31')
        old_statements=json.dumps(financial_statements(old_fin),sort_keys=True)
        self.post('later','1000','3000','1.00')
        with self.workspace.storage() as (registry,ledger,_,_,_):
            ledger.ensure_bank_fee_account(actor_id='test')
            document=dict(next(iter(self.workspace.sources.values()))['document'],document_id='later-evidence')
            registry.register(document,actor_id='test'); ledger.enroll_source(registry,'later-evidence',actor_id='test')
        before_close=self.render()
        preview=self.workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        self.workspace.action('close-confirm',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[],
            confirmed_digest=preview['digest'],confirmed=True,idempotency_key='cash-flow-close'))
        fresh=self.render()
        for field in ('operating_amount','investing_amount','financing_amount','ending_cash_amount','rows'):
            self.assertEqual(fresh[field],before_close[field])
        self.assertEqual(len(fresh['excluded_closing_journal_ids']),1)
        self.assertEqual(json.dumps(self.render(capture),sort_keys=True),old)
        self.assertEqual(json.dumps(financial_statements(old_fin),sort_keys=True),old_statements)
        self.assertEqual(fresh,self.workspace.cash_flow('2026-01-31'))

    def test_large_cents_and_policy_rejection(self):
        self.post('large',amount='90071992547409.93')
        capture=self.capture();report=self.render(capture)
        self.assertEqual(report['ending_cash_amount'],'90071992547409.93')
        self.assertEqual(report['ending_cash_cents'],'9007199254740993')
        with self.assertRaises(ValueError):
            self.render(dataclasses.replace(capture,policy=dataclasses.replace(capture.policy,version='unsupported')))
        self.check_bridge(report)

    def test_capture_ledger_and_payable_reads_share_one_transaction(self):
        build_adjusted_month(self.workspace)
        with self.workspace.storage() as (_,ledger,_,_,_):
            statements=[];ledger._connection.set_trace_callback(statements.append)
            self.module().capture_cash_flow(ledger,'2026-01-31')
            ledger._connection.set_trace_callback(None)
        self.assertEqual([s for s in statements if s.startswith('BEGIN')],['BEGIN'])
        self.assertEqual(statements[-1],'COMMIT')
        self.assertTrue(any('vendor_bill_payments' in s for s in statements))

    def test_demo_reference_bridge_and_identity(self):
        self.module()
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-cash-flow'],cwd=ROOT,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        for value in ('-400.00','9800.00','9400.00','Residual: 0.00','Snapshot:','Classification complete: True'):
            self.assertIn(value,result.stdout)


class CashFlowHTTPTests(unittest.TestCase):
    def test_route_readonly_repeat_exact_cutoff_errors_and_large_money(self):
        with tempfile.TemporaryDirectory() as directory, make_server(directory,port=0) as server:
            build_adjusted_month(server.workspace)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(path):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                connection.request('GET',path);response=connection.getresponse()
                result=response.status,response.read();connection.close();return result
            try:
                before=server.workspace.state()
                status,raw=request('/api/cash-flow?as_of=2026-01-31')
                self.assertEqual(status,200,raw)
                self.assertEqual(json.loads(raw)['ending_cash_amount'],'9400.00')
                self.assertEqual(request('/api/cash-flow?as_of=2026-01-31')[1],raw)
                self.assertEqual(json.loads(request('/api/cash-flow?as_of=2026-01-01')[1])['ending_cash_amount'],'8800.00')
                for query in ('','?as_of=2026-02-01','?as_of=2026-01-01&as_of=2026-01-02',
                              '?as_of=2026-01-31&basis=cash','?as_of='):
                    self.assertEqual(request('/api/cash-flow'+query)[0],409)
                self.assertEqual(server.workspace.state(),before)
                with server.workspace.storage() as (_,ledger,_,_,_):
                    ledger.admit(dict(id='large-http',entity_id=server.workspace.catalog.entity_id,currency='USD',
                        effective_date='2026-01-31',description='Synthetic',source_ids=[next(iter(server.workspace.sources))],
                        lines=[dict(account='1000',side='debit',amount='90071992547409.93'),
                               dict(account='3000',side='credit',amount='90071992547409.93')]),
                        actor_id='test',idempotency_key='large-http')
                report=json.loads(request('/api/cash-flow?as_of=2026-01-31')[1])
                self.assertEqual(report['ending_cash_amount'],'90071992556809.93')
                self.assertEqual(report['ending_cash_cents'],'9007199255680993')
            finally:
                server.shutdown();thread.join()
