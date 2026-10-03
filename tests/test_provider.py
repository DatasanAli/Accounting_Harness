import json
import unittest
from unittest.mock import patch

import test_review
from accounting_harness import runs
from accounting_harness import provider as api


def response(decision=None):
    decision = decision or dict(decision='propose', account='5000', amount='1200.00',
                               effective_date='2026-01-05', reason='supported_expense')
    return dict(status='completed', model=api.MODEL,
                usage=dict(input_tokens=500, output_tokens=60),
                output=[dict(type='message', role='assistant', content=[
                    dict(type='output_text', text=json.dumps(decision))])])


class ProviderTests(unittest.TestCase):
    def setUp(self):
        test_review.ReviewTests.setUp(self)
        self.engine = runs.SQLiteRunEngine(self.path.with_name('runs.sqlite3'), self.store)
        self.addCleanup(self.engine.close)
        self.provider = api.OpenAIExpenseProvider('rent')
        self.limits = runs.RunLimits(5, 60000, api.RESERVATION, 2)

    def start(self, **kwargs):
        return self.engine.start('live', task_id='expense', actor_id='agent', provider=self.provider,
                                 limits=kwargs.get('limits', self.limits))

    def run_response(self, payload):
        self.start()
        with patch.object(api, 'request_response', return_value=payload):
            return self.engine.run('live', self.provider)

    def test_proposal_stops_for_review_and_resume_never_reposts_or_recalls(self):
        paused = self.run_response(response())
        self.assertEqual(paused.state, 'awaiting_review')
        self.assertEqual(self.ledger.counts()['journals'], 0)
        draft = self.store.queue()[0]
        proposal = json.loads(draft.proposal_json)
        self.assertEqual(proposal['lines'], [dict(account='5000', side='debit', amount='1200.00'),
                                            dict(account='1000', side='credit', amount='1200.00')])
        self.assertEqual(draft.actor_id, 'agent')
        with patch.object(api, 'request_response', side_effect=AssertionError('unexpected network')):
            self.assertEqual(self.engine.resume('live', self.provider).state, 'completed')
        self.assertEqual(len(self.store.history(draft.draft_id)), 1)
        self.assertEqual(paused.cost_units, api.RESERVATION)
        usages = [json.loads(c.result_json)['usage'] for c in self.engine.trace('live')
                  if c.result_json and 'usage' in json.loads(c.result_json)]
        self.assertEqual(usages[0]['cost_nanodollars'], 296000)

    def test_abstention_is_durable_review_without_draft(self):
        stopped = self.run_response(response(dict(decision='review', account='', amount='',
                              effective_date='', reason='ambiguous')))
        self.assertEqual((stopped.state, stopped.reason), ('awaiting_review', 'ambiguous'))
        self.assertEqual(self.store.queue(), ())

    def test_invalid_and_unsafe_outputs_fail_closed(self):
        for decision in [dict(decision='post', account='5000', amount='1200.00', effective_date='2026-01-05', reason='supported_expense'),
                         dict(decision='propose', account='3000', amount='1200.00', effective_date='2026-01-05', reason='supported_expense'),
                         dict(decision='propose', account='5000', amount='1199.00', effective_date='2026-01-05', reason='supported_expense'),
                         dict(decision='propose', account='5000', amount=1200.0, effective_date='2026-01-05', reason='supported_expense')]:
            with self.subTest(decision=decision):
                with self.assertRaises(api.ProviderFailure):
                    api.proposal_intent(response(decision), self.provider.context(self.store), 'draft')

    def test_request_is_outside_transaction_and_cancellation_discards_result(self):
        self.start()
        def cancel(*args, **kwargs):
            self.assertFalse(self.engine.db.in_transaction)
            with runs.SQLiteRunEngine(self.path.with_name('runs.sqlite3'), self.store) as other:
                other.cancel('live', actor_id='human', reason='stop')
            return response()
        with patch.object(api, 'request_response', side_effect=cancel):
            stopped = self.engine.run('live', self.provider)
        self.assertEqual(stopped.state, 'cancelled')
        self.assertEqual(self.store.queue(), ())
        self.assertEqual(stopped.cost_units, api.RESERVATION)

    def test_crash_after_reservation_never_retries_network(self):
        self.start()
        with patch.object(api, 'request_response', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.engine.advance('live', self.provider)
        self.assertEqual(self.engine.get('live').state, 'requesting_provider')
        with runs.SQLiteRunEngine(self.path.with_name('runs.sqlite3'), self.store) as reopened:
            with patch.object(api, 'request_response', side_effect=AssertionError('unexpected retry')):
                stopped = reopened.resume('live', self.provider)
        self.assertEqual((stopped.state, stopped.reason), ('awaiting_review', 'provider_completion_unknown'))
        self.assertEqual(stopped.provider_attempts, 1)
        self.assertEqual(stopped.cost_units, api.RESERVATION)

    def test_budgets_block_before_network(self):
        for i, limits in enumerate([runs.RunLimits(5, 60000, api.RESERVATION-1, 2), runs.RunLimits(2, 60000, api.RESERVATION, 2)]):
            run_id = str(i)
            self.engine.start(run_id, task_id='expense', actor_id='agent', provider=self.provider, limits=limits)
            with patch.object(api, 'request_response', side_effect=AssertionError('unexpected network')):
                result = self.engine.run(run_id, self.provider)
            self.assertEqual(result.state, 'exhausted')
            self.assertEqual(result.provider_attempts, 0)

    def test_timeout_and_rate_limit_do_not_retry(self):
        for i, reason in enumerate(['provider_timeout', 'provider_rate_limit', 'provider_unavailable']):
            run_id = str(i)
            self.engine.start(run_id, task_id='expense', actor_id='agent', provider=self.provider, limits=self.limits)
            with patch.object(api, 'request_response', side_effect=api.ProviderFailure(reason)) as call:
                result = self.engine.run(run_id, self.provider)
                self.assertEqual(call.call_count, 1)
            self.assertEqual((result.state, result.reason), ('awaiting_review', reason))
            self.assertEqual(result.cost_units, api.RESERVATION)

    def test_refusal_incomplete_missing_usage_and_wrong_model_are_rejected(self):
        for change in [dict(status='incomplete'), dict(usage=None), dict(model='other'), dict(output=[]),
                       dict(output=[dict(type='message', content=[dict(type='refusal', refusal='raw secret')])])]:
            with self.subTest(change=change), self.assertRaises(api.ProviderFailure):
                api.parse_response(dict(response(), **change))

    def test_context_and_identity_do_not_contain_credentials(self):
        context = self.provider.context(self.store)
        self.assertEqual(context['evidence']['source_id'], 'rent')
        self.assertEqual(context['accounts']['entity_id'], self.catalog.entity_id)
        with patch.dict('os.environ', OPENAI_API_KEY='secret-sentinel'):
            self.start()
        self.assertNotIn('secret-sentinel', self.engine.configuration('live'))
        self.assertEqual(self.provider.identity['model'], api.MODEL)

    def test_context_preparation_cannot_start_request_after_deadline(self):
        now = [1000]
        self.engine._clock_ms = lambda: now[0]
        self.start()
        original = api.OpenAIExpenseProvider.context
        def slow_context(adapter, store):
            value = original(adapter, store)
            now[0] += 60001
            return value
        with patch.object(api.OpenAIExpenseProvider, 'context', slow_context):
            with patch.object(api, 'request_response', side_effect=AssertionError('late billable call')):
                stopped = self.engine.advance('live', self.provider)
        self.assertEqual((stopped.state, stopped.reason), ('exhausted', 'time_budget'))
        self.assertEqual(stopped.provider_attempts, 0)

    def test_source_claimed_during_network_is_not_saved_twice(self):
        self.start()
        def race(*args, **kwargs):
            test_review.ReviewTests.save(self)
            return response()
        with patch.object(api, 'request_response', side_effect=race):
            stopped = self.engine.run('live', self.provider)
        self.assertEqual(stopped.state, 'awaiting_review')
        self.assertEqual(len(self.store.queue()), 1)
        self.assertEqual(stopped.reason, 'duplicate')

    def test_source_claimed_after_intent_is_checked_at_save(self):
        self.start()
        with patch.object(api, 'request_response', return_value=response()):
            self.engine.advance('live', self.provider)
        test_review.ReviewTests.save(self)
        stopped = self.engine.run('live', self.provider)
        self.assertEqual(len(self.store.queue()), 1)
        self.assertEqual(stopped.state, 'awaiting_review')
        self.assertEqual(stopped.reason, 'duplicate')

    def test_live_save_receipt_recovers_after_crash_without_duplicate(self):
        self.start()
        with patch.object(api, 'request_response', return_value=response()):
            self.engine.advance('live', self.provider)
        with patch.object(self.engine, '_result', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.engine.advance('live', self.provider)
        self.assertEqual(len(self.store.queue()), 1)
        with runs.SQLiteRunEngine(self.path.with_name('runs.sqlite3'), self.store) as reopened:
            with patch.object(api, 'request_response', side_effect=AssertionError('unexpected network')):
                stopped = reopened.resume('live', self.provider)
                reasons = [c.reason for c in reopened.trace('live')]
        self.assertEqual(stopped.state, 'awaiting_review')
        self.assertIn('tool_result_recovered', reasons)
        self.assertEqual(len(self.store.history(self.store.queue()[0].draft_id)), 1)

    def test_request_body_is_bounded_and_contains_only_synthetic_context(self):
        context = self.provider.context(self.store)
        body = json.loads(self.provider.body(context))
        self.assertFalse(body['store'])
        self.assertNotIn('tools', body)
        self.assertEqual(body['max_output_tokens'], 512)
        self.assertEqual(body['text']['format']['type'], 'json_schema')
        context['evidence']['document']['description'] = 'x' * 13000
        with self.assertRaisesRegex(api.ProviderFailure, 'provider_input_too_large'):
            self.provider.body(context)

    def test_raw_response_and_key_never_enter_durable_run_log(self):
        payload = response()
        payload['raw_private_marker'] = 'secret-sentinel'
        self.run_response(payload)
        trace = str(self.engine.trace('live')) + self.engine.configuration('live')
        self.assertNotIn('secret-sentinel', trace)
        self.assertNotIn('output_text', trace)
        self.assertNotIn('Bearer', trace)


def slow_worker(pipe, body, key, timeout):
    import time
    time.sleep(30)


def successful_worker(pipe, body, key, timeout):
    pipe.send(('ok', response()))
    pipe.close()


class TransportTests(unittest.TestCase):
    def test_hard_deadline_kills_stalled_child(self):
        import multiprocessing
        import time
        before = {p.pid for p in multiprocessing.active_children()}
        started = time.monotonic()
        with patch.dict('os.environ', OPENAI_API_KEY='synthetic-test-key'):
            with patch.object(api, '_http_worker', slow_worker):
                with self.assertRaisesRegex(api.ProviderFailure, 'provider_timeout'):
                    api.request_response(b'{}', timeout_ms=500, cancelled=lambda: False)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_cancellation_kills_child_before_deadline(self):
        import multiprocessing
        import time
        before = {p.pid for p in multiprocessing.active_children()}
        started = time.monotonic()
        with patch.dict('os.environ', OPENAI_API_KEY='synthetic-test-key'):
            with patch.object(api, '_http_worker', slow_worker):
                with self.assertRaisesRegex(api.ProviderFailure, 'provider_cancelled'):
                    api.request_response(b'{}', timeout_ms=5000,
                                         cancelled=lambda: time.monotonic() - started > .15)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_successful_child_returns_parsable_response(self):
        with patch.dict('os.environ', OPENAI_API_KEY='synthetic-test-key'):
            with patch.object(api, '_http_worker', successful_worker):
                payload = api.request_response(b'{}', timeout_ms=3000, cancelled=lambda: False)
        self.assertEqual(api.parse_response(payload)[1]['cost_nanodollars'], 296000)
