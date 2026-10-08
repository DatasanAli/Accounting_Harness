"""AP final seals and schema 2 migration retain approval and remaining principal."""
import json
import sqlite3
import unittest
from pathlib import Path

import test_bill_payments
from accounting_harness.payables import PayablesService, prepare_payable_post
from accounting_harness.review import digest


class PayableSealTests(unittest.TestCase):
    setUp = test_bill_payments.PaymentTests.setUp
    register = test_bill_payments.PaymentTests.register
    propose = test_bill_payments.PaymentTests.propose
    setup_bill = test_bill_payments.PaymentTests.setup_bill
    approve = test_bill_payments.PaymentTests.approve
    post = test_bill_payments.PaymentTests.post
    payment = test_bill_payments.PaymentTests.payment
    report = test_bill_payments.PaymentTests.report

    def rows(self):
        db = self.ledger._connection
        return {name: db.execute(f'SELECT * FROM "{name}"').fetchall()
                for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def supersede(self, draft, state):
        # Same enabled-guard ordering as the delivered invoice regression. Review service
        # calls own their transaction; use their immutable row envelope inside this unit.
        db = self.ledger._connection
        operation = 'reject' if state == 'rejected' else 'save'
        revision = list(db.execute('SELECT * FROM draft_revisions WHERE draft_id=? AND revision=?',
                                  (draft.draft_id, draft.revision)).fetchone())
        revision[1], revision[6], revision[7], revision[8] = 2, state, 'A later human decision', 'human'
        db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)', revision)
        db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                   (draft.draft_id, 2, draft.operation_intent_json))
        db.execute('INSERT INTO review_events VALUES (?,?,?)', (draft.draft_id, 2, operation))
        db.execute('INSERT INTO review_requests VALUES (?,?,?,?,?)',
            (operation, 'later-decision', digest([operation, draft.draft_id, 1, 'human',
                'A later human decision', None if operation == 'reject' else json.loads(draft.proposal_json),
                None if operation == 'reject' else json.loads(draft.evidence_json), draft.policy_version] +
                ([] if operation == 'reject' else [{'operation_intent_v1': json.loads(draft.operation_intent_json)}])),
             draft.draft_id, 2))

    def assert_stale_seal_rolls_back(self, kind, state):
        if kind == 'payment':
            self.setup_bill()
            draft = self.payment()
            store, app = self.payment_store, self.payment_app
        else:
            self.service = PayablesService(self.ledger, self.registry)
            draft = self.propose(self.service, self.register())
            store, app = self.service.store, self.service.app
        approval = self.approve(app, draft)
        entry = self.ledger._validate_entry(json.loads(draft.proposal_json))
        before = self.rows()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'approved payable effect'):
            with self.ledger._transaction(write=True):
                prepare_payable_post(store, approval, draft, entry)
                self.supersede(draft, state)
                self.ledger._store_entry(entry, 'human')
        self.assertEqual(self.rows(), before)
        receipt = app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual(receipt.entry.id, entry.id)

    def test_bill_rejected_revision_between_effect_and_seal_rolls_back(self):
        self.assert_stale_seal_rolls_back('bill', 'rejected')

    def test_bill_pending_revision_between_effect_and_seal_rolls_back(self):
        self.assert_stale_seal_rolls_back('bill', 'pending')

    def test_payment_rejected_revision_between_effect_and_seal_rolls_back(self):
        self.assert_stale_seal_rolls_back('payment', 'rejected')

    def test_payment_pending_revision_between_effect_and_seal_rolls_back(self):
        self.assert_stale_seal_rolls_back('payment', 'pending')

    def insert_payment_effect(self, draft, approval):
        intent = json.loads(draft.operation_intent_json)
        self.ledger._connection.execute('INSERT INTO vendor_bill_payments VALUES (?,?,?,?,?,?,?)',
            (intent['payment_event_id'], intent['bill_id'], intent['evidence_roles']['cash'],
             intent['allocated_cents'], intent['effective_date'], approval.approval_id,
             json.loads(draft.proposal_json)['id']))

    def test_competing_approved_effects_cannot_seal_negative_outstanding(self):
        self.setup_bill()
        drafts = [self.payment('competing-'+str(i), '200.00') for i in range(2)]
        approvals = [self.approve(self.payment_app, draft) for draft in drafts]
        before = self.rows()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'approved payable effect'):
            with self.ledger._transaction(write=True):
                # Both approved effects fit individually. Neither is sealed yet, so the
                # final guard must count pending effects too, not only posted payments.
                for draft, approval in zip(drafts, approvals):
                    self.insert_payment_effect(draft, approval)
                for draft in drafts:
                    self.ledger._store_entry(self.ledger._validate_entry(json.loads(draft.proposal_json)), 'human')
        self.assertEqual(self.rows(), before)
        self.payment_app.post(approvals[0].approval_id, actor_id='human', idempotency_key='winner')
        with self.assertRaises(ValueError):
            self.payment_app.post(approvals[1].approval_id, actor_id='human', idempotency_key='loser')
        self.assertEqual(self.report()['subledger_cents'], 10000)

    def test_later_effect_cannot_overallocate_after_first_payment_seals(self):
        self.setup_bill()
        drafts = [self.payment('later-'+str(i), '200.00') for i in range(2)]
        approvals = [self.approve(self.payment_app, draft) for draft in drafts]
        before = self.rows()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'approved payable effect'):
            with self.ledger._transaction(write=True):
                for draft, approval in zip(drafts, approvals):
                    self.insert_payment_effect(draft, approval)
                    self.ledger._store_entry(self.ledger._validate_entry(json.loads(draft.proposal_json)), 'human')
        self.assertEqual(self.rows(), before)
        # Omitting the later seal cannot commit its deferred orphan either.
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            with self.ledger._transaction(write=True):
                for draft, approval in zip(drafts, approvals):
                    self.insert_payment_effect(draft, approval)
                    if draft == drafts[0]:
                        self.ledger._store_entry(self.ledger._validate_entry(json.loads(draft.proposal_json)), 'human')
        self.assertEqual(self.rows(), before)

    def test_approved_effects_can_seal_exact_remaining_principal(self):
        self.setup_bill()
        drafts = [self.payment('valid-'+str(i), amount) for i, amount in enumerate(('200.00', '100.00'))]
        approvals = [self.approve(self.payment_app, draft) for draft in drafts]
        with self.ledger._transaction(write=True):
            for draft, approval in zip(drafts, approvals):
                self.insert_payment_effect(draft, approval)
            for draft in drafts:
                self.ledger._store_entry(self.ledger._validate_entry(json.loads(draft.proposal_json)), 'human')
        self.assertEqual(self.report()['subledger_cents'], 0)
        self.assertEqual(self.report()['ap_control_cents'], 0)
        self.assertEqual(self.ledger._connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def install_legacy_guards(self):
        db = self.ledger._connection
        fixture = (Path(__file__).parent/'fixtures/step14b-payables-guards.sql').read_text()
        with self.ledger._transaction(write=True):
            for name in ('bill_approved_operation', 'payment_approved_operation', 'payables_post_guard'):
                db.execute(f'DROP TRIGGER {name}')
            statement = ''
            for line in fixture.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            self.assertFalse(statement.strip())
            db.execute('DROP TRIGGER payables_schema_no_update')
            db.execute('UPDATE payables_schema SET version=2')
            db.execute("""CREATE TRIGGER payables_schema_no_update BEFORE UPDATE ON payables_schema
                BEGIN SELECT RAISE(ABORT,'payables schema is immutable'); END""")

    def legacy_workspace(self):
        from accounting_harness.approval import ReviewApplication
        from accounting_harness.review import SQLiteReviewStore
        self.service = PayablesService(self.ledger, self.registry)
        self.install_legacy_guards()
        # All postings/approvals below use the published schema 2 guards.
        self.bill = self.propose(self.service, self.register())
        bill_receipt = self.post(self.service.app, self.bill)
        self.bill_id = json.loads(self.bill.operation_intent_json)['bill_id']
        self.payment_store = SQLiteReviewStore(self.ledger, self.registry, policy_version='bill-payment-v1')
        self.payment_app = ReviewApplication(self.payment_store)
        payment = self.payment()
        payment_receipt = self.post(self.payment_app, payment)
        pending_bill = self.propose(self.service, self.register('pending-bill', number='B-002'), key='pending-bill')
        bill_approval = self.approve(self.service.app, pending_bill)
        pending_payment = self.payment('pending-payment', '50.00')
        payment_approval = self.approve(self.payment_app, pending_payment)
        return bill_receipt, payment, payment_receipt, pending_bill, bill_approval, pending_payment, payment_approval

    def schema(self):
        return self.ledger._connection.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()

    def test_schema2_migration_rolls_back_every_replacement_and_version_write(self):
        self.legacy_workspace()
        db = self.ledger._connection
        before, schema = self.rows(), self.schema()
        for action, name in ((sqlite3.SQLITE_CREATE_TRIGGER, 'bill_approved_operation'),
                             (sqlite3.SQLITE_CREATE_TRIGGER, 'payment_approved_operation'),
                             (sqlite3.SQLITE_CREATE_TRIGGER, 'payables_post_guard'),
                             (sqlite3.SQLITE_UPDATE, 'payables_schema'),
                             (sqlite3.SQLITE_CREATE_TRIGGER, 'payables_schema_no_update')):
            with self.subTest(action=action, name=name):
                db.set_authorizer(lambda current_action, current_name, *_:
                    sqlite3.SQLITE_DENY if (current_action, current_name) == (action, name) else sqlite3.SQLITE_OK)
                try:
                    with self.assertRaises(sqlite3.DatabaseError):
                        PayablesService(self.ledger, self.registry)
                finally:
                    db.set_authorizer(None)
                self.assertEqual(self.rows(), before)
                self.assertEqual(self.schema(), schema)
                self.assertFalse(db.in_transaction)
        PayablesService(self.ledger, self.registry)
        self.assertEqual(db.execute('SELECT version FROM payables_schema').fetchall(), [(3,)])
        for table, rows in before.items():
            if table != 'payables_schema':
                self.assertEqual(self.rows()[table], rows, table)

    def test_migration_preserves_history_retry_bytes_pending_approvals_and_captured_reports(self):
        from accounting_harness.payables import payables_report
        from accounting_harness.persistence import SQLiteLedger, _canonical
        bill_receipt, payment, payment_receipt, pending_bill, bill_approval, pending_payment, payment_approval = self.legacy_workspace()
        before = self.rows()
        before.pop('payables_schema')
        row_bytes = _canonical(before).encode()
        captured = self.service.snapshot()
        reports = {date: _canonical(payables_report(captured, as_of=date)).encode()
                   for date in ('2026-01-09', '2026-01-10', '2026-01-15', '2026-01-31')}
        # A different connection migrates while existing service objects stay open.
        with SQLiteLedger(self.path, **self.options) as reopened:
            migrated = PayablesService(reopened, self.registry)
            self.assertEqual(reopened._connection.execute('SELECT version FROM payables_schema').fetchall(), [(3,)])
            after = self.rows()
            after.pop('payables_schema')
            self.assertEqual(_canonical(after).encode(), row_bytes)
            for date, report in reports.items():
                self.assertEqual(_canonical(payables_report(migrated.snapshot(), as_of=date)).encode(), report)
        self.assertEqual(self.post(self.service.app, self.bill), bill_receipt)
        self.assertEqual(self.post(self.payment_app, payment), payment_receipt)
        after_retries = self.rows()
        after_retries.pop('payables_schema')
        self.assertEqual(_canonical(after_retries).encode(), row_bytes)
        self.service.app.post(bill_approval.approval_id, actor_id='human', idempotency_key='old-pending-bill')
        self.payment_app.post(payment_approval.approval_id, actor_id='human', idempotency_key='old-pending-payment')
        self.assertEqual(self.report()['subledger_cents'], 45000)
        self.assertEqual(self.report()['ap_control_cents'], 45000)
        for date, report in reports.items():
            self.assertEqual(_canonical(payables_report(captured, as_of=date)).encode(), report)
        # Reinitialization is idempotent and does not rewrite seals or stored bytes.
        final_rows, final_schema = self.rows(), self.schema()
        PayablesService(self.ledger, self.registry)
        self.assertEqual(self.rows(), final_rows)
        self.assertEqual(self.schema(), final_schema)

    def test_migrated_seals_reject_stale_approvals_through_already_open_connection(self):
        from accounting_harness.persistence import SQLiteLedger
        _, _, _, bill, bill_approval, payment, payment_approval = self.legacy_workspace()
        competing = self.payment('legacy-competing-payment', '175.00')
        competing_approval = self.approve(self.payment_app, competing)
        with SQLiteLedger(self.path, **self.options) as reopened:
            PayablesService(reopened, self.registry)
        before = self.rows()
        for draft, approval, store in ((bill, bill_approval, self.service.store),
                                       (payment, payment_approval, self.payment_store)):
            for state in ('pending', 'rejected'):
                with self.subTest(policy=draft.policy_version, state=state):
                    entry = self.ledger._validate_entry(json.loads(draft.proposal_json))
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'approved payable effect'):
                        with self.ledger._transaction(write=True):
                            prepare_payable_post(store, approval, draft, entry)
                            self.supersede(draft, state)
                            self.ledger._store_entry(entry, 'human')
                    self.assertEqual(self.rows(), before)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'approved payable effect'):
            with self.ledger._transaction(write=True):
                self.insert_payment_effect(payment, payment_approval)
                self.insert_payment_effect(competing, competing_approval)
                self.ledger._store_entry(self.ledger._validate_entry(json.loads(payment.proposal_json)), 'human')
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.ledger._connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_failed_ap_migration_also_rolls_back_legacy_review_initialization(self):
        self.legacy_workspace()
        db = self.ledger._connection
        with self.ledger._transaction(write=True):
            self.store._replace_intent_seal("'bill-v1','bill-payment-v1'")
            db.execute('DROP TRIGGER review_schema_no_update')
            db.execute('UPDATE review_schema SET version=3')
            db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
                BEGIN SELECT RAISE(ABORT,'review schema is immutable'); END""")
        before, schema = self.rows(), self.schema()
        db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_UPDATE and name == 'payables_schema' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                PayablesService(self.ledger, self.registry)
        finally:
            db.set_authorizer(None)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(), [(3,)])
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.schema(), schema)
        PayablesService(self.ledger, self.registry)
        self.assertEqual(db.execute('SELECT version FROM payables_schema').fetchall(), [(3,)])
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(), [(10,)])
