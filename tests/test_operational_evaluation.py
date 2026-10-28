"""Durable evaluation limits: real SQLite, restart and killed-worker boundaries."""
import copy
import importlib.util
import json
import multiprocessing
import os
import struct
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def hanging_worker(pipe, marker):
    Path(marker).write_text('started')
    time.sleep(30)
    Path(marker).write_text('escaped deadline')
    pipe.send(('ok', {'cost_nanodollars': 7}))


def partial_message_worker(pipe):
    os.write(pipe.fileno(), struct.pack('!i', 1024) + b'x')
    time.sleep(2)
    pipe.close()


def failed_worker(pipe):
    pipe.send(('error', 'SECRET-RAW-PROVIDER-BODY'))
    pipe.close()


def cancelling_worker(pipe, path, policy):
    from accounting_harness.operational_evaluation import EvaluationBudget
    with EvaluationBudget(path, policy) as budget:
        budget.cancel()
    time.sleep(30)


def successful_worker(pipe, path):
    # Reservation must be committed before external work, with no write lock held.
    with sqlite3.connect(path, timeout=.1) as db:
        db.execute('BEGIN IMMEDIATE')
        count = db.execute('SELECT count(*) FROM attempts').fetchone()[0]
    pipe.send(('ok', {'cost_nanodollars': 7, 'private_response': 'SECRET'}))
    pipe.close()


class EvaluationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.operational_evaluation'),
                             'durable evaluation controls are not implemented')
        from accounting_harness import operational_evaluation as evaluation
        self.e = evaluation
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'evaluation.sqlite3'
        self.now = 1000
        self.manifest = evaluation.load_manifest()
        self.samples = [s['sample_id'] for s in self.manifest['samples']]
        self.policy = dict(manifest_digest=self.manifest['digest'], mode='offline_contract',
                           max_requests=2, max_requests_per_sample=2,
                           max_cost_nanodollars=100, reservation_nanodollars=50,
                           max_elapsed_ms=10000)

    def budget(self, **changes):
        return self.e.EvaluationBudget(self.path, dict(self.policy, **changes), clock_ms=lambda: self.now)

    def test_restart_keeps_full_reservations_separate_from_observed_cost(self):
        with self.budget() as budget:
            attempt = budget.reserve(self.samples[0])
            budget.settle(attempt, cost_nanodollars=7)
        with self.budget() as budget:
            attempt = budget.reserve(self.samples[0])
            budget.settle(attempt, cost_nanodollars=11)
            with self.assertRaisesRegex(ValueError, 'request_budget'):
                budget.reserve(self.samples[1])
            report = budget.report()
        self.assertEqual((report['requests'], report['reserved_nanodollars'], report['observed_nanodollars']),
                         (2, 100, 18))
        self.assertTrue(report['cost_complete'])
        self.assertFalse(report['live_verified'])

    def test_unknown_attempt_survives_actual_process_exit_and_refuses_resend(self):
        with self.budget():
            pass
        code = """import json, os, sys
from accounting_harness.operational_evaluation import EvaluationBudget
with EvaluationBudget(sys.argv[1], json.loads(sys.argv[2]), clock_ms=lambda: 1000) as budget:
    budget.reserve(sys.argv[3])
    os._exit(0)
"""
        subprocess.run([sys.executable, '-c', code, str(self.path), json.dumps(self.policy), self.samples[0]], check=True)
        with self.budget() as budget:
            with self.assertRaisesRegex(ValueError, 'completion_unknown'):
                budget.reserve(self.samples[0])
            report = budget.report()
        self.assertEqual((report['requests'], report['reserved_nanodollars'], report['unknown_attempts']), (1, 50, 1))
        self.assertFalse(report['cost_complete'])
        with self.assertRaisesRegex(ValueError, 'policy differs'):
            with self.budget(max_requests=3):
                pass

    def test_concurrent_reservations_allow_only_one_in_flight(self):
        with self.budget():
            pass
        barrier = Barrier(2)
        def reserve():
            with self.budget() as budget:
                barrier.wait(timeout=5)
                try:
                    budget.reserve(self.samples[0])
                    return 'reserved'
                except ValueError:
                    return 'refused'
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: reserve(), range(2)))
        self.assertCountEqual(results, ['reserved', 'refused'])
        with self.budget() as budget:
            self.assertEqual(budget.report()['requests'], 1)

    def test_per_sample_limit_and_cost_limit_do_not_dispatch(self):
        with self.budget(max_requests=10, max_requests_per_sample=1, max_cost_nanodollars=99) as budget:
            attempt = budget.reserve(self.samples[0])
            budget.settle(attempt, cost_nanodollars=0)
            with self.assertRaisesRegex(ValueError, 'sample_request_budget'):
                budget.reserve(self.samples[0])
            with self.assertRaisesRegex(ValueError, 'cost_budget'):
                budget.reserve(self.samples[1])
            self.assertEqual(budget.report()['requests'], 1)

    def test_reopen_does_not_reset_deadline_and_backwards_clock_fails_closed(self):
        with self.budget():
            pass
        self.now = 11000
        with self.budget() as budget:
            with self.assertRaisesRegex(ValueError, 'time_budget'):
                budget.reserve(self.samples[0])
        self.now = 999
        with self.budget() as budget:
            with self.assertRaisesRegex(ValueError, 'clock_regression|time_budget'):
                budget.reserve(self.samples[0])

    def test_cancel_is_durable_and_late_result_cannot_resume(self):
        with self.budget() as budget:
            attempt = budget.reserve(self.samples[0])
            budget.cancel()
            budget.settle(attempt, cost_nanodollars=7)
        with self.budget() as budget:
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                budget.reserve(self.samples[1])
            self.assertTrue(budget.report()['cancelled'])
            self.assertEqual(budget.report()['observed_nanodollars'], 7)

    def test_missing_usage_and_failed_attempt_never_refund_or_reset(self):
        with self.budget() as budget:
            attempt = budget.reserve(self.samples[0])
            budget.settle(attempt, cost_nanodollars=None, outcome='provider_failed')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                budget.reserve(self.samples[1])
            report = budget.report()
        self.assertEqual(report['reserved_nanodollars'], 50)
        self.assertFalse(report['cost_complete'])
        self.assertEqual(report['failed_attempts'], 1)

    def test_settlement_cannot_be_overwritten_or_understate_invalid_usage(self):
        with self.budget() as budget:
            attempt = budget.reserve(self.samples[0])
            for cost in (True, -1, 51, 1.5, '7'):
                with self.subTest(cost=cost), self.assertRaises(ValueError):
                    budget.settle(attempt, cost_nanodollars=cost)
            self.assertEqual(budget.report()['unknown_attempts'], 1)
            budget.settle(attempt, cost_nanodollars=7)
            budget.settle(attempt, cost_nanodollars=7)
            with self.assertRaisesRegex(ValueError, 'settlement differs'):
                budget.settle(attempt, cost_nanodollars=8)
            with self.assertRaises(ValueError):
                budget.settle(999, cost_nanodollars=7)
        with sqlite3.connect(self.path) as db:
            for table in ('experiment', 'attempts', 'results'):
                with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(f'DELETE FROM {table}')

    def test_invalid_policy_sample_and_live_claim_are_rejected(self):
        for change in ({'max_requests': True}, {'max_elapsed_ms': 0}, {'max_cost_nanodollars': -1},
                       {'mode': 'live'}, {'manifest_digest': '0' * 64}, {'extra': 'secret'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                with self.budget(**change):
                    pass
        with self.budget() as budget:
            with self.assertRaises(ValueError):
                budget.reserve('forged-sample')
            self.assertEqual(budget.report()['requests'], 0)

    def test_policy_cannot_be_mutated_to_bypass_durable_limits(self):
        with self.budget(max_requests=1) as budget:
            budget.settle(budget.reserve(self.samples[0]), cost_nanodollars=7)
            with self.assertRaises(TypeError):
                budget.policy['max_requests'] = 2
            with self.assertRaisesRegex(ValueError, 'request_budget'):
                budget.reserve(self.samples[1])

    def test_expired_deadline_stays_stopped_after_clock_reset(self):
        with self.budget() as budget:
            self.now = 11000
            with self.assertRaisesRegex(ValueError, 'time_budget'):
                budget.reserve(self.samples[0])
        self.now = 1000
        with self.budget() as budget:
            with self.assertRaisesRegex(ValueError, 'time_budget'):
                budget.reserve(self.samples[0])
            self.assertEqual(budget.report()['requests'], 0)

    def test_in_flight_wall_clock_expiry_terminates_worker(self):
        readings = 0
        def clock():
            nonlocal readings
            readings += 1
            return 1000 if readings < 8 else 11000
        started = time.monotonic()
        with self.e.EvaluationBudget(self.path, self.policy, clock_ms=clock) as budget:
            with self.assertRaisesRegex(ValueError, 'time_budget'):
                budget.dispatch(self.samples[0], hanging_worker, (str(Path(self.temp.name) / 'marker'),))
            self.assertFalse(budget.report()['cost_complete'])
        self.assertLess(time.monotonic() - started, 3)

    def test_foreign_database_is_not_modified(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE unrelated (value TEXT)')
            db.execute("INSERT INTO unrelated VALUES ('preserve')")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unsupported evaluation database'):
            with self.budget():
                pass
        self.assertEqual(self.path.read_bytes(), before)

    def test_dispatch_commits_before_worker_and_does_not_store_raw_response(self):
        with self.e.EvaluationBudget(self.path, self.policy) as budget:
            budget.dispatch(self.samples[0], successful_worker, (str(self.path),))
            self.assertEqual(budget.report()['observed_nanodollars'], 7)
        self.assertNotIn(b'SECRET', self.path.read_bytes())

    def test_stalled_worker_is_killed_at_remaining_aggregate_deadline(self):
        marker = Path(self.temp.name) / 'worker-marker'
        started = time.monotonic()
        children = {p.pid for p in multiprocessing.active_children()}
        with self.e.EvaluationBudget(self.path, dict(self.policy, max_elapsed_ms=200)) as budget:
            with self.assertRaisesRegex(ValueError, 'provider_timeout|time_budget'):
                budget.dispatch(self.samples[0], hanging_worker, (str(marker),))
            report = budget.report()
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, children)
        self.assertFalse(report['cost_complete'])
        self.assertEqual(report['reserved_nanodollars'], 50)
        if marker.exists():
            self.assertEqual(marker.read_text(), 'started')

    def test_provider_error_is_redacted_and_keeps_reservation(self):
        with self.e.EvaluationBudget(self.path, self.policy) as budget:
            with self.assertRaisesRegex(ValueError, '^provider_failed$'):
                budget.dispatch(self.samples[0], failed_worker)
            report = budget.report()
            self.assertFalse(report['cost_complete'])
            self.assertEqual(report['reserved_nanodollars'], 50)
        self.assertNotIn(b'SECRET', self.path.read_bytes())

    def test_other_connection_cancels_in_flight_request(self):
        started = time.monotonic()
        with self.e.EvaluationBudget(self.path, self.policy) as budget:
            with self.assertRaisesRegex(ValueError, '^cancelled$'):
                budget.dispatch(self.samples[0], cancelling_worker, (str(self.path), self.policy))
            report = budget.report()
            self.assertTrue(report['cancelled'])
            self.assertFalse(report['cost_complete'])
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(any(t.name == 'accounting-provider-receive' for t in threading.enumerate()))

    def test_partial_worker_message_cannot_block_deadline(self):
        started = time.monotonic()
        with self.e.EvaluationBudget(self.path, dict(self.policy, max_elapsed_ms=200)) as budget:
            with self.assertRaisesRegex(ValueError, 'provider_timeout|time_budget'):
                budget.dispatch(self.samples[0], partial_message_worker)
            self.assertFalse(budget.report()['cost_complete'])
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertFalse(any(t.name == 'accounting-provider-receive' for t in threading.enumerate()))

    def test_manifest_freezes_semantics_and_excludes_injected_faults(self):
        manifest = self.manifest
        self.assertEqual(len(manifest['samples']), 24)
        self.assertEqual(sum(s['category'] == 'reference' for s in manifest['samples'][:20]), 14)
        self.assertEqual(sum(s['category'] == 'handoff' for s in manifest['samples'][:20]), 6)
        self.assertEqual([s['case_id'] for s in manifest['samples'][20:]],
                         ['cash_expense-rent', 'vendor_bill-software', 'prepaid_consumption-january', 'hostile-model-handoff'])
        self.assertEqual(len(manifest['excluded_cases']), 11)
        raw = json.loads(self.e.MANIFEST.read_text())
        for mutate in (lambda x: x['samples'].pop(),
                       lambda x: x['samples'].__setitem__(1, x['samples'][0]),
                       lambda x: x.__setitem__('corpus_digest', '0' * 64)):
            changed = copy.deepcopy(raw); mutate(changed)
            path = Path(self.temp.name) / 'manifest.json'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                self.e.load_manifest(path)
        corpus = json.loads(self.e.CORPUS.read_text())
        corpus['cases'][0]['expect']['lines'][0][2] = '99999.00'
        path = Path(self.temp.name) / 'corpus.json'
        path.write_text(json.dumps(corpus))
        with self.assertRaises(ValueError):
            self.e.load_manifest(corpus_path=path)


if __name__ == '__main__':
    unittest.main()
