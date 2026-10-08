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
from accounting_harness.payables import PayablesService, payables_report
from accounting_harness.receivables import ReceivablesService, receivables_report
from accounting_harness.advances import AdvancesService, advances_report
from accounting_harness.reconciliation import ReconciliationService
from accounting_harness.prepaid import PrepaidService, prepaid_report
from accounting_harness.revenue_accrual import RevenueAccrualService, accrual_report
from accounting_harness.expense_accrual import ExpenseAccrualService, expense_accrual_report
from accounting_harness.bank import BankStatementService
from accounting_harness.bank_fees import BankFeeService, bank_evidence, fee_operation, require_available
from accounting_harness.domain.money import Money
from accounting_harness.operations import cash_expense_proposal, earned_cash_proposal


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
                # The accrual service owns ledger/review/approval/accrual schema setup
                # in one transaction, before generic review handles can commit a migration.
                from accounting_harness.project_dimensions import ProjectDimensionsService
                from accounting_harness.project_time import ProjectTimeService
                from accounting_harness.project_cost import ProjectCostService
                with ledger._transaction(write=True):
                    RevenueAccrualService(ledger, registry)
                    ProjectDimensionsService(ledger)
                    ProjectTimeService(ledger)
                    ProjectCostService(ledger)
                store = SQLiteReviewStore(ledger, registry)
                app = ReviewApplication(store)
                with SQLiteRunEngine(self.root / 'runs.sqlite3', store) as engine:
                    yield registry, ledger, store, app, engine

    @staticmethod
    def _account_activation(ledger):
        receipt = ledger.bank_fee_account_activation()
        return dict(asdict(receipt), recorded_at=receipt.recorded_at.isoformat()) if receipt else None

    def import_bank_statement(self, data):
        with self.storage() as (_, ledger, _, _, _):
            return BankStatementService(ledger).import_statement(data, actor_id='local-operator')

    def list_bank_statements(self):
        with self.storage() as (_, ledger, _, _, _):
            return dict(statements=BankStatementService(ledger).list_statements())

    def bank_statement_detail(self, bank_account_id, statement_id):
        with self.storage() as (_, ledger, _, _, _):
            return BankStatementService(ledger).detail(bank_account_id, statement_id)

    def bank_matches(self, bank_account_id):
        with self.storage() as (_, ledger, _, _, _):
            return BankStatementService(ledger).matching(bank_account_id)

    def bank_reconciliation(self, bank_account_id, statement_id):
        with self.storage() as (_, ledger, _, _, _):
            return ReconciliationService(ledger).view(bank_account_id, statement_id)

    def financial_statements(self, as_of):
        from accounting_harness.financial_reports import capture_financials, financial_statements
        with self.storage() as (_, ledger, _, _, _):
            capture = capture_financials(ledger, as_of)
        return financial_statements(capture)

    def cash_flow(self, as_of):
        from accounting_harness.cash_flow import capture_cash_flow, cash_flow_statement
        with self.storage() as (_, ledger, _, _, _):
            capture = capture_cash_flow(ledger, as_of)
        return cash_flow_statement(capture)

    def report_package(self, as_of):
        from accounting_harness.cash_flow import capture_cash_flow
        from accounting_harness.report_export import report_package
        with self.storage() as (_, ledger, _, _, _):
            capture = capture_cash_flow(ledger, as_of)
        return report_package(capture)

    def project_dimensions(self, as_of):
        from accounting_harness.project_dimensions import capture_dimensions, project_report
        with self.storage() as (_, ledger, _, _, _):
            capture = capture_dimensions(ledger, as_of)
        return project_report(capture)

    def project_time(self, as_of):
        from accounting_harness.project_time import capture_time, time_report
        with self.storage() as (_, ledger, _, _, _):
            capture = capture_time(ledger, as_of)
        return time_report(capture)

    def project_cost_inputs(self, as_of):
        from accounting_harness.project_cost import ProjectCostService
        with self.storage() as (_, ledger, _, _, _):
            return ProjectCostService(ledger).inputs(as_of)

    def project_cost(self, version_id):
        from accounting_harness.project_cost import ProjectCostService
        with self.storage() as (_, ledger, _, _, _):
            return ProjectCostService(ledger).get(version_id)

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
            return self._enroll_registered(registry, ledger, result)

    def register_operation_source(self, data):
        fields(data, dict(document=dict))
        document = data['document']
        if document.get('schema_version') != 2:
            raise ValueError('operation evidence requires schema v2')
        for field in ('document_date', 'incurred_date', 'completion_date'):
            if field in document and not '2026-01-01' <= accounting_date(document[field]).isoformat() <= '2026-01-31':
                raise ValueError('operation evidence dates must be within January 2026')
        with self.storage() as (registry, ledger, _, _, _):
            result = registry.register(document, actor_id='local-operator')
            return self._enroll_registered(registry, ledger, result)

    @staticmethod
    def _enroll_registered(registry, ledger, result):
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

    @staticmethod
    def _draft_services(store, app, draft_id):
        row = store.db.execute('''SELECT policy_version FROM draft_revisions
            WHERE draft_id=? ORDER BY revision DESC LIMIT 1''', (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        if row[0] == 'revenue-accrual-v1':
            accrual = RevenueAccrualService(store.ledger, store.registry)
            return accrual.store, accrual.app
        if row[0] == 'expense-accrual-v1':
            accrual = ExpenseAccrualService(store.ledger, store.registry)
            return accrual.store, accrual.app
        if row[0] == 'prepaid-consumption-v1':
            prepaid = PrepaidService(store.ledger, store.registry)
            return prepaid.store, prepaid.app
        if row[0] == 'bank-fee-v1':
            fees = BankFeeService(store.ledger, store.registry)
            return fees.store, fees.app
        if row[0] == 'review-v1':
            return store, app
        if row[0] == 'advance-v1':
            advances = AdvancesService(store.ledger, store.registry)
            return advances.store, advances.app
        if row[0] == 'advance-earning-v1':
            AdvancesService(store.ledger, store.registry)
            earnings = SQLiteReviewStore(store.ledger, store.registry, policy_version='advance-earning-v1')
            return earnings, ReviewApplication(earnings)
        if row[0] == 'invoice-v1':
            receivables = ReceivablesService(store.ledger, store.registry)
            return receivables.store, receivables.app
        if row[0] == 'invoice-collection-v1':
            ReceivablesService(store.ledger, store.registry)
            collections = SQLiteReviewStore(store.ledger, store.registry, policy_version='invoice-collection-v1')
            return collections, ReviewApplication(collections)
        if row[0] == 'bill-v1':
            payables = PayablesService(store.ledger, store.registry)
            return payables.store, payables.app
        if row[0] == 'bill-payment-v1':
            PayablesService(store.ledger, store.registry)
            payments = SQLiteReviewStore(store.ledger, store.registry, policy_version='bill-payment-v1')
            return payments, ReviewApplication(payments)
        if row[0] != 'cash-v1':
            raise ValueError('unknown stored draft policy')
        cash = SQLiteReviewStore(store.ledger, store.registry, policy_version='cash-v1')
        return cash, ReviewApplication(cash)

    def prepare_expense_accrual(self, data):
        fields(data, dict(incurrence_source_id=str, basis_source_id=str, expected_revision=int))
        with self.storage() as (registry, ledger, _, _, _):
            service = ExpenseAccrualService(ledger, registry)
            draft = service.propose(**data, actor_id='expense-accrual-template',
                idempotency_key='web-expense-accrual:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_revenue_accrual(self, data):
        fields(data, dict(completion_source_id=str, basis_source_id=str, expected_revision=int))
        with self.storage() as (registry, ledger, _, _, _):
            service = RevenueAccrualService(ledger, registry)
            draft = service.propose(**data, actor_id='local-operator',
                idempotency_key='web-revenue-accrual:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_prepaid(self, data):
        fields(data, dict(coverage_source_id=str, allocation_month=str, expected_revision=int))
        with self.storage() as (registry, ledger, _, _, _):
            draft = PrepaidService(ledger, registry).propose(**data, actor_id='local-operator',
                idempotency_key='web-prepaid:' + digest(data))
            if isinstance(draft, dict):
                return draft
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_bank_fee(self, data):
        fields(data, dict(bank_account_id=str, transaction_id=str, classification=str, reason=str, expected_revision=int))
        with self.storage() as (registry, ledger, _, _, _):
            service = BankFeeService(ledger, registry)
            document = bank_evidence(ledger, data['bank_account_id'], data['transaction_id'])
            fee_operation(document, data['classification'], data['reason'])
            key = 'web-bank-fee:' + digest(data)
            # Exact saved retries precede fresh matched/candidate checks, including after posting.
            retry = service.db.execute("SELECT 1 FROM review_requests WHERE operation='save' AND key=?", (key,)).fetchone()
            if not retry:
                if ledger.bank_fee_account_activation() is None:
                    raise ValueError('activate Bank Fees Expense first')
                require_available(ledger, document)
            result = registry.register(document, actor_id='local-operator')
            self._enroll_registered(registry, ledger, result)
            draft = service.propose(document, classification=data['classification'], reason=data['reason'],
                expected_revision=data['expected_revision'], actor_id='local-operator', idempotency_key=key)
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_cash(self, data):
        fields(data, dict(operation=str, cash_source_id=str, recognition_source_id=str))
        templates = {'cash_expense': cash_expense_proposal, 'earned_cash': earned_cash_proposal}
        if data['operation'] not in templates:
            raise ValueError('unsupported cash operation')
        identity = digest([self.catalog.entity_id, 'cash-v1', data['operation'],
                           data['cash_source_id'], data['recognition_source_id']])
        with self.storage() as (registry, ledger, _, _, _):
            proposal, evidence = templates[data['operation']](registry, entry_id='cash-' + identity,
                cash_source_id=data['cash_source_id'], recognition_source_id=data['recognition_source_id'])
            store = SQLiteReviewStore(ledger, registry, policy_version='cash-v1')
            if store.validate(proposal, evidence):
                raise ValueError('cash evidence must be valid and enrolled before preparation')
            draft = store.save('cash-' + identity, proposal, evidence=evidence, expected_revision=0,
                actor_id='cash-template', idempotency_key='cash-' + identity,
                reason='Deterministic synthetic cash proposal; human review required', require_unused_evidence=True)
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_advance(self, data):
        fields(data, dict(prepayment_source_id=str, cash_source_id=str))
        with self.storage() as (registry, ledger, _, _, _):
            service = AdvancesService(ledger, registry)
            draft = service.propose_advance(**data, expected_revision=0, actor_id='advance-template',
                idempotency_key='web-advance:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_invoice(self, data):
        fields(data, dict(invoice_source_id=str, completion_source_id=str))
        with self.storage() as (registry, ledger, _, _, _):
            service = ReceivablesService(ledger, registry)
            draft = service.propose_invoice(**data, expected_revision=0, actor_id='invoice-template',
                idempotency_key='web-invoice:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_bill(self, data):
        fields(data, dict(bill_source_id=str, incurrence_source_id=str))
        with self.storage() as (registry, ledger, _, _, _):
            service = PayablesService(ledger, registry)
            draft = service.propose_bill(**data, expected_revision=0, actor_id='bill-template',
                idempotency_key='web-bill:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_bill_payment(self, data):
        fields(data, dict(bill_id=str, cash_source_id=str))
        with self.storage() as (registry, ledger, _, _, _):
            service = PayablesService(ledger, registry)
            draft = service.propose_payment(**data, expected_revision=0, actor_id='bill-payment-template',
                idempotency_key='web-bill-payment:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_collection(self, data):
        fields(data, dict(invoice_id=str, cash_source_id=str))
        with self.storage() as (registry, ledger, _, _, _):
            service = ReceivablesService(ledger, registry)
            draft = service.propose_collection(**data, expected_revision=0, actor_id='invoice-collection-template',
                idempotency_key='web-invoice-collection:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def prepare_earning(self, data):
        fields(data, dict(advance_id=str, completion_source_id=str))
        with self.storage() as (registry, ledger, _, _, _):
            service = AdvancesService(ledger, registry)
            draft = service.propose_earning(**data, expected_revision=0, actor_id='advance-earning-template',
                idempotency_key='web-advance-earning:' + digest(data))
            return dict(draft_id=draft.draft_id, revision=draft.revision, content_digest=draft.content_digest,
                        policy_version=draft.policy_version, state=draft.state)

    def state(self):
        with self.storage() as (registry, ledger, store, app, engine):
            sources = self._source_list(registry, ledger)
            drafts = []
            for (draft_id,) in store.db.execute('SELECT DISTINCT draft_id FROM draft_revisions ORDER BY draft_id'):
                draft_store, draft_app = self._draft_services(store, app, draft_id)
                revision = draft_store.get(draft_id)
                item = dict(draft_id=draft_id, revision=revision.revision,
                    policy_version=revision.policy_version,
                    content_digest=revision.content_digest, status=draft_app.status(draft_id),
                    reviewable=revision.reviewable, proposal=json.loads(revision.proposal_json),
                    evidence=json.loads(revision.evidence_json), reason=revision.reason,
                    operation_intent=json.loads(revision.operation_intent_json) if revision.operation_intent_json else None,
                    operation_intent_json=revision.operation_intent_json,
                    findings=[asdict(f) for f in revision.findings + revision.current_findings],
                    history=[dict(revision=r.revision, actor=r.actor_id, reason=r.reason,
                                  recorded_at=r.recorded_at) for r in draft_store.history(draft_id)])
                if item['status'] == 'posted':
                    trace = draft_app.trace(draft_id)
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
            accruals = accrual_report(RevenueAccrualService(ledger, registry).combined_snapshot(), as_of='2026-01-31')
            expense_accruals, revenue_accruals = accruals['expenses'], accruals['revenue']
            prepaid = prepaid_report(PrepaidService(ledger, registry).snapshot(), as_of='2026-01-31')
            advances = advances_report(AdvancesService(ledger, registry).snapshot(), as_of='2026-01-31')
            for item in [advances, *advances['customers'], *advances['advances'], *advances['earnings']]:
                for field in ('principal', 'earned', 'remaining', 'unearned_control', 'subledger', 'unassigned_control'):
                    if field + '_cents' in item:
                        cents = item[field + '_cents']
                        item[field + '_amount'] = ('-' if cents < 0 else '') + str(Money(abs(cents)))
            for advance in [*advances['advances'], *advances['earnings']]:
                advance['trace_json'] = json.dumps(advance, indent=2, sort_keys=True)
            receivables = receivables_report(ReceivablesService(ledger, registry).snapshot(), as_of='2026-01-31')
            for field in ('ar_control', 'subledger', 'unassigned_control'):
                cents = receivables[field + '_cents']
                receivables[field + '_amount'] = ('-' if cents < 0 else '') + str(Money(abs(cents)))
            for invoice in receivables['invoices']:
                for field in ('principal', 'paid', 'outstanding'):
                    invoice[field + '_amount'] = str(Money(invoice[field + '_cents']))
                # JSON numbers can exceed JavaScript's exact range; render this text verbatim.
                invoice['trace_json'] = json.dumps(invoice, indent=2, sort_keys=True)
            for collection in receivables['collections']:
                collection['allocated_amount'] = str(Money(collection['allocated_cents']))
                collection['trace_json'] = json.dumps(collection, indent=2, sort_keys=True)
            for item in [receivables, *receivables['customers']]:
                item['aging_amounts'] = {bucket: str(Money(cents)) for bucket, cents in item['aging_cents'].items()}
            for customer in receivables['customers']:
                customer['outstanding_amount'] = str(Money(customer['outstanding_cents']))
            payables = payables_report(PayablesService(ledger, registry).snapshot(), as_of='2026-01-31')
            for field in ('ap_control', 'subledger', 'unassigned_control'):
                cents = payables[field + '_cents']
                payables[field + '_amount'] = ('-' if cents < 0 else '') + str(Money(abs(cents)))
            for bill in payables['bills']:
                for field in ('principal', 'paid', 'outstanding'):
                    bill[field + '_amount'] = str(Money(bill[field + '_cents']))
                # JSON numbers can exceed JavaScript's exact range; render this text verbatim.
                bill['trace_json'] = json.dumps(bill, indent=2, sort_keys=True)
            for payment in payables['payments']:
                payment['allocated_amount'] = str(Money(payment['allocated_cents']))
                payment['trace_json'] = json.dumps(payment, indent=2, sort_keys=True)
            report = ledger.trial_balance('2026-01-31')
            snapshot = [ledger._entry_payload(e) for e in report.snapshot.entries]
            journals = [dict(payload, lines=[dict(account=line.account, side=line.side,
                        amount=str(line.amount)) for line in entry.lines])
                        for payload, entry in zip(snapshot, report.snapshot.entries)]
            catalog = asdict(report.snapshot.catalog)
            report_identity = [ledger._context, snapshot]
            if report.snapshot.catalog != ledger._empty.catalog:
                report_identity.append(catalog)
            return dict(entity_id=self.catalog.entity_id, period='January 2026', currency='USD',
                providers=self.providers(), sources=sources, drafts=drafts, runs=runs,
                period_close=(json.loads(row[0]) if (row := ledger._connection.execute('SELECT result_json FROM period_closes').fetchone()) else None),
                bank_fee_account_activation=self._account_activation(ledger),
                bank_statements=BankStatementService(ledger).list_statements(),
                journal_count=len(snapshot), journals=journals, payables=payables, receivables=receivables, advances=advances, prepaid=prepaid, expense_accruals=expense_accruals, revenue_accruals=revenue_accruals, accruals=accruals,
                trial_balance=dict(as_of=report.as_of.isoformat(), policy=report.policy,
                    snapshot_digest=digest(report_identity), catalog=catalog,
                    included_entry_ids=list(report.included_entry_ids),
                    total_debits=str(report.total_debits), total_credits=str(report.total_credits),
                    rows=[dict(account=r.account, name=r.name, debit=str(r.debit), credit=str(r.credit))
                          for r in report.rows]))

    def action(self, action, data):
        if action == 'project-cost':
            from accounting_harness.project_cost import ProjectCostService
            with self.storage() as (_, ledger, _, _, _):
                return ProjectCostService(ledger).save(data, actor_id='local-operator')
        if action in ('project-time', 'project-time-void'):
            from accounting_harness.project_time import ProjectTimeService
            with self.storage() as (_, ledger, _, _, _):
                service = ProjectTimeService(ledger)
                method = service.record if action == 'project-time' else service.void
                return method(data, actor_id='local-operator')
        if action in ('projects', 'project-assignments'):
            from accounting_harness.project_dimensions import ProjectDimensionsService
            with self.storage() as (_, ledger, _, _, _):
                service = ProjectDimensionsService(ledger)
                method = service.create_project if action == 'projects' else service.assign
                return method(data, actor_id='local-operator')
        if action in ('close-preview', 'close-confirm'):
            from accounting_harness.closing import CloseService
            with self.storage() as (registry, ledger, _, _, _):
                service = CloseService(ledger, registry)
                return service.preview(data) if action == 'close-preview' else service.confirm(data, actor_id='local-operator')
        if action in ('bank-timing', 'bank-reconcile'):
            with self.storage() as (_, ledger, _, _, _):
                return ReconciliationService(ledger).action(action.removeprefix('bank-'), data, actor_id='local-operator')
        if action == 'revenue-accrual-proposals':
            return self.prepare_revenue_accrual(data)
        if action == 'expense-accrual-proposals':
            return self.prepare_expense_accrual(data)
        if action == 'prepaid-proposals':
            return self.prepare_prepaid(data)
        if action == 'bank-fee-proposals':
            return self.prepare_bank_fee(data)
        if action == 'bank-fee-account':
            if data != {}:
                raise ValueError('fixed bank-fee account setup accepts no fields')
            with self.storage() as (_, ledger, _, _, _):
                ledger.ensure_bank_fee_account(actor_id='local-operator')
                return self._account_activation(ledger)
        if action in ('bank-match', 'bank-unmatch'):
            with self.storage() as (_, ledger, _, _, _):
                return BankStatementService(ledger).matching_action(action.removeprefix('bank-'), data, actor_id='local-operator')
        if action == 'bank-statements':
            return self.import_bank_statement(data)
        if action == 'sources':
            return self.register_source(data)
        if action == 'operation-sources':
            return self.register_operation_source(data)
        if action == 'advance-earning-proposals':
            return self.prepare_earning(data)
        if action == 'advance-proposals':
            return self.prepare_advance(data)
        if action == 'invoice-proposals':
            return self.prepare_invoice(data)
        if action == 'invoice-collection-proposals':
            return self.prepare_collection(data)
        if action == 'bill-proposals':
            return self.prepare_bill(data)
        if action == 'bill-payment-proposals':
            return self.prepare_bill_payment(data)
        if action == 'cash-proposals':
            return self.prepare_cash(data)
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
                source = registry.get(data['source_id'])
                if json.loads(source.canonical_content)['schema_version'] != 1:
                    raise ValueError('provider runs require original schema v1 receipt evidence')
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
            store, app = self._draft_services(store, app, data['draft_id'])
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


def demo_cash():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-cash-') as directory:
        workspace = Workspace(directory)
        requests = []
        for event, amount, expense in [('rent', '1200.00', True), ('service', '800.00', False)]:
            common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
                currency='USD', document_date='2026-01-05', amount=amount, event_id=event,
                counterparty='Fictional counterparty', counterparty_id=event + '-party',
                description='Synthetic assertion: ' + event)
            cash = dict(common, document_id=event + '-cash', kind='cash_movement',
                        direction='out' if expense else 'in',
                        purpose='incurred_expense' if expense else 'earned_service')
            fact = dict(common, document_id=event + '-fact',
                        kind='incurred_expense' if expense else 'service_completion')
            fact.update(dict(incurred_date='2026-01-05', expense_account='5000') if expense else
                        dict(completion_date='2026-01-05'))
            for document in (cash, fact):
                workspace.action('operation-sources', dict(document=document))
            request = dict(operation='cash_expense' if expense else 'earned_cash',
                           cash_source_id=cash['document_id'], recognition_source_id=fact['document_id'])
            first = workspace.action('cash-proposals', request)
            assert workspace.action('cash-proposals', request) == first
            requests.append(request)
        state = workspace.state()
        assert len(state['drafts']) == 2 and state['journal_count'] == 0
        print('Pending drafts: 2; posted journals: 0; policy cash-v1.')
        confirmations = []
        for draft in state['drafts']:
            confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],
                                confirmed_digest=draft['content_digest'])
            confirmations.append(confirmation)
            workspace.action('approve-post', confirmation)  # Separate simulated human decision.
        reopened = Workspace(directory)
        for request, confirmation in zip(requests, confirmations):
            reopened.action('cash-proposals', request)
            reopened.action('approve-post', confirmation)
        state = reopened.state()
        rows = {r['account']: (r['debit'], r['credit']) for r in state['trial_balance']['rows']}
        assert rows['1000'] == ('0.00', '400.00')
        assert rows['5000'] == ('1200.00', '0.00')
        assert rows['4000'] == ('0.00', '800.00')
        assert state['trial_balance']['total_debits'] == state['trial_balance']['total_credits'] == '1200.00'
        assert state['journal_count'] == 2
        print('Cash credit 400.00; Rent debit 1200.00; Revenue credit 800.00 USD.')
        print('Trial balance: 1200.00 / 1200.00 USD; 2 journals after reopen/retry.')
        print('Zero opening cash makes this isolated demonstration negative by 400.00 USD.')
        for draft in state['drafts']:
            approval = draft['audit']['approval']
            binding = json.loads(approval['binding_json'])
            assert binding['policy_version'] == 'cash-v1' and len(binding['evidence']) == 2
            print(f"Audit: revision {draft['revision']}; cash-v1; {approval['actor_id']}; effective {draft['proposal']['effective_date']}")
            for source, evidence_digest in binding['evidence'].items():
                print(f'  {source}: {evidence_digest}')
        print('Separate simulated human approvals; zero model calls.')


def demo_bill():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-bill-') as directory:
        workspace = Workspace(directory)
        common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
            currency='USD', document_date='2026-01-10', amount='300.00', event_id='software-incurred-001',
            counterparty='Fictional software vendor', counterparty_id='vendor-synthetic-1',
            description='Synthetic independent expense evidence')
        bill = dict(common, document_id='source-bill-001', kind='vendor_bill',
                    bill_number='B-001', due_date='2026-02-09')
        incurred = dict(common, document_id='source-incurrence-001', kind='incurred_expense',
                        incurred_date='2026-01-10', expense_account='5100')
        for document in (bill, incurred):
            workspace.action('operation-sources', dict(document=document))
        request = dict(bill_source_id=bill['document_id'], incurrence_source_id=incurred['document_id'])
        first = workspace.action('bill-proposals', request)
        before = workspace.state()
        assert before['journal_count'] == 0 and not before['payables']['bills']
        print('Pending bill: 1; posted journals: 0; vendor bill rows: 0; bill-v1.')
        draft = before['drafts'][0]
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],
                            confirmed_digest=draft['content_digest'])
        posted = workspace.action('approve-post', confirmation)  # Separate simulated human decision.
        reopened = Workspace(directory)
        assert reopened.action('bill-proposals', request) == first
        assert reopened.action('approve-post', confirmation) == posted
        state = reopened.state()
        report = state['payables']
        rows = {r['account']: (r['debit'],r['credit']) for r in state['trial_balance']['rows']}
        assert rows['5100'] == ('300.00','0.00') and rows['2000'] == ('0.00','300.00')
        assert report['subledger_cents'] == report['ap_control_cents'] == 30000
        assert report['unassigned_control_cents'] == 0 and len(report['bills']) == 1
        print('Software expense debit 300.00; AP credit 300.00; outstanding 300.00 USD; residual 0.00.')
        print('Due 2026-02-09; separate bill/incurrence documents: 2; no payments recorded.')
        print('Approval:', posted['approval_id'], '; actor: local-operator; policy: bill-v1')
        for source, evidence_digest in draft['evidence'].items():
            print('Evidence:', source, evidence_digest)
        print('Report:', report['policy'], report['snapshot_digest'])
        print('Reopen and exact retries preserve one journal. Managed bill reversals unavailable; zero model calls.')


def demo_bill_payment():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-bill-payment-') as directory:
        workspace = Workspace(directory)
        common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
            currency='USD', document_date='2026-01-10', amount='300.00', event_id='software-incurred-001',
            counterparty='Fictional software vendor', counterparty_id='vendor-synthetic-1',
            description='Synthetic independent expense evidence')
        for document in (dict(common, document_id='source-bill-001', kind='vendor_bill',
                              bill_number='B-001', due_date='2026-02-09'),
                         dict(common, document_id='source-incurrence-001', kind='incurred_expense',
                              incurred_date='2026-01-10', expense_account='5100')):
            workspace.action('operation-sources', dict(document=document))
        draft = workspace.action('bill-proposals', dict(bill_source_id='source-bill-001',
                                                        incurrence_source_id='source-incurrence-001'))
        workspace.action('approve-post', dict(draft_id=draft['draft_id'], revision=1,
                                             confirmed_digest=draft['content_digest']))
        with workspace.storage() as (registry, ledger, _, _, _):
            captured = PayablesService(ledger, registry).snapshot()
        before = payables_report(captured, as_of='2026-01-31')
        payment = dict(common, document_id='source-payment-001', kind='cash_movement',
            document_date='2026-01-15', amount='100.00', event_id='cash-out-001', direction='out',
            purpose='settlement', description='Fictional recorded outgoing settlement; sends no money')
        workspace.action('operation-sources', dict(document=payment))
        request = dict(bill_id=before['bills'][0]['bill_id'], cash_source_id='source-payment-001')
        first = workspace.action('bill-payment-proposals', request)
        pending = workspace.state()
        assert pending['journal_count'] == 1 and not pending['payables']['payments']
        draft = next(d for d in pending['drafts'] if d['policy_version'] == 'bill-payment-v1')
        confirmation = dict(draft_id=draft['draft_id'], revision=1, confirmed_digest=draft['content_digest'])
        posted = workspace.action('approve-post', confirmation)  # Separate simulated human decision.
        reopened = Workspace(directory)
        assert reopened.action('bill-payment-proposals', request) == first
        assert reopened.action('approve-post', confirmation) == posted
        state = reopened.state()
        report = state['payables']
        rows = {r['account']: (r['debit'], r['credit']) for r in state['trial_balance']['rows']}
        assert rows['5100'] == ('300.00','0.00') and rows['2000'] == ('0.00','200.00')
        assert report['subledger_cents'] == report['ap_control_cents'] == 20000
        assert report['unassigned_control_cents'] == 0 and len(report['payments']) == 1
        assert payables_report(captured, as_of='2026-01-31') == before
        print('Before confirmation: one bill journal, zero payment effects; no money is sent.')
        print('AP debit 100.00; Cash credit 100.00; outstanding 200.00 USD; expense remains 300.00; residual 0.00.')
        print('Approval:', posted['approval_id'], '; actor: local-operator; policy: bill-payment-v1')
        for source, evidence_digest in draft['evidence'].items():
            print('Evidence:', source, evidence_digest)
        print('Operation sources: 3; report:', report['policy'], report['snapshot_digest'])
        print('Captured pre-payment outstanding stays 300.00; exact reopen/retries preserve two journals.')
        print('Managed bill/payment reversals unavailable; zero model calls.')


def demo_invoice():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-invoice-') as directory:
        workspace = Workspace(directory)
        common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
            currency='USD', document_date='2026-01-10', amount='2500.00', event_id='service-completed-001',
            counterparty='Fictional service customer', counterparty_id='customer-synthetic-1',
            description='Synthetic independent service evidence')
        invoice = dict(common, document_id='source-invoice-001', kind='customer_invoice',
                    invoice_number='I-001', due_date='2026-01-25')
        completion = dict(common, document_id='source-completion-001', kind='service_completion',
                        completion_date='2026-01-10')
        for document in (invoice, completion):
            workspace.action('operation-sources', dict(document=document))
        request = dict(invoice_source_id=invoice['document_id'], completion_source_id=completion['document_id'])
        first = workspace.action('invoice-proposals', request)
        before = workspace.state()
        assert before['journal_count'] == 0 and not before['receivables']['invoices']
        print('Pending invoice: 1; posted journals: 0; customer invoice rows: 0; invoice-v1.')
        draft = before['drafts'][0]
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],
                            confirmed_digest=draft['content_digest'])
        posted = workspace.action('approve-post', confirmation)  # Separate simulated human decision.
        reopened = Workspace(directory)
        assert reopened.action('invoice-proposals', request) == first
        assert reopened.action('approve-post', confirmation) == posted
        state = reopened.state()
        report = state['receivables']
        rows = {r['account']: (r['debit'],r['credit']) for r in state['trial_balance']['rows']}
        assert rows['1100'] == ('2500.00','0.00') and rows['4000'] == ('0.00','2500.00')
        assert report['subledger_cents'] == report['ar_control_cents'] == 250000
        assert report['unassigned_control_cents'] == 0 and len(report['invoices']) == 1
        print('AR debit 2500.00; Revenue credit 2500.00; outstanding 2500.00 USD; residual 0.00.')
        print('Due 2026-01-25; separate invoice/completion documents: 2; no payments recorded.')
        print('Approval:', posted['approval_id'], '; actor: local-operator; policy: invoice-v1')
        for source, evidence_digest in draft['evidence'].items():
            print('Evidence:', source, evidence_digest)
        print('Report:', report['policy'], report['snapshot_digest'])
        print('Reopen and exact retries preserve one journal. Managed invoice reversals unavailable; zero model calls.')


