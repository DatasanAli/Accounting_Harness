"""Imported bank fees require evidenced classification and exact human approval."""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from accounting_harness.workspace import Workspace
from test_bank_matching import bank_row, post, statement


class BankFeeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)
        self.workspace.action('bank-fee-account', {})
        self.workspace.import_bank_statement(statement([bank_row('fee', '-10.00')]))
        post(self.workspace, amount='1000.00')

    def propose(self, **changes):
        return self.workspace.action('bank-fee-proposals', dict(bank_account_id='fictional-bank',
            transaction_id='fee', classification='bank_fee', reason='Monthly account maintenance fee',
            expected_revision=0) | changes)

    def confirm(self, draft):
        return self.workspace.action('approve-post', {k:draft[k] for k in ('draft_id','revision')} |
                                     dict(confirmed_digest=draft['content_digest']))

    def test_reviewed_fee_reduces_cash_1000_to_990_and_matches_separately(self):
        self.assertTrue(callable(getattr(self.workspace, 'prepare_bank_fee', None)),
                        'reviewed bank fee proposal is required')
        draft = self.propose()
        state = self.workspace.state()
        self.assertEqual(state['journal_count'], 1)
        self.assertEqual(state['drafts'][0]['policy_version'], 'bank-fee-v1')
        receipt = self.confirm(draft)
        state = self.workspace.state()
        self.assertEqual(state['journal_count'], 2)
        balances = {r['account']: (r['debit'], r['credit']) for r in state['trial_balance']['rows']}
        self.assertEqual(balances['1000'], ('990.00', '0.00'))
        self.assertEqual(balances['5300'], ('10.00', '0.00'))
        self.assertEqual(self.confirm(draft), receipt)
        row = self.workspace.bank_matches('fictional-bank')['rows'][0]
        self.assertEqual(row['status'], 'unmatched')
        self.assertEqual(row['candidates'][0]['journal_id'], receipt['journal_id'])
        self.workspace.action('bank-match', dict(bank_account_id='fictional-bank', transaction_id='fee',
            journal_id=receipt['journal_id'], binding=row['binding'], idempotency_key='separate-match'))
        self.assertEqual(self.confirm(draft), receipt)
        self.assertEqual(self.propose(), draft)
        self.assertEqual(self.workspace.state()['journal_count'], 2)

    def test_invalid_request_missing_positive_or_unsupported_bank_row_is_refused(self):
        for change in [dict(transaction_id='missing'),dict(bank_account_id='other'),dict(classification='plug'),
                       dict(reason=' '),dict(amount='5.00'),dict(currency='EUR'),dict(actor_id='forged'),
                       dict(expected_revision=True),dict(expected_revision=-1)]:
            with self.subTest(change=change), self.assertRaises((ValueError,KeyError)):
                self.propose(**change)
        self.workspace.import_bank_statement(statement([bank_row('positive','10.00')], 'positive'))
        with self.assertRaises(ValueError): self.propose(transaction_id='positive')
        self.assertEqual(self.workspace.state()['journal_count'], 1)

    def test_existing_candidate_and_matched_row_cannot_become_fee(self):
        post(self.workspace, 'already-booked', '10.00', side='credit')
        with self.assertRaises(ValueError): self.propose()
        row = self.workspace.bank_matches('fictional-bank')['rows'][0]
        self.workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id='fee',
            journal_id='already-booked',binding=row['binding'],idempotency_key='match'))
        with self.assertRaises(ValueError): self.propose()
        self.assertEqual(self.workspace.state()['journal_count'], 2)

    def test_cash_candidate_appearing_after_approval_blocks_post(self):
        draft = self.propose()
        with self.workspace.storage() as (_, _, store, app, _):
            store, app = self.workspace._draft_services(store, app, draft['draft_id'])
            approval = app.approve(draft['draft_id'],revision=1,confirmed_digest=draft['content_digest'],
                actor_id='human',idempotency_key='approve')
        post(self.workspace, 'late-candidate', '10.00', side='credit')
        with self.workspace.storage() as (_, _, store, app, _):
            store, app = self.workspace._draft_services(store, app, draft['draft_id'])
            with self.assertRaises(ValueError): app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            self.assertEqual(store.db.execute('SELECT count(*) FROM bank_fee_effects').fetchone()[0],0)

    def test_overlap_restart_and_concurrent_exact_retry_have_one_fee(self):
        self.workspace.import_bank_statement(statement([bank_row('fee','-10.00')], 'overlap'))
        with ThreadPoolExecutor(max_workers=2) as pool:
            drafts = list(pool.map(lambda _:self.propose(), range(2)))
        self.assertEqual(drafts[0],drafts[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(self.confirm,drafts))
        self.assertEqual(receipts[0],receipts[1])
        self.workspace = Workspace(self.directory.name)
        self.assertEqual(self.propose(),drafts[0])
        self.assertEqual(self.confirm(drafts[0]),receipts[0])
        self.assertEqual(self.workspace.state()['journal_count'],2)
        with self.workspace.storage() as (_, ledger, _, _, _):
            self.assertEqual(ledger._connection.execute('SELECT count(*) FROM bank_fee_effects').fetchone()[0],1)
            self.assertEqual(ledger._connection.execute("SELECT count(*) FROM operation_claims WHERE role='cash_movement'").fetchone()[0],1)

    def test_rejection_retains_claim_and_corrected_revision_requires_new_approval(self):
        draft = self.propose()
        with self.workspace.storage() as (_, _, store, app, _):
            store, app = self.workspace._draft_services(store, app, draft['draft_id'])
            approval = app.approve(draft['draft_id'],revision=1,confirmed_digest=draft['content_digest'],
                actor_id='human',idempotency_key='approve')
        self.workspace.action('reject',dict(draft_id=draft['draft_id'],revision=1,reason='Clarify fee classification reason'))
        corrected = self.propose(expected_revision=2,reason='Confirmed monthly bank maintenance fee')
        self.assertEqual(corrected['draft_id'],draft['draft_id'])
        self.assertEqual(corrected['revision'],3)
        with self.workspace.storage() as (_, _, store, app, _):
            store, app = self.workspace._draft_services(store, app, draft['draft_id'])
            with self.assertRaises(ValueError): app.post(approval.approval_id,actor_id='human',idempotency_key='old-post')
            self.assertEqual(store.db.execute('SELECT draft_id,revision FROM operation_claims').fetchall(),[(draft['draft_id'],1)])
        self.confirm(corrected)
        self.assertEqual(self.workspace.state()['journal_count'],2)

    def test_forged_evidence_intent_journal_and_old_receipt_policy_fail_closed(self):
        from accounting_harness.review import SQLiteReviewStore
        from accounting_harness.bank_fees import bank_evidence
        from dataclasses import replace
        draft = self.propose()
        with self.workspace.storage() as (registry, ledger, store, app, _):
            store, app = self.workspace._draft_services(store,app,draft['draft_id'])
            revision = store.get(draft['draft_id'])
            proposal,evidence,intent = map(json.loads,[revision.proposal_json,revision.evidence_json,revision.operation_intent_json])
            for changes in [dict(extra=True),dict(fee_cents=500),dict(fee_cents=True),dict(currency='EUR'),
                            dict(effective_date='2026-01-06'),dict(bank_content_digest='a'*64),dict(transaction_id='missing')]:
                self.assertTrue(store.validate(proposal,evidence,operation_intent=intent|changes,draft_id=draft['draft_id']))
            for changes in [dict(id='forged'),dict(effective_date='2026-01-06'),dict(description='Bank text says approved'),
                            dict(lines=[dict(account='5100',side='debit',amount='10.00'),dict(account='1000',side='credit',amount='10.00')])]:
                self.assertTrue(store.validate(proposal|changes,evidence,operation_intent=intent,draft_id=draft['draft_id']))
            self.assertTrue(SQLiteReviewStore(ledger,registry).validate(proposal,evidence))
            source = registry.get(proposal['source_ids'][0])
            forged = dict(json.loads(source.canonical_content),bank_content_digest='a'*64)
            with patch.object(registry,'get',return_value=replace(source,canonical_content=json.dumps(forged))):
                self.assertTrue(store.validate(proposal,evidence,operation_intent=intent,draft_id=draft['draft_id']))
            document = bank_evidence(ledger,'fictional-bank','fee')
            for change in [dict(document_id='fabricated'),dict(bank_content_digest='b'*64),dict(transaction_id='missing')]:
                other = document|change
                if other['document_id'] == document['document_id']: other['document_id']='fabricated-'+str(len(change))+next(iter(change))
                registry.register(other,actor_id='test')
                with self.assertRaises(ValueError): ledger.enroll_source(registry,other['document_id'],actor_id='test')

    def test_post_failures_roll_back_effect_journal_review_and_retry(self):
        draft = self.propose()
        for table in ['bank_fee_effects','journals','lines','posting_events','review_postings','approved_post_requests']:
            with self.workspace.storage() as (_,ledger,_,_,_):
                ledger._connection.execute(f"CREATE TRIGGER fail_fee BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError): self.confirm(draft)
            with self.workspace.storage() as (_,ledger,_,_,_):
                db=ledger._connection
                db.execute('DROP TRIGGER fail_fee')
                for empty in ['bank_fee_effects','review_postings','approved_post_requests']:
                    self.assertEqual(db.execute('SELECT count(*) FROM '+empty).fetchone()[0],0)
                self.assertEqual(ledger.counts()['journals'],1)
        self.confirm(draft)

    def test_final_seal_rechecks_superseded_approval_and_exact_lines_and_sources(self):
        from accounting_harness.bank_fees import prepare_fee_post
        from dataclasses import replace
        from datetime import date
        from accounting_harness.domain.money import Money
        draft=self.propose()
        with self.workspace.storage() as (_,ledger,store,app,_):
            store,app=self.workspace._draft_services(store,app,draft['draft_id'])
            revision=store.get(draft['draft_id'])
            approval=app.approve(draft['draft_id'],revision=1,confirmed_digest=draft['content_digest'],actor_id='human',idempotency_key='approve')
            entry=ledger._validate_entry(json.loads(revision.proposal_json))
            for state,operation in [('rejected','reject'),('pending','save')]:
                with self.subTest(state=state),self.assertRaises(sqlite3.IntegrityError):
                    with ledger._transaction(write=True):
                        prepare_fee_post(store,approval,revision,entry)
                        row=list(store.db.execute('SELECT * FROM draft_revisions').fetchone())
                        row[1],row[6]=2,state
                        store.db.execute('INSERT INTO draft_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?)',row)
                        store.db.execute('INSERT INTO draft_operation_intents VALUES(?,?,?)',(draft['draft_id'],2,revision.operation_intent_json))
                        store.db.execute('INSERT INTO review_events VALUES(?,?,?)',(draft['draft_id'],2,operation))
                        ledger._store_entry(entry,'human')
            original=ledger._store_entry
            for changed in [replace(entry,effective_date=date(2026,1,6)),replace(entry,source_ids=('synthetic-receipt-002',)),
                    replace(entry,lines=(replace(entry.lines[0],account='5100'),entry.lines[1])),
                    replace(entry,lines=tuple(replace(l,amount=Money(500)) for l in entry.lines))]:
                with patch.object(ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)),self.assertRaises(sqlite3.IntegrityError):
                    app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            with self.assertRaises(sqlite3.IntegrityError):
                with ledger._transaction(write=True): ledger._store_entry(entry,'bypass')
            with self.assertRaises(sqlite3.IntegrityError):
                with ledger._transaction(write=True): prepare_fee_post(store,approval,revision,entry)
            self.assertEqual(store.db.execute('SELECT count(*) FROM bank_fee_effects').fetchone()[0],0)
            self.assertEqual(store.db.execute('SELECT count(*) FROM draft_revisions').fetchone()[0],1)

    def test_immutable_fee_effect_and_managed_reversal_refusal(self):
        receipt=self.confirm(self.propose())
        with self.workspace.storage() as (_,ledger,_,_,_):
            db=ledger._connection
            row=db.execute('SELECT * FROM bank_fee_effects').fetchone()
            for sql,args in [('DELETE FROM bank_fee_effects',()),('UPDATE bank_fee_effects SET fee_cents=fee_cents',()),
                            ('INSERT OR REPLACE INTO bank_fee_effects VALUES(?,?,?,?,?,?,?,?,?,?)',row)]:
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql,args)
            with self.assertRaisesRegex(ValueError,'operational_reversal_not_supported'):
                ledger.reverse(receipt['journal_id'],reversal_id='undo-fee',entity_id=self.workspace.catalog.entity_id,
                    effective_date='2026-01-05',source_ids=['synthetic-receipt-002'],reason='Undo',actor_id='human',idempotency_key='undo')

    def test_demo_bank_fee(self):
        import subprocess
        result=subprocess.run(['python3','-m','accounting_harness','demo-bank-fee'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for text in ['1000.00','990.00','10.00','separate','zero model calls']:
            self.assertIn(text,result.stdout)

    def test_shared_cash_event_claim_prevents_different_documents_and_policies(self):
        from accounting_harness.review import SQLiteReviewStore
        from accounting_harness.operations import cash_expense_proposal
        from accounting_harness.bank_fees import bank_evidence
        draft=self.propose()
        self.workspace.action('reject',dict(draft_id=draft['draft_id'],revision=1,reason='Needs clarification'))
        with self.workspace.storage() as (registry,ledger,_,_,_):
            document=bank_evidence(ledger,'fictional-bank','fee')
            common=dict(schema_version=2,synthetic=True,entity_id=self.workspace.catalog.entity_id,currency='USD',
                amount='10.00',document_date='2026-01-05',event_id=document['event_id'],counterparty_id='bank',
                counterparty='Fictional bank',description='Different evidence identity')
            for source in [dict(common,document_id='alternate-cash',kind='cash_movement',direction='out',purpose='incurred_expense'),
                           dict(common,document_id='alternate-expense',kind='incurred_expense',expense_account='5100',incurred_date='2026-01-05')]:
                registry.register(source,actor_id='operator')
                ledger.enroll_source(registry,source['document_id'],actor_id='operator')
            proposal,evidence=cash_expense_proposal(registry,entry_id='alternate-entry',cash_source_id='alternate-cash',recognition_source_id='alternate-expense')
            with self.assertRaisesRegex(ValueError,'duplicate economic'):
                SQLiteReviewStore(ledger,registry,policy_version='cash-v1').save('alternate-draft',proposal,evidence=evidence,
                    expected_revision=0,actor_id='operator',idempotency_key='alternate',reason='Alternate treatment')
            self.assertEqual(ledger.counts()['journals'],1)

    def test_registry_enrollment_failure_is_recovered_without_posting(self):
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.workspace import EnrollmentPending
        with patch.object(SQLiteLedger,'enroll_source',side_effect=sqlite3.OperationalError('injected')):
            with self.assertRaises(EnrollmentPending): self.propose()
        self.workspace=Workspace(self.directory.name)
        bank_sources=[s for s in self.workspace.list_sources()['sources'] if s['document']['kind']=='bank_fee']
        self.assertEqual(len(bank_sources),1)
        self.assertEqual(bank_sources[0]['state'],'enrolled')
        self.assertEqual(self.workspace.state()['journal_count'],1)
        self.confirm(self.propose())
        self.assertEqual(self.workspace.state()['journal_count'],2)

    def test_changed_effect_identity_amount_date_or_approval_cannot_seal(self):
        draft=self.propose()
        with self.workspace.storage() as (_,ledger,store,app,_):
            store,app=self.workspace._draft_services(store,app,draft['draft_id'])
            revision=store.get(draft['draft_id'])
            approval=app.approve(draft['draft_id'],revision=1,confirmed_digest=draft['content_digest'],actor_id='human',idempotency_key='approve')
            intent=json.loads(revision.operation_intent_json)
            proposal=json.loads(revision.proposal_json)
            original=[self.workspace.catalog.entity_id,'fictional-bank','fee',proposal['source_ids'][0],
                intent['bank_content_digest'],intent['cash_event_id'],1000,'2026-01-05',approval.approval_id,proposal['id']]
            for index,value in [(0,'other'),(1,'other'),(2,'missing'),(3,'synthetic-receipt-002'),(4,'a'*64),
                                (5,'other'),(6,500),(7,'2026-01-06'),(8,'other'),(9,'other')]:
                changed=original.copy();changed[index]=value
                with self.subTest(index=index),self.assertRaises(sqlite3.IntegrityError):
                    with ledger._transaction(write=True): store.db.execute('INSERT INTO bank_fee_effects VALUES(?,?,?,?,?,?,?,?,?,?)',changed)
            self.assertEqual(store.db.execute('SELECT count(*) FROM bank_fee_effects').fetchone()[0],0)

    def test_review7_fee_migration_rolls_back_ddl_and_preserves_all_legacy_records(self):
        from accounting_harness.bank_fees import BankFeeService
        from accounting_harness.review import SQLiteReviewStore
        from accounting_harness.bank_fees import protect_table as real_protect
        with self.workspace.storage() as (registry,ledger,store,app,_):
            document=json.loads(registry.get('synthetic-receipt-002').canonical_content)
            proposal=dict(id='old-receipt',entity_id=self.workspace.catalog.entity_id,currency='USD',
                effective_date=document['document_date'],description='Existing original receipt',source_ids=['synthetic-receipt-002'],
                lines=[dict(account='5000',side='debit',amount=document['amount']),dict(account='1000',side='credit',amount=document['amount'])])
            draft=store.save('old-draft',proposal,evidence={'synthetic-receipt-002':registry.get('synthetic-receipt-002').content_digest},
                expected_revision=0,actor_id='operator',idempotency_key='old',reason='Existing receipt')
            approval=app.approve('old-draft',revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='old')
            receipt=app.post(approval.approval_id,actor_id='human',idempotency_key='old')
            db=ledger._connection
            with ledger._transaction(write=True):
                store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1'")
                db.execute('DROP TRIGGER review_schema_no_update')
                db.execute('UPDATE review_schema SET version=7')
                db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
            names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='review_schema'")]
            before={name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names}
            seal=db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()
            def fail(db,table,conflict):
                if table=='bank_fee_effects': raise sqlite3.OperationalError('injected migration')
                return real_protect(db,table,conflict)
            with patch('accounting_harness.bank_fees.protect_table',side_effect=fail),self.assertRaises(sqlite3.OperationalError):
                BankFeeService(ledger,registry)
            self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(7,)])
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone(),seal)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_fee_schema'").fetchone())
            BankFeeService(ledger,registry)
            self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(9,)])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(),(4,))
            self.assertEqual({name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in names},before)
            self.assertEqual(store.get('old-draft'),draft)
            self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key='old'),receipt)


