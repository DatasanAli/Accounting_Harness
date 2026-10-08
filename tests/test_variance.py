"""Independent signs, bridges and frozen operating comparison inputs."""
import copy
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness.workspace import Workspace


class VarianceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.variance'), 'captured variance must be implemented')
        from accounting_harness import variance
        return variance

    def budget_data(self, **changes):
        return dict(dict(entity_id=self.workspace.catalog.entity_id,currency='USD',scenario_id='operating',name='Service plan',
            month='2026-01',planned_minutes=480,opening_cash='0.00',cash_rows=[],prior_version_id=None,reason='Synthetic assumptions',
            explanation='Operator assumption; not causal evidence',idempotency_key='v1',operating_lines=[
                dict(line_id='sales',account='4000',behavior='variable',amount='125.00'),
                dict(line_id='variable-cost',account='5100',behavior='variable',amount='50.00'),
                dict(line_id='fixed-cost',account='5100',behavior='fixed',amount='100.00')]),**changes)

    def budget(self, **changes):
        return self.workspace.action('budget',self.budget_data(**changes))

    def actual(self, identity, cents, account='4000'):
        side='credit' if account=='4000' else 'debit'
        if cents<0: side='credit' if side=='debit' else 'debit'
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.admit(dict(id=identity,entity_id=self.workspace.catalog.entity_id,currency='USD',effective_date='2026-01-10',
                description='Synthetic variance actual',source_ids=[next(iter(self.workspace.sources))],lines=[
                    dict(account=account,side=side,amount=f'{abs(cents)//100}.{abs(cents)%100:02d}'),
                    dict(account='1000',side='credit' if side=='debit' else 'debit',amount=f'{abs(cents)//100}.{abs(cents)%100:02d}')]),
                actor_id='test-human',idempotency_key=identity)

    def time(self, minutes=600, identity='service', day='2026-01-10'):
        if identity=='service':
            self.workspace.action('projects',dict(project_id='A',name='Service A',entity_id=self.workspace.catalog.entity_id,customer_id=None))
        return self.workspace.action('project-time',dict(entity_id=self.workspace.catalog.entity_id,project_id='A',worker_id='worker',
            time_event_id=identity,work_date=day,start_minute=0,end_minute=minutes,replaces_record_id=None))

    def report(self, budget):
        self.module()
        return self.workspace.variance(budget['version_id'])

    def fixture(self):
        self.actual('revenue',110000); self.actual('cost',60000,'5100'); self.time()
        return self.budget()

    def test_reference_signs_two_part_bridges_and_financial_drilldowns(self):
        budget=self.fixture(); before=self.workspace.report_package('2026-01-31'); report=self.report(budget)
        expected={'revenue':('1000.00','1250.00','1100.00','100.00','Favorable','250.00','-150.00'),
                  'expense':('500.00','600.00','600.00','100.00','Unfavorable','100.00','0.00'),
                  'income':('500.00','650.00','500.00','0.00','Neutral','150.00','-150.00')}
        for kind,values in expected.items():
            row=report['totals'][kind]
            self.assertEqual(tuple(row[k] for k in ('static_amount','flexible_amount','actual_amount','variance_amount','label','activity_amount','remaining_amount')),values)
            self.assertEqual(int(row['activity_cents'])+int(row['remaining_cents']),int(row['variance_cents']))
        self.assertEqual(report['totals']['revenue']['static_percent'],dict(numerator='10000',denominator='100000',display='10.00%',base='absolute static budget'))
        self.assertEqual(report['totals']['expense']['favorable_impact_amount'],'-100.00')
        self.assertEqual(report['totals']['expense']['activity_label'],'Unfavorable')
        self.assertEqual(report['totals']['revenue']['remaining_label'],'Unfavorable')
        self.assertEqual(report['actual_minutes'],600)
        self.assertEqual(report['budget_lines'][2]['flexible_amount'],'100.00')
        income=before['reports']['income_statement'] if 'income_statement' in before.get('reports',{}) else self.workspace.financial_statements('2026-01-31')['income_statement']
        for row in report['accounts']:
            actual=next(r for r in income['revenue']+income['expenses'] if r['account']==row['account'])
            self.assertEqual(row['actual_drilldown'],actual['drilldown'])
            self.assertEqual(sum(int(d['net_cents']) for d in row['actual_drilldown']),int(row['actual_cents']))
        self.assertEqual(self.workspace.budget(budget['version_id']),budget)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)
        self.assertTrue(report['reconciled'])
        self.assertEqual(self.module().variance_report(report['capture']),report)

    def test_zero_planned_activity_retains_explicit_rates_and_unavailable_percentage(self):
        self.time(); report=self.report(self.budget(planned_minutes=0))
        revenue=report['totals']['revenue']
        self.assertEqual((revenue['static_amount'],revenue['flexible_amount']),('0.00','1250.00'))
        self.assertIsNone(revenue['static_percent']['display'])
        self.assertIsNone(revenue['static_percent']['denominator'])
        self.assertEqual(revenue['remaining_amount'],'-1250.00')

    def test_no_time_no_actuals_fixed_cost_does_not_flex_and_loss_is_visible(self):
        report=self.report(self.budget())
        self.assertEqual(report['actual_minutes'],0)
        self.assertEqual(report['totals']['expense']['flexible_amount'],'100.00')
        self.assertEqual(report['totals']['income']['flexible_amount'],'-100.00')
        self.assertEqual(report['totals']['revenue']['flexible_percent']['display'],None)
        self.assertTrue(any('No active service time' in f for f in report['findings']))

    def test_unbudgeted_actual_and_budget_only_accounts_are_explicit(self):
        self.actual('unbudgeted',5000,'5200')
        report=self.report(self.budget())
        rows={r['account']:r for r in report['accounts']}
        self.assertEqual(rows['5200']['status'],'unbudgeted')
        self.assertEqual(rows['4000']['status'],'budget-only')
        self.assertEqual(rows['5200']['variance_amount'],'50.00')
        self.assertIsNone(rows['5200']['static_percent']['display'])
        self.assertEqual(report['totals']['expense']['actual_amount'],'50.00')

    def test_opposite_balances_favorable_signs_and_loss_net_bridge(self):
        self.actual('refund',-20000); self.actual('credit',-3000,'5100')
        report=self.report(self.budget())
        self.assertEqual(report['totals']['revenue']['actual_amount'],'-200.00')
        self.assertEqual(report['totals']['expense']['actual_amount'],'-30.00')
        self.assertEqual(report['totals']['expense']['label'],'Favorable')
        self.assertEqual(report['totals']['income']['actual_amount'],'-170.00')
        for field in ('favorable_impact_cents','activity_favorable_impact_cents','remaining_favorable_impact_cents'):
            self.assertEqual(int(report['totals']['income'][field]),sum(int(report['totals'][k][field]) for k in ('revenue','expense')))

    def test_round_per_line_preserves_rounded_bridge_and_large_exact_values(self):
        self.time(3)
        lines=[dict(line_id='a',account='4000',behavior='variable',amount='0.10'),dict(line_id='b',account='4000',behavior='variable',amount='0.10')]
        report=self.report(self.budget(planned_minutes=1,operating_lines=lines))
        self.assertEqual(report['totals']['revenue']['flexible_cents'],'2')
        self.assertEqual([r['flexible_rounding_delta_numerator'] for r in report['budget_lines']],['30','30'])
        self.assertEqual(sum(int(r['activity_cents']) for r in report['budget_lines']),2)
        large=self.report(self.budget(scenario_id='large',planned_minutes=9007199254740991,operating_lines=[dict(lines[0],amount='90071992547409.93')]))
        self.assertEqual(large['totals']['revenue']['static_cents'],str((9007199254740991*9007199254740993+30)//60))
        self.assertIsInstance(large['totals']['revenue']['static_cents'],str)

    def test_percentage_negative_base_and_signed_half_up(self):
        module=self.module()
        self.assertEqual(module._percent(-1,-32,'static')['display'],'-3.13%')
        self.assertEqual(module._percent(1,32,'flexible')['display'],'3.13%')
        self.assertIsNone(module._percent(0,0,'static')['display'])

    def test_frozen_json_survives_budget_time_ledger_updates_and_restart(self):
        budget=self.fixture(); report=self.report(budget); frozen=json.dumps(report,sort_keys=True)
        self.budget(prior_version_id=budget['version_id'],idempotency_key='v2',planned_minutes=720)
        record=self.workspace.project_time('2026-01-31')['active_intervals'][0]
        self.workspace.action('project-time-void',dict(entity_id=budget['entity_id'],record_id=record['record_id'],void_event_id='void',reason='Correction'))
        self.actual('later',5000)
        self.workspace=Workspace(self.directory.name)
        restored=self.module().variance_report(json.loads(frozen)['capture'])
        self.assertEqual(json.dumps(restored,sort_keys=True),frozen)
        self.assertNotEqual(self.report(budget)['snapshot_digest'],report['snapshot_digest'])

    def test_malformed_scopes_policy_digest_and_records_refused(self):
        report=self.report(self.fixture()); module=self.module()
        paths=[('policy','other'),('budget.entity_id','other'),('budget.currency','EUR'),('budget.month','2026-02'),
            ('budget.planned_minutes',True),('budget.operating_lines.0.behavior','mystery'),('financial.policy.basis','cash'),
            ('time.entity_id','other'),('time.as_of','2026-01-30'),('time.policy','other'),('time.records.0.minutes',-1)]
        from accounting_harness.review import digest
        for path,value in paths:
            capture=copy.deepcopy(report['capture']); target=capture
            parts=path.split('.')
            for key in parts[:-1]: target=target[int(key)] if isinstance(target,list) else target[key]
            target[parts[-1]]=value
            capture['input_digest']=digest({k:v for k,v in capture.items() if k!='input_digest'})
            with self.subTest(path=path),self.assertRaises(ValueError): module.variance_report(capture)
        capture=copy.deepcopy(report['capture']); capture['input_digest']='0'*64
        with self.assertRaisesRegex(ValueError,'digest'): module.variance_report(capture)
        with self.assertRaises(ValueError): module.variance_report({})

    def test_remaining_explanation_is_conservative_and_note_attributed(self):
        report=self.report(self.fixture())
        self.assertIn('quantity',report['remaining_policy'])
        self.assertTrue(any('classification' in f for f in report['findings']))
        self.assertEqual(report['operator_note']['actor_id'],'local-operator')
        self.assertEqual(report['operator_note']['text'],'Operator assumption; not causal evidence')

    def test_native_http_route_strict_parameters_exact_response_and_no_post(self):
        self.module()
        import http.client
        import threading
        from accounting_harness.web import make_server
        budget=self.fixture(); before=self.workspace.report_package('2026-01-31')
        server=make_server(self.directory.name,port=0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join,2); self.addCleanup(server.shutdown)
        def get(path):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1]); conn.request('GET',path)
            response=conn.getresponse(); value=json.loads(response.read()); conn.close(); return response.status,value
        status,report=get('/api/variance?version_id='+budget['version_id'])
        self.assertEqual(status,200); self.assertEqual(report['totals']['revenue']['variance_amount'],'100.00')
        for path in ('/api/variance','/api/variance?version_id=','/api/variance?version_id=nope','/api/variance?version_id=a&version_id=b','/api/variance?version_id=a&as_of=2026-01-31'):
            self.assertEqual(get(path)[0],409)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)

    def test_capture_uses_one_read_transaction_despite_concurrent_commit(self):
        import concurrent.futures
        module=self.module(); budget=self.fixture(); original=module._capture_financials
        with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('PRAGMA journal_mode=WAL')
        def interleave(ledger, cutoff):
            captured=original(ledger,cutoff)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                def write():
                    self.actual('concurrent',700)
                    self.time(60,identity='concurrent-time',day='2026-01-11')
                    self.budget(prior_version_id=budget['version_id'],idempotency_key='v2',planned_minutes=999)
                pool.submit(write).result(timeout=10)
            return captured
        with patch.object(module,'_capture_financials',side_effect=interleave): report=self.report(budget)
        self.assertEqual(report['totals']['revenue']['actual_amount'],'1100.00')
        self.assertEqual(report['actual_minutes'],600)
        self.assertEqual(report['planned_minutes'],480)
        current=self.report(budget)
        self.assertEqual(current['actual_minutes'],660)
        self.assertEqual(current['totals']['revenue']['actual_amount'],'1107.00')

    def test_closing_exclusion_and_frozen_classifications(self):
        budget=self.fixture(); report=self.report(budget); frozen=json.dumps(report,sort_keys=True)
        preview=self.workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        self.assertTrue(preview['can_close'],preview['findings'])
        close=self.workspace.action('close-confirm',dict(period_start=preview['period_start'],period_end=preview['period_end'],
            selections=[],confirmed_digest=preview['digest'],confirmed=True,idempotency_key='close-variance'))
        current=self.report(budget)
        self.assertEqual(current['totals'],report['totals'])
        self.assertEqual(current['excluded_closing_journal_ids'],[close['journal_id']])
        self.assertEqual(json.dumps(self.module().variance_report(report['capture']),sort_keys=True),frozen)

    def test_native_variance_controls_and_cli(self):
        from pathlib import Path
        import subprocess
        import sys
        root=Path(__file__).resolve().parents[1]
        html=(root/'accounting_harness/static/index.html').read_text()
        self.assertIn('id="variance-form"',html)
        self.assertIn('id="variance-report"',html)
        script=(root/'accounting_harness/static/app.js').read_text()
        self.assertIn('/api/variance?version_id=',script)
        self.assertIn("'Static · USD'",script)
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-variance'],cwd=root,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for text in ('100.00 Favorable','100.00 Unfavorable','250.00','-150.00','0.00 Neutral'):
            self.assertIn(text,result.stdout)

    def test_resealed_malformed_budget_cash_and_project_inputs_are_refused(self):
        from accounting_harness.budget import budget_report
        from accounting_harness.review import digest
        module=self.module(); original=self.report(self.fixture())['capture']
        cash=dict(row_id='x',direction='mystery',amount='1.00',expected_date='2026-01-10',category='plan',budget_line_id=None,source_reference=None)
        cases=[('cash',cash),('cash',dict(cash,direction='receipt',budget_line_id='missing')),
            ('cash',dict(cash,direction='receipt',amount='0.00')),('project',None)]
        for kind,value in cases:
            capture=copy.deepcopy(original)
            if kind=='cash':
                budget=capture['budget']; budget['cash_rows']=[value]
                budget['payload_digest']=digest(dict({k:budget[k] for k in module.BUDGET_FIELDS},actor_id=budget['actor_id']))
                budget['report']=budget_report(budget)
            else: capture['time']['projects'][0]['name']=value
            capture['input_digest']=digest({k:v for k,v in capture.items() if k!='input_digest'})
            with self.subTest(kind=kind,value=value),self.assertRaises(ValueError): module.variance_report(capture)

    def test_invalid_time_identity_duration_overlap_and_replacement_refused_with_new_digests(self):
        from accounting_harness.review import digest
        module=self.module(); original=self.report(self.fixture())['capture']
        fields=('entity_id','project_id','worker_id','time_event_id','work_date','start_minute','end_minute','replaces_record_id')
        for change in ({'start_minute':True},{'minutes':599},{'end_minute':1500},{'project_id':'missing'},
                       {'replaces_record_id':'missing'},{'work_date':'2026-02-01'}):
            capture=copy.deepcopy(original); record=capture['time']['records'][0]; record.update(change)
            record['payload_digest']=digest({k:record[k] for k in fields})
            capture['input_digest']=digest({k:v for k,v in capture.items() if k!='input_digest'})
            with self.subTest(change=change),self.assertRaises(ValueError): module.variance_report(capture)
        for change in ({},{'record_id':'second','time_event_id':'second'}):
            capture=copy.deepcopy(original); record=dict(capture['time']['records'][0],**change)
            record['payload_digest']=digest({k:record[k] for k in fields}); capture['time']['records'].append(record)
            capture['input_digest']=digest({k:v for k,v in capture.items() if k!='input_digest'})
            with self.subTest(change=change),self.assertRaises(ValueError): module.variance_report(capture)

    def test_shipped_renderer_preserves_large_money_and_null_percent_strings(self):
        from pathlib import Path
        import subprocess
        self.time(1)
        budget=self.budget(planned_minutes=9007199254740991,operating_lines=[dict(line_id='huge',account='4000',behavior='variable',amount='90071992547409.93')])
        report=self.report(budget)
        script=Path('accounting_harness/static/app.js').read_text().split('function renderVariance(report) {',1)[1]
        script='function renderVariance(report) {'+script
        harness="""
const rendered=[];
const node=()=>({append(...x){rendered.push(...x);},replaceChildren(){},click(){}});
const $=()=>node(), el=(tag,text)=>text === undefined || text === null ? node() : text;
const add=(n,...x)=>{n.append(...x);return n;};
const table=(headers,rows)=>{rendered.push(headers,rows);return node();};
const metadata=x=>{rendered.push(x);return node();};
const digest=()=>{},jsonDetails=()=>node(),button=()=>node();
"""+script+'\nrenderVariance('+json.dumps(report)+');\nprocess.stdout.write(JSON.stringify(rendered));'
        result=subprocess.run(['node','-e',harness],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(report['totals']['revenue']['static_amount'],result.stdout)
        self.assertIn(report['totals']['revenue']['variance_amount'],result.stdout)
        self.assertIn('Unavailable · zero base',result.stdout)
