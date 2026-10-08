"""Deterministic candidates and audited human actions against real temporary stores."""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from accounting_harness.bank import BankStatementService
from accounting_harness.workspace import Workspace
from test_bank import HEADER, payload


def statement(rows, statement_id='matching'):
    from decimal import Decimal
    total = sum((Decimal(row[3]) for row in rows), Decimal('0.00'))
    return payload(statement_id=statement_id, opening_balance='0.00', closing_balance=str(total),
                   csv_content=HEADER + ''.join(','.join(row)+'\n' for row in rows))


def bank_row(identity='deposit', amount='200.00', reference='', day='05'):
    return ['fictional-bank', identity, '2026-01-'+day, amount, 'USD', reference, 'Fictional bank movement']


def post(workspace, identity='book', amount='200.00', side='debit', day='05', **changes):
    with workspace.storage() as (_, ledger, _, _, _):
        proposal = dict(id=identity, entity_id=workspace.catalog.entity_id, currency='USD',
            effective_date='2026-01-'+day, description='Fictional owner contribution',
            source_ids=['synthetic-receipt-002'], lines=[dict(account='1000',side=side,amount=amount),
                dict(account='3000',side='credit' if side == 'debit' else 'debit',amount=amount)]) | changes
        return ledger.admit(proposal, actor_id='fixture-operator', idempotency_key=identity)


class BankMatchingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)
        self.workspace.import_bank_statement(statement([bank_row()]))

    def view(self):
        return self.workspace.bank_matches('fictional-bank')

    def confirmation(self, key='confirm', row=None):
        row = row or self.view()['rows'][0]
        return dict(bank_account_id='fictional-bank', transaction_id=row['transaction_id'],
                    journal_id=row['candidates'][0]['journal_id'], binding=row['binding'], idempotency_key=key)

    def match(self, data=None):
        return self.workspace.action('bank-match', data or self.confirmation())

    def undo(self, receipt, key='undo', reason='Wrong selected pair'):
        return self.workspace.action('bank-unmatch', dict(bank_account_id='fictional-bank',
            match_event_id=receipt['event_id'], reason=reason, idempotency_key=key))

    def frozen_rows(self):
        with self.workspace.storage() as (_, ledger, _, _, _):
            db = ledger._connection
            names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('bank_match_events','bank_match_receipts') ORDER BY name")]
            return {name: db.execute('SELECT * FROM "'+name+'" ORDER BY 1').fetchall() for name in names}

    def test_unique_confirmation_changes_only_matching_history_and_preserves_classification(self):
        self.assertTrue(callable(getattr(self.workspace, 'bank_matches', None)), 'bank matching view is required')
        post(self.workspace)
        before = self.workspace.state()
        frozen = self.frozen_rows()
        row = self.view()['rows'][0]
        self.assertEqual(row['status'], 'unmatched')
        self.assertTrue(row['confirmable'])
        self.assertEqual(row['candidates'][0]['amount'], '200.00')
        self.assertEqual(row['candidates'][0]['source_ids'], ['synthetic-receipt-002'])
        self.assertEqual(row['candidates'][0]['reference_match'], False)
        receipt = self.match()
        self.assertEqual(receipt['actor_id'], 'local-operator')
        self.assertEqual(self.view()['rows'][0]['status'], 'matched')
        self.assertEqual(self.frozen_rows(), frozen)
        after = self.workspace.state()
        self.assertEqual(after['journals'], before['journals'])
        self.assertEqual(after['trial_balance'], before['trial_balance'])
        self.assertEqual(after['journal_count'], 1)

    def test_equal_book_amounts_are_ambiguous_without_exact_reference(self):
        post(self.workspace, 'book-a')
        post(self.workspace, 'book-b')
        row = self.view()['rows'][0]
        self.assertEqual(row['status'], 'ambiguous')
        self.assertEqual([c['journal_id'] for c in row['candidates']], ['book-a','book-b'])
        self.assertFalse(row['confirmable'])
        with self.assertRaises(ValueError):
            self.match()

    def test_equal_bank_rows_compete_for_one_journal(self):
        post(self.workspace)
        self.workspace.import_bank_statement(statement([bank_row('second')], 'second'))
        rows = self.view()['rows']
        self.assertEqual([r['status'] for r in rows], ['ambiguous','ambiguous'])
        self.assertEqual([len(r['candidates']) for r in rows], [1,1])
        self.assertFalse(any(r['confirmable'] for r in rows))
        with self.assertRaises(ValueError):
            self.match()

    def test_exact_journal_or_source_reference_narrows_but_description_substring_does_not(self):
        for reference in ['book-b', 'synthetic-receipt-006', 'book', '']:
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as directory:
                workspace = Workspace(directory)
                workspace.import_bank_statement(statement([bank_row(reference=reference)]))
                post(workspace, 'book-a')
                post(workspace, 'book-b', source_ids=['synthetic-receipt-006'])
                row = workspace.bank_matches('fictional-bank')['rows'][0]
                self.assertEqual(row['confirmable'], reference in ['book-b','synthetic-receipt-006'])
                self.assertEqual(len(row['candidates']), 1 if row['confirmable'] else 2)
                if row['confirmable']:
                    self.assertEqual(row['candidates'][0]['journal_id'], 'book-b')

    def test_date_window_sign_and_multiple_cash_lines(self):
        post(self.workspace, 'opposite', side='credit')
        post(self.workspace, 'late', day='09')
        post(self.workspace, 'no-cash', lines=[dict(account='1100',side='debit',amount='200.00'),dict(account='3000',side='credit',amount='200.00')])
        post(self.workspace, 'multiple', lines=[dict(account='1000',side='debit',amount='100.00'),dict(account='1000',side='debit',amount='100.00'),dict(account='3000',side='credit',amount='200.00')])
        row = self.view()['rows'][0]
        self.assertEqual(row['candidates'], [])
        self.assertEqual(row['exceptions'][0]['journal_id'], 'multiple')
        post(self.workspace, 'edge', day='08')
        self.assertEqual(self.view()['rows'][0]['candidates'][0]['date_difference_days'], 3)
        self.assertTrue(self.view()['rows'][0]['confirmable'])
        with self.assertRaises((ValueError,KeyError)):
            self.workspace.bank_matches('other-bank')

    def test_negative_cash_credit_candidate_and_exact_large_cents(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.import_bank_statement(statement([bank_row(amount='-90071992547409.93')]))
            post(workspace, amount='90071992547409.93', side='credit')
            candidate = workspace.bank_matches('fictional-bank')['rows'][0]['candidates'][0]
            self.assertEqual(candidate['amount'], '-90071992547409.93')
            self.assertEqual(candidate['amount_cents'], '-9007199254740993')

    def test_new_competing_journal_or_bank_row_invalidates_confirmation(self):
        post(self.workspace)
        data = self.confirmation()
        post(self.workspace, 'competing')
        with self.assertRaises(ValueError):
            self.match(data)
        self.assertEqual(self.view()['history'], [])

    def test_restart_unmatch_rematch_historical_retries_and_stale_unmatch(self):
        post(self.workspace)
        data = self.confirmation()
        receipt = self.match(data)
        self.assertEqual(self.match(data), receipt)
        with self.assertRaises(ValueError):
            self.match(dict(data, binding='changed'))
        with self.assertRaises(ValueError):
            self.undo(receipt, reason='   ')
        undone = self.undo(receipt)
        self.assertEqual(self.undo(receipt), undone)
        self.assertEqual(self.match(data), receipt)
        self.assertEqual(self.view()['rows'][0]['status'], 'unmatched')
        self.assertNotEqual(self.view()['rows'][0]['binding'], data['binding'])
        self.workspace = Workspace(self.directory.name)
        rematched = self.match(self.confirmation('rematch'))
        self.assertNotEqual(rematched['event_id'], receipt['event_id'])
        with self.assertRaises(ValueError):
            self.undo(receipt, key='stale')
        self.assertEqual(self.undo(receipt), undone)
        self.assertEqual(self.view()['rows'][0]['active_match'], rematched)
        self.assertEqual(len(self.view()['history']), 3)

    def test_overlapping_statement_has_no_extra_capacity_and_import_receipt_is_unchanged(self):
        original = self.workspace.import_bank_statement(statement([bank_row()]))
        post(self.workspace)
        self.match()
        self.workspace.import_bank_statement(statement([bank_row()], 'overlap'))
        self.assertEqual(len(self.view()['rows']), 1)
        self.assertEqual(self.workspace.import_bank_statement(statement([bank_row()])), original)

    def test_concurrent_confirmations_and_exact_retries(self):
        post(self.workspace)
        data = self.confirmation()
        def run(request):
            try:
                return self.match(request)
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run,[data,data]))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.view()['history']), 1)
        self.undo(results[0])
        data = self.confirmation('new')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run,[data,dict(data,idempotency_key='other')]))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(len(self.view()['history']),3)

    def test_request_fields_identity_and_binding_fail_closed(self):
        post(self.workspace)
        data = self.confirmation()
        for change in [dict(actor_id='forged'), dict(amount='1.00'), dict(policy='other'),
                       dict(entity_id='other'), dict(journal_id='missing'), dict(transaction_id='missing'),
                       dict(bank_account_id='other'), dict(binding='stale'), dict(idempotency_key='')]:
            with self.subTest(change=change), self.assertRaises((ValueError,KeyError)):
                self.match(data | change)
        self.assertEqual(self.view()['history'], [])

    def test_event_and_retry_failure_roll_back_atomically(self):
        post(self.workspace)
        data = self.confirmation()
        for table in ['bank_match_events', 'bank_match_receipts']:
            with self.workspace.storage() as (_, ledger, _, _, _):
                db = ledger._connection
                db.execute(f"CREATE TRIGGER fail_match BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.match(data)
            with self.workspace.storage() as (_, ledger, _, _, _):
                ledger._connection.execute('DROP TRIGGER fail_match')
                self.assertEqual(ledger._connection.execute('SELECT count(*) FROM bank_match_receipts').fetchone()[0],0)
            self.assertEqual(self.view()['history'], [])
        self.match(data)

    def test_events_and_receipts_reject_update_delete_replace(self):
        post(self.workspace)
        receipt = self.match()
        self.undo(receipt)
        with self.workspace.storage() as (_, ledger, _, _, _):
            db = ledger._connection
            for table in ['bank_match_events','bank_match_receipts']:
                row = db.execute('SELECT * FROM '+table+' LIMIT 1').fetchone()
                column = db.execute('PRAGMA table_info('+table+')').fetchone()[1]
                for sql,args in [('DELETE FROM '+table,()),('UPDATE '+table+' SET '+column+'='+column,()),
                    ('INSERT OR REPLACE INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',row)]:
                    with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql,args)

    def test_schema_one_migration_preserves_import_bytes_and_rolls_back_failed_ddl(self):
        # Golden schema/import exported by the actual delivered Step 17 implementation.
        self.workspace = Workspace(Path(self.directory.name) / 'legacy')
        with self.workspace.storage() as (_, ledger, _, _, _):
            fixture = Path(__file__).with_name('fixtures') / 'step17-bank-v1.sql'
            ledger._connection.executescript('BEGIN; PRAGMA defer_foreign_keys=ON;\n' + fixture.read_text() + '\nCOMMIT;')
        before = self.frozen_rows()
        from accounting_harness.bank import protect_table as real_protect
        def fail(db, table, conflict):
            if table == 'bank_match_receipts':
                raise sqlite3.OperationalError('injected migration failure')
            return real_protect(db,table,conflict)
        with self.workspace.storage() as (_, ledger, _, _, _):
            with patch('accounting_harness.bank.protect_table', side_effect=fail), self.assertRaises(sqlite3.OperationalError):
                BankStatementService(ledger)
            self.assertEqual(ledger._connection.execute('SELECT version FROM bank_schema').fetchall(),[(1,)])
            self.assertIsNone(ledger._connection.execute("SELECT 1 FROM sqlite_master WHERE name='bank_match_events'").fetchone())
        self.assertEqual(self.frozen_rows(),before)
        self.view()
        after = self.frozen_rows()
        self.assertEqual(after.pop('bank_schema'),[(2,)])
        before.pop('bank_schema')
        self.assertEqual(after,before)

    def test_new_bank_competitor_invalidates_prior_binding_and_cannot_consume_matched_journal(self):
        post(self.workspace)
        data = self.confirmation()
        self.workspace.import_bank_statement(statement([bank_row('other')], 'other'))
        with self.assertRaises(ValueError):
            self.match(data)
        self.assertEqual(self.view()['history'], [])
        # Separate unique referenced book entry resolves the competing row, never the prior binding.
        post(self.workspace, 'other-book', amount='100.00')
        self.assertFalse(any(row['confirmable'] for row in self.view()['rows']))

    def test_unmatch_failure_retains_active_pair_and_retry_receipt(self):
        post(self.workspace)
        receipt = self.match()
        before = self.frozen_rows()
        with self.workspace.storage() as (_, ledger, _, _, _):
            ledger._connection.execute("CREATE TRIGGER fail_undo BEFORE INSERT ON bank_match_receipts WHEN NEW.operation='unmatch' BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.undo(receipt)
        self.assertEqual(self.view()['rows'][0]['active_match'], receipt)
        self.assertEqual(len(self.view()['history']),1)
        self.assertEqual(self.frozen_rows(),before)
        with self.workspace.storage() as (_, ledger, _, _, _):
            ledger._connection.execute('DROP TRIGGER fail_undo')
        self.undo(receipt)

    def test_actively_matched_journal_is_excluded_from_later_bank_row(self):
        post(self.workspace)
        receipt = self.match()
        self.workspace.import_bank_statement(statement([bank_row('later')], 'later'))
        row = next(row for row in self.view()['rows'] if row['transaction_id'] == 'later')
        self.assertEqual(row['status'],'unmatched')
        self.assertEqual(row['candidates'],[])
        with self.assertRaises(ValueError):
            self.match(dict(bank_account_id='fictional-bank',transaction_id='later',journal_id='book',binding=receipt['binding'],idempotency_key='late'))

    def test_database_guards_reject_missing_wrong_entity_and_wrong_unmatch_target(self):
        post(self.workspace)
        receipt = self.match()
        with self.workspace.storage() as (_, ledger, _, _, _):
            db = ledger._connection
            values = list(db.execute('SELECT * FROM bank_match_events').fetchone())
            # sequence,event,entity,bank,transaction,journal,operation,key,target,event_json
            for index,value in [(2,'other-entity'),(3,'other-bank'),(4,'missing-bank-row'),(5,'missing-journal'),(8,'missing-match')]:
                forged = list(values)
                forged[0],forged[1],forged[7] = 2,'forged-event','forged-key'
                forged[index] = value
                if index == 8:
                    forged[6] = 'unmatch'
                with self.subTest(index=index), self.assertRaises(sqlite3.IntegrityError):
                    with ledger._transaction(write=True):
                        db.execute('INSERT INTO bank_match_events VALUES(?,?,?,?,?,?,?,?,?,?)',forged)
                        db.execute('INSERT INTO bank_match_receipts VALUES(?,?,?,?,?,?)',
                            (forged[2],forged[3],forged[6],forged[7],'digest',forged[1]))
        self.assertEqual(self.view()['rows'][0]['active_match'], receipt)



class BankMatchHTTPTests(unittest.TestCase):
    from test_web import WorkspaceHTTPTests as _HTTP
    setUp = _HTTP.setUp
    tearDown = _HTTP.tearDown
    start = _HTTP.start
    stop = _HTTP.stop
    request = _HTTP.request

    def test_http_pair_confirmation_unmatch_restart_and_strict_boundary(self):
        workspace = self.server.workspace
        workspace.import_bank_statement(statement([bank_row()]))
        post(workspace)
        status, view = self.request('GET','/api/bank-matches?bank_account_id=fictional-bank')
        self.assertEqual(status,200,view)
        row = view['rows'][0]
        data = dict(bank_account_id='fictional-bank',transaction_id='deposit',journal_id='book',
                    binding=row['binding'],idempotency_key='http')
        for change in [dict(actor_id='forged'),dict(amount='1.00'),dict(entity_id='other')]:
            self.assertEqual(self.request('POST','/api/bank-match',data | change)[0],409)
        self.assertEqual(self.request('POST','/api/bank-match',data,headers={'X-CSRF-Token':'bad'})[0],403)
        status, receipt = self.request('POST','/api/bank-match',data)
        self.assertEqual(status,200,receipt)
        self.assertEqual(receipt['actor_id'],'local-operator')
        undo = dict(bank_account_id='fictional-bank',match_event_id=receipt['event_id'],reason='Human correction',idempotency_key='http')
        self.assertEqual(self.request('POST','/api/bank-unmatch',undo)[0],200)
        self.stop()
        self.start()
        self.assertEqual(self.request('POST','/api/bank-match',data),(200,receipt))
        view = self.request('GET','/api/bank-matches?bank_account_id=fictional-bank')[1]
        self.assertEqual(view['rows'][0]['status'],'unmatched')
        self.assertEqual(len(view['history']),2)
        for query in ['', '?bank_account_id=', '?bank_account_id=fictional-bank&bank_account_id=other', '?entity_id=other']:
            self.assertEqual(self.request('GET','/api/bank-matches'+query)[0],409)
        self.assertEqual(self.request('GET','/api/bank-matches?bank_account_id=other')[0],404)

    def test_demo_bank_match_command(self):
        import subprocess
        result = subprocess.run(['python3','-m','accounting_harness','demo-bank-match'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('200.00', result.stdout)
        self.assertIn('ambiguous', result.stdout)
        self.assertIn('unchanged', result.stdout)
