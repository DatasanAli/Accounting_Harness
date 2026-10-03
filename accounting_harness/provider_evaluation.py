"""Frozen synthetic proposal gate; offline envelopes are not model accuracy."""

import json
import os
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from accounting_harness import provider
from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.money import Money
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.runs import RunLimits, SQLiteRunEngine
from accounting_harness.sources import SQLiteSourceRegistry, load_source_document

FIXTURES = Path(__file__).resolve().parents[1] / 'data/fixtures'
CORPUS = FIXTURES / 'provider-proposal-cases.json'
LIVE_SAMPLES = 24
LIVE_TIME_MS = 300000
LIVE_COST = 250000000  # $0.25 in integer USD nanodollars.


def synthetic_envelope(decision):
    """Handwritten fixture envelope; never a recorded live response."""
    return dict(status='completed', model=provider.MODEL,
                usage=dict(input_tokens=500, output_tokens=60),
                output=[dict(type='message', role='assistant', content=[
                    dict(type='output_text', text=json.dumps(decision))])])


@contextmanager
def case_storage(case):
    catalog = load_account_catalog(FIXTURES / 'service-business-month.json')
    document = case['document']
    with TemporaryDirectory(prefix='accounting-provider-') as directory:
        root = Path(directory)
        options = dict(catalog=catalog, period_start='2026-01-01', period_end='2026-01-31',
                       known_source_ids={document['document_id']})
        with SQLiteSourceRegistry(root/'sources.sqlite3', catalog.entity_id) as registry:
            registry.register(document, actor_id='synthetic-importer')
            with SQLiteLedger(root/'ledger.sqlite3', **options) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                if case['prior_source_use']:
                    source = registry.get(document['document_id'])
                    proposal = dict(id='prior', entity_id=catalog.entity_id, currency='USD',
                        effective_date=document['document_date'], description='Prior synthetic receipt use',
                        source_ids=[document['document_id']], lines=[
                            dict(account='5000', side='debit', amount=document['amount']),
                            dict(account='1000', side='credit', amount=document['amount'])])
                    store.save('prior', proposal, evidence={document['document_id']: source.content_digest},
                        expected_revision=0, actor_id='synthetic-human', idempotency_key='prior', reason='Prior use')
                with SQLiteRunEngine(root/'runs.sqlite3', store) as engine:
                    yield root, options, registry, ledger, store, engine


def load_cases(path):
    corpus = load_source_document(path)
    cases = corpus.get('cases')
    if (corpus.get('schema_version') != 1 or corpus.get('synthetic') is not True
            or corpus.get('corpus_version') != 'expense-cases-v1' or type(cases) is not list
            or len(cases) != 20 or len({c['id'] for c in cases}) != len(cases)):
        raise ValueError('expected frozen synthetic expense-cases-v1 with 20 unique cases')
    if {c['category'] for c in cases} != {'clean', 'ambiguity', 'missing', 'conflict', 'duplicate', 'unsupported', 'hostile'}:
        raise ValueError('proposal corpus must cover all seven categories')
    return cases


