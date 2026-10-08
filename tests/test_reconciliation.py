"""Captured reconciliation uses existing cash movements and explicit human review."""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from accounting_harness.workspace import Workspace
from test_bank_matching import bank_row, post, statement


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)
        self.workspace.import_bank_statement(statement([bank_row('funding','950.00',day='01'),bank_row('fee','-10.00')]))
        post(self.workspace,'funding','950.00',day='01')
        post(self.workspace,'deposit','200.00',day='20')
        post(self.workspace,'payment','150.00',side='credit',day='21')

    def view(self):
        return self.workspace.bank_reconciliation('fictional-bank','matching')

    def match(self, identity):
        row=next(r for r in self.workspace.bank_matches('fictional-bank')['rows'] if r['transaction_id']==identity)
        return self.workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id=identity,
            journal_id=row['candidates'][0]['journal_id'],binding=row['binding'],idempotency_key='match-'+identity))

    def timing(self, journal, role, **changes):
        return self.workspace.action('bank-timing',dict(bank_account_id='fictional-bank',statement_id='matching',
            journal_id=journal,role=role,reason='Reviewed cash evidence and statement cutoff',
            binding=self.view()['report']['digest'],idempotency_key=journal) | changes)

    def complete_data(self):
        return dict(bank_account_id='fictional-bank',statement_id='matching',binding=self.view()['report']['digest'],idempotency_key='complete')

    def ready(self):
        self.workspace.action('bank-fee-account',{})
        draft=self.workspace.action('bank-fee-proposals',dict(bank_account_id='fictional-bank',transaction_id='fee',
            classification='bank_fee',reason='Reviewed monthly bank fee',expected_revision=0))
        self.workspace.action('approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        self.match('funding');self.match('fee')
        self.timing('deposit','deposit_in_transit');self.timing('payment','outstanding_payment')

    def test_reference_bridge_only_fee_posts_and_completion_is_explicit(self):
        self.assertTrue(callable(getattr(self.workspace,'bank_reconciliation',None)), 'captured reconciliation view required')
        self.assertEqual(self.view()['report']['book_balance'],'1000.00')
        self.assertFalse(self.view()['report']['can_complete'])
        self.ready()
        report=self.view()['report']
        self.assertEqual([report[k] for k in ['original_book_balance','book_adjustments_total','book_balance','bank_closing','deposits_in_transit','outstanding_payments','adjusted_bank_balance','unexplained_difference']],
                         ['1000.00','-10.00','990.00','940.00','200.00','150.00','990.00','0.00'])
        self.assertTrue(report['can_complete'])
        self.assertEqual(self.workspace.state()['journal_count'],4)
        self.assertEqual(self.view()['completions'],[])
        data=self.complete_data()
        receipt=self.workspace.action('bank-reconcile',data)
        self.assertEqual(receipt['actor_id'],'local-operator')
        self.assertEqual(receipt['report'],report)
        self.assertEqual(self.workspace.action('bank-reconcile',data),receipt)
        self.assertEqual(self.workspace.state()['journal_count'],4)

    def test_timing_refuses_wrong_sign_duplicate_cleared_future_account_and_plug(self):
        self.assertTrue(callable(getattr(self.workspace,'bank_reconciliation',None)), 'captured reconciliation view required')
        self.match('funding')
        for journal,role,change in [('deposit','outstanding_payment',{}),('payment','deposit_in_transit',{}),
            ('funding','deposit_in_transit',{}),('missing','deposit_in_transit',{}),('deposit','plug',{}),
            ('deposit','deposit_in_transit',{'amount':'999.00'}),('deposit','deposit_in_transit',{'actor_id':'forged'})]:
            with self.subTest(journal=journal,role=role,change=change),self.assertRaises((ValueError,KeyError)):
                self.timing(journal,role,**change)
        self.timing('deposit','deposit_in_transit')
        with self.assertRaises(ValueError):self.timing('deposit','deposit_in_transit',idempotency_key='duplicate')
        with self.assertRaises(ValueError):self.workspace.action('bank-reconcile',self.complete_data())

    def test_exact_concurrent_retry_changed_payload_and_later_drift(self):
        self.assertTrue(callable(getattr(self.workspace,'bank_reconciliation',None)), 'captured reconciliation view required')
        self.ready();data=self.complete_data()
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts=list(pool.map(lambda _:self.workspace.action('bank-reconcile',data),range(2)))
        self.assertEqual(receipts[0],receipts[1])
        with self.assertRaises(ValueError):self.workspace.action('bank-reconcile',data|dict(binding='different'))
        post(self.workspace,'later','1.00',day='25')
        self.workspace=Workspace(self.directory.name)
        self.assertEqual(self.workspace.action('bank-reconcile',data),receipts[0])
        view=self.view()
        self.assertTrue(view['completions'][0]['current_state_drift'])
        self.assertEqual(view['completions'][0]['completion'],receipts[0])
        with self.assertRaises(ValueError):self.workspace.action('bank-reconcile',data|dict(idempotency_key='new'))

    def test_zero_residual_unmatched_bank_rows_still_block(self):
        self.assertTrue(callable(getattr(self.workspace,'bank_reconciliation',None)), 'captured reconciliation view required')
        self.ready()
        # A separate equal statement has the same closing total, with offsetting unresolved rows.
        self.workspace.import_bank_statement(statement([bank_row('funding','950.00',day='01'),bank_row('fee','-10.00'),bank_row('plus','7.00'),bank_row('minus','-7.00')],'offset'))
        for journal,role in [('deposit','deposit_in_transit'),('payment','outstanding_payment')]:
            report=self.workspace.bank_reconciliation('fictional-bank','offset')['report']
            self.workspace.action('bank-timing',dict(bank_account_id='fictional-bank',statement_id='offset',journal_id=journal,role=role,
                reason='Reviewed timing',binding=report['digest'],idempotency_key=journal))
        report=self.workspace.bank_reconciliation('fictional-bank','offset')['report']
        self.assertEqual(report['unexplained_difference'],'0.00')
        self.assertFalse(report['can_complete'])
        self.assertEqual(len(report['bank_exceptions']),2)

    def test_immutable_completion_and_atomic_write_failure(self):
        self.assertTrue(callable(getattr(self.workspace,'bank_reconciliation',None)), 'captured reconciliation view required')
        self.ready();data=self.complete_data()
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger._connection.execute("CREATE TRIGGER fail_reconciliation BEFORE INSERT ON reconciliation_receipts BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.workspace.action('bank-reconcile',data)
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger._connection.execute('DROP TRIGGER fail_reconciliation')
            self.assertEqual(ledger._connection.execute('SELECT count(*) FROM reconciliation_completions').fetchone()[0],0)
        self.workspace.action('bank-reconcile',data)
        with self.workspace.storage() as (_,ledger,_,_,_):
            for table in ['reconciliation_completions','reconciliation_receipts','reconciliation_timing']:
                db=ledger._connection;row=db.execute('SELECT * FROM '+table+' LIMIT 1').fetchone()
                col=db.execute('PRAGMA table_info('+table+')').fetchone()[1]
                for sql,args in [('DELETE FROM '+table,()),('UPDATE '+table+' SET '+col+'='+col,()),
                    ('INSERT OR REPLACE INTO '+table+' VALUES('+','.join('?' for _ in row)+')',row)]:
                    with self.assertRaises(sqlite3.IntegrityError):db.execute(sql,args)

    def test_later_clearing_does_not_remove_earlier_cutoff_timing(self):
        self.ready()
        self.workspace.import_bank_statement(statement([bank_row('funding','950.00',day='01'),bank_row('fee','-10.00')],'early') | dict(period_end='2026-01-21'))
        def early():return self.workspace.bank_reconciliation('fictional-bank','early')['report']
        for journal,role in [('deposit','deposit_in_transit'),('payment','outstanding_payment')]:
            self.workspace.action('bank-timing',dict(bank_account_id='fictional-bank',statement_id='early',journal_id=journal,
                role=role,reason='Uncleared at January 21',binding=early()['digest'],idempotency_key=journal))
        self.assertTrue(early()['can_complete'])
        self.workspace.import_bank_statement(statement([bank_row('deposit-clears','200.00',day='22')],'later'))
        self.match('deposit-clears')
        self.assertEqual(early()['deposits_in_transit'],'200.00')
        self.assertTrue(early()['can_complete'])
        post(self.workspace,'future','1.00',day='23')
        with self.assertRaises(ValueError):
            self.workspace.action('bank-timing',dict(bank_account_id='fictional-bank',statement_id='early',journal_id='future',
                role='deposit_in_transit',reason='Wrong cutoff',binding=early()['digest'],idempotency_key='future'))

    def test_frozen_capture_and_single_read_snapshot_with_concurrent_writer(self):
        from accounting_harness.reconciliation import ReconciliationService,reconciliation_report
        self.ready()
        with self.workspace.storage() as (_,ledger,_,_,_):
            # WAL allows a writer to commit between independent reads in one reader snapshot.
            ledger._connection.execute('PRAGMA journal_mode=WAL')
            service=ReconciliationService(ledger)
            old=service.capture('fictional-bank','matching')
            original=service.bank._detail
            def interleave(identity):
                detail=original(identity)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(post,self.workspace,'interleaved','1.00').result()
                return detail
            with patch.object(service.bank,'_detail',side_effect=interleave):
                captured=service.capture('fictional-bank','matching')
            self.assertEqual(captured,old)
            self.assertEqual(reconciliation_report(old)['book_balance'],'990.00')
            self.assertEqual(service.view('fictional-bank','matching')['report']['book_balance'],'991.00')
        self.assertEqual(reconciliation_report(old)['book_balance'],'990.00')

    def test_match_drift_blocks_pending_completion_preserves_old_receipt_and_can_withdraw_timing(self):
        self.ready();data=self.complete_data()
        receipt=self.workspace.action('bank-reconcile',data)
        event=next(r['active_match'] for r in self.workspace.bank_matches('fictional-bank')['rows'] if r['transaction_id']=='funding')
        self.workspace.action('bank-unmatch',dict(bank_account_id='fictional-bank',match_event_id=event['event_id'],
            reason='Recheck selected pair',idempotency_key='undo'))
        with self.assertRaises(ValueError):self.workspace.action('bank-reconcile',data|dict(idempotency_key='new'))
        self.assertEqual(self.workspace.action('bank-reconcile',data),receipt)
        self.assertTrue(self.view()['completions'][0]['current_state_drift'])
        self.timing('deposit','withdraw',idempotency_key='withdraw')
        self.assertEqual(self.view()['report']['deposits_in_transit'],'0.00')
        self.timing('deposit','deposit_in_transit',idempotency_key='review-again')
        self.assertEqual(self.view()['report']['deposits_in_transit'],'200.00')

    def test_unsupported_multiple_cash_lines_and_non_cash_cannot_be_timing(self):
        post(self.workspace,'no-cash',lines=[dict(account='1100',side='debit',amount='1.00'),dict(account='3000',side='credit',amount='1.00')])
        post(self.workspace,'self-cancel',lines=[dict(account='1000',side='debit',amount='1.00'),dict(account='1000',side='credit',amount='1.00')])
        for journal in ['no-cash','self-cancel']:
            with self.assertRaises(ValueError):self.timing(journal,'deposit_in_transit')
        self.assertTrue(any(item['journal_id']=='self-cancel' for item in self.view()['report']['book_exceptions']))

    def test_timing_failure_rolls_back_and_exact_retry_preserves_original(self):
        self.view()
        data=dict(bank_account_id='fictional-bank',statement_id='matching',journal_id='deposit',role='deposit_in_transit',
            reason='Reviewed timing',binding=self.view()['report']['digest'],idempotency_key='timing')
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger._connection.execute("CREATE TRIGGER fail_timing BEFORE INSERT ON reconciliation_receipts BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.workspace.action('bank-timing',data)
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger._connection.execute('DROP TRIGGER fail_timing')
            self.assertEqual(ledger._connection.execute('SELECT count(*) FROM reconciliation_timing').fetchone()[0],0)
        event=self.workspace.action('bank-timing',data)
        self.assertEqual(self.workspace.action('bank-timing',data),event)
        with self.assertRaises(ValueError):self.workspace.action('bank-timing',data|dict(reason='Changed'))

    def test_ambiguous_offsetting_rows_cannot_hide_behind_zero_difference(self):
        self.ready()
        post(self.workspace,'same-a','7.00');post(self.workspace,'same-b','7.00')
        post(self.workspace,'offset-book','14.00',side='credit')
        self.workspace.import_bank_statement(statement([bank_row('funding','950.00',day='01'),bank_row('fee','-10.00'),
            bank_row('ambiguous','7.00'),bank_row('offset-bank','-7.00')],'ambiguous'))
        report=self.workspace.bank_reconciliation('fictional-bank','ambiguous')['report']
        for item in report['eligible_timing']:
            current=self.workspace.bank_reconciliation('fictional-bank','ambiguous')['report']
            self.workspace.action('bank-timing',dict(bank_account_id='fictional-bank',statement_id='ambiguous',
                journal_id=item['journal_id'],role=item['role'],reason='Reviewed timing',binding=current['digest'],idempotency_key=item['journal_id']))
        report=self.workspace.bank_reconciliation('fictional-bank','ambiguous')['report']
        self.assertEqual(report['unexplained_difference'],'0.00')
        self.assertEqual(next(row for row in report['bank_exceptions'] if row['transaction_id']=='ambiguous')['reason'],'ambiguous bank row')
        self.assertFalse(report['can_complete'])

    def test_large_exact_values_and_unsupported_capture_policy(self):
        from accounting_harness.reconciliation import ReconciliationService,reconciliation_report
        post(self.workspace,'large','90071992547409.93',day='25')
        self.assertEqual(self.view()['report']['book_balance'],'90071992548409.93')
        with self.workspace.storage() as (_,ledger,_,_,_):
            capture=ReconciliationService(ledger).capture('fictional-bank','matching')
        changed=json.loads(capture);changed['policy']='unknown-future-policy'
        with self.assertRaises(ValueError):reconciliation_report(json.dumps(changed))

    def test_initialization_failure_rolls_back_new_schema_and_preserves_old_records(self):
        from accounting_harness.reconciliation import ReconciliationService
        from accounting_harness.review import protect_table
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            before={name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names}
            def fail(db,table,conflict):
                if table=='reconciliation_completions':raise sqlite3.OperationalError('injected')
                return protect_table(db,table,conflict)
            with patch('accounting_harness.reconciliation.protect_table',side_effect=fail),self.assertRaises(sqlite3.OperationalError):
                ReconciliationService(ledger)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='reconciliation_schema'").fetchone())
            self.assertEqual({name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names},before)
            ReconciliationService(ledger)
            self.assertEqual({name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names},before)

    def test_demo_reconciliation(self):
        import subprocess
        result=subprocess.run(['python3','-m','accounting_harness','demo-reconciliation'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for text in ['1000.00','940.00','200.00','150.00','990.00','10.00','zero model calls']:
            self.assertIn(text,result.stdout)


class ReconciliationHTTPTests(unittest.TestCase):
    from test_web import WorkspaceHTTPTests as _HTTP
    setUp=_HTTP.setUp
    tearDown=_HTTP.tearDown
    start=_HTTP.start
    stop=_HTTP.stop
    request=_HTTP.request

    def test_http_review_completion_strict_scope_csrf_and_restart(self):
        workspace=self.server.workspace
        workspace.import_bank_statement(statement([bank_row()]))
        post(workspace)
        query='/api/bank-reconciliation?bank_account_id=fictional-bank&statement_id=matching'
        status,view=self.request('GET',query)
        self.assertEqual(status,200,view)
        data=dict(bank_account_id='fictional-bank',statement_id='matching',binding=view['report']['digest'],idempotency_key='http')
        self.assertEqual(self.request('POST','/api/bank-reconcile',data,headers={'X-CSRF-Token':'bad'})[0],403)
        self.assertEqual(self.request('POST','/api/bank-reconcile',data)[0],409)
        row=workspace.bank_matches('fictional-bank')['rows'][0]
        workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id='deposit',journal_id='book',binding=row['binding'],idempotency_key='match'))
        data['binding']=self.request('GET',query)[1]['report']['digest']
        for change in [dict(actor_id='forged'),dict(amount='0.00'),dict(binding='stale')]:
            self.assertEqual(self.request('POST','/api/bank-reconcile',data|change)[0],409)
        status,receipt=self.request('POST','/api/bank-reconcile',data)
        self.assertEqual(status,200,receipt)
        self.stop();self.start()
        self.assertEqual(self.request('POST','/api/bank-reconcile',data),(200,receipt))
        for suffix in ['', '?bank_account_id=fictional-bank', '?bank_account_id=fictional-bank&statement_id=matching&extra=x']:
            self.assertEqual(self.request('GET','/api/bank-reconciliation'+suffix)[0],409)
