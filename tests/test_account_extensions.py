"""Fixed account activation preserves historical identity and approval boundaries."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
from threading import Barrier
from unittest.mock import patch

import test_review
from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.ledger import EntryRejected, trial_balance
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.runs import FakeProvider, RunLimits, SQLiteRunEngine


class AccountExtensionTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp
    save = test_review.ReviewTests.save

    def activate(self, ledger=None, actor='human'):
        self.assertTrue(hasattr(SQLiteLedger, 'ensure_bank_fee_account'), 'audited account activation is required')
        return (ledger or self.ledger).ensure_bank_fee_account(actor_id=actor)

    def test_fixed_activation_is_audited_idempotent_and_visible_to_open_connections(self):
        old = self.ledger.snapshot
        old_report = trial_balance(old, '2026-01-31')
        context = self.ledger._context
        with self.assertRaises(ValueError): old.catalog.get_for_posting('5300')
        with SQLiteLedger(self.path, **self.options) as other:
            first = self.activate()
            self.assertEqual(first, self.activate(other, 'retrying-human'))
            account = other.current_catalog().get_for_posting('5300')
            self.assertEqual(asdict(account), dict(code='5300', name='Bank Fees Expense',
                classification='expense', normal_side='debit', active=True, temporary=True))
            self.assertEqual(json.loads(first.canonical_metadata), asdict(account))
            self.assertEqual(first.metadata_digest, hashlib.sha256(first.canonical_metadata.encode()).hexdigest())
            self.assertEqual(first.entity_id, self.catalog.entity_id)
            self.assertEqual(first.actor_id, 'human')
            self.assertEqual(first.operation, 'activate-bank-fee-account-v1')
            self.assertEqual(other.snapshot.catalog, other.current_catalog())
        self.assertEqual(self.ledger._context, context)
        self.assertEqual(self.ledger._empty.catalog, old.catalog)
        self.assertEqual(self.ledger.snapshot.entries, old.entries)
        self.assertEqual(len(old.catalog.accounts), 13)
        self.assertEqual(len(self.ledger.snapshot.catalog.accounts), 14)
        self.assertEqual(trial_balance(old, '2026-01-31'), old_report)
        self.assertEqual(self.ledger.counts()['journals'], 0)
        self.assertEqual(self.ledger.trial_balance('2026-01-31').total_debits.cents, 0)

    def test_current_validation_accepts_fee_account_but_receipt_policy_refuses_it(self):
        fee = dict(self.proposal, lines=[dict(account='5300', side='debit', amount='1200.00'),
                                       dict(account='1000', side='credit', amount='1200.00')])
        with self.assertRaises(EntryRejected): self.ledger._validate_entry(fee)
        self.activate()
        self.assertEqual(self.ledger._validate_entry(fee).lines[0].account, '5300')
        findings = self.store.validate(fee, self.evidence)
        self.assertTrue(findings)
        self.assertNotIn('invalid_account', [f.code for f in findings])
        draft = self.save(proposal=fee)
        with self.assertRaises(ValueError):
            ReviewApplication(self.store).approve('draft', revision=1, confirmed_digest=draft.content_digest,
                actor_id='human', idempotency_key='denied')
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_legacy_post_approval_and_provider_run_keep_exact_bytes_after_reopen(self):
        receipt = self.ledger.admit(self.proposal, actor_id='legacy', idempotency_key='legacy')
        draft = self.save(proposal=dict(self.proposal, id='approved-journal'))
        app = ReviewApplication(self.store)
        approval = app.approve('draft', revision=1, confirmed_digest=draft.content_digest,
                               actor_id='human', idempotency_key='approval')
        path = self.path.with_name('runs.sqlite3')
        provider = FakeProvider([dict(tool='read_accounts', arguments=dict(entity_id=self.catalog.entity_id))])
        with SQLiteRunEngine(path, self.store) as engine:
            checkpoint = engine.start('in-progress', task_id='task', provider=provider,
                                      actor_id='agent', limits=RunLimits(2, 10000, 10, 0))
            configuration, scope = engine.configuration('in-progress'), engine._scope
        tables = ('ledger_context', 'sources', 'source_enrollments', 'journals', 'lines',
                  'idempotency', 'approvals', 'approval_requests', 'draft_revisions')
        before = {t: self.ledger._connection.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        first = self.activate()
        with SQLiteLedger(self.path, **self.options) as ledger:
            store = SQLiteReviewStore(ledger, self.registry)
            for table, rows in before.items():
                self.assertEqual(ledger._connection.execute(f'SELECT * FROM {table}').fetchall(), rows)
            self.assertEqual(ledger._context, self.ledger._context)
            self.assertEqual(ledger.admit(self.proposal, actor_id='legacy', idempotency_key='legacy'), receipt)
            self.assertEqual(self.activate(ledger), first)
            with SQLiteRunEngine(path, store) as engine:
                self.assertEqual(engine.get('in-progress'), checkpoint)
                self.assertEqual(engine.configuration('in-progress'), configuration)
                self.assertEqual(engine._scope, scope)
            self.assertEqual(ReviewApplication(store).post(approval.approval_id,
                actor_id='human', idempotency_key='post').entry.id, 'approved-journal')

    def test_concurrent_activation_returns_original_audit(self):
        barrier = Barrier(2)
        def activate(actor):
            with SQLiteLedger(self.path, **self.options) as ledger:
                barrier.wait()
                return self.activate(ledger, actor)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(activate, ('first', 'second')))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.ledger._connection.execute('SELECT count(*) FROM account_extensions').fetchone(), (1,))

    def test_direct_unaudited_insert_replace_update_delete_are_denied(self):
        self.activate()
        db = self.ledger._connection
        row = db.execute('SELECT * FROM account_extensions').fetchone()
        for sql, values in [("INSERT INTO accounts VALUES ('5400')", ()),
                ("INSERT OR REPLACE INTO accounts VALUES ('1000')", ()),
                ("INSERT OR REPLACE INTO accounts VALUES ('5300')", ()),
                ("UPDATE accounts SET code='changed' WHERE code='5300'", ()),
                ("DELETE FROM accounts WHERE code='5300'", ()),
                ("UPDATE account_extensions SET actor_id='changed'", ()),
                ('DELETE FROM account_extensions', ()),
                ('INSERT OR REPLACE INTO account_extensions VALUES (?,?,?,?,?,?,?)', row)]:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError): db.execute(sql, values)

    def test_anchor_and_account_write_faults_rollback_both_rows(self):
        self.assertTrue(hasattr(SQLiteLedger, 'ensure_bank_fee_account'))
        db = self.ledger._connection
        for table in ('account_extensions', 'accounts'):
            db.execute(f"CREATE TRIGGER fail_activation BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError): self.activate()
            self.assertEqual(db.execute('SELECT * FROM account_extensions').fetchall(), [])
            self.assertEqual(db.execute("SELECT * FROM accounts WHERE code='5300'").fetchall(), [])
            db.execute('DROP TRIGGER fail_activation')
        self.activate()

    def test_actor_wrong_entity_and_conflicting_baseline_metadata_refused(self):
        self.assertTrue(hasattr(SQLiteLedger, 'ensure_bank_fee_account'))
        for actor in ('', ' bad', None):
            with self.assertRaises((TypeError, ValueError)): self.activate(actor=actor)
        with self.assertRaises(ValueError):
            SQLiteLedger(self.path, **dict(self.options, catalog=replace(self.catalog, entity_id='wrong')))
        from accounting_harness.domain.accounts import Account
        conflict = replace(self.catalog, accounts=(*self.catalog.accounts,
            Account('5300', 'Wrong Expense', 'expense', 'debit', temporary=True)))
        with SQLiteLedger(self.path.with_name('conflict.sqlite3'), **dict(self.options, catalog=conflict)) as ledger:
            with self.assertRaisesRegex(ValueError, 'conflict|baseline'): self.activate(ledger)
            self.assertEqual(ledger.counts()['journals'], 0)

    def test_migration_failure_restores_schema_rows_and_original_guards(self):
        self.assertTrue(hasattr(SQLiteLedger, '_migrate_v4'))
        path = self.path.with_name('v3.sqlite3')
        with patch.object(SQLiteLedger, '_migrate_v4', lambda ledger: None):
            with SQLiteLedger(path, **self.options) as ledger:
                receipt = ledger.admit(self.proposal, actor_id='old', idempotency_key='old')
        with closing(sqlite3.connect(path)) as db:
            before = tuple(db.iterdump())
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (3,))
        migrate = SQLiteLedger._migrate_v4
        def fail(ledger):
            migrate(ledger)
            raise RuntimeError('injected migration failure')
        with patch.object(SQLiteLedger, '_migrate_v4', fail), self.assertRaisesRegex(RuntimeError, 'injected'):
            SQLiteLedger(path, **self.options)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(tuple(db.iterdump()), before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (3,))
        with SQLiteLedger(path, **self.options) as ledger:
            self.assertEqual(ledger._connection.execute('PRAGMA user_version').fetchone(), (4,))
            self.assertEqual(ledger.admit(self.proposal, actor_id='old', idempotency_key='old'), receipt)
            self.activate(ledger)
            self.assertEqual(ledger._connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_conflicting_audit_metadata_fails_closed_and_entity_fk_is_enforced(self):
        self.activate()
        db = self.ledger._connection
        # Simulate externally corrupted storage, not an application-supported edit.
        with self.ledger._transaction(write=True):
            db.execute('DROP TRIGGER account_extensions_no_update')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE account_extensions SET entity_id='wrong'")
            db.execute("UPDATE account_extensions SET canonical_metadata='{}'")
        with self.assertRaisesRegex(ValueError, 'conflicts'): self.activate()
        with self.assertRaisesRegex(ValueError, 'conflicts'): self.ledger.current_catalog()
        with self.assertRaisesRegex(ValueError, 'conflicts'): self.ledger.snapshot
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_existing_agent_reads_current_catalog_without_gaining_activation_or_fee_permissions(self):
        from accounting_harness.agent_tools import AgentTools, ToolError
        tools = AgentTools(self.store, actor_id='agent')
        args = dict(entity_id=self.catalog.entity_id)
        before = tools.call('read_accounts', args)
        self.activate()
        after = tools.call('read_accounts', args)
        self.assertEqual(len(before['accounts']), 13)
        self.assertEqual(after['accounts'][-1]['code'], '5300')
        for name in ('ensure_bank_fee_account', 'bank-fee-account', 'post', 'approve'):
            with self.assertRaises(ToolError): tools.call(name, args)
        fee = dict(self.proposal, lines=[dict(account='5300', side='debit', amount='1200.00'),
                                       dict(account='1000', side='credit', amount='1200.00')])
        result = tools.call('validate_proposal', dict(args, proposal=fee, evidence=self.evidence))
        self.assertFalse(result['valid'])
        self.assertIn('unsupported_account', [f['code'] for f in result['findings']])
        self.assertEqual(self.ledger.counts()['journals'], 0)

    def test_new_subledger_reports_bind_current_catalog_and_old_captures_are_unchanged(self):
        from accounting_harness.payables import PayablesService, payables_report
        from accounting_harness.receivables import ReceivablesService, receivables_report
        from accounting_harness.advances import AdvancesService, advances_report
        services = [(PayablesService(self.ledger, self.registry), payables_report),
                    (ReceivablesService(self.ledger, self.registry), receivables_report),
                    (AdvancesService(self.ledger, self.registry), advances_report)]
        captured = [(service.snapshot(), report) for service, report in services]
        before = [report(snapshot, as_of='2026-01-31') for snapshot, report in captured]
        self.activate()
        for (service, report), (snapshot, _), old in zip(services, captured, before):
            new = report(service.snapshot(), as_of='2026-01-31')
            self.assertEqual(report(snapshot, as_of='2026-01-31'), old)
            self.assertNotIn('catalog', old)
            self.assertNotEqual(new['snapshot_digest'], old['snapshot_digest'])
            self.assertEqual(len(new['catalog']['accounts']), 14)
            self.assertEqual(new['subledger_cents'], old['subledger_cents'])

    def test_cli_demonstrates_no_posting(self):
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-bank-fee-account'],
                                capture_output=True, text=True, cwd=test_review.ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('5300', result.stdout)
        self.assertIn('zero additional journals', result.stdout)


class AccountExtensionHTTPTests(unittest.TestCase):
    import test_web
    setUp = test_web.WorkspaceHTTPTests.setUp
    start = test_web.WorkspaceHTTPTests.start
    stop = test_web.WorkspaceHTTPTests.stop
    tearDown = test_web.WorkspaceHTTPTests.tearDown
    request = test_web.WorkspaceHTTPTests.request

    def test_fixed_action_rejects_account_actor_fields_preserves_reports_and_restarts(self):
        from accounting_harness.review import digest
        before = self.request('GET', '/api/state')[1]
        with self.server.workspace.storage() as (_, ledger, _, _, _):
            self.assertEqual(before['trial_balance']['snapshot_digest'], digest([ledger._context, []]))
        for fields in ({'code': '5400'}, {'actor_id': 'agent'}, {'entity_id': 'wrong'}, {'temporary': False}):
            status, _ = self.request('POST', '/api/bank-fee-account', fields)
            self.assertEqual(status, 409)
        status, first = self.request('POST', '/api/bank-fee-account', {})
        self.assertEqual(status, 200, first)
        self.assertEqual(first['actor_id'], 'local-operator')
        self.assertEqual(self.request('POST', '/api/bank-fee-account', {})[1], first)
        after = self.request('GET', '/api/state')[1]
        self.assertEqual(after['bank_fee_account_activation'], first)
        self.assertEqual(after['journal_count'], before['journal_count'])
        self.assertEqual(after['journals'], before['journals'])
        self.assertEqual(after['trial_balance']['total_debits'], before['trial_balance']['total_debits'])
        self.assertNotEqual(after['trial_balance']['snapshot_digest'], before['trial_balance']['snapshot_digest'])
        self.assertEqual(len(before['trial_balance']['catalog']['accounts']), 13)
        self.assertEqual(len(after['trial_balance']['catalog']['accounts']), 14)
        self.stop(); self.start()
        self.assertEqual(self.request('GET', '/api/state')[1]['trial_balance'], after['trial_balance'])
        self.assertEqual(self.request('POST', '/api/bank-fee-account', {})[1], first)


class OperationalApprovalPreservationTests(unittest.TestCase):
    import test_bill_payments
    setUp = test_bill_payments.PaymentTests.setUp
    register = test_bill_payments.PaymentTests.register
    propose = test_bill_payments.PaymentTests.propose
    setup_bill = test_bill_payments.PaymentTests.setup_bill
    post = test_bill_payments.PaymentTests.post
    approve = test_bill_payments.PaymentTests.approve
    payment = test_bill_payments.PaymentTests.payment

    def test_pending_invoice_and_payment_approvals_survive_activation_and_reopen(self):
        import test_receivables
        from accounting_harness.payables import PayablesService, payables_report
        from accounting_harness.receivables import ReceivablesService
        self.setup_bill()
        payment = self.payment()
        payment_approval = self.approve(self.payment_app, payment)
        invoice_service = ReceivablesService(self.ledger, self.registry)
        docs = test_receivables.ReceivablesTests.register(self)
        invoice = test_receivables.ReceivablesTests.propose(self, invoice_service, docs)
        invoice_approval = self.approve(invoice_service.app, invoice)
        frozen = self.service.snapshot()
        frozen_report = payables_report(frozen, as_of='2026-01-31')
        db = self.ledger._connection
        tables = ('approvals', 'approval_requests', 'draft_revisions', 'vendor_bills', 'approved_post_requests')
        before = {t: db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        self.assertTrue(hasattr(self.ledger, 'ensure_bank_fee_account'))
        self.ledger.ensure_bank_fee_account(actor_id='human')
        with SQLiteLedger(self.path, **self.options) as ledger:
            PayablesService(ledger, self.registry)
            ReceivablesService(ledger, self.registry)
            for table, rows in before.items():
                self.assertEqual(ledger._connection.execute(f'SELECT * FROM {table}').fetchall(), rows)
            for policy, approval in [('bill-payment-v1', payment_approval), ('invoice-v1', invoice_approval)]:
                app = ReviewApplication(SQLiteReviewStore(ledger, self.registry, policy_version=policy))
                receipt = app.post(approval.approval_id, actor_id='human', idempotency_key=policy)
                self.assertEqual(app.post(approval.approval_id, actor_id='human', idempotency_key=policy), receipt)
        self.assertEqual(payables_report(frozen, as_of='2026-01-31'), frozen_report)
