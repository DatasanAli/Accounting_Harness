"""Captured statement accounting and native read-only HTTP contract."""
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
from accounting_harness.domain.ledger import LedgerLine
from accounting_harness.domain.money import Money
from accounting_harness.web import make_server
from accounting_harness.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]


class FinancialReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.financial_reports'),
                             'captured financial statements must be implemented')
        from accounting_harness import financial_reports
        return financial_reports

    def capture(self, cutoff='2026-01-31', **policy):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return self.module().capture_financials(ledger, cutoff, **policy)

    def post(self, entry_id, debit, credit, amount, effective_date='2026-01-31'):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return ledger.admit(dict(id=entry_id, entity_id=self.workspace.catalog.entity_id,
                currency='USD', effective_date=effective_date, description='Synthetic test fact',
                source_ids=[next(iter(self.workspace.sources))], lines=[
                    dict(account=debit, side='debit', amount=amount),
                    dict(account=credit, side='credit', amount=amount)]),
                actor_id='synthetic-test', idempotency_key=entry_id)

    def render(self, capture=None):
        return self.module().financial_statements(capture or self.capture())

    def assert_trace(self, report):
        for statement in ('income_statement', 'owners_equity', 'balance_sheet'):
            item = report[statement]
            for key in ('snapshot_digest', 'policy_digest', 'as_of', 'period_start', 'entity_id',
                        'catalog', 'included_journal_ids'):
                self.assertEqual(item[key], report[key])
        rows = (report['income_statement']['revenue'] + report['income_statement']['expenses'] +
                report['balance_sheet']['assets'] + report['balance_sheet']['liabilities'] +
                [report['owners_equity']['contributions'], report['owners_equity']['drawings']])
        for row in rows:
            self.assertEqual(sum(int(line['net_cents']) for line in row['drilldown']), int(row['net_cents']), row)
            for line in row['drilldown']:
                self.assertIn(line['journal_id'], report['included_journal_ids'])
                self.assertTrue(line['source_ids'])
                self.assertTrue(line['actor_id'])
                self.assertEqual(line['classification'], 'ordinary')
                self.assertIsInstance(line['amount'], str)
        self.assertEqual(report['owners_equity']['income_statement_digest'], report['income_statement']['report_digest'])
        self.assertEqual(report['balance_sheet']['owners_equity_digest'], report['owners_equity']['report_digest'])

    def test_reference_totals_every_account_and_trace(self):
        fixture = build_adjusted_month(self.workspace)
        report = self.render()
        income, equity, balance = (report[k] for k in ('income_statement', 'owners_equity', 'balance_sheet'))
        self.assertEqual([income[k] for k in ('revenue_amount','expenses_amount','net_income_amount')],
                         ['2700.00','1600.00','1100.00'])
        self.assertEqual([equity[k] for k in ('opening_capital_amount','contributions_amount','drawings_amount','ending_equity_amount')],
                         ['0.00','10000.00','200.00','10900.00'])
        self.assertEqual([balance[k] for k in ('assets_amount','liabilities_amount','equity_amount','residual_amount')],
                         ['11500.00','600.00','10900.00','0.00'])
        self.assertTrue(balance['reconciled'])
        rows = income['revenue'] + income['expenses'] + balance['assets'] + balance['liabilities'] + [equity['contributions'],equity['drawings']]
        self.assertEqual({r['account']:r['amount'] for r in rows}, {
            '1000':'9400.00','1100':'1000.00','1200':'1100.00','1500':'0.00','1590':'0.00',
            '2000':'200.00','2100':'400.00','3000':'10000.00','3100':'200.00',
            '4000':'2700.00','5000':'1200.00','5100':'300.00','5200':'100.00'})
        self.assertEqual(set(report['included_journal_ids']), {t['journal_id'] for t in fixture['transactions'].values()})
        self.assert_trace(report)

    def test_no_activity_is_zero_and_deterministic(self):
        capture = self.capture()
        report = self.render(capture)
        self.assertEqual(report, self.render(self.capture()))
        self.assertEqual(report['included_journal_ids'], [])
        for key in ('assets_amount','liabilities_amount','equity_amount','residual_amount'):
            self.assertEqual(report['balance_sheet'][key], '0.00')
        self.assert_trace(report)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            capture.as_of = '2026-01-01'

    def test_loss_opposite_balances_and_contra_asset_keep_signs(self):
        self.post('expense', '5000', '1000', '100.00')
        self.post('negative-revenue', '4000', '1000', '25.00')
        self.post('negative-expense', '1000', '5100', '10.00')
        self.post('contra', '5200', '1590', '7.00')
        self.post('withdraw-contribution', '3000', '1000', '12.00')
        self.post('reverse-drawing', '1000', '3100', '3.00')
        report = self.render()
        self.assertEqual(report['income_statement']['net_income_amount'], '-122.00')
        self.assertEqual(report['owners_equity']['contributions_amount'], '-12.00')
        self.assertEqual(report['owners_equity']['drawings_amount'], '-3.00')
        self.assertEqual(report['owners_equity']['ending_equity_amount'], '-131.00')
        self.assertEqual({r['account']:r['amount'] for r in report['balance_sheet']['assets']}['1590'], '-7.00')
        self.assertTrue(report['balance_sheet']['reconciled'])
        self.assert_trace(report)

    def test_linked_reversal_drilldown_retains_both_postings(self):
        self.post('capital', '1000', '3000', '12.00', '2026-01-02')
        with self.workspace.storage() as (_, ledger, _, _, _):
            ledger.reverse('capital', reversal_id='undo-capital', entity_id=self.workspace.catalog.entity_id,
                effective_date='2026-01-03', reason='Synthetic correction',
                source_ids=[next(iter(self.workspace.sources))], actor_id='reverser', idempotency_key='undo')
        before = self.render(self.capture('2026-01-02'))
        after = self.render(self.capture('2026-01-03'))
        self.assertEqual(before['owners_equity']['contributions_amount'],'12.00')
        self.assertEqual(after['owners_equity']['contributions_amount'],'0.00')
        lines = after['owners_equity']['contributions']['drilldown']
        self.assertEqual([line['net_cents'] for line in lines], ['1200','-1200'])
        self.assertEqual(lines[1]['original_entry_id'], 'capital')
        self.assert_trace(after)

    def test_cutoff_is_inclusive_and_invalid_outside_dates_rejected(self):
        build_adjusted_month(self.workspace)
        for cutoff, count, assets, income in [('2026-01-01',2,'10000.00','0.00'),
                                               ('2026-01-02',3,'8800.00','-1200.00')]:
            report = self.render(self.capture(cutoff))
            self.assertEqual(len(report['included_journal_ids']), count)
            self.assertEqual(report['balance_sheet']['assets_amount'],assets)
            self.assertEqual(report['income_statement']['net_income_amount'],income)
        for cutoff in ('2025-12-31','2026-02-01','2026-01-32','2026-1-1','',True):
            with self.subTest(cutoff=cutoff), self.assertRaises((ValueError,TypeError)):
                self.capture(cutoff)

    def test_capture_survives_posting_catalog_and_registry_mutation(self):
        capture = self.capture()
        old = json.dumps(self.render(capture), sort_keys=True)
        self.post('later', '1000', '3000', '1.00')
        with self.workspace.storage() as (registry, ledger, _, _, _):
            ledger.ensure_bank_fee_account(actor_id='synthetic-test')
            document = dict(next(iter(self.workspace.sources.values()))['document'],
                            document_id='new-synthetic-source')
            registry.register(document, actor_id='synthetic-test')
        self.assertEqual(json.dumps(self.render(capture), sort_keys=True), old)
        current = self.render()
        self.assertNotEqual(current['snapshot_digest'], self.render(capture)['snapshot_digest'])
        self.assertIn('5300', [a['code'] for a in current['catalog']])
        self.assertNotIn('5300', [a['code'] for a in self.render(capture)['catalog']])

    def test_very_large_integer_money_stays_exact(self):
        self.post('large', '1000', '4000', '90071992547409.93')
        report = self.render()
        self.assertEqual(report['income_statement']['net_income_amount'],'90071992547409.93')
        self.assertEqual(report['balance_sheet']['assets_amount'],'90071992547409.93')
        self.assert_trace(report)
        def reject_float_or_money_number(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key.endswith('_cents') or key == 'cents': self.assertIsInstance(item,str)
                    reject_float_or_money_number(item)
            elif isinstance(value,list):
                for item in value: reject_float_or_money_number(item)
            else: self.assertNotIsInstance(value,float)
        reject_float_or_money_number(report)

    def test_explicit_closing_classification_excluded_from_all_statements(self):
        self.post('ordinary', '1000', '4000', '100.00')
        self.post('closing', '4000', '3000', '100.00')
        capture = self.capture()
        journals = tuple(dataclasses.replace(j, classification='closing') if j.journal_id=='closing' else j for j in capture.journals)
        report = self.render(dataclasses.replace(capture,journals=journals))
        self.assertEqual(report['income_statement']['net_income_amount'],'100.00')
        self.assertEqual(report['owners_equity']['contributions_amount'],'0.00')
        self.assertEqual(report['balance_sheet']['equity_amount'],'100.00')
        self.assertTrue(report['balance_sheet']['reconciled'])
        self.assertEqual(report['excluded_closing_journal_ids'],['closing'])
        self.assertNotEqual(report['snapshot_digest'],self.render(capture)['snapshot_digest'])
        self.assert_trace(report)

    def test_unsupported_policies_and_currency_rejected(self):
        for policy in (dict(basis='cash'),dict(equity_model='corporate'),dict(opening_balances='carried')):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError,'unsupported'):
                self.capture(**policy)
        with self.assertRaisesRegex(ValueError,'USD'):
            self.capture(currency='EUR')

    def test_inconsistent_capture_is_not_called_reconciled(self):
        self.post('fact', '1000', '3000', '1.00')
        capture = self.capture()
        entry = capture.ledger.entries[0]
        entry = dataclasses.replace(entry,lines=(LedgerLine('1000','debit',Money(101)),entry.lines[1]))
        broken = dataclasses.replace(capture,ledger=dataclasses.replace(capture.ledger,entries=(entry,)))
        report = self.render(broken)
        self.assertEqual(report['balance_sheet']['residual_amount'],'0.01')
        self.assertFalse(report['balance_sheet']['reconciled'])

    def test_capture_all_reads_share_one_transaction(self):
        self.post('fact', '1000', '3000', '1.00')
        with self.workspace.storage() as (_,ledger,_,_,_):
            statements=[]
            ledger._connection.set_trace_callback(statements.append)
            self.module().capture_financials(ledger,'2026-01-31')
            ledger._connection.set_trace_callback(None)
        self.assertEqual([s for s in statements if s.startswith('BEGIN')],['BEGIN'])
        self.assertEqual(statements[-1],'COMMIT')

    def test_demo_prints_reference_values_and_capture_identity(self):
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-statements'],cwd=ROOT,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        for value in ('2700.00','1600.00','1100.00','11500.00','600.00','10900.00','Snapshot','Residual: 0.00'):
            self.assertIn(value,result.stdout)


