"""Persistent fictional workspace over the existing accounting services."""

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.domain.dates import accounting_date
from accounting_harness.local_providers import CORPUS, OfflineExpenseProvider, OllamaExpenseProvider
from accounting_harness.persistence import SQLiteLedger, PersistenceBusy
from accounting_harness.provider import MODEL, OpenAIExpenseProvider
from accounting_harness.review import SQLiteReviewStore, digest
from accounting_harness.runs import RunLimits, SQLiteRunEngine
from accounting_harness.sources import SQLiteSourceRegistry


def fields(data, expected):
    if type(data) is not dict or set(data) != set(expected):
        raise ValueError('request must contain exactly: ' + ', '.join(expected))
    for key, kind in expected.items():
        if type(data[key]) is not kind:
            raise ValueError(f'{key} has the wrong type')
        if kind is str and (not data[key].strip() or len(data[key]) > 1000):
            raise ValueError(f'{key} must be nonempty and at most 1000 characters')


class EnrollmentPending(RuntimeError):
    """Registration succeeded in its file; ledger enrollment can be retried."""
    def __init__(self, registration):
        self.result = dict(state='registered_pending_enrollment', registration=registration,
            error='Receipt registered; enrollment pending. Resubmit the same receipt or restart to retry.')
        super().__init__(self.result['error'])