def demo_collection():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-invoice-collection-') as directory:
        workspace = Workspace(directory)
        common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
            currency='USD', document_date='2026-01-10', amount='2500.00', event_id='service-completed-001',
            counterparty='Fictional service customer', counterparty_id='customer-synthetic-1',
            description='Synthetic independent service evidence')
        for document in (dict(common, document_id='source-invoice-001', kind='customer_invoice',
                              invoice_number='I-001', due_date='2026-01-25'),
                         dict(common, document_id='source-completion-001', kind='service_completion',
                              completion_date='2026-01-10')):
            workspace.action('operation-sources', dict(document=document))
        draft = workspace.action('invoice-proposals', dict(invoice_source_id='source-invoice-001',
                                                        completion_source_id='source-completion-001'))
        workspace.action('approve-post', dict(draft_id=draft['draft_id'], revision=1,
                                             confirmed_digest=draft['content_digest']))
        with workspace.storage() as (registry, ledger, _, _, _):
            captured = ReceivablesService(ledger, registry).snapshot()
        before = receivables_report(captured, as_of='2026-01-31')
        collection = dict(common, document_id='source-collection-001', kind='cash_movement',
            document_date='2026-01-20', amount='1500.00', event_id='cash-in-001', direction='in',
            purpose='settlement', description='Fictional recorded incoming settlement; sends no money')
        workspace.action('operation-sources', dict(document=collection))
        request = dict(invoice_id=before['invoices'][0]['invoice_id'], cash_source_id='source-collection-001')
        first = workspace.action('invoice-collection-proposals', request)
        pending = workspace.state()
        assert pending['journal_count'] == 1 and not pending['receivables']['collections']
        draft = next(d for d in pending['drafts'] if d['policy_version'] == 'invoice-collection-v1')
        confirmation = dict(draft_id=draft['draft_id'], revision=1, confirmed_digest=draft['content_digest'])
        posted = workspace.action('approve-post', confirmation)  # Separate simulated human decision.
        reopened = Workspace(directory)
        assert reopened.action('invoice-collection-proposals', request) == first
        assert reopened.action('approve-post', confirmation) == posted
        state = reopened.state()
        report = state['receivables']
        rows = {r['account']: (r['debit'], r['credit']) for r in state['trial_balance']['rows']}
        assert rows['4000'] == ('0.00','2500.00') and rows['1100'] == ('1000.00','0.00')
        assert rows['1000'] == ('1500.00','0.00')
        assert report['invoices'][0]['days_past_due'] == 6
        assert report['aging_cents']['days_1_30'] == 100000
        assert report['subledger_cents'] == report['ar_control_cents'] == 100000
        assert report['unassigned_control_cents'] == 0 and len(report['collections']) == 1
        assert receivables_report(captured, as_of='2026-01-31') == before
        print('Before confirmation: one invoice journal, zero collection effects; no money is sent.')
        print('AR credit 1500.00; Cash debit 1500.00; outstanding 1000.00 USD; revenue remains 2500.00; residual 0.00.')
        print('Due 2026-01-25; as of 2026-01-31: six days past due, 1–30 day aging 1000.00.')
        print('Approval:', posted['approval_id'], '; actor: local-operator; policy: invoice-collection-v1')
        for source, evidence_digest in draft['evidence'].items():
            print('Evidence:', source, evidence_digest)
        print('Operation sources: 3; report:', report['policy'], report['snapshot_digest'])
        print('Captured pre-collection outstanding stays 2500.00; exact reopen/retries preserve two journals.')
        print('Managed invoice/collection reversals unavailable; zero model calls.')