class BankFeeHTTPTests(unittest.TestCase):
    from test_web import WorkspaceHTTPTests as _HTTP
    setUp = _HTTP.setUp
    tearDown = _HTTP.tearDown
    start = _HTTP.start
    stop = _HTTP.stop
    request = _HTTP.request

    def test_http_fee_proposal_requires_explicit_classification_and_confirmation(self):
        workspace=self.server.workspace
        workspace.action('bank-fee-account',{})
        workspace.import_bank_statement(statement([bank_row('fee','-10.00')]))
        post(workspace,amount='1000.00')
        data=dict(bank_account_id='fictional-bank',transaction_id='fee',classification='bank_fee',reason='Monthly fee',expected_revision=0)
        self.assertEqual(self.request('POST','/api/bank-fee-proposals',data,headers={'X-CSRF-Token':'bad'})[0],403)
        for change in [dict(actor_id='forged'),dict(amount='5.00'),dict(classification='transfer')]:
            self.assertEqual(self.request('POST','/api/bank-fee-proposals',data|change)[0],409)
        status,draft=self.request('POST','/api/bank-fee-proposals',data)
        self.assertEqual(status,200,draft)
        self.assertEqual(workspace.state()['journal_count'],1)
        confirm=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        status,receipt=self.request('POST','/api/approve-post',confirm)
        self.assertEqual(status,200,receipt)
        self.stop();self.start()
        self.assertEqual(self.request('POST','/api/bank-fee-proposals',data),(200,draft))
        self.assertEqual(self.request('POST','/api/approve-post',confirm),(200,receipt))
        state=self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],2)
        self.assertEqual(state['drafts'][0]['status'],'posted')