class Workspace:
    def __init__(self, directory, *, enable_providers=False, ollama_model=None):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.enable_providers = enable_providers
        self.ollama_model = ollama_model
        if ollama_model:
            OllamaExpenseProvider('configuration', ollama_model)
        self.catalog = load_account_catalog(CORPUS.parent / 'service-business-month.json')
        selected = {'rent-standard', 'software-standard', 'ambiguity-1', 'missing-1', 'hostile-1'}
        self.cases = [c for c in json.loads(CORPUS.read_text())['cases'] if c['id'] in selected]
        self.sources = {c['document']['document_id']: c for c in self.cases}
        with self.storage() as (registry, ledger, _, _, _):
            for case in self.cases:
                registry.register(case['document'], actor_id='workspace-fixture-import')
            for source in registry.list_documents():
                if source.document_id not in ledger.known_source_ids():
                    try:
                        ledger.enroll_source(registry, source.document_id, actor_id='workspace-startup-recovery')
                    except (ValueError, TypeError, sqlite3.Error, PersistenceBusy):
                        pass  # Retain registered evidence; state explicitly shows pending enrollment.

    @contextmanager
    def storage(self):
        with SQLiteSourceRegistry(self.root / 'sources.sqlite3', self.catalog.entity_id) as registry:
            with SQLiteLedger(self.root / 'ledger.sqlite3', self.catalog, '2026-01-01', '2026-01-31',
                              known_source_ids=set(self.sources)) as ledger:
                store = SQLiteReviewStore(ledger, registry)
                app = ReviewApplication(store)
                with SQLiteRunEngine(self.root / 'runs.sqlite3', store) as engine:
                    yield registry, ledger, store, app, engine

    def providers(self):
        return [dict(id='offline', name='Offline demo', model='Fixture playback', available=True,
                     note='No model calls. Fixed fictional examples.'),
                dict(id='ollama', name='Ollama · local', model=self.ollama_model or 'Not configured',
                     available=bool(self.enable_providers and self.ollama_model),
                     note='Connection unverified. Local model requests require explicit startup opt-in.'),
                dict(id='openai', name='OpenAI · API', model=MODEL,
                     available=bool(self.enable_providers and os.environ.get('OPENAI_API_KEY')),
                     note='Connection unverified. Billable requests require explicit startup opt-in.')]

    def _source_list(self, registry, ledger):
        known = ledger.known_source_ids()
        return [dict(source_id=s.document_id,
                     sample_id=self.sources.get(s.document_id, {}).get('id'),
                     offline_supported=s.document_id in self.sources,
                     state=('already_known' if s.document_id in self.sources else 'enrolled')
                         if s.document_id in known else 'registered_pending_enrollment',
                     document=json.loads(s.canonical_content), content_digest=s.content_digest,
                     registered_by=s.actor_id, registered_at=s.recorded_at.isoformat())
                for s in registry.list_documents()]

    def list_sources(self):
        with self.storage() as (registry, ledger, _, _, _):
            return dict(sources=self._source_list(registry, ledger))

    def register_source(self, data):
        fields(data, dict(document_id=str, document_date=str, amount=str, counterparty=str, description=str))
        document_date = accounting_date(data['document_date'])
        with self.storage() as (registry, ledger, _, _, _):
            if not ledger._empty.period_start <= document_date <= ledger._empty.period_end:
                raise ValueError('receipt date must be within January 2026')
            result = registry.register(dict(data, entity_id=self.catalog.entity_id, schema_version=1,
                                            synthetic=True, kind='receipt', currency='USD'), actor_id='local-operator')
            registration = dict(document_id=result.record.document_id, repeated=result.repeated,
                content_digest=result.record.content_digest, actor_id=result.record.actor_id,
                recorded_at=result.record.recorded_at.isoformat())
            try:
                enrollment = ledger.enroll_source(registry, result.record.document_id, actor_id='local-operator')
            except (ValueError, TypeError, sqlite3.Error, PersistenceBusy) as error:
                raise EnrollmentPending(registration) from error
            receipt = asdict(enrollment)
            receipt['recorded_at'] = enrollment.recorded_at.isoformat() if enrollment.recorded_at else None
            return dict(state=enrollment.state, registration=registration, enrollment=receipt)

    def state(self):
        with self.storage() as (registry, ledger, store, app, engine):
            sources = self._source_list(registry, ledger)
            drafts = []
            for (draft_id,) in store.db.execute('SELECT DISTINCT draft_id FROM draft_revisions ORDER BY draft_id'):
                revision = store.get(draft_id)
                item = dict(draft_id=draft_id, revision=revision.revision,
                    content_digest=revision.content_digest, status=app.status(draft_id),
                    reviewable=revision.reviewable, proposal=json.loads(revision.proposal_json),
                    evidence=json.loads(revision.evidence_json), reason=revision.reason,
                    findings=[asdict(f) for f in revision.findings + revision.current_findings],
                    history=[dict(revision=r.revision, actor=r.actor_id, reason=r.reason,
                                  recorded_at=r.recorded_at) for r in store.history(draft_id)])
                if item['status'] == 'posted':
                    trace = app.trace(draft_id)
                    item['audit'] = dict(approval=asdict(trace['approval']),
                        journal_id=trace['receipt'].entry.id, recorded_at=trace['receipt'].recorded_at.isoformat())
                drafts.append(item)
            runs = []
            for (run_id,) in engine.db.execute('SELECT run_id FROM runs ORDER BY run_id'):
                checkpoint = engine.get(run_id)
                configuration = json.loads(engine.configuration(run_id))
                runs.append(dict(run_id=run_id, state=checkpoint.state, reason=checkpoint.reason,
                    source_id=configuration['provider']['source_id'], provider=configuration['provider'],
                    attempts=checkpoint.provider_attempts, reserved_nanodollars=checkpoint.cost_units,
                    trace=[dict(sequence=c.sequence, state=c.state, reason=c.reason,
                                recorded_at_ms=c.recorded_at_ms) for c in engine.trace(run_id)]))
            report = ledger.trial_balance('2026-01-31')
            snapshot = [ledger._entry_payload(e) for e in report.snapshot.entries]
            journals = [dict(payload, lines=[dict(account=line.account, side=line.side,
                        amount=str(line.amount)) for line in entry.lines])
                        for payload, entry in zip(snapshot, report.snapshot.entries)]
            return dict(entity_id=self.catalog.entity_id, period='January 2026', currency='USD',
                providers=self.providers(), sources=sources, drafts=drafts, runs=runs,
                journal_count=len(snapshot), journals=journals,
                trial_balance=dict(as_of=report.as_of.isoformat(), policy=report.policy,
                    snapshot_digest=digest([ledger._context, snapshot]),
                    included_entry_ids=list(report.included_entry_ids),
                    total_debits=str(report.total_debits), total_credits=str(report.total_credits),
                    rows=[dict(account=r.account, name=r.name, debit=str(r.debit), credit=str(r.credit))
                          for r in report.rows]))

    def action(self, action, data):
        if action == 'sources':
            return self.register_source(data)
        schemas = {
            'run': dict(source_id=str, provider=str, run_id=str),
            'cancel': dict(run_id=str),
            'reject': dict(draft_id=str, revision=int, reason=str),
            'approve-post': dict(draft_id=str, revision=int, confirmed_digest=str),
        }
        if action not in schemas:
            raise ValueError('unknown action')
        fields(data, schemas[action])
        adapter = None
        if action == 'run':
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', data['run_id']):
                raise ValueError('invalid run ID')
            with self.storage() as (registry, ledger, _, _, _):
                registry.get(data['source_id'])
                if data['source_id'] not in ledger.known_source_ids():
                    raise ValueError('receipt enrollment pending; retry registration first')
            if data['provider'] == 'offline' and data['source_id'] not in self.sources:
                raise ValueError('offline playback supports only the original sample receipts')
            selected = next((p for p in self.providers() if p['id'] == data['provider']), None)
            if not selected or not selected['available']:
                raise ValueError('provider disabled or not configured; offline demo is available')
            if data['provider'] == 'offline':
                adapter = OfflineExpenseProvider(data['source_id'])
            elif data['provider'] == 'ollama':
                adapter = OllamaExpenseProvider(data['source_id'], self.ollama_model)
            else:
                adapter = OpenAIExpenseProvider(data['source_id'])
        with self.storage() as (_, _, store, app, engine):
            if action == 'run':
                engine.start(data['run_id'], task_id=data['source_id'], provider=adapter,
                    actor_id='workspace-agent', limits=RunLimits(5, adapter.timeout_ms + 10000,
                                                               adapter.identity['reservation'], 0))
                result = engine.run(data['run_id'], adapter)
                return dict(run_id=result.run_id, state=result.state, reason=result.reason)
            if action == 'cancel':
                result = engine.cancel(data['run_id'], actor_id='local-operator', reason='Cancelled in workspace')
                return dict(state=result.state)
            if action == 'reject':
                result = store.reject(data['draft_id'], expected_revision=data['revision'],
                    reason=data['reason'], actor_id='local-operator',
                    idempotency_key='web-reject:' + digest(data))
                return dict(state=result.state)
            approval = app.approve(**data, actor_id='local-operator',
                                   idempotency_key='web-approve:' + digest(data))
            receipt = app.post(approval.approval_id, actor_id='local-operator',
                               idempotency_key='web-post:' + approval.approval_id)
            return dict(journal_id=receipt.entry.id, approval_id=approval.approval_id)


