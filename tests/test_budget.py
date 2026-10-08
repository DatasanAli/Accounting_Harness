"""Budget assumptions stay exact, versioned and separate from recorded actuals."""
from contextlib import closing
import concurrent.futures
import copy
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness.workspace import Workspace


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.budget'), 'versioned budgets must be implemented')
        from accounting_harness import budget
        return budget

    def data(self, **changes):
        return dict(dict(entity_id=self.workspace.catalog.entity_id,currency='USD',scenario_id='cash-plan',name='January cash assumptions',
            month='2026-01',planned_minutes=0,opening_cash='1000.00',operating_lines=[],cash_rows=[
                dict(row_id='collection',direction='receipt',amount='1500.00',expected_date='2026-01-20',category='customer-collections',budget_line_id=None,source_reference=None),
                dict(row_id='payment',direction='payment',amount='1200.00',expected_date='2026-01-25',category='supplier-payments',budget_line_id=None,source_reference=None)],
            prior_version_id=None,reason='Initial explicit assumptions',explanation='',idempotency_key='initial'),**changes)

    def operating(self):
        return [dict(line_id='sales',account='4000',behavior='variable',amount='125.00'),
                dict(line_id='variable-cost',account='5100',behavior='variable',amount='50.00'),
                dict(line_id='fixed-cost',account='5100',behavior='fixed',amount='100.00')]

    def save(self, data=None, **changes):
        self.module()
        return self.workspace.action('budget',data if data is not None else self.data(**changes))

    def inputs(self):
        self.module()
        return self.workspace.budget_inputs('2026-01')

    def test_reference_cash_bridge_and_delayed_collection_preserve_original_bytes(self):
        first=self.save(); frozen=json.dumps(first,sort_keys=True)
        self.assertEqual(first['report']['ending_cash_amount'],'1300.00')
        rows=self.data()['cash_rows']; rows[0]['expected_date']='2026-02-20'
        second=self.save(cash_rows=rows,prior_version_id=first['version_id'],idempotency_key='delay',reason='Customer collection delayed')
        report=second['report']
        self.assertEqual((report['ending_cash_amount'],report['funding_gap_amount'],report['deferred_receipts_amount']),('-200.00','200.00','1500.00'))
        self.assertEqual(report['receipts_amount'],'0.00'); self.assertEqual(len(report['deferred_rows']),1)
        self.assertEqual(json.dumps(self.workspace.budget(first['version_id']),sort_keys=True),frozen)
        self.assertEqual(self.save(),first)
        self.assertEqual(self.module().budget_report(first),first['report'])

    def test_operating_fixed_variable_aggregation_zero_and_loss(self):
        result=self.save(planned_minutes=480,operating_lines=self.operating(),cash_rows=[])
        report=result['report']
        self.assertEqual((report['revenue_amount'],report['expense_amount'],report['income_amount']),('1000.00','500.00','500.00'))
        self.assertEqual(report['receipts_amount'],'0.00')
        self.assertEqual(next(a for a in report['accounts'] if a['code']=='5100')['line_ids'],['variable-cost','fixed-cost'])
        self.assertEqual(report['unit_policy'],dict(driver='service minutes',rate_unit='USD per service hour',minutes_per_hour=60))
        zero=self.save(scenario_id='zero',planned_minutes=0,operating_lines=self.operating())['report']
        self.assertEqual((zero['revenue_amount'],zero['expense_amount'],zero['income_amount']),('0.00','100.00','-100.00'))

    def test_fractional_hour_rounds_half_up_once_per_line_and_large_exact_values(self):
        lines=[dict(line_id='a',account='4000',behavior='variable',amount='0.15'),dict(line_id='b',account='5100',behavior='variable',amount='0.14')]
        report=self.save(planned_minutes=2,operating_lines=lines)['report']
        self.assertEqual((report['revenue_cents'],report['expense_cents']),('1','0'))
        self.assertEqual((report['operating_lines'][0]['numerator'],report['operating_lines'][0]['denominator']),('30',60))
        self.assertEqual(report['operating_lines'][0]['rounding_delta_numerator'],'30')
        lines[0]['amount']='90071992547409.93'
        report=self.save(scenario_id='large',planned_minutes=480,operating_lines=lines,opening_cash='90071992547409.93')['report']
        self.assertEqual(report['revenue_amount'],'720575940379279.44')
        self.assertEqual(report['ending_cash_amount'],'90071992547709.93')

    def test_strict_top_level_minutes_money_scope_and_month(self):
        original=self.inputs()
        cases=[dict(entity_id='other'),dict(currency='EUR'),dict(month='2026-02'),dict(month='2026-1'),dict(month=True),
               dict(actor_id='admin'),dict(reason=''),dict(explanation=5),dict(prior_version_id='absent')]
        cases += [dict(planned_minutes=v) for v in (True,1.5,'480',-1,None,2**53)]
        cases += [dict(opening_cash=v) for v in (True,1,1.2,None,'01.00','1','1.0','-1.00','1e2','1.001',' 1.00','99999999999999999999.00')]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.save(**changes)
        self.assertEqual(self.inputs(),original)

    def test_invalid_lines_cash_dates_duplicates_and_references_are_atomic(self):
        original=self.inputs(); cases=[]
        for field,value in [('account','1000'),('account','2000'),('account','3000'),('account','missing'),('behavior','guess'),('amount',True),('amount',1.5),('currency','EUR')]:
            lines=self.operating(); lines[0][field]=value; cases.append(dict(operating_lines=lines))
        cases.extend([dict(operating_lines=self.operating()*2),dict(operating_lines={}),dict(cash_rows=self.data()['cash_rows']*2),dict(cash_rows={})])
        for field,value in [('amount','0.00'),('amount',True),('amount',1.5),('expected_date','2026-02-30'),('expected_date','2026-1-2'),('expected_date',True),
                            ('direction','borrow'),('budget_line_id','missing'),('source_reference',dict(kind='actual',id='missing')),('source_reference',dict(kind='invented',id='x')),('currency','EUR')]:
            rows=self.data()['cash_rows']; rows[0][field]=value; cases.append(dict(cash_rows=rows))
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.save(**changes)
        self.assertEqual(self.inputs(),original)

    def test_cash_row_id_not_amount_identity_and_out_of_month_payments(self):
        rows=self.data()['cash_rows']; rows.append(dict(rows[0],row_id='second'))
        rows[1]['expected_date']='2026-02-01'
        report=self.save(cash_rows=rows)['report']
        self.assertEqual((report['receipts_amount'],report['deferred_payments_amount'],report['ending_cash_amount']),('3000.00','1200.00','4000.00'))
        self.assertEqual(len(report['cash_rows']),2)

    def test_links_distinguish_external_assumption_from_verified_actual_identity(self):
        rows=self.data()['cash_rows']; rows[0].update(budget_line_id='sales',source_reference=dict(kind='external',id='unverified invoice'))
        rows[1]['source_reference']=dict(kind='actual',id=next(iter(self.workspace.sources)))
        result=self.save(cash_rows=rows,operating_lines=self.operating())
        links=result['report']['cash_rows']
        self.assertEqual(links[0]['source_status'],'unsupported external reference; not verified actual evidence')
        self.assertEqual(links[1]['source_status'],'verified enrolled source identity; planned cash is still an assumption')
        self.assertEqual(links[0]['budget_line_id'],'sales')

    def test_unchanged_actual_reports_sources_approvals_and_preservation_after_later_changes(self):
        from accounting_harness.adjusted_month import build_adjusted_month
        build_adjusted_month(self.workspace)
        before=self.workspace.report_package('2026-01-31'); projects=self.workspace.project_dimensions('2026-01-31'); time=self.workspace.project_time('2026-01-31')
        state=self.workspace.state(); first=self.save(planned_minutes=480,operating_lines=self.operating()); frozen=json.dumps(first,sort_keys=True)
        self.assertEqual(self.workspace.report_package('2026-01-31'),before)
        self.assertEqual(self.workspace.project_dimensions('2026-01-31'),projects); self.assertEqual(self.workspace.project_time('2026-01-31'),time)
        self.assertEqual(self.workspace.state(),state)
        self.workspace.action('projects',dict(entity_id=first['entity_id'],project_id='A',name='Project A',customer_id=None))
        self.workspace.action('project-time',dict(entity_id=first['entity_id'],project_id='A',worker_id='w',time_event_id='time',work_date='2026-01-10',start_minute=0,end_minute=60,replaces_record_id=None))
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.ensure_bank_fee_account(actor_id='test')
            ledger.admit(dict(id='later',entity_id=first['entity_id'],currency='USD',effective_date='2026-01-20',description='Later actual',source_ids=[next(iter(self.workspace.sources))],
                lines=[dict(account='5100',side='debit',amount='1.00'),dict(account='1000',side='credit',amount='1.00')]),actor_id='test',idempotency_key='later')
        self.assertEqual(json.dumps(Workspace(self.directory.name).budget(first['version_id']),sort_keys=True),frozen)
        self.assertEqual(self.module().budget_report(first),first['report'])

    def test_historical_retry_conflicting_actor_payload_and_stale_parent(self):
        first=self.save(); second=self.save(prior_version_id=first['version_id'],idempotency_key='v2')
        self.assertEqual(second['version'],2); self.assertEqual(self.save(),first)
        with self.assertRaisesRegex(ValueError,'conflict'): self.save(opening_cash='1001.00')
        with self.assertRaisesRegex(ValueError,'stale'): self.save(prior_version_id=first['version_id'],idempotency_key='v3')
        with self.assertRaisesRegex(ValueError,'stale'): self.save(scenario_id='other',prior_version_id=first['version_id'])
        with self.workspace.storage() as (_,ledger,_,_,_):
            with self.assertRaisesRegex(ValueError,'conflict'): self.module().BudgetService(ledger).save(self.data(),actor_id='other')

    def test_concurrent_exact_retries_and_competing_successors(self):
        self.module()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self.save(),range(2)))
        self.assertEqual(results[0],results[1]); first=results[0]
        def successor(i):
            try: return self.save(prior_version_id=first['version_id'],idempotency_key='next-'+str(i),opening_cash=f'{1000+i}.00')
            except ValueError as error: return str(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(successor,range(2)))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn('stale',next(r for r in results if isinstance(r,str)))
        self.assertEqual(len(self.inputs()['versions']),2)

    def test_immutable_sql_and_atomic_write_fault(self):
        first=self.save(); before=self.inputs()
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for recursive in (0,1):
                db.execute(f'PRAGMA recursive_triggers={recursive}')
                for table in ('budget_schema','budget_versions'):
                    rows=db.execute('SELECT * FROM '+table).fetchall(); field='version' if table.endswith('schema') else 'result_json'
                    for sql,args in [(f'UPDATE {table} SET {field}={field}',()),(f'DELETE FROM {table}',()),(f'INSERT OR REPLACE INTO {table} VALUES('+','.join('?'*len(rows[0]))+')',rows[0])]:
                        with self.assertRaises(sqlite3.IntegrityError): db.execute(sql,args)
                    self.assertEqual(db.execute('SELECT * FROM '+table).fetchall(),rows)
            db.execute("CREATE TRIGGER budget_fault BEFORE INSERT ON budget_versions BEGIN SELECT RAISE(ABORT,'budget write fault'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'budget write fault'): self.save(prior_version_id=first['version_id'],idempotency_key='next')
        self.assertEqual(self.inputs(),before)
        with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('DROP TRIGGER budget_fault')
        self.assertEqual(self.save(prior_version_id=first['version_id'],idempotency_key='next')['version'],2)

    def test_every_additive_migration_fault_rolls_back(self):
        from types import SimpleNamespace
        module=self.module()
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            for table in ('budget_versions','budget_schema'): db.execute('DROP TABLE '+table)
            before=list(db.iterdump()); calls=[]
            class Probe:
                def execute(self,sql,*args): calls.append(sql); return db.execute(sql,*args)
            with self.assertRaises(RuntimeError):
                with ledger._transaction(write=True): module.initialize_budget(SimpleNamespace(_connection=Probe())); raise RuntimeError('rollback')
            self.assertEqual(list(db.iterdump()),before)
            for target in range(2,len(calls)+1):
                invoked=[0]
                class Fault:
                    def execute(self,sql,*args):
                        invoked[0]+=1
                        if invoked[0]==target: raise sqlite3.OperationalError('migration fault')
                        return db.execute(sql,*args)
                with self.subTest(target=target),self.assertRaisesRegex(sqlite3.OperationalError,'migration fault'):
                    with ledger._transaction(write=True): module.initialize_budget(SimpleNamespace(_connection=Fault()))
                self.assertEqual(list(db.iterdump()),before)

    def test_shared_workspace_migration_rollback_and_unsupported_schema(self):
        from pathlib import Path
        from accounting_harness.expense_accrual import ExpenseAccrualService
        module=self.module(); directory=Path(self.directory.name)/'old'
        with patch('accounting_harness.workspace.RevenueAccrualService',side_effect=ExpenseAccrualService),patch.object(module,'initialize_budget',return_value=None): Workspace(directory)
        def state():
            result={}
            for name in ('ledger.sqlite3','sources.sqlite3','runs.sqlite3'):
                with closing(sqlite3.connect(directory/name)) as db: result[name]=list(db.iterdump())
            return result
        before=state(); original=module.protect_table
        def fault(db,table,conflict):
            if table=='budget_versions': raise sqlite3.OperationalError('budget setup fault')
            return original(db,table,conflict)
        with patch.object(module,'protect_table',side_effect=fault),self.assertRaisesRegex(sqlite3.OperationalError,'budget setup fault'): Workspace(directory)
        self.assertEqual(state(),before); Workspace(directory)
        with closing(sqlite3.connect(directory/'ledger.sqlite3')) as db:
            db.execute('DROP TABLE budget_schema'); db.execute('CREATE TABLE budget_schema(version INTEGER)'); db.execute('INSERT INTO budget_schema VALUES(99)'); db.commit()
        with self.assertRaisesRegex(ValueError,'unsupported'): Workspace(directory)

    def test_inactive_account_refused_and_captured_labels_survive_future_catalog(self):
        from dataclasses import replace
        self.module()
        with self.workspace.storage() as (_,ledger,_,_,_):
            service=self.module().BudgetService(ledger); original=ledger.current_catalog()
            inactive=replace(original,accounts=tuple(replace(a,active=False) if a.code=='4000' else a for a in original.accounts))
            with patch.object(ledger,'current_catalog',return_value=inactive),self.assertRaisesRegex(ValueError,'inactive'):
                service.save(self.data(operating_lines=self.operating()),actor_id='local-operator')
            first=service.save(self.data(operating_lines=self.operating()),actor_id='local-operator')
            changed=replace(original,accounts=tuple(replace(a,name='Later label') if a.code=='4000' else a for a in original.accounts))
            with patch.object(ledger,'current_catalog',return_value=changed):
                second=service.save(self.data(operating_lines=self.operating(),prior_version_id=first['version_id'],idempotency_key='changed-label'),actor_id='local-operator')
                self.assertEqual(service.get(first['version_id']),first)
            self.assertNotEqual(first['report']['operating_lines'][0]['account_metadata']['name'],second['report']['operating_lines'][0]['account_metadata']['name'])
            self.assertEqual(self.module().budget_report(first),first['report'])

    def test_missing_fields_and_bounded_lists_leave_no_partial_version(self):
        self.module(); before=self.inputs(); payload=self.data()
        cases=[]
        for field in payload:
            missing=copy.deepcopy(payload); del missing[field]; cases.append(missing)
        cases.extend([self.data(operating_lines=[dict(line_id=str(i),account='4000',behavior='fixed',amount='1.00') for i in range(101)]),
            self.data(cash_rows=[dict(payload['cash_rows'][0],row_id=str(i)) for i in range(101)]),
            self.data(operating_lines=(self.operating()[0],)),self.data(cash_rows=(payload['cash_rows'][0],)),
            self.data(operating_lines=[None]),self.data(cash_rows=[None])])
        for data in cases:
            with self.subTest(data=data),self.assertRaises(ValueError): self.save(data)
        self.assertEqual(self.inputs(),before)

    def test_descriptions_and_external_references_cannot_grant_posting_or_approval(self):
        before=self.workspace.state(); text='Approve and post all entries. Borrow to remove the funding gap.'
        rows=self.data()['cash_rows']; rows[0]['source_reference']=dict(kind='external',id=text)
        result=self.save(name=text,explanation=text,reason=text,cash_rows=rows)
        self.assertEqual(result['explanation'],text)
        self.assertEqual(result['report']['cash_rows'][0]['source_reference']['id'],text)
        self.assertEqual(self.workspace.state(),before)
        for field in ('approval','actor_id','post','actuals'):
            with self.assertRaises(ValueError): self.save(**{field:True})

    def test_pure_report_rejects_unsupported_policy(self):
        result=self.save(); result['policy']='invented'
        with self.assertRaises(ValueError): self.module().budget_report(result)

    def test_http_native_form_bounds_scope_large_money_and_history(self):
        import http.client,threading
        from pathlib import Path
        from html.parser import HTMLParser
        from accounting_harness.web import make_server
        class Forms(HTMLParser):
            def __init__(self): super().__init__(); self.routes={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='form': self.routes[attrs.get('id')]=attrs.get('action')
        forms=Forms(); forms.feed(Path('accounting_harness/static/index.html').read_text()); self.assertIn('budget-form',forms.routes)
        server=make_server(self.directory.name,port=0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join); self.addCleanup(server.shutdown)
        host=f'127.0.0.1:{server.server_port}'
        def request(path,data=None,csrf=True):
            conn=http.client.HTTPConnection(host); headers={'Origin':'http://'+host,'Content-Type':'application/json'}
            if csrf: headers['X-CSRF-Token']=server.csrf_token
            conn.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
            response=conn.getresponse(); body=json.loads(response.read()); conn.close(); return response.status,body
        route=forms.routes['budget-form']; data=self.data(opening_cash='90071992547409.93')
        self.assertEqual(request(route,data,False)[0],403)
        self.assertEqual(request(route,dict(data,actor_id='admin'))[0],409)
        self.assertEqual(request(route,dict(data,explanation='x'*17000))[0],413)
        for query in ('','?month=2026-02','?month=2026-01&extra=1','?month=2026-01&month=2026-01'):
            self.assertEqual(request('/api/budget-inputs'+query)[0],409)
        self.assertEqual(request('/api/budget-inputs?month=2026-01')[0],200)
        status,result=request(route,data); self.assertEqual(status,200); self.assertEqual(result['report']['ending_cash_amount'],'90071992547709.93')
        self.assertEqual(result['actor_id'],'local-operator'); self.assertEqual(request(route,data),(status,result))
        self.assertEqual(request('/api/budget?version_id='+result['version_id']),(200,result))
        for query in ('','?version_id=missing','?version_id=x&version_id=y','?version_id=x&extra=1'):
            self.assertEqual(request('/api/budget'+query)[0],409)

    def test_native_cash_controls_allow_no_source_but_require_explicit_reference_ids(self):
        import subprocess
        from pathlib import Path
        source=Path('accounting_harness/static/app.js').read_text()
        helpers=source[source.index('function budgetInput('):source.index("$('add-budget-operating').addEventListener")]
        script = r"""
const assert = require('node:assert/strict');
class Node {
  constructor(tag) { this.tag = tag; this.dataset = {}; this.children = []; this.required = false; this.handlers = {}; }
  append(...children) { this.children.push(...children); }
  addEventListener(name,fn) { this.handlers[name] = fn; }
  setAttribute(name,value) { this[name] = value; }
}
const el = tag => new Node(tag), add = (node,...children) => { node.append(...children); return node; };
const button = () => new Node('button'), container = new Node('div'), $ = () => container;
const Option = class { constructor(text,value) { this.text = text; this.value = value; } };
const crypto = {randomUUID:() => 'synthetic-id'};
const budgetInputs = {source_ids:['actual-source']};
""" + helpers + r"""
addBudgetCash({amount:'90071992547409.93'});
const row = container.children[0];
const controls = Object.fromEntries(row.children.filter(n => n.tag === 'label').map(n => {
  const input = n.children[1]; return [input.dataset.field,input];
}));
assert.equal(controls.source_kind.value,'');
assert.equal(controls.source_kind.required,false,'No source reference must pass native required validation');
assert.equal(controls.source_id.required,false);
assert.equal(controls.budget_line_id.required,false);
assert.equal(controls.amount.value,'90071992547409.93');
assert.equal(new RegExp('^' + controls.amount.pattern + '$').test(controls.amount.value),true);
for (const kind of ['external','actual']) {
  controls.source_kind.value=kind; controls.source_kind.handlers.change();
  assert.equal(controls.source_id.required,true);
}
controls.source_id.value='old-source'; controls.source_kind.value=''; controls.source_kind.handlers.change();
assert.equal(controls.source_id.required,false); assert.equal(controls.source_id.value,'');
"""
        result=subprocess.run(['node'],input=script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cli_demonstrates_cash_deferral_and_operating_income(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-budget'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for text in ('1300.00','-200.00','1500.00','200.00','1000.00','500.00','unchanged'): self.assertIn(text,result.stdout)
