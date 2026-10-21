"""Release acceptance must cross the authenticated accounting boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class AcceptanceTests(unittest.TestCase):
    def test_complete_authenticated_month_and_verified_recovery(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.acceptance'),
                             'authenticated release rehearsal required')
        from accounting_harness.acceptance import create_acceptance_drill
        with tempfile.TemporaryDirectory() as directory, patch(
                'accounting_harness.adjusted_month.build_adjusted_month',
                side_effect=AssertionError('Authenticated month must not use trusted fixture seeding')):
            result = create_acceptance_drill(Path(directory) / 'acceptance')
            report = result['report']
            self.assertEqual(report['month']['journal_count'], 11)
            self.assertEqual(len(report['month']['transactions']), 11)
            for trace in report['month']['transactions'].values():
                self.assertEqual(trace['boundary'], 'authenticated_separate_review')
                self.assertNotEqual(trace['preparer'], trace['reviewer'])
                self.assertEqual(trace['journal_delta_before_review'], 0)
                self.assertTrue(trace['sources'])
                self.assertTrue(trace['approval_id'])
            self.assertEqual(report['close']['trial_balance']['total_debits'], '11500.00')
            self.assertTrue(report['close']['captured_bytes_unchanged'])
            self.assertEqual(report['security']['unauthorized_successes'], 0)
            self.assertEqual(report['security'].get('agent_journals_before_review'), 0)
            self.assertEqual(report['security'].get('agent_pending_drafts_before_review'), 1)
            self.assertNotIn('agent_pending_before_review', report['security'])
            self.assertGreaterEqual(len(report['security']['denials']), 10)
            self.assertTrue(all(report['recovery']['comparisons'].values()))
            self.assertTrue(report['recovery']['transports_disabled'])
            self.assertTrue(report['recovery']['resume_no_duplicate'])
            self.assertEqual(report['close']['refused_post_draft_status'], 'approved')
            self.assertTrue(report['security']['missing_evidence_handoff'])
            self.assertTrue(Path(result['access_db']).exists())
            self.assertNotIn(result['credentials']['owner']['password'], json.dumps(report))
            with self.assertRaises(ValueError):
                create_acceptance_drill(Path(directory) / 'acceptance')

    def test_secondary_published_results_are_separate(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.acceptance'))
        from accounting_harness.acceptance import secondary_scenarios
        with tempfile.TemporaryDirectory() as directory:
            result = secondary_scenarios(Path(directory))
        self.assertEqual(result['bank']['book_balance'], '990.00')
        self.assertEqual(result['bank']['zero_difference_exceptions'], 2)
        self.assertEqual(result['corpus']['cases'], 31)
        self.assertEqual(result['corpus']['scope'], 'offline_mock_trusted_fixture')
        self.assertEqual(result['lost_export']['first_status'], 'uncertain')
        self.assertEqual(result['lost_export']['final_status'], 'confirmed')
        self.assertEqual(result['lost_export']['remote_receipts'], 1)
        self.assertEqual(set(result['regressions']), {'expense_accrual', 'revenue_accrual',
            'project_cost', 'budget', 'variance', 'indicators', 'sandbox_read', 'sandbox_export'})