def demo_advance():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-advance-') as directory:
        workspace = Workspace(directory)
        common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
            currency='USD', amount='600.00', document_date='2026-01-22', event_id='advance-cash-1',
            counterparty_id='customer-1', counterparty='Fictional advance customer', description='Synthetic receipt before service')
        for document in (dict(common, document_id='prepayment-source', kind='customer_prepayment', contract_id='contract-1'),
                         dict(common, document_id='cash-source', kind='cash_movement', direction='in', purpose='customer_advance')):
            workspace.action('operation-sources', dict(document=document))
        request = dict(prepayment_source_id='prepayment-source', cash_source_id='cash-source')
        draft = workspace.action('advance-proposals', request)
        before = workspace.state()
        assert before['journal_count'] == 0 and not before['advances']['advances']
        posting = dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])
        posted = workspace.action('approve-post', posting)
        reopened = Workspace(directory)
        assert reopened.action('advance-proposals', request) == draft
        assert reopened.action('approve-post', posting) == posted
        state = reopened.state()
        report = state['advances']
        assert state['journal_count'] == 1
        assert [report[k] for k in ('principal_cents','earned_cents','remaining_cents','unearned_control_cents','unassigned_control_cents')] == [60000,0,60000,60000,0]
        balances = {r['account']: (r['debit'],r['credit']) for r in state['trial_balance']['rows']}
        assert balances['1000'] == ('600.00','0.00') and balances['2100'] == ('0.00','600.00')
        assert balances['4000'] == ('0.00','0.00')
        print('Before approval: zero journals and liability effects; paired prepayment/cash evidence.')
        print('Cash debit 600.00; Unearned Revenue credit 600.00; earned revenue 0.00.')
        print('Principal 600.00; earned 0.00; remaining 600.00; control residual 0.00.')
        print('Approval:', posted['approval_id'], '; actor: local-operator; policy: advance-v1')
        print('Snapshot:', report['snapshot_digest'], '; report:', report['report_digest'])
        print('Restart and exact retries retain one journal; managed advance reversals unavailable; zero model calls.')


