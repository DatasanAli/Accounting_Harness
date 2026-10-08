"""Adapter tests use fictional envelopes; never contact a model service."""

import json
import unittest
from unittest.mock import patch

from accounting_harness import provider, local_providers
from accounting_harness.provider_evaluation import CORPUS, case_storage, load_cases
from accounting_harness.runs import RunLimits, SQLiteRunEngine


class LocalProviderTests(unittest.TestCase):
    def test_offline_fixture_stops_for_review_without_posting(self):
        case = load_cases(CORPUS)[1]
        with case_storage(case) as (_, _, _, ledger, store, engine):
            adapter = local_providers.OfflineExpenseProvider(case['document']['document_id'])
            engine.start('offline', task_id='receipt', provider=adapter, actor_id='agent',
                         limits=RunLimits(5, 60000, 0, 0))
            with patch.object(provider, 'request_response', side_effect=AssertionError('network')):
                result = engine.run('offline', adapter)
            self.assertEqual(result.state, 'awaiting_review')
            self.assertEqual(result.cost_units, 0)
            self.assertEqual(json.loads(store.queue()[0].proposal_json)['lines'][0]['amount'], '1200.00')
            self.assertEqual(ledger.counts()['journals'], 0)

    def test_ollama_contract_corpus_and_usage(self):
        for case in load_cases(CORPUS):
            with self.subTest(case=case['id']), case_storage(case) as (_, _, _, ledger, store, engine):
                adapter = local_providers.OllamaExpenseProvider(case['document']['document_id'], 'test-local:1')
                context = adapter.context(store)
                body = json.loads(adapter.body(context))
                self.assertFalse(body['stream'])
                self.assertEqual(body['format'], provider.DECISION_SCHEMA)
                envelope = dict(model='test-local:1', done=True, done_reason='stop',
                    message=dict(role='assistant', content=json.dumps(case['synthetic_response'])),
                    prompt_eval_count=500, eval_count=60)
                engine.start('local', task_id='receipt', provider=adapter, actor_id='agent',
                             limits=RunLimits(5, 60000, 0, 0))
                with patch.object(local_providers, 'request_ollama', return_value=envelope):
                    result = engine.run('local', adapter)
                self.assertEqual(result.state, 'awaiting_review')
                drafts = [d for d in store.queue() if d.draft_id != 'prior']
                self.assertEqual(len(drafts), int(case['expected']['outcome'] == 'proposal'))
                if drafts:
                    line = json.loads(drafts[0].proposal_json)['lines'][0]
                    self.assertEqual(line['account'], case['expected']['account'])
                    self.assertEqual(line['amount'], case['expected']['amount'])
                self.assertEqual(ledger.counts()['journals'], 0)
                self.assertEqual(result.cost_units, 0)

    def test_ollama_rejects_truncated_foreign_or_malformed_output(self):
        case = load_cases(CORPUS)[1]
        adapter = local_providers.OllamaExpenseProvider(case['document']['document_id'], 'test-local:1')
        with case_storage(case) as (_, _, _, _, store, _):
            context = adapter.context(store)
            valid = dict(model='test-local:1', done=True, done_reason='stop',
                message=dict(role='assistant', content=json.dumps(case['synthetic_response'])),
                prompt_eval_count=500, eval_count=60)
            for update in [dict(done=False), dict(done_reason='length'), dict(model='another'),
                           dict(eval_count=True), dict(message=dict(content='not json'))]:
                with self.subTest(update=update), self.assertRaises(provider.ProviderFailure):
                    adapter.intent(dict(valid, **update), context, 'draft')
            _, _, usage = adapter.intent(valid, context, 'draft')
            self.assertEqual(usage['cost_nanodollars'], 0)
            self.assertEqual(usage['input_tokens'], 500)

    def test_unknown_completion_does_not_repeat_ollama_request(self):
        case = load_cases(CORPUS)[1]
        with case_storage(case) as (_, _, _, _, _, engine):
            adapter = local_providers.OllamaExpenseProvider(case['document']['document_id'], 'test-local:1')
            engine.start('uncertain', task_id='receipt', provider=adapter, actor_id='agent',
                         limits=RunLimits(5, 60000, 0, 0))
            with patch.object(local_providers, 'request_ollama', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    engine.run('uncertain', adapter)
            with patch.object(local_providers, 'request_ollama', side_effect=AssertionError('repeat')):
                result = engine.run('uncertain', adapter)
            self.assertEqual(result.reason, 'provider_completion_unknown')

    def test_model_and_input_bounds(self):
        for name in ['', 'x'*201, 'model:cloud', 'https://remote/model']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                local_providers.OllamaExpenseProvider('source', name)
        adapter = local_providers.OllamaExpenseProvider('source', 'test-local:1')
        with self.assertRaises(provider.ProviderFailure):
            adapter.body({'untrusted': 'x'*20000})

    def test_local_adapters_recover_committed_draft_without_another_request(self):
        case = load_cases(CORPUS)[1]
        adapters = [local_providers.OfflineExpenseProvider(case['document']['document_id']),
                    local_providers.OllamaExpenseProvider(case['document']['document_id'], 'test-local:1')]
        response = dict(model='test-local:1', done=True, done_reason='stop',
            message=dict(role='assistant', content=json.dumps(case['synthetic_response'])),
            prompt_eval_count=500, eval_count=60)
        for adapter in adapters:
            with self.subTest(adapter=type(adapter).__name__), case_storage(case) as (root, _, _, ledger, store, engine):
                engine.start('recovery', task_id='receipt', provider=adapter, actor_id='agent',
                             limits=RunLimits(5, 60000, 0, 0))
                with patch.object(local_providers, 'request_ollama', return_value=response):
                    engine.advance('recovery', adapter)
                with patch.object(engine, '_result', side_effect=SystemExit):
                    with self.assertRaises(SystemExit):
                        engine.advance('recovery', adapter)
                with SQLiteRunEngine(root / 'runs.sqlite3', store) as reopened:
                    with patch.object(type(adapter), 'request', side_effect=AssertionError('repeat request')):
                        result = reopened.resume('recovery', adapter)
                    self.assertIn('tool_result_recovered', [c.reason for c in reopened.trace('recovery')])
                self.assertEqual(result.state, 'awaiting_review')
                self.assertEqual(len(store.history(store.queue()[0].draft_id)), 1)
                self.assertEqual(ledger.counts()['journals'], 0)

    def test_ollama_cancellation_wins_over_late_response_without_transaction(self):
        case = load_cases(CORPUS)[1]
        with case_storage(case) as (root, _, _, ledger, store, engine):
            adapter = local_providers.OllamaExpenseProvider(case['document']['document_id'], 'test-local:1')
            engine.start('cancel', task_id='receipt', provider=adapter, actor_id='agent',
                         limits=RunLimits(5, 60000, 0, 0))
            def request(*args, **kwargs):
                self.assertFalse(engine.db.in_transaction)
                self.assertFalse(store.db.in_transaction)
                with SQLiteRunEngine(root / 'runs.sqlite3', store) as other:
                    other.cancel('cancel', actor_id='human', reason='Stop')
                return dict(model='test-local:1', done=True, done_reason='stop',
                    message=dict(role='assistant', content=json.dumps(case['synthetic_response'])),
                    prompt_eval_count=500, eval_count=60)
            with patch.object(local_providers, 'request_ollama', side_effect=request):
                result = engine.run('cancel', adapter)
            self.assertEqual(result.state, 'cancelled')
            self.assertEqual(store.queue(), ())
            self.assertEqual(ledger.counts()['journals'], 0)
