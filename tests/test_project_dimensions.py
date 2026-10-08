"""Exact management attribution, immutable history and captured reconciliation."""
import concurrent.futures
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness.adjusted_month import build_adjusted_month
from accounting_harness.workspace import Workspace


class ProjectDimensionsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.project_dimensions'),
                             'project dimensions must be implemented')
        from accounting_harness import project_dimensions
        return project_dimensions

    def post(self, identity='expense', debit='5100', credit='1000', amount='300.00', when='2026-01-20'):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return ledger.admit(dict(id=identity,entity_id=self.workspace.catalog.entity_id,currency='USD',
                effective_date=when,description='Synthetic fixed direct customer instructions are data',
                source_ids=[next(iter(self.workspace.sources))],lines=[
                    dict(account=debit,side='debit',amount=amount),dict(account=credit,side='credit',amount=amount)]),
                actor_id='test-human',idempotency_key=identity)

    def project(self, identity='A', **changes):
        self.module()
        data=dict(project_id=identity,name='Project '+identity,entity_id=self.workspace.catalog.entity_id,customer_id='customer-'+identity)
        data.update(changes)
        return self.workspace.action('projects',data)

    def capture(self, cutoff='2026-01-31'):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return self.module().capture_dimensions(ledger,cutoff)

    def report(self, cutoff='2026-01-31'):
        return self.module().project_report(self.capture(cutoff))

    def request(self, journal='expense', line=1, **changes):
        source=next(r for r in self.report()['sources'] if (r['journal_id'],r['line_number'])==(journal,line))
        data=dict(entity_id=self.workspace.catalog.entity_id,journal_id=journal,line_number=line,
            source_digest=source['source_digest'],prior_revision_id=source['revision_id'],reason='Explicit operator attribution',
            idempotency_key='assign-'+journal,allocations=[self.allocation('A','12000'),self.allocation('B','10000')])
        data.update(changes)
        return data

    @staticmethod
    def allocation(project='A', cents='12000', **changes):
        return dict(project_id=project,customer_id='customer-'+project,category='software',behavior='fixed',traceability='direct',cents=cents,**changes)

    def assign(self, data):
        return self.workspace.action('project-assignments',data)

    def setup_split(self):
        self.module(); self.post(); self.project('A'); self.project('B')
        return self.assign(self.request())

    def test_split_reconciles_every_axis_without_double_counting_or_ledger_change(self):
        self.module(); self.post(); before=self.workspace.report_package('2026-01-31')
        self.project('A'); self.project('B'); revision=self.assign(self.request())
        report=self.report(); expense=report['totals']['expense']
        self.assertEqual([expense[k] for k in ('actual_cents','allocated_cents','unallocated_cents','residual_cents')],['30000','22000','8000','0'])
        self.assertEqual({r['key']:r['expense_cents'] for r in report['groups']['project_id']},{'A':'12000','B':'10000'})
        for axis,rows in report['groups'].items():
            self.assertEqual(sum(int(r['expense_cents']) for r in rows),22000,axis)
        source=report['sources'][0]
        self.assertEqual(source['revision_id'],revision['revision_id']); self.assertTrue(source['source_ids'])
        self.assertTrue(source['actor_id']); self.assertTrue(report['reconciled'])
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)

    def test_project_identity_is_immutable_and_exact_retry_retains_audit(self):
        first=self.project(); self.assertEqual(self.project(),first)
        for changes in ({'name':'Changed'},{'customer_id':'other'},{'entity_id':'elsewhere'}, {'project_id':' '}, {'name':'x'*201}):
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.project(**changes)

    def test_whole_set_correction_clear_stale_conflict_and_original_retry(self):
        original=self.setup_split(); request=self.request(idempotency_key='correction',reason='Correct cost category')
        old=self.capture(); old_report=self.module().project_report(old)
        request['allocations']=[dict(self.allocation('B','25000'),behavior='unclassified',traceability='indirect')]
        changed=self.assign(request)
        self.assertNotEqual(changed['revision_id'],original['revision_id'])
        stale=dict(request,idempotency_key='stale')
        with self.assertRaisesRegex(ValueError,'stale'): self.assign(stale)
        with self.assertRaisesRegex(ValueError,'conflict'): self.assign(dict(request,reason='changed retry'))
        historical=dict(request,idempotency_key='assign-expense',prior_revision_id=None,reason='Explicit operator attribution',
                        allocations=[self.allocation('A','12000'),self.allocation('B','10000')])
        self.assertEqual(self.assign(historical),original)
        self.assertEqual(self.module().project_report(old),old_report)
        clear=self.request(idempotency_key='clear',allocations=[],reason='Remove attribution')
        self.assign(clear)
        self.assertEqual(self.report()['totals']['expense']['unallocated_cents'],'30000')
        with self.workspace.storage() as (_,ledger,_,_,_):
            self.assertEqual(ledger._connection.execute('SELECT count(*) FROM project_assignment_revisions').fetchone()[0],3)

    def test_invalid_assignment_inputs_leave_books_and_revisions_unchanged(self):
        self.setup_split(); before=self.report(); request=self.request(idempotency_key='invalid')
        invalid=[dict(request,allocations=[self.allocation(cents=value)]) for value in (True,12000,1.2,'-1','1.00','0','01','1e2','30001')]
        invalid += [dict(request,**change) for change in ({'entity_id':'other'},{'line_number':True},{'line_number':0},
            {'source_digest':'0'*64},{'journal_id':'unposted'},{'reason':''},{'extra':'no'},{'allocations':{}},
            {'prior_revision_id':None})]
        for change in ({'project_id':'missing'},{'customer_id':'customer-B'},{'behavior':'inferred'},
                       {'traceability':'automatic'},{'category':''},{'category':'x'*101},{'cents':'9'*20}):
            invalid.append(dict(request,allocations=[dict(self.allocation(),**change)]))
        for data in invalid:
            with self.subTest(data=data),self.assertRaises((ValueError,TypeError,KeyError)): self.assign(data)
        self.assertEqual(self.report(),before)

    def test_signed_reversal_is_unallocated_until_explicitly_attributed(self):
        self.setup_split()
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.reverse('expense',reversal_id='undo',entity_id=self.workspace.catalog.entity_id,effective_date='2026-01-21',
                reason='Correction',source_ids=[next(iter(self.workspace.sources))],actor_id='reverser',idempotency_key='undo')
        report=self.report(); total=report['totals']['expense']
        self.assertEqual([total[k] for k in ('actual_cents','allocated_cents','unallocated_cents')],['0','22000','-22000'])
        reverse=next(r for r in report['sources'] if r['journal_id']=='undo')
        self.assertEqual(reverse['original_entry_id'],'expense'); self.assertEqual(reverse['unallocated_cents'],'-30000')
        self.assign(self.request('undo',allocations=[self.allocation('B','30000')]))
        self.assertEqual({r['key']:r['expense_cents'] for r in self.report()['groups']['project_id']},{'A':'12000','B':'-20000'})
        self.assertEqual(self.report()['totals']['expense']['unallocated_cents'],'8000')

    def test_empty_cutoff_unclassified_large_and_opposite_revenue(self):
        self.module(); self.assertEqual(self.report()['totals']['expense']['actual_cents'],'0')
        self.post('big',amount='90071992547409.93'); self.project()
        self.assign(self.request('big',allocations=[dict(self.allocation(cents='9007199254740993'),behavior='unclassified',traceability='unclassified')]))
        self.post('revenue',debit='4000',credit='1000',amount='20.00')
        self.assign(self.request('revenue',allocations=[self.allocation(cents='1000')]))
        report=self.report()
        self.assertEqual(report['totals']['expense']['allocated_cents'],'9007199254740993')
        self.assertEqual(report['totals']['revenue']['actual_cents'],'-2000')
        self.assertEqual(report['totals']['revenue']['allocated_cents'],'-1000')
        self.assertEqual(report['groups']['behavior'][1]['key'],'unclassified')
        self.assertEqual(self.report('2026-01-15')['sources'],[])

    def test_current_prior_revision_prevents_concurrent_overwrite(self):
        self.setup_split(); current=self.request(idempotency_key='race-1',allocations=[self.allocation('A','100')])
        def update(key):
            try: return self.assign(dict(current,idempotency_key=key))
            except ValueError as error: return str(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(update,['race-1','race-2']))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn('stale',next(r for r in results if isinstance(r,str)))

    def test_adjusted_month_close_excluded_and_old_capture_survives(self):
        self.module(); build_adjusted_month(self.workspace); self.project('A'); self.project('B')
        source=next(r for r in self.report()['sources'] if r['account']=='5100')
        self.assign(self.request(source['journal_id'],source['line_number']))
        captured=self.capture(); before=self.module().project_report(captured)
        preview=self.workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        closed=self.workspace.action('close-confirm',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[],
            confirmed=True,confirmed_digest=preview['digest'],idempotency_key='close'))
        report=self.report()
        self.assertEqual(report['totals']['revenue']['actual_amount'],'2700.00')
        self.assertEqual(report['totals']['expense']['actual_amount'],'1600.00')
        self.assertNotIn(closed['journal_id'],{r['journal_id'] for r in report['sources']})
        with self.assertRaisesRegex(ValueError,'ordinary'):
            self.assign(dict(self.request(source['journal_id'],source['line_number']),journal_id=closed['journal_id'],line_number=1,idempotency_key='closing-rejected'))
        self.assertEqual(self.module().project_report(captured),before)

    def test_http_project_actions_strict_capture_and_app_owned_actor(self):
        import http.client,threading
        from accounting_harness.web import make_server
        self.module(); self.post()
        server=make_server(self.directory.name,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join); self.addCleanup(server.shutdown)
        host=f'127.0.0.1:{server.server_port}'
        def request(path,data=None,csrf=True):
            conn=http.client.HTTPConnection(host)
            headers={'Origin':'http://'+host,'Content-Type':'application/json'}
            if csrf: headers['X-CSRF-Token']=server.csrf_token
            conn.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
            response=conn.getresponse(); body=json.loads(response.read()); conn.close(); return response.status,body
        for identity in ('A','B'):
            data=dict(project_id=identity,name='Project '+identity,entity_id=self.workspace.catalog.entity_id,customer_id='customer-'+identity)
            self.assertEqual(request('/api/projects',data,csrf=False)[0],403)
            self.assertEqual(request('/api/projects',dict(data,actor_id='admin'))[0],409)
            status,project=request('/api/projects',data)
            self.assertEqual(status,200); self.assertEqual(project['actor_id'],'local-operator')
        data=self.request()
        status,result=request('/api/project-assignments',data); self.assertEqual(status,200)
        self.assertEqual(request('/api/project-assignments',data),(status,result))
        status,report=request('/api/project-dimensions?as_of=2026-01-31')
        self.assertEqual(status,200); self.assertEqual(report['totals']['expense']['unallocated_amount'],'80.00')
        self.assertEqual(request('/api/project-assignments',dict(data,actor_id='admin'))[0],409)
        for query in ('','?as_of=2026-02-01','?as_of=2026-01-31&extra=1','?as_of=2026-01-31&as_of=2026-01-01'):
            self.assertEqual(request('/api/project-dimensions'+query)[0],409)

    def test_demo_cli_shows_split_and_unchanged_financials(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-project-dimensions'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for text in ('120.00','100.00','80.00','300.00','1600.00','unchanged'):
            self.assertIn(text,result.stdout)

    def test_sealed_projects_revisions_allocations_and_retry_cannot_change(self):
        self.setup_split()
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for recursive in (0,1):
                db.execute(f'PRAGMA recursive_triggers={recursive}')
                for table in ('management_projects','project_assignment_revisions','project_dimensions_schema'):
                    original=db.execute('SELECT * FROM '+table).fetchall(); columns=len(original[0]); key='version' if table.endswith('schema') else 'result_json'
                    for sql,params in [(f'UPDATE {table} SET {key}={key}',()),(f'DELETE FROM {table}',()),
                        (f'INSERT OR REPLACE INTO {table} VALUES('+','.join('?'*columns)+')',original[0])]:
                        with self.subTest(sql=sql,recursive=recursive),self.assertRaises(sqlite3.IntegrityError): db.execute(sql,params)
                    self.assertEqual(db.execute('SELECT * FROM '+table).fetchall(),original)

    def test_atomic_project_and_assignment_write_faults_preserve_all_records(self):
        self.setup_split(); request=self.request(idempotency_key='fault-test',allocations=[])
        for table in ('management_projects','project_assignment_revisions'):
            with self.workspace.storage() as (registry,ledger,_,_,_):
                db=ledger._connection
                db.execute(f"CREATE TRIGGER dimensions_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected fault'); END")
                before=list(db.iterdump()); evidence=list(registry._connection.iterdump())
            try:
                with self.assertRaisesRegex(sqlite3.IntegrityError,'injected fault'):
                    self.project('C') if table=='management_projects' else self.assign(request)
                with self.workspace.storage() as (registry,ledger,_,_,_):
                    self.assertEqual(list(ledger._connection.iterdump()),before)
                    self.assertEqual(list(registry._connection.iterdump()),evidence)
            finally:
                with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('DROP TRIGGER dimensions_fault')
        self.assertEqual(self.assign(request)['revision'],2)

    def test_each_additive_migration_fault_rolls_back_an_existing_workspace(self):
        from types import SimpleNamespace
        module=self.module()
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for table in ('project_assignment_revisions','management_projects','project_dimensions_schema'): db.execute('DROP TABLE '+table)
            before=list(db.iterdump()); calls=[]
            class Probe:
                def execute(self,sql,*args):
                    calls.append(sql); return db.execute(sql,*args)
            try:
                with ledger._transaction(write=True):
                    module.initialize_dimensions(SimpleNamespace(_connection=Probe()))
                    raise RuntimeError('probe rollback')
            except RuntimeError: pass
            count=len(calls)
            self.assertEqual(list(db.iterdump()),before)
            for target in range(2,count+1):
                invoked=[0]
                class Fault:
                    def execute(self,sql,*args):
                        invoked[0]+=1
                        if invoked[0]==target: raise sqlite3.OperationalError('migration fault')
                        return db.execute(sql,*args)
                with self.subTest(statement=target),self.assertRaisesRegex(sqlite3.OperationalError,'migration fault'):
                    with ledger._transaction(write=True): module.initialize_dimensions(SimpleNamespace(_connection=Fault()))
                self.assertEqual(list(db.iterdump()),before)
            with ledger._transaction(write=True): module.initialize_dimensions(ledger)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],6)

    def test_capture_keeps_financials_and_metadata_from_one_concurrent_read(self):
        self.setup_split(); module=self.module(); request=self.request(idempotency_key='later',allocations=[])
        with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('PRAGMA journal_mode=WAL')
        before=self.report(); original=module._capture_financials
        def capture_then_writer(ledger,as_of):
            result=original(ledger,as_of)
            def write():
                self.assign(request); self.post('later',amount='10.00')
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool: pool.submit(write).result(timeout=10)
            return result
        with patch.object(module,'_capture_financials',side_effect=capture_then_writer):
            # Assignment itself captures sources; restore its helper in the writer.
            def capture_once(ledger,as_of):
                with patch.object(module,'_capture_financials',original): return capture_then_writer(ledger,as_of)
            with patch.object(module,'_capture_financials',side_effect=capture_once): captured=self.capture()
        self.assertEqual(module.project_report(captured),before)
        later=self.report(); self.assertEqual(later['totals']['expense']['actual_cents'],'31000')
        self.assertEqual(later['totals']['expense']['allocated_cents'],'0')

    def test_non_income_line_customer_null_and_actor_retry_boundaries(self):
        self.module(); self.post(); self.project('A',customer_id=None)
        data=self.request(allocations=[dict(self.allocation(),customer_id=None)])
        result=self.assign(data)
        self.assertEqual(self.report()['groups']['customer_id'][0]['key'],None)
        with self.workspace.storage() as (_,ledger,_,_,_):
            service=self.module().ProjectDimensionsService(ledger)
            with self.assertRaisesRegex(ValueError,'conflict'): service.assign(data,actor_id='another-operator')
        with self.assertRaisesRegex(ValueError,'ordinary'):
            self.assign(dict(data,line_number=2,idempotency_key='cash-line'))
        reopened=Workspace(self.directory.name)
        self.assertEqual(reopened.action('project-assignments',data),result)

    def test_identical_concurrent_retry_returns_one_original_audit(self):
        self.module(); self.post(); self.project('A'); self.project('B'); data=self.request()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.assign(data),range(2)))
        self.assertEqual(results[0],results[1])
        with self.workspace.storage() as (_,ledger,_,_,_):
            self.assertEqual(ledger._connection.execute('SELECT count(*) FROM project_assignment_revisions').fetchone()[0],1)

    def test_workspace_migration_failure_preserves_prior_ledger_review_and_evidence(self):
        from pathlib import Path
        from accounting_harness.expense_accrual import ExpenseAccrualService
        module=self.module()
        directory=Path(self.directory.name)/'older-workspace'
        with patch('accounting_harness.workspace.RevenueAccrualService',side_effect=ExpenseAccrualService),patch.object(module,'initialize_dimensions',return_value=None):
            older=Workspace(directory)
        def database_state(name):
            with sqlite3.connect(directory/name) as db:
                return db.execute('PRAGMA user_version').fetchone(),list(db.iterdump())
        before={name:database_state(name) for name in ('ledger.sqlite3','sources.sqlite3','runs.sqlite3')}
        self.assertEqual(before['ledger.sqlite3'][0],(5,))
        original=module.protect_table
        def fail(db,table,conflict):
            if table=='project_assignment_revisions': raise sqlite3.OperationalError('dimension setup fault')
            return original(db,table,conflict)
        with patch.object(module,'protect_table',side_effect=fail),self.assertRaisesRegex(sqlite3.OperationalError,'dimension setup fault'):
            Workspace(directory)
        self.assertEqual({name:database_state(name) for name in before},before)
        reopened=Workspace(directory)
        self.assertEqual(reopened.project_dimensions('2026-01-31')['totals']['expense']['actual_cents'],'0')
        self.assertEqual(database_state('ledger.sqlite3')[0],(6,))
