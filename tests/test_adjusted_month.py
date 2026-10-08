"""Independent reference totals and resumable supported-operation fixture assembly."""
import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounting_harness.approval import ReviewApplication
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'data/fixtures/service-business-month.json'
EXPECTED = {'1000': (940000, 0), '1100': (100000, 0), '1200': (110000, 0),
            '1500': (0, 0), '1590': (0, 0), '2000': (0, 20000),
            '2100': (0, 40000), '3000': (0, 1000000), '3100': (20000, 0),
            '4000': (0, 270000), '5000': (120000, 0), '5100': (30000, 0), '5200': (10000, 0)}


class AdjustedMonthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.adjusted_month'),
                             'the reusable adjusted month builder is required')
        from accounting_harness import adjusted_month
        return adjusted_month

    def build(self):
        return self.module().build_adjusted_month(self.workspace)

    def counts(self):
        with self.workspace.storage() as (registry, ledger, store, _, _):
            tables = ('source_enrollments', 'draft_revisions', 'approvals', 'review_postings',
                      'vendor_bills', 'vendor_bill_payments', 'customer_invoices', 'customer_invoice_collections',
                      'customer_advances', 'customer_advance_earnings', 'prepaid_effects')
            return registry.counts(), ledger.counts(), {t: store.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}

    def test_independent_adjusted_balances_and_unchanged_adjustment_cash(self):
        module = self.module()
        cash_observations = []
        original = ReviewApplication.post
        def observe(app, *args, **kwargs):
            before = app.ledger.trial_balance('2026-01-31')
            receipt = original(app, *args, **kwargs)
            if app.store.policy_version in ('prepaid-consumption-v1', 'advance-earning-v1'):
                after = app.ledger.trial_balance('2026-01-31')
                cash_observations.append(tuple(next(r.debit.cents-r.credit.cents for r in b.rows if r.account=='1000') for b in (before, after)))
            return receipt
        with patch.object(ReviewApplication, 'post', observe):
            result = self.build()
        self.assertEqual(cash_observations, [(940000, 940000), (940000, 940000)])
        with self.workspace.storage() as (_, ledger, _, _, _):
            report = ledger.trial_balance('2026-01-31')
            self.assertEqual({r.account:(r.debit.cents,r.credit.cents) for r in report.rows}, EXPECTED)
            self.assertEqual((report.total_debits.cents,report.total_credits.cents),(1330000,1330000))
            self.assertEqual(ledger.counts()['journals'],11)
        state = self.workspace.state()
        for key in ('payables','receivables','advances','prepaid'):
            self.assertEqual(state[key]['unassigned_control_cents'],0,key)
        self.assertEqual(set(result['transactions']), {'T01','T02','T03','T04','T05','T06','T07','T08','T09','A01','A02'})
        self.assertEqual(self.counts()[2]['approvals'],8)

    def test_trace_retains_actual_evidence_approvals_actors_and_dates(self):
        result = self.build()
        with self.workspace.storage() as (registry, ledger, store, _, _):
            for name, trace in result['transactions'].items():
                receipt = ledger.receipt(trace['journal_id'])
                self.assertEqual(set(receipt.entry.source_ids),set(trace['sources']))
                for source_id, content_digest in trace['sources'].items():
                    self.assertEqual(registry.get(source_id).content_digest,content_digest)
                    self.assertIn(source_id,ledger.known_source_ids())
                if name in ('T01','T03','T09'):
                    self.assertEqual(trace['boundary'],'trusted_core_fixture')
                    self.assertIsNone(trace['approval_id'])
                    self.assertIsNone(trace['draft_id'])
                    self.assertEqual(receipt.actor_id,'synthetic-adjusted-month-core')
                else:
                    self.assertEqual(trace['boundary'],'simulated_human_approval')
                    selected, app = self.workspace._draft_services(store,None,trace['draft_id'])
                    recorded = app.trace(trace['draft_id'])
                    self.assertEqual(recorded['approval'].approval_id,trace['approval_id'])
                    self.assertEqual(recorded['approval'].actor_id,'synthetic-adjusted-month-reviewer')
                    self.assertEqual(recorded['receipt'],receipt)
                    self.assertEqual(receipt.actor_id,'synthetic-adjusted-month-poster')
                    self.assertEqual(json.loads(recorded['approval'].binding_json)['evidence'],trace['sources'])
            self.assertNotEqual(result['transactions']['T04']['journal_id'],'T04')
        json.dumps(result)

    def test_date_variant_preserves_original_and_has_explicit_early_cutoffs(self):
        before = REFERENCE.read_bytes()
        self.assertEqual(json.loads(before)['transactions'][2]['date'],'2026-01-03')
        result = self.build()
        self.assertEqual(REFERENCE.read_bytes(),before)
        self.assertEqual(result['reference_sha256'],hashlib.sha256(before).hexdigest())
        self.assertIn('2026-01-01',result['date_variant'])
        with self.workspace.storage() as (registry, ledger, _, _, _):
            purchase = ledger.receipt(result['transactions']['T03']['journal_id']).entry
            self.assertEqual(purchase.effective_date.isoformat(),'2026-01-01')
            source = registry.get(purchase.source_ids[0])
            self.assertEqual(json.loads(source.canonical_content)['document_date'],'2026-01-01')
            for date, cash, rent, count in [('2026-01-01',880000,0,2),('2026-01-02',760000,120000,3)]:
                report = ledger.trial_balance(date)
                balances = {r.account:(r.debit.cents,r.credit.cents) for r in report.rows}
                self.assertEqual(balances['1000'],(cash,0))
                self.assertEqual(balances['1200'],(120000,0))
                self.assertEqual(balances['5000'],(rent,0))
                self.assertEqual(balances['3000'],(0,1000000))
                self.assertEqual(len(report.included_entry_ids),count)
                self.assertEqual((report.total_debits.cents,report.total_credits.cents),(1000000,1000000))

    def test_exact_retry_and_reopen_preserve_all_receipts(self):
        result = self.build()
        counts = self.counts()
        with self.workspace.storage() as (_, ledger, _, _, _):
            receipts = [ledger.receipt(t['journal_id']) for t in result['transactions'].values()]
        self.assertEqual(self.build(),result)
        self.workspace = Workspace(self.directory.name)
        self.assertEqual(self.build(),result)
        self.assertEqual(self.counts(),counts)
        with self.workspace.storage() as (_, ledger, _, _, _):
            self.assertEqual([ledger.receipt(t['journal_id']) for t in result['transactions'].values()],receipts)

    def test_interrupted_enrollment_resumes_registered_source(self):
        self.module()
        original = SQLiteLedger.enroll_source
        def interrupt(ledger, registry, source_id, **kwargs):
            if source_id.endswith(':T02-cash'):
                raise sqlite3.OperationalError('synthetic enrollment interruption')
            return original(ledger,registry,source_id,**kwargs)
        with patch.object(SQLiteLedger,'enroll_source',interrupt), self.assertRaisesRegex(sqlite3.OperationalError,'interruption'):
            self.build()
        with self.workspace.storage() as (registry,ledger,_,_,_):
            pending = [r.document_id for r in registry.list_documents() if r.document_id.endswith(':T02-cash')]
            self.assertEqual(len(pending),1)
            self.assertNotIn(pending[0],ledger.known_source_ids())
        self.workspace = Workspace(self.directory.name)
        result = self.build()
        counts = self.counts()
        self.assertEqual(self.build(),result)
        self.assertEqual(self.counts(),counts)
        self.assertEqual(counts[1]['journals'],11)
        self.assertEqual(counts[2]['approvals'],8)

    def test_interrupted_after_completed_post_resumes_without_duplicate_effects(self):
        self.module()
        original = ReviewApplication.post
        def interrupt(app,*args,**kwargs):
            result = original(app,*args,**kwargs)
            if app.store.policy_version=='invoice-v1':
                raise RuntimeError('synthetic post acknowledgement lost')
            return result
        with patch.object(ReviewApplication,'post',interrupt), self.assertRaisesRegex(RuntimeError,'acknowledgement'):
            self.build()
        self.workspace = Workspace(self.directory.name)
        result = self.build()
        counts = self.counts()
        self.assertEqual(self.build(),result)
        self.assertEqual(self.counts(),counts)
        self.assertEqual(counts[1]['journals'],11)
        self.assertEqual(counts[2]['customer_invoices'],1)
        self.assertEqual(counts[2]['approvals'],8)

    def test_unrelated_populated_workspace_refused_without_mutation(self):
        with self.workspace.storage() as (_,ledger,_,_,_):
            ledger.admit(dict(id='unrelated',entity_id=self.workspace.catalog.entity_id,currency='USD',effective_date='2026-01-01',
                description='Unrelated synthetic contribution',source_ids=[next(iter(self.workspace.sources))],
                lines=[dict(account='1000',side='debit',amount='1.00'),dict(account='3000',side='credit',amount='1.00')]),
                actor_id='other',idempotency_key='other')
            before = ledger.snapshot
        with self.assertRaisesRegex(ValueError,'isolated|unrelated'):
            self.build()
        with self.workspace.storage() as (_,ledger,_,_,_):self.assertEqual(ledger.snapshot,before)

    def test_changed_identity_and_payload_refused_before_mutation(self):
        module = self.module()
        self.build()
        counts = self.counts()
        with patch.object(module,'FIXTURE_ID','adjusted-month-insurance-jan1-v2'), self.assertRaisesRegex(ValueError,'identity|payload|fixture'):
            self.build()
        original = module.fixture_inputs
        def changed():
            inputs = copy.deepcopy(original())
            inputs['documents']['T02-cash']['amount']='1201.00'
            return inputs
        with patch.object(module,'fixture_inputs',changed), self.assertRaisesRegex(ValueError,'identity|payload|fixture'):
            self.build()
        self.assertEqual(self.counts(),counts)

    def test_managed_control_approval_and_reversal_guards_remain_active(self):
        result = self.build()
        with self.workspace.storage() as (_,ledger,store,_,_):
            before = ledger.snapshot
            for account in ('1100','2000','2100'):
                proposal=dict(id='forged-'+account,entity_id=self.workspace.catalog.entity_id,currency='USD',effective_date='2026-01-31',
                    description='Forbidden control shortcut',source_ids=list(result['transactions']['T01']['sources']),
                    lines=[dict(account=account,side='debit',amount='1.00'),dict(account='1000',side='credit',amount='1.00')])
                with self.assertRaises((ValueError,sqlite3.IntegrityError)):
                    ledger.admit(proposal,actor_id='fixture',idempotency_key=proposal['id'])
            for name in ('T03','T04','T06','T08','A01','A02'):
                with self.assertRaises((ValueError,sqlite3.IntegrityError)):
                    ledger.reverse(result['transactions'][name]['journal_id'],reversal_id='reverse-'+name,
                        entity_id=self.workspace.catalog.entity_id,effective_date='2026-01-31',reason='Synthetic reversal attempt',
                        source_ids=list(result['transactions']['T01']['sources']),actor_id='fixture',idempotency_key='reverse-'+name)
            trace = result['transactions']['T04']
            _, app = self.workspace._draft_services(store,None,trace['draft_id'])
            with self.assertRaises(ValueError):
                app.approve(trace['draft_id'],revision=trace['revision'],confirmed_digest=trace['draft_digest'],
                    actor_id='other',idempotency_key='new-approval')
            self.assertEqual(ledger.snapshot,before)

    def test_cli_demonstrates_balances_traces_variant_and_boundary(self):
        result = subprocess.run([sys.executable,'-m','accounting_harness','demo-adjusted-month'],cwd=ROOT,
                                capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        for value in ('11 journals','13300.00','9400.00','2026-01-01','trusted_core_fixture','approval', 'residuals: 0', 'T04'):
            self.assertIn(value,result.stdout)
