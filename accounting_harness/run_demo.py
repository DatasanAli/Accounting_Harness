"""Temporary synthetic run checkpoint/review handoff demonstration."""

from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.review_demo import FIXTURE, rent_example
from accounting_harness.runs import FakeProvider, RunLimits, SQLiteRunEngine
from accounting_harness.sources import SQLiteSourceRegistry


def demo_run():
    document, proposal = rent_example()
    options = dict(catalog=load_account_catalog(FIXTURE), period_start='2026-01-01',
                   period_end='2026-01-31', known_source_ids={'rent'})
    with TemporaryDirectory(prefix='accounting-run-') as directory:
        ledger_path, source_path, run_path = (Path(directory)/name for name in
                                             ('ledger.sqlite3', 'sources.sqlite3', 'runs.sqlite3'))
        with SQLiteSourceRegistry(source_path, document['entity_id']) as registry:
            source = registry.register(document, actor_id='synthetic-importer').record
            evidence = {'rent': source.content_digest}
            entity = dict(entity_id=document['entity_id'])
            calls = [
                dict(tool='read_accounts', arguments=entity),
                dict(tool='get_evidence', arguments=dict(entity, source_id='rent')),
                dict(tool='validate_proposal', arguments=dict(entity, proposal=proposal, evidence=evidence)),
                dict(tool='save_draft', arguments=dict(entity, draft_id='run-rent', proposal=proposal,
                     evidence=evidence, expected_revision=0, idempotency_key='provider-placeholder',
                     reason='Synthetic rent; review exact evidence and classification')),
                dict(tool='request_review', arguments=dict(entity, draft_id='run-rent', revision=1)),
            ]
            provider = FakeProvider(calls)
            with SQLiteLedger(ledger_path, **options) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                before = ledger.snapshot
                with SQLiteRunEngine(run_path, store) as engine:
                    engine.start('rent-run', task_id='rent-task', provider=provider, actor_id='synthetic-agent',
                                 limits=RunLimits(tool_calls=10, elapsed_ms=60000, cost_units=20, retries=2))
                    paused = engine.run('rent-run', provider)
                    if paused.state != 'awaiting_review':
                        raise ValueError('run did not pause for human review')
                    draft = store.get('run-rent')
                    history = engine.trace('rent-run')
                    print(f'Paused: {paused.state}; rent draft revision {draft.revision}')
                    print(f'Budget: {paused.tool_calls}/10 tool calls; {paused.cost_units}/20 simulated cost units')
        # Close and reopen all three files, and reconstruct the same fake provider.
        with SQLiteSourceRegistry(source_path, document['entity_id']) as registry:
            with SQLiteLedger(ledger_path, **options) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                with SQLiteRunEngine(run_path, store) as engine:
                    if engine.trace('rent-run') != history or len(history) != 16:
                        raise ValueError('checkpoint history changed across restart')
                    print('Reopened: 16 unchanged checkpoints')
                    done = engine.resume('rent-run', FakeProvider(calls))
                    if done.state != 'completed' or done.reason != 'review_handoff_acknowledged':
                        raise ValueError('review handoff was not acknowledged safely')
                    if ledger.snapshot != before or store.history('run-rent') != (draft,):
                        raise ValueError('resume changed draft history or ledger')
                    print(f'Resumed: {done.state}; {done.reason}')
                    print('1 unchanged draft revision; 0 posted journals')
                    for checkpoint in engine.trace('rent-run'):
                        print(f'  {checkpoint.sequence:02d}: {checkpoint.state} / {checkpoint.reason}')
    print('Human approval is still required; temporary synthetic storage removed. No model calls.')
