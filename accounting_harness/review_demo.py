"""Temporary, synthetic review examples for the local CLI."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.sources import SQLiteSourceRegistry, load_source_document

FIXTURE = Path(__file__).resolve().parents[1] / 'data/fixtures/service-business-month.json'


def rent_example():
    document = load_source_document(FIXTURE.with_name('source-receipt.json'))
    document.update(document_id='rent', amount='1200.00', description='Synthetic rent receipt')
    proposal = dict(id='rent-journal', entity_id=document['entity_id'], currency='USD',
                    effective_date=document['document_date'], description='Synthetic rent',
                    source_ids=['rent'], lines=[dict(account='5000', side='debit', amount='1200.00'),
                                               dict(account='1000', side='credit', amount='1200.00')])
    return document, proposal


def demo_review():
    document, proposal = rent_example()
    options = dict(catalog=load_account_catalog(FIXTURE), period_start='2026-01-01',
                   period_end='2026-01-31', known_source_ids={'rent'})
    with TemporaryDirectory(prefix='accounting-harness-') as directory:
        with SQLiteSourceRegistry(Path(directory)/'sources.sqlite3', document['entity_id']) as registry:
            source = registry.register(document, actor_id='synthetic-operator').record
            with SQLiteLedger(Path(directory)/'ledger.sqlite3', **options) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                first = store.save('rent-draft', proposal, evidence={'rent': source.content_digest},
                                   expected_revision=0, actor_id='synthetic-proposer',
                                   idempotency_key='create', reason='Propose rent')
                assert first.reviewable
                proposal['lines'][0]['amount'] = '1100.00'
                second = store.save('rent-draft', proposal, evidence={'rent': source.content_digest},
                                    expected_revision=1, actor_id='synthetic-proposer',
                                    idempotency_key='edit', reason='Edit rent amount')
                assert not second.reviewable
            with SQLiteLedger(Path(directory)/'ledger.sqlite3', **options) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                assert store.history('rent-draft') == (first, second)
                print('Reopened: 2 unchanged revisions; original 1200.00, edited debit 1100.00 USD')
                print('Pending findings:', ', '.join(f.code for f in second.findings))
                rejected = store.reject('rent-draft', expected_revision=2, actor_id='synthetic-reviewer',
                                        idempotency_key='reject', reason='Amount disagrees with receipt')
                assert store.queue('rejected') == (rejected,)
                print(f'Queue: {rejected.state}; reason: {rejected.reason}')
                assert ledger.counts()['journals'] == 0
                print('0 posted journals; temporary synthetic storage removed after demo.')


def demo_approval():
    from accounting_harness.approval import ReviewApplication
    document, proposal = rent_example()
    options = dict(catalog=load_account_catalog(FIXTURE), period_start='2026-01-01',
                   period_end='2026-01-31', known_source_ids={'rent'})
    with TemporaryDirectory(prefix='accounting-harness-') as directory:
        path = Path(directory)/'ledger.sqlite3'
        with SQLiteSourceRegistry(Path(directory)/'sources.sqlite3', document['entity_id']) as registry:
            source = registry.register(document, actor_id='synthetic-operator').record
            with SQLiteLedger(path, **options) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                revision = store.save('rent-draft', proposal, evidence={'rent': source.content_digest},
                                      expected_revision=0, actor_id='synthetic-proposer',
                                      idempotency_key='create', reason='Propose rent')
                app = ReviewApplication(store)
                approval = app.approve('rent-draft', revision=1, confirmed_digest=revision.content_digest,
                                       actor_id='synthetic-human', idempotency_key='approve')
                print('Approved revision 1; simulated local human decision bound to exact evidence/policy')
                receipt = app.post(approval.approval_id, actor_id='synthetic-human', idempotency_key='post')
                assert receipt.entry.lines[0].amount.cents == 120000
            with SQLiteLedger(path, **options) as ledger:
                app = ReviewApplication(SQLiteReviewStore(ledger, registry))
                assert app.post(approval.approval_id, actor_id='synthetic-human', idempotency_key='post') == receipt
                assert ledger.counts()['journals'] == 1
                trail = app.trace('rent-draft')
                assert trail['evidence'] == (source,) and trail['receipt'] == receipt
                print('Reopened retry: 1 journal; rent expense debit 1200.00 / Cash credit 1200.00 USD')
                print('Audit: rent -> rent-draft revision 1 -> rent-journal; original evidence and actors retained')
    print('Temporary synthetic storage removed; authenticated roles remain Step 29.')
