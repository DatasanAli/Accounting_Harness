"""Portable reports remain exact, bounded, untrusted and detached from books."""
import csv
import dataclasses
import http.client
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from accounting_harness.adjusted_month import build_adjusted_month
from accounting_harness.cash_flow import capture_cash_flow
from accounting_harness.review import digest
from accounting_harness.workspace import Workspace
from accounting_harness.web import make_server


class ReportExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.report_export'),
                             'portable report export must be implemented')
        from accounting_harness import report_export
        return report_export

    def capture(self, cutoff='2026-01-31'):
        with self.workspace.storage() as (_, ledger, _, _, _):
            return capture_cash_flow(ledger, cutoff)

    def package(self, reference=True):
        module = self.module()
        if reference: build_adjusted_month(self.workspace)
        return module.report_package(self.capture())

    def refused(self, package):
        with self.assertRaises(ValueError):
            self.module().read_report_package(json.dumps(package).encode())

    def post(self, identity='later', amount='1.00', debit='1000', credit='3000'):
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.admit(dict(id=identity,entity_id=self.workspace.catalog.entity_id,currency='USD',
                effective_date='2026-01-20',description='Synthetic',source_ids=[next(iter(self.workspace.sources))],
                lines=[dict(account=debit,side='debit',amount=amount),dict(account=credit,side='credit',amount=amount)]),
                actor_id='test',idempotency_key=identity)

    def archive(self, members):
        data=io.BytesIO()
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='Duplicate name:')
            with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name,content in members: archive.writestr(name,content)
        return data.getvalue()

    def test_reference_roundtrip_json_and_csv_offline_preserves_exact_trace(self):
        package=self.package();module=self.module()
        before=self.workspace.state()
        for kind in ('json','zip'):
            raw=module.export_report_package(package,kind)
            with patch.object(Workspace,'storage',side_effect=AssertionError('offline read-back opened storage')):
                restored=module.read_report_package(raw)
            self.assertEqual(restored,package)
            reports=restored['reports']; statements=reports['financial_statements']; cash=reports['cash_flow']
            self.assertEqual(cash['ending_cash_amount'],'9400.00')
            self.assertEqual(statements['income_statement']['net_income_amount'],'1100.00')
            self.assertEqual(statements['owners_equity']['ending_equity_amount'],'10900.00')
            self.assertEqual(statements['snapshot_digest'],cash['financial_snapshot_digest'])
            self.assertTrue(next(r for r in cash['rows'] if 'payable_trace' in r)['payable_trace']['payment_approval']['actor_id'])
        self.assertEqual(self.workspace.state(),before)
        with self.assertRaises(ValueError): self.workspace.action('report-import',package)

    def test_deterministic_members_bytes_and_immutable_after_later_changes(self):
        package=self.package();module=self.module();frozen={k:module.export_report_package(package,k) for k in ('json','zip')}
        self.post()
        with self.workspace.storage() as (_,ledger,_,_,_): ledger.ensure_bank_fee_account(actor_id='test')
        preview=self.workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        self.workspace.action('close-confirm',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[],
            confirmed_digest=preview['digest'],confirmed=True,idempotency_key='export-close'))
        for kind,raw in frozen.items():
            self.assertEqual(module.export_report_package(package,kind),raw)
            self.assertEqual(module.read_report_package(raw),package)
        self.assertNotEqual(module.report_package(self.capture())['package_digest'],package['package_digest'])
        with zipfile.ZipFile(io.BytesIO(frozen['zip'])) as archive:
            self.assertEqual(archive.namelist(),['report.json','report.csv'])
            self.assertTrue(all(i.date_time==(1980,1,1,0,0,0) for i in archive.infolist()))

    def test_cutoff_is_explicit_and_changes_package_identity(self):
        self.module();build_adjusted_month(self.workspace)
        early=self.module().report_package(self.capture('2026-01-01'));late=self.module().report_package(self.capture())
        self.assertEqual(early['reports']['cash_flow']['ending_cash_amount'],'8800.00')
        self.assertNotEqual(early['package_digest'],late['package_digest'])
        early['as_of']='2026-01-31';self.refused(early)

    def test_empty_negative_and_large_cents_remain_exact(self):
        module=self.module()
        empty=module.read_report_package(module.export_report_package(self.package(False),'zip'))
        self.assertEqual(empty['reports']['cash_flow']['ending_cash_cents'],'0')
        self.post(amount='90071992547409.93',debit='3000',credit='1000')
        result=module.read_report_package(module.export_report_package(module.report_package(self.capture()),'zip'))
        self.assertEqual(result['reports']['cash_flow']['ending_cash_cents'],'-9007199254740993')
        self.assertEqual(result['reports']['cash_flow']['ending_cash_amount'],'-90071992547409.93')

    def test_csv_unicode_quotes_newlines_and_formula_text_are_reversible(self):
        module=self.module();capture=self.capture()
        name='=SUM(1,2) "雪"\nsecond line'
        accounts=tuple(dataclasses.replace(a,name=name) if a.code=='1000' else a for a in capture.financial.ledger.catalog.accounts)
        catalog=dataclasses.replace(capture.financial.ledger.catalog,accounts=accounts)
        capture=dataclasses.replace(capture,financial=dataclasses.replace(capture.financial,
            ledger=dataclasses.replace(capture.financial.ledger,catalog=catalog)))
        package=module.report_package(capture);raw=module.export_report_package(package,'zip')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rows=list(csv.DictReader(io.StringIO(archive.read('report.csv').decode())))
        row=next(r for r in rows if r['account']=='1000' and r['section']=='assets')
        self.assertEqual(row['label'],"'"+name)
        self.assertEqual(module.read_report_package(raw),package)
        for text in ('=x','+x','-x','@x','\tx','\rx',"'x",'ordinary'):
            self.assertEqual(module.csv_text_decode(module.csv_text_encode(text)),text)
            self.assertFalse(module.csv_text_encode(text).startswith(('=','+','-','@','\t','\r','\n')))

    def test_csv_field_limit_roundtrips_boundary_and_refuses_oversized_projection(self):
        module=self.module();capture=self.capture();original_limit=csv.field_size_limit()
        def package_for(name):
            accounts=tuple(dataclasses.replace(a,name=name) if a.code=='1000' else a for a in capture.financial.ledger.catalog.accounts)
            catalog=dataclasses.replace(capture.financial.ledger.catalog,accounts=accounts)
            changed=dataclasses.replace(capture,financial=dataclasses.replace(capture.financial,
                ledger=dataclasses.replace(capture.financial.ledger,catalog=catalog)))
            return module.report_package(changed)
        for name in ('a'*131071,'a'*131071+'雪','='+'a'*131070):
            with self.subTest(length=len(name),formula=name.startswith('=')):
                package=package_for(name)
                for kind in ('json','zip'):
                    self.assertEqual(module.read_report_package(module.export_report_package(package,kind)),package)
        for name in ('a'*131073,'='+'a'*131071):
            with self.subTest(length=len(name),formula=name.startswith('=')):
                package=package_for(name)
                self.assertEqual(module.read_report_package(module.export_report_package(package,'json')),package)
                with self.assertRaisesRegex(ValueError,'CSV field'):
                    module.export_report_package(package,'zip')
        raw=module.export_report_package(package_for('Cash'),'zip')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest=archive.read('report.json');projection=archive.read('report.csv')
        oversized=self.archive([('report.json',manifest),('report.csv',projection.replace(b'Cash',b'a'*131073))])
        with self.assertRaises(ValueError):module.read_report_package(oversized)
        self.assertEqual(csv.field_size_limit(),original_limit)

    def test_unknown_missing_fields_and_schema_policy_refused(self):
        original=self.package()
        for change in (lambda p:p.update(extra=1),lambda p:p.pop('as_of'),lambda p:p.update(schema_version=True),
                       lambda p:p.update(schema_version=99),lambda p:p['capture']['policy'].update(version='future'),
                       lambda p:p['capture']['financial']['catalog'][0].update(extra=1)):
            package=json.loads(json.dumps(original));change(package);self.refused(package)

    def test_duplicate_keys_nonfinite_numbers_and_invalid_utf8_refused(self):
        module=self.module()
        for raw in (b'{"as_of":"2026-01-01","as_of":"2026-01-02"}',b'{"x":NaN}',b'{"x":Infinity}',b'\xff'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):module.read_report_package(raw)

    def test_cent_strings_and_decimal_agreement_strict(self):
        original=self.package()
        for value in (True,1.0,1,'01','+1','1e2','-0','1.00','-1'):
            package=json.loads(json.dumps(original));package['capture']['financial']['entries'][0]['lines'][0]['cents']=value
            self.refused(package)
        original['capture']['financial']['entries'][0]['lines'][0]['amount']='1.00';self.refused(original)

    def test_capture_dates_references_actors_balances_and_contexts_refused(self):
        original=self.package()
        changes=[lambda e:e.update(effective_date='2026-1-1'),lambda e:e.update(source_ids=[]),
            lambda e:e['context'].update(actor_id=''),lambda e:e['context'].update(journal_id='missing'),
            lambda e:e['context'].update(original_entry_id='missing'),lambda e:e['context'].update(recorded_at='yesterday'),
            lambda e:e['lines'][0].update(account='missing'),lambda e:e['lines'][0].update(side='left'),
            lambda e:e.update(currency='EUR'),lambda e:e['context'].update(classification='made_up')]
        for change in changes:
            package=json.loads(json.dumps(original));change(package['capture']['financial']['entries'][0]);self.refused(package)

    def test_changed_totals_labels_dates_digests_and_csv_rows_refused(self):
        original=self.package();module=self.module()
        for change in (lambda p:p['reports']['cash_flow'].update(ending_cash_cents='1'),
            lambda p:p.update(package_digest='0'*64),lambda p:p['capture']['financial']['catalog'][0].update(name='changed'),
            lambda p:p['reports']['financial_statements'].update(report_digest='0'*64)):
            package=json.loads(json.dumps(original));change(package);self.refused(package)
        with zipfile.ZipFile(io.BytesIO(module.export_report_package(original,'zip'))) as archive:
            manifest=archive.read('report.json');projection=archive.read('report.csv')
        for altered in (projection.replace(b'940000',b'940001'),projection+b'bad,row\r\n',projection.replace(b'Cash',b'Changed Cash')):
            with self.assertRaises(ValueError):module.read_report_package(self.archive([('report.json',manifest),('report.csv',altered)]))

    def test_payable_trace_unknown_fields_missing_references_and_identity_refused(self):
        original=self.package()
        for change in (lambda t:t['bills'][0].update(extra='x'),lambda t:t['payments'][0].update(bill_id='missing'),
            lambda t:t['approvals'][0].update(actor_id='other'),lambda t:t['approvals'][0].update(binding_json='{}'),
            lambda t:t['bills'][0].update(due_date='2026-02-30'),lambda t:t['payments'][0].update(allocated_cents=True)):
            package=json.loads(json.dumps(original));change(package['capture']['payables']);self.refused(package)

    def test_unsafe_duplicate_extra_missing_and_oversized_archives_refused(self):
        module=self.module();package=self.package(False);manifest=module.export_report_package(package,'json')
        for names in (['../report.json','report.csv'],['/report.json','report.csv'],['report.json','report.json'],
                      ['report.json','report.csv','extra'],['report.json']):
            with self.subTest(names=names),self.assertRaises(ValueError):
                module.read_report_package(self.archive([(name,manifest) for name in names]))
        with self.assertRaises(ValueError): module.read_report_package(b'x'*(module.MAX_PACKAGE_BYTES+1))
        with self.assertRaises(ValueError): module.read_report_package(self.archive([('report.json',manifest),('report.csv',b'x'*(module.MAX_MEMBER_BYTES+1))]))
        with self.assertRaises(ValueError):module.read_report_package(b'PK\x03\x04broken')

    def test_self_consistent_rewrite_is_new_untrusted_capture_not_provenance(self):
        module=self.module();capture=self.capture();first=module.report_package(capture)
        catalog=dataclasses.replace(capture.financial.ledger.catalog,entity_id='another-fictional-entity')
        changed=dataclasses.replace(capture,financial=dataclasses.replace(capture.financial,
            ledger=dataclasses.replace(capture.financial.ledger,catalog=catalog)))
        second=module.report_package(changed)
        self.assertNotEqual(first['package_digest'],second['package_digest'])
        self.assertEqual(module.read_report_package(module.export_report_package(second,'json')),second)
        preview=module.report_preview(second)
        self.assertEqual(preview['label'],'Imported report · untrusted, read-only')
        self.assertFalse(preview['posting_authority'])

    def test_cli_demo_and_offline_verification(self):
        module=self.module();package=self.package(False)
        path=Path(self.directory.name)/'portable.zip';path.write_bytes(module.export_report_package(package,'zip'))
        result=subprocess.run([sys.executable,'-m','accounting_harness','verify-report-export',str(path)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(package['package_digest'],result.stdout);self.assertIn('untrusted',result.stdout)
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-report-export'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        for expected in ('9400.00','1100.00','10900.00','Snapshot:','Package:'):self.assertIn(expected,result.stdout)

    def test_missing_cash_account_and_deeply_nested_json_fail_cleanly(self):
        package=self.package(False)
        package['capture']['financial']['catalog']=[a for a in package['capture']['financial']['catalog'] if a['code']!='1000']
        self.refused(package)
        with self.assertRaises(ValueError):self.module().read_report_package(b'['*2000+b']'*2000)

    def test_concurrent_post_between_capture_and_render_cannot_mix_reports(self):
        module=self.module();build_adjusted_month(self.workspace)
        captured=threading.Event();posted=threading.Event();failures=[]
        def writer():
            try:
                if not captured.wait(5): raise AssertionError('capture did not reach renderer')
                self.post('concurrent',amount='7.00',credit='4000')
                with self.workspace.storage() as (_,ledger,_,_,_): ledger.ensure_bank_fee_account(actor_id='test')
            except Exception as error: failures.append(error)
            finally: posted.set()
        worker=threading.Thread(target=writer);worker.start()
        from accounting_harness.financial_reports import financial_statements
        def render(capture):
            captured.set()
            if not posted.wait(5): raise AssertionError('concurrent writer did not finish')
            return financial_statements(capture)
        with patch.object(module,'financial_statements',side_effect=render):
            package=self.workspace.report_package('2026-01-31')
        worker.join(5);self.assertFalse(worker.is_alive());self.assertEqual(failures,[])
        report=module.read_report_package(module.export_report_package(package,'zip'))['reports']
        self.assertEqual(report['cash_flow']['ending_cash_amount'],'9400.00')
        self.assertEqual(report['financial_statements']['income_statement']['net_income_amount'],'1100.00')
        self.assertNotIn('5300',{a['code'] for a in report['financial_statements']['catalog']})
        latest=self.workspace.report_package('2026-01-31')['reports']
        self.assertEqual(latest['cash_flow']['ending_cash_amount'],'9407.00')
        self.assertEqual(latest['financial_statements']['income_statement']['net_income_amount'],'1107.00')

    def test_download_capture_is_one_read_transaction_and_no_tables_mutate(self):
        module=self.module();build_adjusted_month(self.workspace)
        with self.workspace.storage() as (registry,ledger,store,_,_):
            before=list(ledger._connection.iterdump())
            sources_before=list(registry._connection.iterdump())
            statements=[];ledger._connection.set_trace_callback(statements.append)
            capture=capture_cash_flow(ledger,'2026-01-31')
            ledger._connection.set_trace_callback(None)
            raw=module.export_report_package(module.report_package(capture),'zip')
            module.read_report_package(raw)
            self.assertEqual(list(ledger._connection.iterdump()),before)
            self.assertEqual(list(registry._connection.iterdump()),sources_before)
        self.assertEqual([s for s in statements if s.startswith('BEGIN')],['BEGIN'])
        self.assertEqual(statements[-1],'COMMIT')

    def test_consistent_but_invalid_capture_cannot_bypass_strict_rehydration(self):
        module=self.module();build_adjusted_month(self.workspace);capture=self.capture()
        for value in ('not a timestamp','2026-01-01T01:00:00'):
            contexts=tuple(dataclasses.replace(c,recorded_at=value) for c in capture.financial.journals)
            changed=dataclasses.replace(capture,financial=dataclasses.replace(capture.financial,journals=contexts))
            self.refused(module.report_package(changed))
        trace=json.loads(capture.payables_json);trace['approvals'][0]['actor_id']='changed-actor'
        changed=dataclasses.replace(capture,payables_json=json.dumps(trace))
        self.refused(module.report_package(changed))
        trace=json.loads(capture.payables_json);trace['bills'][0]['unknown']='not permitted'
        self.refused(module.report_package(dataclasses.replace(capture,payables_json=json.dumps(trace))))

    def test_http_download_filename_exact_same_capture_and_strict_queries(self):
        module=self.module()
        with make_server(self.directory.name,port=0) as server:
            build_adjusted_month(server.workspace);before=server.workspace.state()
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(query):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                conn.request('GET','/api/report-export'+query);response=conn.getresponse()
                result=response.status,dict(response.getheaders()),response.read();conn.close();return result
            try:
                for kind,mime,filename in [('json','application/json','report.json'),('zip','application/zip','reports.zip')]:
                    status,headers,raw=request('?as_of=2026-01-31&format='+kind)
                    self.assertEqual(status,200,raw);self.assertIn(mime,headers['Content-Type'])
                    self.assertEqual(headers['Content-Disposition'],'attachment; filename="'+filename+'"')
                    package=module.read_report_package(raw)
                    self.assertEqual(package['reports']['cash_flow']['ending_cash_amount'],'9400.00')
                    self.assertEqual(request('?as_of=2026-01-31&format='+kind)[2],raw)
                for query in ('','?as_of=2026-01-31','?as_of=2026-01-31&format=csv','?as_of=2026-01-31&format=json&path=/tmp/x',
                              '?as_of=2026-01-31&format=json&format=zip','?as_of=2026-02-01&format=json'):
                    self.assertEqual(request(query)[0],409)
                self.assertEqual(server.workspace.state(),before)
            finally:server.shutdown();thread.join()
