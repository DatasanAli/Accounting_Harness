"""Exact scenario costing, input ownership and immutable model history."""
import concurrent.futures
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness.workspace import Workspace


class ProjectCostTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.project_cost'), 'project costing must be implemented')
        from accounting_harness import project_cost
        return project_cost

    def project(self, identity='A'):
        self.workspace.action('projects',dict(project_id=identity,name='Project '+identity,entity_id=self.workspace.catalog.entity_id,customer_id=None))

    def actual(self, identity, cents, *, kind='expense', category='software', traceability='direct', project='A'):
        amount = f'{abs(cents)//100}.{abs(cents)%100:02d}'
        account, side = ('5100','debit') if kind=='expense' else ('4000','credit')
        if cents<0: side = 'credit' if side=='debit' else 'debit'
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.admit(dict(id=identity,entity_id=self.workspace.catalog.entity_id,currency='USD',effective_date='2026-01-10',
                description='Synthetic costing actual',source_ids=[next(iter(self.workspace.sources))],lines=[
                    dict(account=account,side=side,amount=amount),dict(account='1000',side='credit' if side=='debit' else 'debit',amount=amount)]),
                actor_id='test-human',idempotency_key=identity)
        source = next(s for s in self.workspace.project_dimensions('2026-01-31')['sources'] if s['journal_id']==identity)
        return self.workspace.action('project-assignments',dict(entity_id=self.workspace.catalog.entity_id,journal_id=identity,line_number=1,
            source_digest=source['source_digest'],prior_revision_id=None,reason='Explicit synthetic classification',idempotency_key='assign-'+identity,
            allocations=[dict(project_id=project,customer_id=None,category=category,traceability=traceability,behavior='fixed',cents=str(abs(cents)))]))

    def time(self, minutes=300, identity='day1', day='2026-01-10', project='A'):
        return self.workspace.action('project-time',dict(entity_id=self.workspace.catalog.entity_id,project_id=project,worker_id='worker',time_event_id=identity,
            work_date=day,start_minute=0,end_minute=minutes,replaces_record_id=None))

    def inputs(self):
        self.module()
        return self.workspace.project_cost_inputs('2026-01-31')

    def data(self, **changes):
        inputs = self.inputs()
        return dict(dict(entity_id=self.workspace.catalog.entity_id,scenario_id='cost-A',name='Project A costing',project_id='A',as_of='2026-01-31',
            labor_rate='40.00',overhead_rate='20.00',actual_snapshot_digest=inputs['actuals']['snapshot_digest'],time_snapshot_digest=inputs['time']['snapshot_digest'],
            direct_cost_portions=[p['reference'] for p in inputs['eligible_direct_costs'] if p['project_id']=='A'],prior_version_id=None,
            reason='Initial explicit management model',explanation='',idempotency_key='cost-v1'),**changes)

    def save(self, data=None, **changes):
        return self.workspace.action('project-cost',self.data(**changes) if data is None else data)

    def fixture(self):
        self.module(); self.project(); self.actual('expense',10000); self.actual('revenue',100000,kind='revenue',category='service')
        self.time(); self.time(identity='day2',day='2026-01-11')

    def test_reference_cost_and_pure_trace_no_financial_or_actual_changes(self):
        self.fixture(); before=self.workspace.report_package('2026-01-31'); actuals=self.workspace.project_dimensions('2026-01-31')
        result=self.save(); sheet=result['cost_sheet']
        self.assertEqual([sheet[k] for k in ('labor_amount','direct_nonlabor_amount','overhead_amount','total_cost_amount','revenue_amount','margin_amount')],
            ['400.00','100.00','200.00','700.00','1000.00','300.00'])
        self.assertEqual(sheet['total_minutes'],600); self.assertEqual(len(sheet['time_records']),2)
        self.assertEqual(sheet['calculations']['labor']['numerator'],'2400000')
        self.assertEqual(sheet['calculations']['labor']['denominator'],60)
        self.assertEqual(sheet['calculations']['labor']['rounding_delta_numerator'],'0')
        self.assertEqual(len(sheet['actuals_bridge']),2); self.assertTrue(sheet['actuals']['reconciled'])
        self.assertEqual(self.module().cost_sheet(result),sheet)
        self.assertEqual(self.workspace.project_cost(result['version_id']),result)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)
        self.assertEqual(self.workspace.project_dimensions('2026-01-31'),actuals)

    def test_component_rounding_once_half_up_zero_and_large_exact_rates(self):
        self.module(); self.project(); self.time(1); self.time(1,identity='day2',day='2026-01-11')
        sheet=self.save(labor_rate='0.15',overhead_rate='0.14')['cost_sheet']
        self.assertEqual(sheet['labor_cents'],'1'); self.assertEqual(sheet['overhead_cents'],'0')
        self.assertEqual(sheet['calculations']['labor']['rounding_delta_numerator'],'30')
        self.assertEqual(sheet['calculations']['overhead']['rounding_delta_numerator'],'-28')
        result=self.save(scenario_id='large',idempotency_key='large',labor_rate='90071992547409.93',overhead_rate='0.00')
        self.assertEqual(result['cost_sheet']['labor_cents'],'300239975158033')
        self.assertEqual(result['cost_sheet']['overhead_cents'],'0')
        self.project('B'); result=self.save(project_id='B',scenario_id='zero',idempotency_key='zero')
        self.assertEqual(result['cost_sheet']['total_cost_cents'],'0')

    def test_actual_labor_indirect_unclassified_and_unselected_are_visible_not_double_counted(self):
        self.fixture(); self.actual('labor',50000,category='labor'); self.actual('overhead',20000,traceability='indirect')
        self.actual('unknown',1000,category='unclassified'); self.actual('other-direct',500,category='materials')
        inputs=self.inputs(); chosen=[r['reference'] for r in inputs['eligible_direct_costs'] if r['journal_id']=='expense']
        sheet=self.save(direct_cost_portions=chosen)['cost_sheet']
        self.assertEqual(sheet['total_cost_amount'],'700.00'); self.assertEqual(sheet['actual_expense_amount'],'815.00')
        self.assertEqual(sheet['excluded_actual_expense_amount'],'715.00'); self.assertEqual(sheet['model_minus_actual_amount'],'-115.00')
        self.assertEqual({r['treatment'] for r in sheet['actuals_bridge']}, {'revenue','selected_direct_nonlabor','modeled_labor','modeled_overhead','unclassified','not_selected'})
        self.assertTrue(any('unknown' in f or 'unclassified' in f for f in sheet['findings']))

    def test_negative_actual_adjustment_and_loss(self):
        self.fixture(); self.actual('refund',-2000)
        sheet=self.save(labor_rate='100.00')['cost_sheet']
        self.assertEqual(sheet['direct_nonlabor_amount'],'80.00'); self.assertEqual(sheet['total_cost_amount'],'1280.00')
        self.assertEqual(sheet['margin_amount'],'-280.00')
        self.assertTrue(any(r['signed_cents']=='-2000' and r['included_in_model'] for r in sheet['actuals_bridge']))

    def test_strict_requests_scope_rates_and_duplicate_portions(self):
        self.fixture(); data=self.data(); original=self.inputs()
        cases=[dict(entity_id='other'),dict(project_id='missing'),dict(actual_snapshot_digest='0'*64),dict(time_snapshot_digest='0'*64),
            dict(direct_cost_portions=data['direct_cost_portions']*2),dict(direct_cost_portions=[dict(revision_id='missing',allocation_number=1)]),
            dict(reason=''),dict(actor_id='admin'),dict(actuals={'total':'100'}),dict(prior_version_id='missing')]
        cases += [dict(labor_rate=v) for v in ('1','1.0','-1.00','1.001','1e2',' 1.00','01.00',1,True,None,'99999999999999999999.00')]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ValueError): self.save(dict(data,**change))
        missing=dict(data); del missing['time_snapshot_digest']
        with self.assertRaises(ValueError): self.save(missing)
        self.assertEqual(self.inputs(),original)

    def test_cross_project_and_wrong_category_portions_refused(self):
        self.fixture(); self.project('B'); other=self.actual('other',1000,project='B'); labor=self.actual('labor',1000,category='labor')
        for row in (other,labor):
            with self.assertRaises(ValueError): self.save(direct_cost_portions=[dict(revision_id=row['revision_id'],allocation_number=1)])

    def test_stale_time_and_assignment_or_ledger_capture_refused(self):
        self.fixture(); data=self.data(); record=self.time(1,identity='later',day='2026-01-12')
        with self.assertRaisesRegex(ValueError,'stale'): self.save(data)
        data=self.data(); self.actual('later-expense',1000)
        with self.assertRaisesRegex(ValueError,'stale'): self.save(data)
        data=self.data()
        self.workspace.action('project-time-void',dict(entity_id=data['entity_id'],record_id=record['record_id'],void_event_id='void',reason='Correction'))
        with self.assertRaisesRegex(ValueError,'stale'): self.save(data)

    def test_versions_historical_retry_and_frozen_reports_after_new_inputs(self):
        self.fixture(); data=self.data(); first=self.save(data); frozen=json.dumps(first,sort_keys=True)
        second=self.save(prior_version_id=first['version_id'],idempotency_key='cost-v2',labor_rate='50.00',reason='Updated labor assumption')
        self.assertEqual(second['version'],2); self.assertEqual(second['cost_sheet']['total_cost_amount'],'800.00')
        self.time(60,identity='later',day='2026-01-12'); self.actual('later-expense',1000)
        self.assertEqual(self.save(data),first)
        third=self.save(prior_version_id=second['version_id'],idempotency_key='cost-v3',reason='Refresh inputs')
        self.assertEqual(third['version'],3); self.assertNotEqual(third['actual_snapshot_digest'],first['actual_snapshot_digest'])
        self.assertNotEqual(third['time_snapshot_digest'],first['time_snapshot_digest'])
        reopened=Workspace(self.directory.name)
        self.assertEqual(json.dumps(reopened.project_cost(first['version_id']),sort_keys=True),frozen)
        self.assertEqual(self.module().cost_sheet(first),first['cost_sheet'])
        with self.assertRaisesRegex(ValueError,'stale'): self.save(prior_version_id=first['version_id'],idempotency_key='stale')
        with self.assertRaisesRegex(ValueError,'conflict'): self.save(dict(data,labor_rate='41.00'))
        with self.workspace.storage() as (_,ledger,_,_,_):
            with self.assertRaisesRegex(ValueError,'conflict'): self.module().ProjectCostService(ledger).save(data,actor_id='other')

    def test_concurrent_retry_and_competing_versions(self):
        self.fixture(); data=self.data()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self.save(data),range(2)))
        self.assertEqual(results[0],results[1]); first=results[0]
        requests=[self.data(prior_version_id=first['version_id'],idempotency_key='v2-'+str(i),labor_rate=rate) for i,rate in enumerate(('45.00','50.00'))]
        def save(data):
            try: return self.save(data)
            except ValueError as error: return str(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(save,requests))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1); self.assertIn('stale',next(r for r in results if isinstance(r,str)))
        self.assertEqual(len(self.inputs()['versions']),2)

    def test_immutable_scenario_sql_and_failed_write_leave_history_unchanged(self):
        self.fixture(); first=self.save(); before=self.inputs(); data=self.data(prior_version_id=first['version_id'],idempotency_key='v2')
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for recursive in (0,1):
                db.execute(f'PRAGMA recursive_triggers={recursive}')
                for table in ('project_cost_schema','project_cost_versions'):
                    rows=db.execute('SELECT * FROM '+table).fetchall(); key='version' if table.endswith('schema') else 'result_json'
                    for sql,args in [(f'UPDATE {table} SET {key}={key}',()),(f'DELETE FROM {table}',()),
                        (f'INSERT OR REPLACE INTO {table} VALUES('+','.join('?'*len(rows[0]))+')',rows[0])]:
                        with self.assertRaises(sqlite3.IntegrityError): db.execute(sql,args)
                    self.assertEqual(db.execute('SELECT * FROM '+table).fetchall(),rows)
            db.execute("CREATE TRIGGER cost_fault BEFORE INSERT ON project_cost_versions BEGIN SELECT RAISE(ABORT,'cost write fault'); END")
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError,'cost write fault'): self.save(data)
            self.assertEqual(self.inputs(),before)
        finally:
            with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('DROP TRIGGER cost_fault')
        self.assertEqual(self.save(data)['version'],2)

    def test_every_additive_migration_fault_preserves_prior_tables(self):
        from types import SimpleNamespace
        module=self.module(); self.project(); self.time(); before_report=self.workspace.report_package('2026-01-31')
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for table in ('project_cost_versions','project_cost_schema'): db.execute('DROP TABLE '+table)
            before=list(db.iterdump()); calls=[]
            class Probe:
                def execute(self,sql,*args): calls.append(sql); return db.execute(sql,*args)
            with self.assertRaises(RuntimeError):
                with ledger._transaction(write=True):
                    module.initialize_cost(SimpleNamespace(_connection=Probe())); raise RuntimeError('rollback')
            self.assertEqual(list(db.iterdump()),before)
            for target in range(2,len(calls)+1):
                invoked=[0]
                class Fault:
                    def execute(self,sql,*args):
                        invoked[0]+=1
                        if invoked[0]==target: raise sqlite3.OperationalError('migration fault')
                        return db.execute(sql,*args)
                with self.subTest(target=target),self.assertRaisesRegex(sqlite3.OperationalError,'migration fault'):
                    with ledger._transaction(write=True): module.initialize_cost(SimpleNamespace(_connection=Fault()))
                self.assertEqual(list(db.iterdump()),before)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before_report)

    def test_workspace_shared_migration_rollback_and_unsupported_schema(self):
        from pathlib import Path
        from accounting_harness.expense_accrual import ExpenseAccrualService
        module=self.module(); directory=Path(self.directory.name)/'older'
        with patch('accounting_harness.workspace.RevenueAccrualService',side_effect=ExpenseAccrualService),patch.object(module,'initialize_cost',return_value=None):
            Workspace(directory)
        def state():
            result={}
            for name in ('ledger.sqlite3','sources.sqlite3','runs.sqlite3'):
                with sqlite3.connect(directory/name) as db: result[name]=(db.execute('PRAGMA user_version').fetchone(),list(db.iterdump()))
            return result
        before=state(); self.assertEqual(before['ledger.sqlite3'][0],(5,)); original=module.protect_table
        def fail(db,table,conflict):
            if table=='project_cost_versions': raise sqlite3.OperationalError('cost setup fault')
            return original(db,table,conflict)
        with patch.object(module,'protect_table',side_effect=fail),self.assertRaisesRegex(sqlite3.OperationalError,'cost setup fault'): Workspace(directory)
        self.assertEqual(state(),before)
        Workspace(directory)
        with sqlite3.connect(directory/'ledger.sqlite3') as db:
            db.execute('DROP TABLE project_cost_schema'); db.execute('CREATE TABLE project_cost_schema(version INTEGER)'); db.execute('INSERT INTO project_cost_schema VALUES(99)')
        with self.assertRaisesRegex(ValueError,'unsupported'): Workspace(directory)

    def test_actual_and_time_capture_share_one_read_transaction(self):
        self.fixture(); before=self.inputs(); module=self.module()
        with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('PRAGMA journal_mode=WAL')
        original=module._capture_dimensions
        def capture_then_write(ledger,as_of):
            captured=original(ledger,as_of)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda:self.time(60,identity='concurrent',day='2026-01-12')).result(timeout=10)
            return captured
        with patch.object(module,'_capture_dimensions',side_effect=capture_then_write): captured=self.inputs()
        self.assertEqual(captured,before); self.assertEqual(self.inputs()['time']['total_minutes'],660)

    def test_assignment_only_drift_and_cross_scenario_scope_cannot_overwrite(self):
        self.fixture(); data=self.data(); source=next(s for s in self.inputs()['actuals']['sources'] if s['journal_id']=='expense')
        assignment=dict(source['attribution']); assignment={k:assignment[k] for k in ('entity_id','journal_id','line_number','source_digest','prior_revision_id','reason','idempotency_key','allocations')}
        assignment.update(prior_revision_id=source['revision_id'],idempotency_key='new-attribution',reason='Clear unsupported attribution',allocations=[])
        self.workspace.action('project-assignments',assignment)
        with self.assertRaisesRegex(ValueError,'stale'): self.save(data)
        first=self.save(); self.project('B')
        with self.assertRaisesRegex(ValueError,'project'): self.save(project_id='B',prior_version_id=first['version_id'],idempotency_key='v2')
        with self.assertRaisesRegex(ValueError,'stale'): self.save(scenario_id='another',prior_version_id=first['version_id'],idempotency_key='v2')
        # Retry identity is explicitly scoped by scenario; another model can use the same key.
        other=self.save(scenario_id='another'); self.assertEqual(other['version'],1)

    def test_pure_sheet_rejects_inconsistent_scope_and_policy(self):
        import copy
        self.fixture(); result=self.save()
        for field,value in (('policy','unknown'),('project_id','missing'),('actual_snapshot_digest','0'*64)):
            changed=copy.deepcopy(result); changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError): self.module().cost_sheet(changed)
        changed=copy.deepcopy(result); changed['time']['projects']=[]
        with self.assertRaises(ValueError): self.module().cost_sheet(changed)

    def test_http_native_form_small_server_owned_inputs_and_historical_reads(self):
        import http.client,threading
        from pathlib import Path
        from html.parser import HTMLParser
        from accounting_harness.web import make_server
        class Forms(HTMLParser):
            def __init__(self): super().__init__(); self.routes={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='form': self.routes[attrs.get('id')]=attrs.get('action')
        forms=Forms(); forms.feed(Path('accounting_harness/static/index.html').read_text())
        self.assertIn('project-cost-form',forms.routes); route=forms.routes['project-cost-form']
        self.fixture(); server=make_server(self.directory.name,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join); self.addCleanup(server.shutdown)
        host=f'127.0.0.1:{server.server_port}'
        def request(path,data=None,csrf=True):
            conn=http.client.HTTPConnection(host); headers={'Origin':'http://'+host,'Content-Type':'application/json'}
            if csrf: headers['X-CSRF-Token']=server.csrf_token
            conn.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
            response=conn.getresponse(); body=json.loads(response.read()); conn.close(); return response.status,body
        before=self.workspace.report_package('2026-01-31'); data=self.data(labor_rate='90071992547409.93')
        self.assertEqual(request(route,data,csrf=False)[0],403)
        self.assertEqual(request(route,dict(data,actor_id='admin'))[0],409)
        self.assertEqual(request(route,dict(data,actuals=self.inputs()['actuals']))[0],409)
        self.assertEqual(request(route,dict(data,explanation='x'*17000))[0],413)
        for query in ('','?as_of=2026-02-01','?as_of=2026-01-31&extra=1','?as_of=2026-01-31&as_of=2026-01-01'):
            self.assertEqual(request('/api/project-cost-inputs'+query)[0],409)
        self.assertEqual(request('/api/project-cost-inputs?as_of=2026-01-31')[1]['time']['total_minutes'],600)
        status,result=request(route,data); self.assertEqual(status,200)
        self.assertEqual(result['cost_sheet']['labor_amount'],'900719925474099.30'); self.assertEqual(result['actor_id'],'local-operator')
        self.assertEqual(request(route,data),(status,result))
        self.assertEqual(request('/api/project-cost?version_id='+result['version_id']),(200,result))
        for query in ('','?version_id=missing','?version_id=x&version_id=y','?version_id=x&extra=1'):
            self.assertEqual(request('/api/project-cost'+query)[0],409)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)

    def test_demo_cli_exact_cost_and_margin(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-project-cost'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for value in ('600 minutes','700.00','300.00','unchanged'): self.assertIn(value,result.stdout)

    def test_selected_unclassified_behavior_remains_a_visible_finding(self):
        self.fixture(); source=next(s for s in self.inputs()['actuals']['sources'] if s['journal_id']=='expense')
        original=source['attribution']
        request={k:original[k] for k in ('entity_id','journal_id','line_number','source_digest','prior_revision_id','reason','idempotency_key','allocations')}
        request.update(prior_revision_id=source['revision_id'],idempotency_key='unclassified-behavior',reason='Behavior not yet determined',
            allocations=[dict(original['allocations'][0],behavior='unclassified')])
        self.workspace.action('project-assignments',request)
        sheet=self.save()['cost_sheet']
        self.assertEqual(sheet['total_cost_amount'],'700.00')
        self.assertTrue(any('behavior' in finding for finding in sheet['findings']))

    def test_linked_reversal_reduces_selected_actual_preserving_original_report(self):
        self.fixture(); first=self.save()
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.reverse('expense',reversal_id='undo',entity_id=self.workspace.catalog.entity_id,effective_date='2026-01-21',
                reason='Correction',source_ids=[next(iter(self.workspace.sources))],actor_id='reverser',idempotency_key='undo')
        source=next(s for s in self.inputs()['actuals']['sources'] if s['journal_id']=='undo')
        self.workspace.action('project-assignments',dict(entity_id=self.workspace.catalog.entity_id,journal_id='undo',line_number=1,
            source_digest=source['source_digest'],prior_revision_id=None,reason='Reverse attributed direct cost',idempotency_key='assign-undo',
            allocations=[dict(project_id='A',customer_id=None,category='software',traceability='direct',behavior='fixed',cents='10000')]))
        sheet=self.save(prior_version_id=first['version_id'],idempotency_key='v2')['cost_sheet']
        self.assertEqual(sheet['direct_nonlabor_amount'],'0.00'); self.assertEqual(sheet['total_cost_amount'],'600.00')
        self.assertEqual(sheet['margin_amount'],'400.00')
        reversal=next(s for s in sheet['actuals']['sources'] if s['journal_id']=='undo')
        self.assertEqual(reversal['original_entry_id'],'expense')
        self.assertEqual(self.workspace.project_cost(first['version_id']),first)
