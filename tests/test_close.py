"""Period close accounting, exact human confirmation and durable seal."""
import concurrent.futures
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness.adjusted_month import build_adjusted_month
from accounting_harness.workspace import Workspace


class CloseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.closing'), 'period closing service required')
        from accounting_harness import closing
        return closing

    def preview(self, **changes):
        self.module()
        return self.workspace.action('close-preview', dict(period_start='2026-01-01', period_end='2026-01-31', selections=[], **changes))

    def confirm(self, preview, **changes):
        data = dict(period_start=preview['period_start'], period_end=preview['period_end'],
                    selections=preview['selections'], confirmed_digest=preview['digest'],
                    confirmed=True, idempotency_key='close-test')
        data.update(changes)
        return self.workspace.action('close-confirm', data)

    def post(self, identity='ordinary', debit='1000', credit='4000', amount='10.00', ledger=None):
        proposal = dict(id=identity,entity_id=self.workspace.catalog.entity_id,currency='USD',effective_date='2026-01-20',
            description='Synthetic ordinary posting',source_ids=[next(iter(self.workspace.sources))],lines=[
                dict(account=debit,side='debit',amount=amount),dict(account=credit,side='credit',amount=amount)])
        if ledger:
            return ledger.admit(proposal,actor_id='test-human',idempotency_key=identity)
        with self.workspace.storage() as (_,ledger,_,_,_):
            return self.post(identity,debit,credit,amount,ledger)

    def test_reference_close_and_captured_statements(self):
        build_adjusted_month(self.workspace)
        before=self.workspace.financial_statements('2026-01-31')
        preview=self.preview()
        self.assertTrue(preview['can_close'], preview['findings'])
        self.assertEqual(preview['statements'],before)
        result=self.confirm(preview)
        state=self.workspace.state()
        balances={r['account']:(r['debit'],r['credit']) for r in state['trial_balance']['rows']}
        self.assertEqual(balances['3000'],('0.00','10900.00'))
        self.assertEqual(balances['1000'],('9400.00','0.00'))
        for row in preview['temporary_balances']:
            self.assertEqual(balances[row['account']],('0.00','0.00'))
        self.assertEqual(state['trial_balance']['total_debits'],'11500.00')
        self.assertEqual(state['trial_balance']['total_credits'],'11500.00')
        fresh=self.workspace.financial_statements('2026-01-31')
        self.assertEqual(fresh['income_statement']['net_income_amount'],'1100.00')
        self.assertEqual(fresh['owners_equity']['ending_equity_amount'],'10900.00')
        self.assertEqual(fresh['excluded_closing_journal_ids'],[result['journal_id']])
        self.assertEqual(result['preview']['statements'],before)
        self.assertEqual(self.confirm(preview),result)
        self.assertEqual(Workspace(self.directory.name).state()['period_close'],result)

    def test_empty_close_has_no_journal_or_fabricated_source(self):
        before=self.workspace.list_sources()
        preview=self.preview()
        self.assertIsNone(preview['journal'])
        self.assertIsNone(preview['artifact'])
        result=self.confirm(preview)
        self.assertIsNone(result['journal_id'])
        self.assertEqual(self.workspace.state()['journal_count'],0)
        self.assertEqual(before,self.workspace.list_sources())
        with self.assertRaisesRegex((ValueError,sqlite3.IntegrityError),'closed'):
            self.post()

    def test_loss_opposite_balances_zero_capital_and_fee(self):
        for debit,credit,expected in [('5000','1000',-1000),('1000','5000',1000),('4000','1000',-1000),('3100','4000',0),('5300','1000',-1000)]:
            with self.subTest(debit=debit,credit=credit),tempfile.TemporaryDirectory() as directory:
                original=self.workspace; self.workspace=Workspace(directory)
                try:
                    if debit=='5300': self.workspace.action('bank-fee-account',{})
                    self.post(debit=debit,credit=credit)
                    preview=self.preview()
                    self.assertEqual(int(preview['capital_transfer_cents']),expected)
                    self.assertEqual(any(l['account']=='3000' for l in preview['journal']['lines']),expected!=0)
                    self.confirm(preview)
                    rows=self.workspace.state()['trial_balance']['rows']
                    for row in rows:
                        if row['account'] in (debit,credit) and row['account']!='1000':
                            self.assertEqual((row['debit'],row['credit']),('0.00','0.00'))
                finally: self.workspace=original

    def test_stale_posting_and_catalog_and_strict_confirmation(self):
        preview=self.preview(); self.post()
        with self.assertRaisesRegex(ValueError,'stale'): self.confirm(preview)
        preview=self.preview(); self.workspace.action('bank-fee-account',{})
        with self.assertRaisesRegex(ValueError,'stale'): self.confirm(preview)
        preview=self.preview()
        for changes in [dict(confirmed=False),dict(actor_id='admin'),dict(journal={}),dict(confirmed_digest='forged')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.confirm(preview,**changes)
        self.confirm(preview)
        with self.assertRaisesRegex(ValueError,'conflict'): self.confirm(preview,confirmed_digest='changed')
        with self.assertRaisesRegex(ValueError,'closed'): self.confirm(preview,idempotency_key='another')

    def test_old_connection_backdate_reversal_and_exact_post_retry(self):
        self.module()
        with self.workspace.storage() as (_,old,_,_,_):
            receipt=self.post(ledger=old)
            preview=self.preview(); self.confirm(preview)
            self.assertEqual(self.post(ledger=old),receipt)
            with self.assertRaisesRegex((ValueError,sqlite3.IntegrityError),'closed'):
                self.post('late',ledger=old)
            with self.assertRaisesRegex((ValueError,sqlite3.IntegrityError),'closed'):
                old.reverse('ordinary',reversal_id='late-reversal',entity_id=self.workspace.catalog.entity_id,
                    effective_date='2026-01-01',reason='Late correction',source_ids=list(receipt.entry.source_ids),
                    actor_id='test-human',idempotency_key='late-reversal')
            with self.assertRaisesRegex(sqlite3.IntegrityError,'closed'):
                with old._transaction(write=True):
                    old._connection.execute('INSERT INTO journals VALUES(?,?,?,?,?)',('direct',self.workspace.catalog.entity_id,'USD','2026-01-20','Raw posting'))
                    old._connection.execute('INSERT INTO posting_events VALUES(?,?,?,?)',('direct','raw','2026-10-08T00:00:00+00:00','post-v1'))

    def test_concurrent_confirmation_one_close(self):
        self.post(); preview=self.preview()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.confirm(preview),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(self.workspace.state()['journal_count'],2)

    def test_unsupported_period(self):
        self.module()
        with self.assertRaisesRegex(ValueError,'complete configured period'):
            self.workspace.action('close-preview',dict(period_start='2026-01-15',period_end='2026-01-31',selections=[]))

    def test_empty_close_blocks_exact_period_end_direct_seal(self):
        self.confirm(self.preview())
        with self.workspace.storage() as (_,ledger,_,_,_):
            with self.assertRaisesRegex(sqlite3.IntegrityError,'closed'):
                with ledger._transaction(write=True):
                    ledger._connection.execute('INSERT INTO journals VALUES(?,?,?,?,?)',('raw-end',self.workspace.catalog.entity_id,'USD','2026-01-31','Close lookalike'))
                    ledger._connection.execute('INSERT INTO journal_sources VALUES(?,?,?)',('raw-end',0,next(iter(self.workspace.sources))))
                    ledger._connection.execute('INSERT INTO lines VALUES(?,?,?,?,?)',('raw-end',0,'1000','debit',100))
                    ledger._connection.execute('INSERT INTO lines VALUES(?,?,?,?,?)',('raw-end',1,'4000','credit',100))
                    ledger._connection.execute('INSERT INTO posting_events VALUES(?,?,?,?)',('raw-end','local-operator','2026-10-08T00:00:00+00:00','post-v1'))

    def test_every_close_write_fault_rolls_back_and_records_are_immutable(self):
        self.post();preview=self.preview()
        before=self.workspace.state()
        for table in ['period_closes','journals','journal_sources','lines','posting_events']:
            with self.subTest(table=table):
                with self.workspace.storage() as (_,ledger,_,_,_):
                    ledger._connection.execute(f"CREATE TRIGGER close_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected fault'); END")
                with self.assertRaisesRegex(sqlite3.IntegrityError,'injected fault'): self.confirm(preview)
                with self.workspace.storage() as (_,ledger,_,_,_): ledger._connection.execute('DROP TRIGGER close_fault')
                self.assertEqual(self.workspace.state(),before)
        self.confirm(preview)
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection;row=db.execute('SELECT * FROM period_closes').fetchone()
            for sql,args in [('DELETE FROM period_closes',()),('UPDATE period_closes SET actor_id=actor_id',()),
                ('INSERT OR REPLACE INTO period_closes VALUES(?,?,?,?,?,?,?)',row)]:
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql,args)

    def test_close_seal_refuses_changed_lines_or_actor_before_any_commit(self):
        self.post();preview=self.preview();module=self.module()
        from dataclasses import replace
        from accounting_harness.domain.ledger import LedgerLine
        from accounting_harness.domain.money import Money
        for change in ['actor','lines']:
            with self.subTest(change=change),self.workspace.storage() as (registry,ledger,_,_,_):
                service=module.CloseService(ledger,registry);original=ledger._store_entry
                def tamper(entry,actor):
                    if change=='actor': return original(entry,'forged')
                    return original(replace(entry,lines=tuple(LedgerLine(l.account,l.side,Money(l.amount.cents+1)) for l in entry.lines)),actor)
                request=dict(period_start=preview['period_start'],period_end=preview['period_end'],selections=[],confirmed=True,
                    confirmed_digest=preview['digest'],idempotency_key='tamper')
                with patch.object(ledger,'_store_entry',side_effect=tamper),self.assertRaisesRegex((ValueError,sqlite3.IntegrityError),'closed'):
                    service.confirm(request,actor_id='local-operator')
                self.assertIsNone(service.recorded())

    def test_generated_calculation_enrollment_recovery_does_not_close(self):
        self.post()
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.workspace import EnrollmentPending
        with patch.object(SQLiteLedger,'enroll_source',side_effect=sqlite3.OperationalError('injected enrollment')):
            with self.assertRaises(EnrollmentPending): self.preview()
        self.assertIsNone(self.workspace.state()['period_close'])
        self.workspace=Workspace(self.directory.name)
        preview=self.preview();result=self.confirm(preview)
        with self.workspace.storage() as (registry,ledger,_,_,_):
            artifact=registry.get(preview['artifact']['document_id'])
            content=json.loads(artifact.canonical_content)
            self.assertEqual(content['calculation_digest'],preview['calculation_digest'])
            self.assertEqual(json.loads(content['calculation_json'])['journal_ids'],['ordinary'])
            self.assertEqual(ledger.receipt(result['journal_id']).entry.source_ids,(artifact.document_id,))

    def test_activated_subsidiary_residual_blocks_close(self):
        from dataclasses import replace
        build_adjusted_month(self.workspace)
        module=self.module()
        with self.workspace.storage() as (registry,ledger,_,_,_):
            service=module.CloseService(ledger,registry);original=service.prepaid._snapshot
            # Captured supported policy omits its consumed effect: this simulates
            # a damaged subsidiary capture without weakening durable posting guards.
            with patch.object(service.prepaid,'_snapshot',side_effect=lambda:replace(original(),effects=())):
                preview=service.preview(dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
                self.assertFalse(preview['can_close'])
                self.assertIn('prepaid subsidiary control does not reconcile',preview['findings'])

    def test_bank_selection_completion_and_stale_matching_bind_confirmation(self):
        from test_bank_matching import bank_row,statement,post
        self.module()
        post(self.workspace,'funding','10.00',day='01')
        self.workspace.import_bank_statement(statement([bank_row('funding','10.00',day='01')]))
        blocked=self.preview();self.assertFalse(blocked['can_close'])
        self.assertIn('Select a statement',blocked['findings'][0])
        row=self.workspace.bank_matches('fictional-bank')['rows'][0]
        self.workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id='funding',journal_id='funding',binding=row['binding'],idempotency_key='match'))
        view=self.workspace.bank_reconciliation('fictional-bank','matching')
        completion=self.workspace.action('bank-reconcile',dict(bank_account_id='fictional-bank',statement_id='matching',binding=view['report']['digest'],idempotency_key='complete'))
        selection=dict(bank_account_id='fictional-bank',statement_id='matching',completion_id=completion['completion_id'])
        request=dict(period_start='2026-01-01',period_end='2026-01-31',selections=[selection])
        preview=self.workspace.action('close-preview',request);self.assertTrue(preview['can_close'])
        # An overlapping import itself changes readiness, even with identical rows.
        self.workspace.import_bank_statement(statement([bank_row('funding','10.00',day='01')],'overlap'))
        with self.assertRaisesRegex(ValueError,'stale'): self.confirm(preview)
        self.assertFalse(self.preview()['can_close'])
        preview=self.workspace.action('close-preview',request)
        self.assertEqual(len(preview['readiness']['overlapping_statements']),2)
        self.assertTrue(preview['can_close'])
        row=self.workspace.bank_matches('fictional-bank')['rows'][0]
        self.workspace.action('bank-unmatch',dict(bank_account_id='fictional-bank',match_event_id=row['active_match']['event_id'],reason='Synthetic unmatch invalidates close',idempotency_key='unmatch'))
        with self.assertRaisesRegex(ValueError,'stale'): self.confirm(preview)
        blocked=self.workspace.action('close-preview',request)
        self.assertFalse(blocked['can_close']); self.assertIn('stale',blocked['findings'][0])
        self.assertIsNone(self.workspace.state()['period_close'])

    def test_http_close_confirmation_forgery_and_pending_draft_refusal(self):
        import http.client,threading
        from accounting_harness.web import make_server
        server=make_server(self.directory.name,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        host=f'127.0.0.1:{server.server_port}'
        def request(path,data):
            connection=http.client.HTTPConnection(host)
            connection.request('POST',path,json.dumps(data),headers={'Origin':'http://'+host,'Content-Type':'application/json','X-CSRF-Token':server.csrf_token})
            response=connection.getresponse();body=json.loads(response.read());connection.close();return response.status,body
        self.module()
        self.workspace.action('run',dict(source_id='synthetic-receipt-002',provider='offline',run_id='pending-close'))
        draft=self.workspace.state()['drafts'][0]
        status,preview=request('/api/close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        self.assertEqual(status,200)
        confirmation=dict(period_start='2026-01-01',period_end='2026-01-31',selections=[],confirmed=True,confirmed_digest=preview['digest'],idempotency_key='http-close')
        self.assertEqual(request('/api/close-confirm',confirmation|dict(actor_id='admin'))[0],409)
        self.assertEqual(request('/api/close-confirm',confirmation|dict(journal={}))[0],409)
        result=request('/api/close-confirm',confirmation);self.assertEqual(result[0],200)
        self.assertEqual(request('/api/close-confirm',confirmation),result)
        status,body=request('/api/approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        self.assertEqual(status,409);self.assertIn('closed',body['error'])
        self.assertEqual(self.workspace.state()['journal_count'],0)

    def test_competing_keys_and_changed_actor_do_not_create_second_close(self):
        self.post();preview=self.preview()
        def compete(key):
            try: return self.confirm(preview,idempotency_key=key)
            except ValueError as error: return str(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(compete,['first-close','second-close']))
        winners=[r for r in results if isinstance(r,dict)]
        self.assertEqual(len(winners),1);self.assertIn('already closed',next(r for r in results if isinstance(r,str)))
        result=winners[0]
        with self.workspace.storage() as (registry,ledger,_,_,_):
            service=self.module().CloseService(ledger,registry)
            with self.assertRaisesRegex(ValueError,'conflict'):
                service.confirm(dict(period_start=preview['period_start'],period_end=preview['period_end'],selections=[],
                    confirmed=True,confirmed_digest=preview['digest'],idempotency_key=result['idempotency_key']),actor_id='other-human')
        self.assertEqual(self.workspace.state()['journal_count'],2)

    def test_preexisting_post_approval_reversal_retry_and_report_preserved(self):
        self.post()
        with self.workspace.storage() as (_,ledger,_,_,_):
            args=dict(reversal_id='old-reversal',entity_id=self.workspace.catalog.entity_id,effective_date='2026-01-25',
                reason='Original synthetic correction',source_ids=[next(iter(self.workspace.sources))],actor_id='test-human',idempotency_key='original-reversal')
            receipt=ledger.reverse('ordinary',**args)
        self.workspace.action('run',dict(source_id='synthetic-receipt-006',provider='offline',run_id='prior-post'))
        draft=self.workspace.state()['drafts'][0]
        approval=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        posted=self.workspace.action('approve-post',approval)
        with self.workspace.storage() as (_,ledger,_,_,_):
            before={table:ledger._connection.execute('SELECT * FROM '+table).fetchall() for table in ['idempotency','reversals','approvals']}
        preview=self.preview(); self.confirm(preview)
        self.assertEqual(self.workspace.action('approve-post',approval),posted)
        with self.workspace.storage() as (_,ledger,_,_,_):
            self.assertEqual(ledger.reverse('ordinary',**args),receipt)
            for table,rows in before.items(): self.assertEqual(ledger._connection.execute('SELECT * FROM '+table).fetchall(),rows)
        self.assertEqual(self.workspace.state()['period_close']['preview']['statements'],preview['statements'])

    def test_unsupported_equity_metadata(self):
        from dataclasses import replace
        from accounting_harness.domain.accounts import Account
        with self.workspace.storage() as (registry,ledger,_,_,_):
            service=self.module().CloseService(ledger,registry);catalog=ledger.current_catalog()
            changed=replace(catalog,accounts=catalog.accounts+(Account('3200','Corporate equity','equity','credit'),))
            with patch.object(ledger,'current_catalog',return_value=changed),self.assertRaisesRegex(ValueError,'unsupported equity'):
                service.preview(dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))

    def test_every_migration_statement_fault_restores_original_database(self):
        from types import SimpleNamespace
        from pathlib import Path
        from accounting_harness.persistence import SQLiteLedger
        module=self.module()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.sqlite3'
            with patch.object(module,'initialize_close',return_value=None):
                ledger=SQLiteLedger(path,self.workspace.catalog,'2026-01-01','2026-01-31',known_source_ids=set(self.workspace.sources))
            self.addCleanup(ledger.close)
            db=ledger._connection;before='\n'.join(db.iterdump());statements=[]
            class Proxy:
                def execute(self,sql,*args):
                    statements.append(sql)
                    return db.execute(sql,*args)
            with self.assertRaisesRegex(RuntimeError,'probe'):
                with ledger._transaction(write=True):
                    module.initialize_close(SimpleNamespace(_connection=Proxy()))
                    raise RuntimeError('probe')
            self.assertEqual('\n'.join(db.iterdump()),before)
            count=len(statements)
            for target in range(1,count+1):
                with self.subTest(statement=target):
                    calls=[0]
                    class Fault:
                        def execute(self,sql,*args):
                            calls[0]+=1
                            if calls[0]==target: raise sqlite3.OperationalError('migration fault')
                            return db.execute(sql,*args)
                    with self.assertRaisesRegex(sqlite3.OperationalError,'migration fault'):
                        with ledger._transaction(write=True): module.initialize_close(SimpleNamespace(_connection=Fault()))
                    self.assertEqual('\n'.join(db.iterdump()),before)
            with ledger._transaction(write=True): module.initialize_close(ledger)
            self.assertEqual(db.execute('SELECT version FROM period_close_schema').fetchall(),[(1,)])
            self.assertGreater(count,10)

    def test_typed_bank_fee_closes_using_calculation_evidence_only(self):
        from test_bank_matching import bank_row,statement
        self.module();self.workspace.action('bank-fee-account',{})
        self.workspace.import_bank_statement(statement([bank_row('fee','-10.00')]))
        draft=self.workspace.action('bank-fee-proposals',dict(bank_account_id='fictional-bank',transaction_id='fee',
            classification='bank_fee',reason='Reviewed synthetic monthly fee',expected_revision=0))
        self.workspace.action('approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        row=self.workspace.bank_matches('fictional-bank')['rows'][0]
        self.workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id='fee',journal_id=row['candidates'][0]['journal_id'],binding=row['binding'],idempotency_key='fee-match'))
        report=self.workspace.bank_reconciliation('fictional-bank','matching')['report']
        completion=self.workspace.action('bank-reconcile',dict(bank_account_id='fictional-bank',statement_id='matching',binding=report['digest'],idempotency_key='fee-reconcile'))
        with self.workspace.storage() as (_,ledger,_,_,_): effects=ledger._connection.execute('SELECT * FROM bank_fee_effects').fetchall()
        preview=self.workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[
            dict(bank_account_id='fictional-bank',statement_id='matching',completion_id=completion['completion_id'])]))
        self.assertTrue(preview['can_close']); self.assertEqual(preview['capital_transfer_amount'],'-10.00')
        result=self.confirm(preview)
        with self.workspace.storage() as (registry,ledger,_,_,_):
            self.assertEqual(ledger._connection.execute('SELECT * FROM bank_fee_effects').fetchall(),effects)
            receipt=ledger.receipt(result['journal_id'])
            self.assertEqual(receipt.entry.source_ids,(preview['artifact']['document_id'],))
            self.assertEqual(json.loads(registry.get(receipt.entry.source_ids[0]).canonical_content)['kind'],'close_calculation')
            self.assertTrue(any(json.loads(registry.get(source).canonical_content)['kind']=='bank_fee' for source in preview['source_ids']))
        rows={r['account']:r for r in self.workspace.state()['trial_balance']['rows']}
        self.assertEqual((rows['5300']['debit'],rows['5300']['credit']),('0.00','0.00'))
        self.assertEqual(self.workspace.financial_statements('2026-01-31')['income_statement']['expenses_amount'],'10.00')

if __name__=='__main__': unittest.main()
