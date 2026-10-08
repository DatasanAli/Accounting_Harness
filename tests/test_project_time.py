"""Supported integer-minute time, immutable correction and financial isolation."""
import concurrent.futures
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness.workspace import Workspace


class ProjectTimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)
        for identity in ('A', 'B'):
            self.workspace.action('projects', dict(project_id=identity, name='Project '+identity,
                entity_id=self.workspace.catalog.entity_id, customer_id=None))

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.project_time'), 'auditable project time must be implemented')
        from accounting_harness import project_time
        return project_time

    def data(self, **changes):
        return dict(dict(entity_id=self.workspace.catalog.entity_id, project_id='A', worker_id='worker-1',
            time_event_id='service-1', work_date='2026-01-10', start_minute=540, end_minute=840,
            replaces_record_id=None), **changes)

    def record(self, **changes):
        self.module()
        return self.workspace.action('project-time', self.data(**changes))

    def void_data(self, record, **changes):
        return dict(dict(entity_id=self.workspace.catalog.entity_id, record_id=record['record_id'],
            void_event_id='void-1', reason='Correct supported service interval'), **changes)

    def void(self, record, **changes):
        return self.workspace.action('project-time-void', self.void_data(record, **changes))

    def capture(self, as_of='2026-01-31'):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return self.module().capture_time(ledger, as_of)

    def report(self, as_of='2026-01-31'):
        return self.module().time_report(self.capture(as_of))

    def test_ten_hours_repeat_original_audit_and_no_financial_change(self):
        self.module()
        before=self.workspace.report_package('2026-01-31'); dimensions=self.workspace.project_dimensions('2026-01-31')
        first=self.record(); second=self.record(time_event_id='service-2', work_date='2026-01-11')
        self.assertEqual(self.record(), first)
        self.assertEqual(self.record(time_event_id='service-2', work_date='2026-01-11'), second)
        report=self.report()
        self.assertEqual(report['total_minutes'], 600); self.assertEqual(report['duration'], '10h 0m')
        self.assertEqual(len(report['active_intervals']), 2)
        self.assertEqual(report['policy'], 'service-time-v1'); self.assertTrue(report['reconciled'])
        self.assertEqual(self.workspace.report_package('2026-01-31'), before)
        self.assertEqual(self.workspace.project_dimensions('2026-01-31'), dimensions)

    def test_invalid_inputs_leave_time_and_books_unchanged(self):
        self.module(); before=self.report()
        changes=[{k:v} for k in ('start_minute','end_minute') for v in (True,False,1.5,'540',None,-1,1441)]
        changes += [{'start_minute':840}, {'start_minute':900}, {'start_minute':1440}, {'end_minute':0},
                    {'work_date':'2026-02-01'}, {'work_date':'2026-01-32'}, {'work_date':'2026-1-10'},
                    {'project_id':'missing'}, {'entity_id':'other'}, {'worker_id':''}, {'worker_id':'x'*201},
                    {'time_event_id':' '}, {'time_event_id':'x'*201}, {'actor_id':'admin'}, {'replaces_record_id':'missing'}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError): self.record(**change)
        self.assertEqual(self.report(), before)

    def test_event_scope_is_worker_and_entity_independent_of_project(self):
        first=self.record()
        for change in ({'project_id':'B'}, {'end_minute':841}, {'work_date':'2026-01-11'}):
            with self.assertRaisesRegex(ValueError, 'conflict'): self.record(**change)
        other=self.record(worker_id='worker-2')
        self.assertNotEqual(first['record_id'],other['record_id'])
        with self.workspace.storage() as (_,ledger,_,_,_):
            # Exact event retry returns original audit even through another operator.
            self.assertEqual(self.module().ProjectTimeService(ledger).record(self.data(), actor_id='second-human'), first)
        self.assertEqual(self.report()['total_minutes'],600)

    def test_overlap_is_cross_project_and_adjacent_intervals_are_allowed(self):
        self.record()
        for start,end in ((539,541),(540,840),(600,700),(839,900),(0,1440)):
            with self.subTest(start=start,end=end),self.assertRaisesRegex(ValueError,'overlap'):
                self.record(project_id='B',time_event_id=f'overlap-{start}-{end}',start_minute=start,end_minute=end)
        self.record(time_event_id='before',start_minute=0,end_minute=540)
        self.record(time_event_id='after',project_id='B',start_minute=840,end_minute=1440)
        self.assertEqual(self.report()['total_minutes'],1440)

    def test_void_retry_replacement_preserves_captured_history(self):
        first=self.record(); self.record(time_event_id='service-2',work_date='2026-01-11')
        captured=self.capture(); before=self.module().time_report(captured)
        void=self.void(first)
        self.assertEqual(self.void(first),void)
        retry=self.record(); self.assertEqual(retry['record_id'],first['record_id'])
        self.assertEqual(retry['recorded_at'],first['recorded_at']); self.assertEqual(retry['status'],'voided')
        self.assertEqual(self.report()['total_minutes'],300)
        replacement=self.record(time_event_id='corrected',start_minute=600,end_minute=900,replaces_record_id=first['record_id'])
        self.assertEqual(replacement['replaces_record_id'],first['record_id'])
        report=self.report(); self.assertEqual(report['total_minutes'],600)
        self.assertEqual(len(report['records']),3); self.assertEqual(len(report['voids']),1)
        self.assertEqual(self.module().time_report(captured),before)
        self.assertEqual(report['recorded_minutes']-report['voided_minutes'],600)
        reopened=Workspace(self.directory.name)
        self.assertEqual(reopened.project_time('2026-01-31'),report)
        self.assertEqual(reopened.action('project-time',self.data())['status'],'voided')

    def test_void_requires_reason_active_record_and_immutable_retry(self):
        first=self.record()
        for change in ({'reason':''},{'entity_id':'other'},{'record_id':'missing'},{'actor_id':'admin'}):
            with self.assertRaises(ValueError): self.void(first,**change)
        self.void(first)
        with self.assertRaisesRegex(ValueError,'conflict'): self.void(first,reason='changed')
        with self.assertRaisesRegex(ValueError,'voided'): self.void(first,void_event_id='again')
        with self.workspace.storage() as (_,ledger,_,_,_):
            with self.assertRaisesRegex(ValueError,'conflict'):
                self.module().ProjectTimeService(ledger).void(self.void_data(first),actor_id='other-human')

    def test_replacement_must_reference_voided_same_worker_once(self):
        first=self.record()
        with self.assertRaisesRegex(ValueError,'voided'):
            self.record(time_event_id='new',work_date='2026-01-12',replaces_record_id=first['record_id'])
        self.void(first)
        with self.assertRaisesRegex(ValueError,'worker'):
            self.record(time_event_id='new',worker_id='other',replaces_record_id=first['record_id'])
        self.record(time_event_id='new',replaces_record_id=first['record_id'])
        with self.assertRaisesRegex(ValueError,'replacement'):
            self.record(time_event_id='another',work_date='2026-01-12',replaces_record_id=first['record_id'])

    def test_concurrent_exact_duplicate_and_cross_project_overlap(self):
        self.module()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.record(),range(2)))
        self.assertEqual(results[0],results[1]); self.assertEqual(self.report()['total_minutes'],300)
        def overlapping(identity):
            try: return self.record(time_event_id=identity,project_id=identity,work_date='2026-01-11')
            except ValueError as error: return str(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(overlapping,('A','B')))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn('overlap',next(r for r in results if isinstance(r,str)))
        self.assertEqual(self.report()['total_minutes'],600)

    def test_cutoff_exact_partial_hour_and_unsupported_policy(self):
        self.record(start_minute=0,end_minute=61)
        self.assertEqual(self.report('2026-01-09')['total_minutes'],0)
        self.assertEqual(self.report('2026-01-10')['duration'],'1h 1m')
        self.assertEqual(self.report()['groups'][0]['total_minutes'],61)
        with self.assertRaises(ValueError): self.report('2026-02-01')
        from dataclasses import replace
        with self.assertRaises(ValueError): self.module().time_report(replace(self.capture(),policy='unsupported'))

    def test_immutable_time_void_retry_rows_and_sql_references(self):
        first=self.record(); self.void(first)
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for recursive in (0,1):
                db.execute(f'PRAGMA recursive_triggers={recursive}')
                for table in ('project_time_schema','project_time_records','project_time_voids'):
                    original=db.execute('SELECT * FROM '+table).fetchall(); key='version' if table.endswith('schema') else 'result_json'
                    for sql,args in [(f'UPDATE {table} SET {key}={key}',()),(f'DELETE FROM {table}',()),
                        (f'INSERT OR REPLACE INTO {table} VALUES('+','.join('?'*len(original[0]))+')',original[0])]:
                        with self.assertRaises(sqlite3.IntegrityError): db.execute(sql,args)
                    self.assertEqual(db.execute('SELECT * FROM '+table).fetchall(),original)
            row=list(db.execute('SELECT * FROM project_time_records').fetchone())
            columns=[r[1] for r in db.execute('PRAGMA table_info(project_time_records)')]
            for field in ('project_id','replaces_record_id'):
                bad=dict(zip(columns,row)); bad.update(record_id='new-'+field,time_event_id='new-'+field); bad[field]='missing'
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO project_time_records VALUES('+','.join('?'*len(row))+')',list(bad.values()))
            row=list(db.execute('SELECT * FROM project_time_voids').fetchone()); columns=[r[1] for r in db.execute('PRAGMA table_info(project_time_voids)')]
            bad=dict(zip(columns,row)); bad.update(record_id='missing',void_event_id='missing')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO project_time_voids VALUES('+','.join('?'*len(row))+')',list(bad.values()))

    def test_write_faults_rollback_and_two_step_correction_is_recoverable(self):
        first=self.record(); before=self.report()
        for table in ('project_time_records','project_time_voids'):
            with self.workspace.storage() as (_,ledger,_,_,_):
                ledger._connection.execute(f"CREATE TRIGGER time_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'time fault'); END")
            try:
                with self.assertRaisesRegex(sqlite3.IntegrityError,'time fault'):
                    self.void(first) if table.endswith('voids') else self.record(time_event_id='second',work_date='2026-01-11')
                self.assertEqual(self.report(),before)
            finally:
                with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('DROP TRIGGER time_fault')
        self.void(first)
        with self.assertRaises(ValueError): self.record(time_event_id='new',end_minute=0,replaces_record_id=first['record_id'])
        self.assertEqual(self.report()['total_minutes'],0)
        self.record(time_event_id='new',replaces_record_id=first['record_id'])
        self.assertEqual(self.report()['total_minutes'],300)

    def test_additive_migration_every_fault_preserves_project_and_financial_history(self):
        from types import SimpleNamespace
        module=self.module()
        before_report=self.workspace.report_package('2026-01-31'); before_projects=self.workspace.project_dimensions('2026-01-31')
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for table in ('project_time_voids','project_time_records','project_time_schema'): db.execute('DROP TABLE '+table)
            before=list(db.iterdump()); calls=[]
            class Probe:
                def execute(self,sql,*args): calls.append(sql); return db.execute(sql,*args)
            with self.assertRaises(RuntimeError):
                with ledger._transaction(write=True):
                    module.initialize_time(SimpleNamespace(_connection=Probe())); raise RuntimeError('rollback')
            self.assertEqual(list(db.iterdump()),before)
            for target in range(2,len(calls)+1):
                invoked=[0]
                class Fault:
                    def execute(self,sql,*args):
                        invoked[0]+=1
                        if invoked[0]==target: raise sqlite3.OperationalError('migration fault')
                        return db.execute(sql,*args)
                with self.subTest(target=target),self.assertRaisesRegex(sqlite3.OperationalError,'migration fault'):
                    with ledger._transaction(write=True): module.initialize_time(SimpleNamespace(_connection=Fault()))
                self.assertEqual(list(db.iterdump()),before)
        self.assertEqual(self.workspace.project_dimensions('2026-01-31'),before_projects)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before_report)

    def test_workspace_initialization_fault_rolls_back_shared_migrations(self):
        from pathlib import Path
        from accounting_harness.expense_accrual import ExpenseAccrualService
        module=self.module(); directory=Path(self.directory.name)/'older'
        with patch('accounting_harness.workspace.RevenueAccrualService',side_effect=ExpenseAccrualService),patch.object(module,'initialize_time',return_value=None):
            Workspace(directory)
        def state():
            result={}
            for name in ('ledger.sqlite3','sources.sqlite3','runs.sqlite3'):
                with sqlite3.connect(directory/name) as db: result[name]=(db.execute('PRAGMA user_version').fetchone(),list(db.iterdump()))
            return result
        before=state(); self.assertEqual(before['ledger.sqlite3'][0],(5,))
        original=module.protect_table
        def fail(db,table,conflict):
            if table=='project_time_voids': raise sqlite3.OperationalError('time setup fault')
            return original(db,table,conflict)
        with patch.object(module,'protect_table',side_effect=fail),self.assertRaisesRegex(sqlite3.OperationalError,'time setup fault'): Workspace(directory)
        self.assertEqual(state(),before)
        self.assertEqual(Workspace(directory).project_time('2026-01-31')['total_minutes'],0)

    def test_capture_is_one_read_with_immutable_project_definitions(self):
        self.record(); before=self.report(); module=self.module()
        with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('PRAGMA journal_mode=WAL')
        original=module._read_projects
        def read_then_write(ledger):
            projects=original(ledger)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: self.record(time_event_id='later',work_date='2026-01-11')).result(timeout=10)
            return projects
        with patch.object(module,'_read_projects',side_effect=read_then_write): captured=self.capture()
        self.assertEqual(module.time_report(captured),before)
        self.assertEqual(self.report()['total_minutes'],600)

    def test_closed_books_and_old_project_and_financial_captures_remain_exact(self):
        from accounting_harness.adjusted_month import build_adjusted_month
        from accounting_harness.project_dimensions import capture_dimensions, project_report
        self.module(); build_adjusted_month(self.workspace)
        preview=self.workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        self.workspace.action('close-confirm',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[],
            confirmed=True,confirmed_digest=preview['digest'],idempotency_key='time-test-close'))
        with self.workspace.storage() as (_,ledger,_,_,_): captured=capture_dimensions(ledger,'2026-01-31')
        before_projects=project_report(captured); before=self.workspace.report_package('2026-01-31')
        first=self.record(); self.void(first)
        self.record(time_event_id='replacement',replaces_record_id=first['record_id'])
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)
        self.assertEqual(self.workspace.project_dimensions('2026-01-31'),before_projects)
        self.assertEqual(project_report(captured),before_projects)
        self.assertEqual(self.report()['total_minutes'],300)

    def test_concurrent_void_retry_and_conflict_keep_one_audit(self):
        first=self.record()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.void(first),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(self.report()['voids']),1)
        self.assertEqual(self.report()['total_minutes'],0)

    def test_http_strict_payload_read_only_capture_and_native_routes(self):
        import http.client,threading
        from pathlib import Path
        from accounting_harness.web import make_server
        from html.parser import HTMLParser
        class Forms(HTMLParser):
            def __init__(self): super().__init__(); self.routes={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='form': self.routes[attrs.get('id')]=attrs.get('action')
        forms=Forms(); forms.feed(Path('accounting_harness/static/index.html').read_text())
        self.assertIn('project-time-form',forms.routes)
        self.assertIn('project-time-void-form',forms.routes)
        record_route=forms.routes['project-time-form']; void_route=forms.routes['project-time-void-form']
        self.module(); server=make_server(self.directory.name,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join); self.addCleanup(server.shutdown)
        host=f'127.0.0.1:{server.server_port}'
        def request(path,data=None,csrf=True):
            conn=http.client.HTTPConnection(host); headers={'Origin':'http://'+host,'Content-Type':'application/json'}
            if csrf: headers['X-CSRF-Token']=server.csrf_token
            conn.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
            response=conn.getresponse(); body=json.loads(response.read()); conn.close(); return response.status,body
        self.assertEqual(request('/api/project-time',self.data(),csrf=False)[0],403)
        self.assertEqual(request('/api/project-time',self.data(actor_id='admin'))[0],409)
        status,record=request(record_route,self.data()); self.assertEqual(status,200)
        self.assertEqual(record['actor_id'],'local-operator')
        self.assertEqual(request('/api/project-time',self.data()),(status,record))
        self.assertEqual(request('/api/project-time?as_of=2026-01-31')[1]['total_minutes'],300)
        self.assertEqual(request('/api/project-time-void',dict(self.void_data(record),actor_id='admin'))[0],409)
        self.assertEqual(request(void_route,self.void_data(record))[0],200)
        self.assertEqual(request('/api/project-time',self.data())[1]['status'],'voided')
        for query in ('','?as_of=2026-02-01','?as_of=2026-01-31&extra=1','?as_of=2026-01-31&as_of=2026-01-01'):
            self.assertEqual(request('/api/project-time'+query)[0],409)

    def test_demo_cli_ten_hours_duplicate_detection_no_cost(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-project-time'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for value in ('600 minutes','10h 0m','overlap rejected','unchanged'): self.assertIn(value,result.stdout)
