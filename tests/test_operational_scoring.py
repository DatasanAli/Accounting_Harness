"""Authenticated synthetic scoring, durable resume and honest failure denominators."""
import importlib.util
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


def missing_usage_worker(pipe, body, sample_id):
    from accounting_harness.operational_scoring import reference_response
    response = reference_response(body, sample_id)
    del response['usage']
    pipe.send(('ok', response)); pipe.close()


def wrong_semantics_worker(pipe, body, sample_id):
    from accounting_harness.operational_scoring import reference_response
    response = reference_response(body, sample_id)
    response['output'][0].update(name='handoff_review', arguments=json.dumps(dict(
        reason='other', explanation='SECRET raw explanation must not enter score report', citations=[])))
    pipe.send(('ok', response)); pipe.close()


def forged_approval_worker(pipe, body, sample_id):
    from accounting_harness.operational_scoring import reference_response
    response = reference_response(body, sample_id)
    response['output'][0].update(name='approve-post', arguments='{}')
    pipe.send(('ok', response)); pipe.close()


def slow_worker(pipe, body, sample_id):
    time.sleep(2)
    from accounting_harness.operational_scoring import reference_response
    pipe.send(('ok', reference_response(body, sample_id))); pipe.close()


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.operational_scoring'),
                             'authenticated scoring is not implemented')
        from accounting_harness import operational_scoring as scoring
        self.s = scoring
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'experiment'

    def test_all_semantics_repeats_and_completed_reopen_without_dispatch(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            report = evaluation.run()
            self.assertTrue(report['offline_contract_passed'], report)
            self.assertEqual(report['exact_proposals'], [14, 14])
            self.assertEqual(report['correct_handoffs'], [6, 6])
            self.assertEqual(report['exact_repeats'], [4, 4])
            self.assertEqual(report['unauthorized_effects'], 0)
            self.assertEqual(len(report['samples']), 24)
            self.assertTrue(all(s['evidence_valid'] and s['effects_unchanged'] for s in report['samples']))
            self.assertTrue(all(s['initiator_bound'] for s in report['samples']))
            self.assertGreater(report['setup_postings'], 0)
            self.assertGreater(report['budget']['requests'], 24)
            self.assertLessEqual(report['budget']['requests'], 192)
            self.assertEqual(sum(s['requests'] for s in report['samples']), report['budget']['requests'])
            self.assertTrue(all(s['usage']['complete'] for s in report['samples']))
            self.assertEqual(sum(s['usage']['observed_nanodollars'] for s in report['samples']),
                             report['budget']['observed_nanodollars'])
            self.assertFalse(report['live_verified'])
            self.assertEqual(report['mode'], 'offline_contract')
        with self.s.OperationalEvaluation(self.root) as evaluation, patch.object(
                self.s.EvaluationBudget, 'dispatch', side_effect=AssertionError('completed experiment redispatched')):
            self.assertEqual(evaluation.run(), report)
        serialized = json.dumps(report)
        for forbidden in ('password', 'session_token', 'SECRET', 'description', 'explanation'):
            self.assertNotIn(forbidden, serialized)

    def test_resume_between_samples_retains_budget_and_setup_history(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            first = evaluation.run(limit_samples=1)
            self.assertEqual(first['completed_samples'], 1)
            self.assertFalse(first['offline_contract_passed'])
            first_record = first['samples'][0]
        with self.s.OperationalEvaluation(self.root) as evaluation:
            second = evaluation.run(limit_samples=1)
            self.assertEqual(second['completed_samples'], 2)
            self.assertEqual(second['samples'][0], first_record)
            self.assertGreater(second['budget']['requests'], first['budget']['requests'])
            self.assertEqual(second['exact_proposals'][1], 14)
            self.assertEqual(second['correct_handoffs'][1], 6)

    def test_missing_usage_stops_and_remains_in_denominator_after_restart(self):
        with self.s.OperationalEvaluation(self.root, worker=missing_usage_worker) as evaluation:
            report = evaluation.run()
            self.assertFalse(report['offline_contract_passed'])
            self.assertFalse(report['budget']['cost_complete'])
            self.assertEqual(report['budget']['requests'], 1)
            self.assertEqual(report['completed_samples'], 1)
            self.assertEqual(report['exact_proposals'], [0, 14])
            self.assertEqual(report['correct_handoffs'], [0, 6])
        with self.s.OperationalEvaluation(self.root, worker=missing_usage_worker) as evaluation:
            self.assertEqual(evaluation.run(), report)

    def test_wrong_semantic_result_cannot_pass_and_raw_explanation_is_redacted(self):
        with self.s.OperationalEvaluation(self.root, worker=wrong_semantics_worker) as evaluation:
            report = evaluation.run(limit_samples=1)
        self.assertFalse(report['offline_contract_passed'])
        self.assertFalse(report['samples'][0]['matched'])
        self.assertEqual(report['exact_proposals'], [0, 14])
        self.assertEqual(report['unauthorized_effects'], 0)
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertNotIn(b'SECRET', (self.root / 'scoring.sqlite3').read_bytes())

    def test_forged_approval_is_refused_with_no_journal_effect(self):
        with self.s.OperationalEvaluation(self.root, worker=forged_approval_worker) as evaluation:
            report = evaluation.run(limit_samples=1)
        self.assertFalse(report['samples'][0]['matched'])
        self.assertEqual(report['samples'][0]['observed']['reason'], 'invalid_tool_call')
        self.assertEqual(report['unauthorized_effects'], 0)

    def test_aggregate_request_exhaustion_does_not_reset_on_reopen(self):
        policy = self.s.default_policy(); policy['max_requests'] = 1
        with self.s.OperationalEvaluation(self.root, policy=policy) as evaluation:
            report = evaluation.run()
            self.assertEqual(report['budget']['requests'], 1)
            self.assertFalse(report['offline_contract_passed'])
            self.assertEqual(report['completed_samples'], 1)
        with self.s.OperationalEvaluation(self.root, policy=policy) as evaluation:
            self.assertEqual(evaluation.run(), report)
        with self.assertRaises(ValueError):
            self.s.OperationalEvaluation(self.root)

    def test_unfinished_sample_cannot_be_replayed_after_crash(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            with patch.object(evaluation, '_evaluate_sample', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    evaluation.run(limit_samples=1)
        with self.s.OperationalEvaluation(self.root) as evaluation:
            report = evaluation.run()
            self.assertFalse(report['offline_contract_passed'])
            self.assertEqual(report['stop_reason'], 'sample_completion_unknown')
            self.assertEqual(report['completed_samples'], 0)
            self.assertEqual(report['effects_unknown'], 1)
            self.assertEqual(report['setup_postings_unknown'], 1)
            self.assertEqual(report['budget']['requests'], 0)

    def test_revocation_during_provider_request_prevents_tool_effect(self):
        original = self.s.EvaluationBudget.dispatch
        with self.s.OperationalEvaluation(self.root) as evaluation:
            def revoke(budget, *args, **kwargs):
                result = original(budget, *args, **kwargs)
                evaluation.access.bootstrap_revoke(evaluation.users['preparer'], 'eval-00',
                    reason='Synthetic evaluation revocation', retry_key='revoke')
                return result
            with patch.object(self.s.EvaluationBudget, 'dispatch', revoke):
                report = evaluation.run(limit_samples=1)
            self.assertFalse(report['samples'][0]['matched'])
            self.assertEqual(report['samples'][0]['failure'], 'access_denied')
            self.assertEqual(report['unauthorized_effects'], 0)
        with self.s.OperationalEvaluation(self.root) as evaluation:
            self.assertEqual(evaluation.run(), report)

    def test_stored_proposal_mismatch_cannot_hide_behind_run_projection(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            evaluation.run(limit_samples=1)
            state = evaluation._state('eval-00')
            altered = copy.deepcopy(state)
            altered['drafts'][0]['proposal']['lines'][0]['amount'] = '0.01'
            altered['drafts'][0]['policy_version'] = 'wrong-policy'
            result = evaluation._score(evaluation.manifest['samples'][0], 'eval-00', state, altered)
            self.assertFalse(result['matched'])

    def test_setup_failure_is_sanitized_and_durable_incomplete_result(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            with patch.object(evaluation, '_setup', side_effect=ValueError('SECRET setup failure')):
                report = evaluation.run()
            self.assertEqual(report['stop_reason'], 'setup_failed')
            self.assertFalse(report['offline_contract_passed'])
            self.assertNotIn('SECRET', json.dumps(report))
        with self.s.OperationalEvaluation(self.root) as evaluation:
            self.assertEqual(evaluation.run(), report)

    def test_failure_after_dependency_posting_reports_unknown_not_zero(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            evaluation.run(limit_samples=1)
            original = evaluation._setup
            def fail_after_setup(*args):
                original(*args)
                raise ValueError('Synthetic setup interruption')
            with patch.object(evaluation, '_setup', fail_after_setup):
                report = evaluation.run(limit_samples=1)
            self.assertEqual(evaluation._state('eval-01')['journal_count'], 1)
            self.assertIsNone(report['samples'][-1]['setup_postings'])
            self.assertEqual(report['setup_postings_unknown'], 1)
            self.assertEqual(report['effects_unknown'], 1)
            self.assertFalse(report['offline_contract_passed'])

    def test_per_request_deadline_applies_below_aggregate_deadline(self):
        from accounting_harness.operational_agent import OfflineEvaluationProvider
        with self.s.OperationalEvaluation(self.root, worker=slow_worker) as evaluation:
            started = time.monotonic()
            with patch.object(OfflineEvaluationProvider, 'timeout_ms', 100):
                report = evaluation.run(limit_samples=1)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertFalse(report['offline_contract_passed'])
            self.assertFalse(report['budget']['cost_complete'])
            self.assertEqual(report['budget']['requests'], 1)

    def test_false_date_label_fails_actual_semantic_score(self):
        with patch.object(self.s, 'EXPECTED_DATES', dict(self.s.EXPECTED_DATES,
                          **{'nonoperating_cash-owner-contribution': '2026-01-02'})):
            with self.s.OperationalEvaluation(self.root) as evaluation:
                report = evaluation.run(limit_samples=1)
        self.assertEqual(report['exact_proposals'], [0, 14])
        self.assertFalse(report['samples'][0]['evidence_valid'])

    def test_separate_review_permissions_and_post_retry_without_agent_dispatch(self):
        from accounting_harness.access import AccessDenied
        from accounting_harness.operational_agent import OfflineEvaluationProvider
        with self.s.OperationalEvaluation(self.root) as evaluation:
            report = evaluation.run(limit_samples=1)
            state = evaluation._state('eval-00')
            draft = state['drafts'][0]
            confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],
                                confirmed_digest=draft['content_digest'])
            with self.assertRaises(AccessDenied):
                evaluation._act('eval-00', 'approve-post', confirmation)
            receipt = evaluation._act('eval-00', 'approve-post', confirmation, 'reviewer')
            self.assertEqual(evaluation._act('eval-00', 'approve-post', confirmation, 'reviewer'), receipt)
            self.assertEqual(evaluation._state('eval-00')['journal_count'], 1)
            adapter = OfflineEvaluationProvider(evaluation.budget, evaluation.manifest['samples'][0]['sample_id'],
                evaluation.worker, self.s.digest(evaluation.binding))
            selection = dict(run_id='forged', workflow='nonoperating_cash', source_ids=['owner-cash','owner-basis'],
                             target_ids=[], operator={})
            with self.assertRaises(AccessDenied):
                evaluation.app.evaluate_operational(evaluation.tokens['reviewer'], 'eval-00', selection, adapter)
            with self.assertRaises(AccessDenied):
                evaluation.app.evaluate_operational(evaluation.tokens['preparer'], 'ungranted', selection, adapter)
            self.assertEqual(evaluation.report(), report)

    def test_cli_persists_offline_report_and_rejects_live_flag(self):
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'eval-operational',
            '--directory', str(self.root)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['offline_contract_passed'])
        self.assertFalse(report['live_verified'])
        rejected = subprocess.run([sys.executable, '-m', 'accounting_harness', 'eval-operational',
            '--directory', str(self.root), '--live'], text=True, capture_output=True)
        self.assertEqual(rejected.returncode, 2)

    def test_existing_directory_and_changed_worker_are_not_adopted(self):
        self.root.mkdir(); marker = self.root / 'preserve'; marker.write_text('original')
        with self.assertRaises(ValueError):
            self.s.OperationalEvaluation(self.root)
        self.assertEqual(marker.read_text(), 'original')
        marker.unlink(); self.root.rmdir()
        with self.s.OperationalEvaluation(self.root):
            pass
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            self.s.OperationalEvaluation(self.root, worker=wrong_semantics_worker)

    def test_scores_are_immutable_and_false_expected_labels_are_rejected(self):
        with self.s.OperationalEvaluation(self.root) as evaluation:
            evaluation.run(limit_samples=1)
        with closing(sqlite3.connect(self.root / 'scoring.sqlite3')) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM sample_results')
        from accounting_harness import operational_evaluation
        original = operational_evaluation.CORPUS.read_bytes()
        with patch.object(self.s, 'EXPECTED_DATES', dict(self.s.EXPECTED_DATES, **{'nonoperating_cash-owner-contribution': '2026-01-02'})):
            with self.assertRaisesRegex(ValueError, 'binding differs'):
                self.s.OperationalEvaluation(self.root)
        self.assertEqual(operational_evaluation.CORPUS.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