class FinancialReportHTTPTests(unittest.TestCase):
    def test_native_route_cutoff_capture_readonly_and_errors(self):
        with tempfile.TemporaryDirectory() as directory, make_server(directory,port=0) as server:
            build_adjusted_month(server.workspace)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(path):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                connection.request('GET',path)
                response=connection.getresponse();payload=response.read();status=response.status
                connection.close()
                return status,payload
            try:
                before=server.workspace.state()
                status,raw=request('/api/financial-statements?as_of=2026-01-31')
                self.assertEqual(status,200,raw)
                report=json.loads(raw)
                self.assertEqual(report['income_statement']['net_income_amount'],'1100.00')
                self.assertEqual(report['balance_sheet']['assets_amount'],'11500.00')
                self.assertEqual(request('/api/financial-statements?as_of=2026-01-31')[1],raw)
                status,early=request('/api/financial-statements?as_of=2026-01-01')
                self.assertEqual(status,200)
                self.assertEqual(json.loads(early)['balance_sheet']['assets_amount'],'10000.00')
                for query in ('','?as_of=2026-02-01','?as_of=2026-01-01&as_of=2026-01-02',
                              '?as_of=2026-01-31&basis=cash','?as_of='):
                    self.assertEqual(request('/api/financial-statements'+query)[0],409)
                self.assertEqual(server.workspace.state(),before)
                html=request('/')[1].decode();js=request('/app.js')[1].decode()
                self.assertIn('data-view="reports"',html)
                self.assertIn('id="financial-cutoff"',html)
                self.assertIn('/api/financial-statements?as_of=',js)
                self.assertIn('net_income_amount',js)
                self.assertIn('drilldown',js)
            finally:
                server.shutdown();thread.join()
