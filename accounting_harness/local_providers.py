"""Explicit offline fixture and loopback Ollama expense adapters."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from accounting_harness import provider
from accounting_harness.review import digest

CORPUS = Path(__file__).resolve().parents[1] / 'data/fixtures/provider-proposal-cases.json'


def envelope(decision, inputs=0, outputs=0):
    # Internal normalization only; identity/audit keep the actual provider/model.
    return dict(status='completed', model=provider.MODEL,
        usage=dict(input_tokens=inputs, output_tokens=outputs), output=[dict(type='message',
        content=[dict(type='output_text', text=json.dumps(decision))])])


def request_ollama(body, *, timeout_ms, cancelled):
    return provider.bounded_request(provider._http_worker,
        (body, None, timeout_ms / 1000, 'http://127.0.0.1:11434/api/chat'),
        timeout_ms=timeout_ms, cancelled=cancelled)


@dataclass(frozen=True, slots=True)
class OllamaExpenseProvider(provider.OpenAIExpenseProvider):
    model: str
    timeout_ms = 120000

    def __post_init__(self):
        super(OllamaExpenseProvider, self).__post_init__()
        if (type(self.model) is not str or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', self.model)
                or '://' in self.model or self.model.endswith((':cloud', '-cloud'))):
            raise ValueError('choose an installed local Ollama model name (not a cloud model)')

    @property
    def identity(self):
        return dict(provider_version='ollama-chat-v1', model=self.model,
            prompt_version=provider.PROMPT_VERSION, source_id=self.source_id,
            cost_unit='USD_nanodollar', reservation=0,
            fingerprint=digest([provider.PROMPT, provider.DECISION_SCHEMA, self.model,
                                self.source_id, self.timeout_ms, provider.MAX_BYTES]))

    def body(self, context):
        body = json.dumps(dict(model=self.model, stream=False, format=provider.DECISION_SCHEMA,
            messages=[dict(role='system', content=provider.PROMPT),
                      dict(role='user', content=json.dumps(context, sort_keys=True))],
            options=dict(temperature=0, num_predict=provider.MAX_OUTPUT, num_ctx=32768)),
            ensure_ascii=True, separators=(',', ':')).encode()
        if len(body) > provider.MAX_BYTES:
            raise provider.ProviderFailure('provider_input_too_large')
        return body

    def request(self, body, *, timeout_ms, cancelled):
        return request_ollama(body, timeout_ms=timeout_ms, cancelled=cancelled)

    def intent(self, payload, context, draft_id):
        try:
            if (payload['done'] is not True or payload['done_reason'] != 'stop'
                    or payload['model'] != self.model or payload['message']['role'] != 'assistant'
                    or payload['message'].get('tool_calls')):
                raise ValueError
            normalized = envelope(json.loads(payload['message']['content']),
                                  payload['prompt_eval_count'], payload['eval_count'])
        except (KeyError, TypeError, ValueError):
            raise provider.ProviderFailure('invalid_provider_output') from None
        intent, reason, usage = provider.proposal_intent(normalized, context, draft_id)
        usage['cost_nanodollars'] = 0  # Local inference; does not measure electricity/hardware costs.
        return intent, reason, usage


@dataclass(frozen=True, slots=True)
class OfflineExpenseProvider(provider.OpenAIExpenseProvider):
    """Exact fixture playback; no keyword inference and no model accuracy claim."""

    @property
    def identity(self):
        return dict(provider_version='offline-expense-v1', model='fixture-playback',
            prompt_version=provider.PROMPT_VERSION, source_id=self.source_id,
            cost_unit='USD_nanodollar', reservation=0,
            fingerprint=digest([self.source_id, CORPUS.read_text()]))

    def request(self, body, *, timeout_ms, cancelled):
        if cancelled():
            raise provider.ProviderFailure('provider_cancelled')
        context = json.loads(json.loads(body)['input'])
        for case in json.loads(CORPUS.read_text())['cases']:
            document = case['document']
            content = {k: v for k, v in document.items() if k not in ('entity_id', 'document_id')}
            if (document['document_id'] == context['evidence']['source_id']
                    and document['entity_id'] == context['evidence']['entity_id']
                    and content == context['evidence']['document']):
                return envelope(case['synthetic_response'])
        raise provider.ProviderFailure('offline_fixture_not_found')
