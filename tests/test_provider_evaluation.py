import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from accounting_harness import provider_evaluation as evaluation


class EvaluationTests(unittest.TestCase):
    def test_frozen_offline_gate_covers_categories_and_safety_counts(self):
        report = evaluation.evaluate_provider()
        self.assertTrue(report['passed'])
        self.assertEqual(report['mode'], 'offline_synthetic_responses')
        self.assertEqual(report['cases'], 20)
        self.assertEqual(report['exact_proposals'], [8, 8])
        self.assertEqual(report['required_review'], [12, 12])
        self.assertEqual(report['evidence_linked'], [8, 8])
        self.assertEqual(report['unauthorized_postings'], 0)
        self.assertEqual(report['accepted_unbalanced'], 0)
        self.assertEqual(report['categories']['clean'], [8, 8])
        self.assertEqual(len(report['categories']), 7)
        self.assertIsNone(report['live_cost_nanodollars'])

    def test_wrong_label_and_unsafe_response_fail_gate(self):
        corpus = json.loads(evaluation.CORPUS.read_text())
        for mutation in ('label', 'response', 'review'):
            changed = copy.deepcopy(corpus)
            if mutation == 'label':
                changed['cases'][0]['expected']['account'] = '5100'
            elif mutation == 'response':
                changed['cases'][0]['synthetic_response']['amount'] = '86.00'
            else:
                changed['cases'][-1]['synthetic_response'] = dict(decision='propose', account='5100', amount='125.00', effective_date='2026-01-05', reason='supported_expense')
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'cases.json'
                path.write_text(json.dumps(changed))
                report = evaluation.evaluate_provider(path)
            self.assertFalse(report['passed'], mutation)

    def test_empty_and_duplicate_corpus_are_rejected(self):
        corpus = json.loads(evaluation.CORPUS.read_text())
        for cases in ([], corpus['cases'][:19] + [corpus['cases'][0]]):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'cases.json'
                path.write_text(json.dumps(dict(corpus, cases=cases)))
                with self.assertRaises(ValueError):
                    evaluation.evaluate_provider(path)

    def test_live_missing_credentials_fails_without_network_or_fake_score(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                evaluation.evaluate_provider(live=True)

    def test_demo_shows_separate_approval_and_one_posting(self):
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-provider'],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Offline synthetic responses; no live model calls', result.stdout)
        self.assertIn('Before human approval: 0 posted journals', result.stdout)
        self.assertIn('After separate simulated human approval: 1 posted journal', result.stdout)
        self.assertIn('Reopened retry: 1 posted journal', result.stdout)

    def test_live_cli_without_credentials_exits_nonzero(self):
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'eval-provider', '--live'],
                                capture_output=True, text=True, timeout=10, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OPENAI_API_KEY', result.stderr)