def demo_advance_earning():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-advance-earning-') as directory:
        workspace = Workspace(directory)
        common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id,
            currency='USD', amount='600.00', document_date='2026-01-22', event_id='advance-cash-1',
            counterparty_id='customer-1', counterparty='Fictional advance customer', description='Synthetic receipt before service')
        for document in (dict(common, document_id='prepayment-source', kind='customer_prepayment', contract_id='contract-1'),
                         dict(common, document_id='cash-source', kind='cash_movement', direction='in', purpose='customer_advance')):
            workspace.action('operation-sources', dict(document=document))
        draft = workspace.action('advance-proposals', dict(prepayment_source_id='prepayment-source',cash_source_id='cash-source'))
        workspace.action('approve-post', dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        with workspace.storage() as (registry, ledger, _, _, _):
            frozen = AdvancesService(ledger, registry).snapshot()
        before = advances_report(frozen, as_of='2026-01-31')
        completion = dict(common, document_id='completion-source', kind='advance_completion', contract_id='contract-1',
            event_id='completion-1', amount='200.00', document_date='2026-01-31',completion_date='2026-01-31')
        workspace.action('operation-sources', dict(document=completion))
        request = dict(advance_id=before['advances'][0]['advance_id'],completion_source_id='completion-source')
        draft = workspace.action('advance-earning-proposals', request)
        assert workspace.state()['journal_count'] == 1
        posting = dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        posted = workspace.action('approve-post', posting)
        reopened = Workspace(directory)
        assert reopened.action('advance-earning-proposals', request) == draft
        assert reopened.action('approve-post', posting) == posted
        state = reopened.state()
        report = state['advances']
        assert state['journal_count'] == 2
        assert [report[k] for k in ('principal_cents','earned_cents','remaining_cents','unearned_control_cents','unassigned_control_cents')] == [60000,20000,40000,40000,0]
        balances = {r['account']:(r['debit'],r['credit']) for r in state['trial_balance']['rows']}
        assert balances['1000'] == ('600.00','0.00') and balances['2100'] == ('0.00','400.00')
        assert balances['4000'] == ('0.00','200.00')
        assert advances_report(frozen,as_of='2026-01-31') == before
        print('Before confirmation: one receipt journal, zero earning effects; completion alone cannot post.')
        print('Cash unchanged 600.00; Unearned Revenue debit 200.00; Service Revenue credit 200.00.')
        print('Principal 600.00; earned 200.00; remaining 400.00; control residual 0.00.')
        print('Approval:', posted['approval_id'], '; actor: local-operator; policy: advance-earning-v1')
        print('Snapshot:', report['snapshot_digest'], '; report:', report['report_digest'])
        print('Captured pre-earning report remains 600.00; restart/exact retries retain two journals; zero model calls.')


def demo_bank_fee_account():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-bank-fee-account-') as directory:
        workspace = Workspace(directory)
        before = workspace.state()
        original = workspace.action('bank-fee-account', {})
        reopened = Workspace(directory)
        assert reopened.action('bank-fee-account', {}) == original
        after = reopened.state()
        assert before['journal_count'] == after['journal_count'] == 0
        assert before['trial_balance']['total_debits'] == after['trial_balance']['total_debits'] == '0.00'
        assert len(before['trial_balance']['catalog']['accounts']) == 13
        assert len(after['trial_balance']['catalog']['accounts']) == 14
        assert original['account_code'] == '5300'
        assert json.loads(original['canonical_metadata'])['temporary'] is True
        print('Activated 5300 Bank Fees Expense (temporary, debit-normal expense).')
        print('Reopen/retry preserves original activation actor/time; zero additional journals.')
        print('Original 13-account context unchanged; current catalog has 14 accounts; no model calls.')