def demo_enrollment():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-enrollment-') as directory:
        workspace = Workspace(directory)
        confirmations = []
        for sample, run_id in [('rent-standard', 'rent'), ('software-standard', 'software')]:
            source_id = next(s for s, c in workspace.sources.items() if c['id'] == sample)
            workspace.action('run', dict(source_id=source_id, provider='offline', run_id=run_id))
            draft = next(d for d in workspace.state()['drafts'] if source_id in d['evidence'])
            confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],
                                confirmed_digest=draft['content_digest'])
            confirmations.append(confirmation)
        posted = workspace.action('approve-post', confirmations[0])
        with workspace.storage() as (_, ledger, _, app, _):
            approval = app.approve(**confirmations[1], actor_id='local-operator', idempotency_key='demo-approval')
            frozen_context = ledger._context
        before = workspace.state()['trial_balance']
        payload = dict(document_id='fictional-receipt-006', document_date='2026-01-15', amount='125.00',
                       counterparty='Fictional supplies shop', description='Synthetic receipt for human review')
        first = workspace.register_source(payload)
        reopened = Workspace(directory)
        retry = reopened.register_source(payload)
        assert first['enrollment'] == retry['enrollment']
        assert reopened.state()['trial_balance'] == before
        assert reopened.action('approve-post', confirmations[0]) == posted
        with reopened.storage() as (_, ledger, _, app, _):
            assert ledger._context == frozen_context
            assert app.approve(**confirmations[1], actor_id='local-operator', idempotency_key='demo-approval') == approval
            assert ledger.counts()['journals'] == 1
        assert next(s for s in reopened.list_sources()['sources'] if s['source_id'] == payload['document_id'])['state'] == 'enrolled'
        print('Enrolled synthetic receipt 125.00 USD; reopen and retry preserve original enrollment actor/time.')
        print('Original trial balance and posting retry receipt unchanged; prior approval remains bound.')
        print('New evidence available for human review; zero additional journals and zero model calls.')