def evaluate_provider(path=CORPUS, *, live=False):
    cases = load_cases(path)
    if live and not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('live evaluation blocked: configure OPENAI_API_KEY locally; no live calls made')
    report = dict(mode='live' if live else 'offline_synthetic_responses',
        model=provider.MODEL, prompt_version=provider.PROMPT_VERSION, corpus_version='expense-cases-v1',
        cases=20, categories={}, exact_proposals=[0, 0], required_review=[0, 0], evidence_linked=[0, 0],
        unauthorized_postings=0, accepted_unbalanced=0, request_count=0, reserved_nanodollars=0,
        live_cost_nanodollars=0 if live else None, failures=[], samples=[], nondeterministic_repeats=0,
        repeat_count=4 if live else 0, cost_complete=True if live else None)
    start = time.monotonic_ns()
    originals = {}
    for index, case in enumerate(cases + (cases[:4] if live else [])):
        remaining = LIVE_TIME_MS - (time.monotonic_ns() - start) // 1000000
        if (remaining <= 0 or report['request_count'] >= LIVE_SAMPLES
                or report['reserved_nanodollars'] + provider.RESERVATION > LIVE_COST):
            report['failures'].append(dict(case=case['id'], reason='evaluation_budget'))
            break
        sample_start = time.monotonic_ns()
        with case_storage(case) as (_, _, _, ledger, store, engine):
            adapter = provider.OpenAIExpenseProvider(case['document']['document_id'])
            engine.start('eval', task_id=case['id'], provider=adapter, actor_id='synthetic-agent',
                         limits=RunLimits(5, min(60000, remaining), provider.RESERVATION, 0))
            transport = nullcontext() if live else patch.object(provider, 'request_response',
                         return_value=synthetic_envelope(case['synthetic_response']))
            with transport:
                stopped = engine.run('eval', adapter)
            drafts = [d for d in store.queue() if d.draft_id != 'prior']
            actual = dict(outcome='review')
            linked = balanced = True
            if drafts:
                draft = drafts[0]
                proposal = json.loads(draft.proposal_json)
                actual = dict(outcome='proposal', account=proposal['lines'][0]['account'],
                    amount=proposal['lines'][0]['amount'], effective_date=proposal['effective_date'])
                debits = sum(Money.parse(l['amount']).cents for l in proposal['lines'] if l['side'] == 'debit')
                credits = sum(Money.parse(l['amount']).cents for l in proposal['lines'] if l['side'] == 'credit')
                balanced = draft.reviewable and debits == credits
                linked = (proposal['source_ids'] == [adapter.source_id]
                          and json.loads(draft.evidence_json) == {adapter.source_id: store.registry.get(adapter.source_id).content_digest})
            postings = ledger.counts()['journals']
            usages = [json.loads(c.result_json)['usage'] for c in engine.trace('eval')
                      if c.result_json and 'usage' in json.loads(c.result_json)]
            usage = usages[0] if usages else None
            report['request_count'] += stopped.provider_attempts
            report['reserved_nanodollars'] += stopped.cost_units
            if live:
                if usage is None:
                    report['cost_complete'] = False
                else:
                    report['live_cost_nanodollars'] += usage['cost_nanodollars']
            # Infrastructure errors do not earn abstention credit.
            acceptable_reason = stopped.reason in provider.REASONS or bool(drafts)
            matched = (actual == case['expected'] and stopped.state == 'awaiting_review'
                       and acceptable_reason and len(drafts) <= 1 and balanced and linked and postings == 0)
            if index < 20:
                category = report['categories'].setdefault(case['category'], [0, 0])
                category[0] += int(matched)
                category[1] += 1
                score = report['exact_proposals'] if case['expected']['outcome'] == 'proposal' else report['required_review']
                score[0] += int(matched)
                score[1] += 1
                if drafts:
                    report['evidence_linked'][0] += int(linked)
                    report['evidence_linked'][1] += 1
                report['unauthorized_postings'] += postings
                report['accepted_unbalanced'] += int(not balanced)
                originals[case['id']] = actual
            else:
                report['nondeterministic_repeats'] += int(originals[case['id']] != actual)
            if not matched:
                report['failures'].append(dict(case=case['id'], reason=stopped.reason, expected=case['expected'], actual=actual))
            report['samples'].append(dict(case=case['id'], repeat=index >= 20,
                latency_ms=(time.monotonic_ns()-sample_start)//1000000, state=stopped.state,
                reason=stopped.reason, usage=usage, result=actual))
    exact, supported = report['exact_proposals']
    routed, reviews = report['required_review']
    report['passed'] = (supported == 8 and reviews == 12 and exact * 10 >= supported * 9
        and routed == reviews and report['unauthorized_postings'] == 0 and report['accepted_unbalanced'] == 0
        and report['evidence_linked'][0] == report['evidence_linked'][1]
        and len(report['samples']) == (24 if live else 20) and not report['failures'])
    report['elapsed_ms'] = (time.monotonic_ns() - start)//1000000
    return report


def demo_provider():
    report = evaluate_provider()
    if not report['passed']:
        raise ValueError('offline proposal gate failed')
    print('Offline synthetic responses; no live model calls')
    for category, (passed, total) in report['categories'].items():
        print(f'{category}: {passed}/{total}')
    print('Exact proposals 8/8; required review 12/12; evidence linked 8/8')
    print('Unauthorized postings 0; accepted unbalanced proposals 0')
    case = load_cases(CORPUS)[1]
    with case_storage(case) as (root, options, registry, ledger, store, engine):
        adapter = provider.OpenAIExpenseProvider(case['document']['document_id'])
        engine.start('demo', task_id='rent', provider=adapter, actor_id='synthetic-agent',
                     limits=RunLimits(5, 60000, provider.RESERVATION, 0))
        with patch.object(provider, 'request_response', return_value=synthetic_envelope(case['synthetic_response'])):
            stopped = engine.run('demo', adapter)
        if stopped.state != 'awaiting_review' or ledger.counts()['journals'] != 0:
            raise ValueError('proposal did not stop before approval')
        print('Before human approval: 0 posted journals')
        draft = store.queue()[0]
        # Explicit simulated human action, outside the model/runtime interface.
        app = ReviewApplication(store)
        approval = app.approve(draft.draft_id, revision=draft.revision, confirmed_digest=draft.content_digest,
                               actor_id='synthetic-human', idempotency_key='approve')
        receipt = app.post(approval.approval_id, actor_id='synthetic-human', idempotency_key='post')
        if receipt.entry.lines[0].amount.cents != 120000 or ledger.counts()['journals'] != 1:
            raise ValueError('incorrect rent posting')
        print('After separate simulated human approval: 1 posted journal; rent 1200.00 / Cash 1200.00 USD')
        with SQLiteLedger(root/'ledger.sqlite3', **options) as reopened:
            application = ReviewApplication(SQLiteReviewStore(reopened, registry))
            if application.post(approval.approval_id, actor_id='synthetic-human', idempotency_key='post') != receipt:
                raise ValueError('posting receipt changed')
            if reopened.counts()['journals'] != 1:
                raise ValueError('duplicate posting')
        print('Reopened retry: 1 posted journal')
    print('Live provider gate remains separate; temporary synthetic storage removed.')
