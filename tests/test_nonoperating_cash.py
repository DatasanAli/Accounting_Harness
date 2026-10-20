"""Reviewed owner contribution, owner drawing and prepaid purchase cash entries."""
import http.client
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from accounting_harness.workspace import Workspace
from accounting_harness.review import SQLiteReviewStore

REFERENCE = (('capital', 'owner_contribution', 'in', '10000.00', 'owner-1', 'Fictional owner'),
             ('drawing', 'owner_draw', 'out', '200.00', 'owner-1', 'Fictional owner'),
             ('insurance', 'prepaid_insurance', 'out', '1200.00', 'insurer-1', 'Fictional insurer'))


class NonoperatingCashTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def facts(self, event, classification, direction, amount, counterparty_id, counterparty, *, date='2026-01-01', purpose=None):
        common = dict(schema_version=2, synthetic=True, entity_id=self.workspace.catalog.entity_id, currency='USD', document_date=date,
                      amount=amount, event_id=event, counterparty_id=counterparty_id, counterparty=counterparty)
        cash = dict(common, document_id=event + '-cash', kind='cash_movement', direction=direction, purpose=purpose or classification,
                    description='Synthetic recorded cash movement; sends no money')
        basis = dict(common, document_id=event + '-basis', kind='nonoperating_cash_basis', classification=classification,
                     description='Operator classification of the same event')
        return cash, basis

    def register(self, *documents):
        for document in documents:
            self.workspace.action('operation-sources', dict(document=document))

    def prepare(self, event, revision=0, cash=None, basis=None):
        return self.workspace.action('nonoperating-cash-proposals', dict(cash_source_id=cash or event + '-cash',
            basis_source_id=basis or event + '-basis', expected_revision=revision))

    def confirm(self, draft):
        return self.workspace.action('approve-post', dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest']))

    def rows(self, state=None):
        return {r['account']: (r['debit'], r['credit']) for r in (state or self.workspace.state())['trial_balance']['rows']}

    def reference(self):
        drafts = []
        for fact in REFERENCE:
            self.register(*self.facts(*fact)); drafts.append(self.prepare(fact[0]))
        return drafts

    def test_reference_entries_post_only_after_separate_approvals(self):
        drafts = self.reference()
        self.assertEqual(self.workspace.state()['journal_count'], 0, 'preparing all three creates no journals')
        self.assertEqual({d['policy_version'] for d in drafts}, {'nonoperating-cash-v1'})
        receipts = [self.confirm(d) for d in drafts]
        self.assertEqual(len({r['journal_id'] for r in receipts}), 3)
        state = self.workspace.state(); rows = self.rows(state)
        self.assertEqual((rows['1000'], rows['3000'], rows['3100'], rows['1200']),
                         (('8600.00', '0.00'), ('0.00', '10000.00'), ('200.00', '0.00'), ('1200.00', '0.00')))
        self.assertEqual(state['trial_balance']['total_debits'], '10000.00')
        purchase = next(j for j in state['journals'] if any(l['account'] == '1200' for l in j['lines']))
        self.assertEqual(sorted((l['account'], l['side'], l['amount']) for l in purchase['lines']), [('1000', 'credit', '1200.00'), ('1200', 'debit', '1200.00')])
        draft = next(d for d in state['drafts'] if d['draft_id'] == drafts[2]['draft_id'])
        self.assertEqual((draft['operation_intent']['classification'], draft['operation_intent']['amount_cents']), ('prepaid_insurance', 120000))
        reopened = Workspace(self.directory.name)
        self.assertEqual(reopened.action('nonoperating-cash-proposals', dict(cash_source_id='capital-cash', basis_source_id='capital-basis', expected_revision=0)), drafts[0])
        self.assertEqual(reopened.action('approve-post', dict(draft_id=drafts[0]['draft_id'], revision=1, confirmed_digest=drafts[0]['content_digest'])), receipts[0])
        self.assertEqual(reopened.state()['journal_count'], 3)

    def test_reviewed_purchase_feeds_existing_prepaid_consumption_and_reports(self):
        drafts = self.reference(); receipts = [self.confirm(d) for d in drafts]
        coverage = dict(self.facts(*REFERENCE[2])[1], kind='prepaid_coverage', document_id='annual-coverage', original_journal_id=receipts[2]['journal_id'],
                        original_source_id='insurance-cash', coverage_start='2026-01-01', coverage_end='2026-12-31', allocation_policy='equal-months-cents-v1')
        for key in ('event_id', 'counterparty_id', 'classification'): coverage.pop(key)
        self.register(coverage)
        consumption = self.workspace.action('prepaid-proposals', dict(coverage_source_id='annual-coverage', allocation_month='2026-01', expected_revision=0))
        self.confirm(consumption)
        state = self.workspace.state(); rows = self.rows(state)
        self.assertEqual((rows['5200'], rows['1200'], rows['1000']), (('100.00', '0.00'), ('1100.00', '0.00'), ('8600.00', '0.00')))
        self.assertEqual((state['prepaid']['remaining_amount'], state['prepaid']['unassigned_control_amount']), ('1100.00', '0.00'))
        with self.workspace.storage() as (_, ledger, _, _, _), self.assertRaisesRegex(ValueError, 'prepaid dependency'):
            ledger.reverse(receipts[2]['journal_id'], reversal_id='undo-purchase', entity_id=self.workspace.catalog.entity_id, effective_date='2026-01-31',
                           reason='Refused while consumption depends on it', source_ids=['insurance-cash'], actor_id='synthetic-human', idempotency_key='undo-purchase')
        statements = self.workspace.financial_statements('2026-01-31')
        income, equity = statements['income_statement'], statements['owners_equity']
        # Owner capital and drawings are equity movements, never revenue or expense.
        self.assertEqual((income['revenue_amount'], income['expenses_amount'], income['net_income_amount']), ('0.00', '100.00', '-100.00'))
        self.assertEqual([equity[k + '_amount'] for k in ('contributions', 'drawings', 'net_income', 'ending_equity')], ['10000.00', '200.00', '-100.00', '9700.00'])
        cash_flow = self.workspace.cash_flow('2026-01-31')
        # Owner contribution less drawing is financing; the prepaid purchase is an operating payment.
        self.assertEqual([cash_flow[k + '_amount'] for k in ('operating', 'investing', 'financing', 'ending_cash', 'residual')],
                         ['-1200.00', '0.00', '9800.00', '8600.00', '0.00'])
        self.assertTrue(cash_flow['classification_complete'])

    def test_mismatched_unsupported_and_forged_inputs_are_refused(self):
        cases = {'direction': dict(direction='out'), 'purpose': dict(purpose='owner_draw'), 'amount': dict(amount='9999.00'),
                 'date': dict(document_date='2026-01-02'), 'event': dict(event_id='other'), 'counterparty': dict(counterparty_id='someone-else')}
        for name, change in cases.items():
            with self.subTest(name=name):
                fact = ('bad-' + name, 'owner_contribution', change.get('direction', 'in'), '10000.00', 'owner-1', 'Fictional owner')
                cash, basis = self.facts(*fact, purpose=change.get('purpose'))
                for key in ('amount', 'document_date', 'event_id', 'counterparty_id'):
                    if key in change: basis[key] = change[key]
                self.register(cash, basis)
                with self.assertRaises(ValueError): self.prepare(fact[0])
        cash, basis = self.facts(*REFERENCE[0])
        for change in (dict(classification='retained_earnings'), dict(classification=7)):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                self.register(dict(basis, document_id='bad-classification', **change))
        self.register(cash, basis)
        with self.assertRaises(ValueError):
            self.prepare('capital', basis='capital-cash')
        expense_cash = dict(cash, document_id='expense-cash', purpose='incurred_expense', direction='out', event_id='expense')
        self.register(expense_cash)
        with self.assertRaises(ValueError):
            self.prepare('capital', cash='expense-cash')
        draft = self.prepare('capital')
        with self.workspace.storage() as (registry, ledger, _, _, _):
            store = SQLiteReviewStore(ledger, registry, policy_version='nonoperating-cash-v1')
            original = store.get(draft['draft_id'])
            proposal, intent = json.loads(original.proposal_json), json.loads(original.operation_intent_json)
            forgeries = [(dict(proposal, lines=[dict(proposal['lines'][0], amount='9999.00'), dict(proposal['lines'][1], amount='9999.00')]), intent),
                         (dict(proposal, lines=[dict(proposal['lines'][0]), dict(proposal['lines'][1], account='2000')]), intent),
                         (proposal, dict(intent, amount_cents=True)), (proposal, dict(intent, classification='owner_draw')), (proposal, None)]
            for index, (forged, forged_intent) in enumerate(forgeries):
                with self.subTest(forgery=index):
                    try:
                        revision = store.save(draft['draft_id'], forged, evidence=json.loads(original.evidence_json), operation_intent=forged_intent,
                            expected_revision=store.get(draft['draft_id']).revision, actor_id='forger', idempotency_key=f'forged-{index}', reason='Forged')
                    except sqlite3.DatabaseError:
                        continue  # The intent seal refuses a missing intent at the storage layer.
                    self.assertFalse(revision.reviewable)
        self.assertEqual(self.workspace.state()['journal_count'], 0)

    def test_duplicate_events_and_cross_policy_cash_reuse_are_refused(self):
        self.register(*self.facts(*REFERENCE[0])); posted = self.confirm(self.prepare('capital'))
        renamed_cash, renamed_basis = self.facts(*REFERENCE[0])
        renamed_cash['document_id'], renamed_basis['document_id'] = 'capital-cash-2', 'capital-basis-2'
        self.register(renamed_cash, renamed_basis)
        for revision in (0, 1):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.prepare('capital', revision=revision, cash='capital-cash-2', basis='capital-basis-2')
        rent = dict(schema_version=2, synthetic=True, entity_id=self.workspace.catalog.entity_id, currency='USD', document_date='2026-01-05',
                    amount='125.00', event_id='shared-event', counterparty_id='landlord', counterparty='Fictional landlord', description='Synthetic rent')
        self.register(dict(rent, document_id='rent-cash', kind='cash_movement', direction='out', purpose='incurred_expense'),
                      dict(rent, document_id='rent-fact', kind='incurred_expense', incurred_date='2026-01-05', expense_account='5000'))
        self.workspace.action('cash-proposals', dict(operation='cash_expense', cash_source_id='rent-cash', recognition_source_id='rent-fact'))
        cash, basis = self.facts('shared-event', 'owner_draw', 'out', '125.00', 'landlord', 'Fictional landlord', date='2026-01-05')
        self.register(cash, basis)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.prepare('shared-event')
        state = self.workspace.state()
        self.assertEqual((state['journal_count'], posted['journal_id'] in [j['id'] for j in state['journals']]), (1, True))

    def test_corrections_cannot_attach_used_or_unenrolled_evidence(self):
        old_cash, old_basis = self.facts(*REFERENCE[0])
        old_cash['document_id'], old_basis['document_id'] = 'capital-cash-old', 'capital-basis-old'
        self.register(old_cash, old_basis)
        with self.workspace.storage() as (_, ledger, _, _, _):  # A trusted fixture posting holds the old cash document without a claim.
            ledger.admit(dict(id='fixture-capital', entity_id=self.workspace.catalog.entity_id, currency='USD', effective_date='2026-01-01',
                description='Trusted fixture capital', source_ids=['capital-cash-old'], lines=[dict(account='1000', side='debit', amount='10000.00'),
                dict(account='3000', side='credit', amount='10000.00')]), actor_id='fixture-operator', idempotency_key='fixture-capital')
        with self.assertRaisesRegex(ValueError, 'duplicate evidence'):
            self.prepare('capital', cash='capital-cash-old', basis='capital-basis-old')
        self.register(*self.facts(*REFERENCE[0])); draft = self.prepare('capital')
        with self.assertRaisesRegex(ValueError, 'duplicate evidence'):
            self.prepare('capital', revision=draft['revision'], cash='capital-cash-old')
        self.assertEqual(self.prepare('capital', revision=draft['revision'])['revision'], 2, 'a correction may keep its own evidence')
        cash, basis = self.facts(*REFERENCE[1])
        with self.workspace.storage() as (registry, _, _, _, _):
            for document in (cash, basis): registry.register(document, actor_id='fixture-operator')  # Registered, never enrolled.
        with self.assertRaisesRegex(ValueError, 'enrolled'):
            self.prepare('drawing')

    def test_rejected_revision_concurrent_retry_and_posting_rollback(self):
        self.register(*self.facts(*REFERENCE[1]))
        first = self.prepare('drawing')
        rejected = self.workspace.action('reject', dict(draft_id=first['draft_id'], revision=1, reason='Recheck the owner withdrawal'))
        self.assertEqual(rejected['state'], 'rejected')
        self.assertEqual(self.prepare('drawing'), first, 'an exact retry returns its original historical result')
        renamed = self.facts(*REFERENCE[1]); renamed[0]['document_id'], renamed[1]['document_id'] = 'drawing-cash-2', 'drawing-basis-2'
        self.register(*renamed)
        with self.assertRaises(ValueError): self.prepare('drawing', cash='drawing-cash-2', basis='drawing-basis-2')  # Stale: revise instead.
        with self.assertRaises(ValueError): self.confirm(first)
        revised = self.prepare('drawing', revision=2)
        self.assertEqual((revised['draft_id'], revised['revision']), (first['draft_id'], 3))
        results, errors = [], []
        def post():
            try: results.append(Workspace(self.directory.name).action('approve-post', dict(draft_id=revised['draft_id'], revision=3, confirmed_digest=revised['content_digest'])))
            except Exception as error: errors.append(error)
        with self.workspace.storage() as (_, ledger, _, _, _):
            ledger._connection.execute("CREATE TRIGGER injected_post_fault BEFORE INSERT ON review_postings BEGIN SELECT RAISE(ABORT,'injected fault'); END")
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'injected fault'): self.confirm(revised)
        self.assertEqual(self.workspace.state()['journal_count'], 0, 'a failed post rolls back its journal')
        with self.workspace.storage() as (_, ledger, _, _, _):
            ledger._connection.execute('DROP TRIGGER injected_post_fault')
        threads = [threading.Thread(target=post) for _ in range(3)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(30)
        self.assertEqual(self.workspace.state()['journal_count'], 1)
        self.assertTrue(results); self.assertEqual(len({r['journal_id'] for r in results}), 1)
        self.assertTrue(all(isinstance(e, (ValueError, sqlite3.DatabaseError)) for e in errors), errors)

    def test_period_lock_refuses_late_reviewed_entry(self):
        self.register(*self.facts(*REFERENCE[0]), *self.facts(*REFERENCE[1]))
        self.confirm(self.prepare('capital')); pending = self.prepare('drawing')
        preview = self.workspace.action('close-preview', dict(period_start='2026-01-01', period_end='2026-01-31', selections=[]))
        self.workspace.action('close-confirm', dict(period_start='2026-01-01', period_end='2026-01-31', selections=[], confirmed=True,
                                                    confirmed_digest=preview['digest'], idempotency_key='close'))
        before = self.workspace.state()['journal_count']
        with self.assertRaisesRegex(ValueError, 'closed'): self.confirm(pending)
        self.assertEqual(self.workspace.state()['journal_count'], before)

    def test_review_schema_migration_is_atomic_and_preserves_records(self):
        self.register(*self.facts(*REFERENCE[0]))
        draft = self.prepare('capital')
        path = Path(self.directory.name) / 'ledger.sqlite3'
        with sqlite3.connect(path) as db:
            seal = db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0]
            db.execute('DROP TRIGGER review_schema_no_update'); db.execute('UPDATE review_schema SET version=11')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
            db.execute('DROP TRIGGER intent_required_at_seal'); db.execute(seal.replace(",'nonoperating-cash-v1'", ''))
            before = list(db.execute('SELECT * FROM draft_revisions ORDER BY draft_id,revision'))
        from accounting_harness.persistence import SQLiteLedger
        from accounting_harness.sources import SQLiteSourceRegistry
        # Open the ledger alone (no review store) so the migration happens only under the injected denial.
        with SQLiteSourceRegistry(Path(self.directory.name) / 'sources.sqlite3', self.workspace.catalog.entity_id) as registry, \
                SQLiteLedger(path, self.workspace.catalog, '2026-01-01', '2026-01-31', known_source_ids=set(self.workspace.sources)) as ledger:
            db = ledger._connection
            db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_UPDATE and name == 'review_schema' else sqlite3.SQLITE_OK)
            with self.assertRaises(sqlite3.DatabaseError): SQLiteReviewStore(ledger, registry)
            db.set_authorizer(None)
            self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(), [(11,)])
            self.assertNotIn('nonoperating', db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()[0])
        reopened = Workspace(self.directory.name)
        db = sqlite3.connect(path); self.addCleanup(db.close)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(), [(12,)])
        self.assertEqual(list(db.execute('SELECT * FROM draft_revisions ORDER BY draft_id,revision')), before)
        self.assertEqual(reopened.action('approve-post', dict(draft_id=draft['draft_id'], revision=1, confirmed_digest=draft['content_digest']))['journal_id'][:8], 'journal:')

    def test_http_forms_and_demo(self):
        from auth_fixture import make_server
        server = make_server(self.directory.name, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        def post(path, data):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            connection.request('POST', path, json.dumps(data), dict(server.test_headers, **{'Content-Type': 'application/json',
                'Origin': f'http://127.0.0.1:{server.server_port}', 'X-CSRF-Token': server.csrf_token}))
            response = connection.getresponse(); result = (response.status, json.loads(response.read())); connection.close()
            return result
        for document in self.facts(*REFERENCE[0]):
            self.assertEqual(post('/api/operation-sources', dict(document=document))[0], 200)
        status, draft = post('/api/nonoperating-cash-proposals', dict(cash_source_id='capital-cash', basis_source_id='capital-basis', expected_revision=0))
        self.assertEqual((status, draft['policy_version']), (200, 'nonoperating-cash-v1'))
        self.assertEqual(post('/api/nonoperating-cash-proposals', dict(cash_source_id='capital-cash', basis_source_id='capital-basis', expected_revision=0, debit_account='2000'))[0], 409)
        static = Path(__file__).resolve().parents[1] / 'accounting_harness' / 'static'
        html = (static / 'index.html').read_text()
        for text in ('id="nonoperating-evidence-form"', 'data-action="nonoperating-cash-proposals"', 'value="prepaid_insurance"'):
            self.assertIn(text, html)
        demo = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-owner-prepaid-cash'], capture_output=True, text=True)
        self.assertEqual(demo.returncode, 0, demo.stderr)
        for text in ('Cash 8600.00', 'Prepaid 1100.00', 'no journals'):
            self.assertIn(text, demo.stdout)


if __name__ == '__main__':
    unittest.main()
