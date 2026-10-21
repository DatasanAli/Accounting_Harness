"""The application boundary. Workspace and its stores remain trusted local primitives."""
from contextlib import contextmanager
import json
import re

from accounting_harness.access import AccessDenied

# Exhaustive mappings: adding a Workspace method/action requires an explicit choice.
READ_METHODS = {
    'state': 'read_audit', 'providers': 'read_audit', 'list_sources': 'read_evidence',
    'list_bank_statements': 'read_evidence', 'bank_statement_detail': 'read_evidence',
    'bank_matches': 'read_reports', 'bank_reconciliation': 'read_reports',
    'financial_statements': 'read_reports', 'cash_flow': 'read_reports',
    'report_package': 'read_reports', 'project_dimensions': 'read_reports',
    'project_time': 'read_reports', 'project_cost_inputs': 'read_reports',
    'project_cost': 'read_reports', 'indicator_inputs': 'read_reports',
    'indicators': 'read_reports', 'variance': 'read_reports',
    'external_exports': 'read_reports', 'budget_inputs': 'read_reports', 'budget': 'read_reports', 'external_reads': 'read_reports',
}
PREPARATIONS = {
    'prepare_expense_accrual': 'expense-accrual-proposals',
    'prepare_revenue_accrual': 'revenue-accrual-proposals', 'prepare_prepaid': 'prepaid-proposals',
    'prepare_bank_fee': 'bank-fee-proposals', 'prepare_cash': 'cash-proposals',
    'prepare_nonoperating_cash': 'nonoperating-cash-proposals',
    'prepare_advance': 'advance-proposals', 'prepare_invoice': 'invoice-proposals',
    'prepare_bill': 'bill-proposals', 'prepare_bill_payment': 'bill-payment-proposals',
    'prepare_collection': 'invoice-collection-proposals', 'prepare_earning': 'advance-earning-proposals',
}
METHOD_ACTIONS = dict(PREPARATIONS, import_bank_statement='bank-statements',
                      register_source='sources', register_operation_source='operation-sources')
ACTION_OPERATIONS = {
    **{action: 'prepare_proposal' for action in PREPARATIONS.values()},
    'indicators': 'manage_scenarios', 'budget': 'manage_scenarios',
    'project-cost': 'manage_allocations', 'projects': 'manage_allocations',
    'project-assignments': 'manage_allocations', 'project-time': 'manage_time',
    'project-time-void': 'manage_time', 'close-preview': 'read_reports',
    'close-confirm': 'confirm_close', 'bank-timing': 'record_timing',
    'bank-reconcile': 'confirm_reconciliation', 'bank-fee-account': 'activate_accounts',
    'activate-account': 'activate_accounts', 'bank-match': 'match_bank',
    'bank-unmatch': 'withdraw_bank_match', 'bank-statements': 'import_bank_csv',
    'sources': 'register_evidence', 'operation-sources': 'register_evidence',
    'run': 'start_run', 'cancel': 'cancel_run', 'reject': 'reject_proposal',
    'approve-post': 'approve_post', 'qbo-read': 'stage_external',
    'qbo-export-preview': 'read_reports', 'qbo-export-authorize': 'authorize_export',
    'qbo-export-send': 'authorize_export', 'qbo-export-check': 'authorize_export',
    'agent-proposals': 'start_run', 'agent-cancel': 'cancel_run',
}
# Fixed activations with an audit record, including the three pre-existing controls.
IMPLICIT_ACTIVATIONS = {'expense-accrual-proposals': '2050', 'revenue-accrual-proposals': '1150',
                       'bill-proposals': '2000', 'invoice-proposals': '1100', 'advance-proposals': '2100'}
TRUSTED_ONLY_METHODS = {'storage'}


class AuthenticatedWorkspace:
    def __init__(self, access, *, enable_providers=False, ollama_model=None):
        self.access = access
        self.options = dict(enable_providers=enable_providers, ollama_model=ollama_model)

    def _workspace(self, principal):
        from accounting_harness.workspace import Workspace
        return Workspace(principal.workspace_path, entity_id=principal.entity_id,
                         actor_id=principal.user_id, **self.options)

    @contextmanager
    def _guard(self, token, entity, operation):
        # Same serialization as perform; used by short run transactions only.
        with self.access._transaction() as connection:
            yield self.access._authorize(connection, token, entity, operation)

    @staticmethod
    def _activation(workspace, account, *, activate=False):
        from accounting_harness.workspace import PayablesService, ReceivablesService, AdvancesService
        with workspace.storage() as (registry, ledger, _, _, _):
            if account in ('2050', '1150', '5300'):
                name = {'2050': 'expense_accrual', '1150': 'revenue_accrual', '5300': 'bank_fee'}[account]
                if activate:
                    if account == '5300':
                        ledger.ensure_bank_fee_account(actor_id=workspace.actor_id)
                    else:
                        # Extension and account rows have a deferred circular FK.
                        with ledger._transaction(write=True):
                            getattr(ledger, '_ensure_' + name + '_account')(actor_id=workspace.actor_id)
                return getattr(ledger, name + '_account_activation')() is not None
            services = {'2000': (PayablesService, 'payables_context'),
                        '1100': (ReceivablesService, 'receivables_context'),
                        '2100': (AdvancesService, 'advances_context')}
            if account not in services:
                raise ValueError('unsupported fixed account')
            service, table = services[account]
            service = service(ledger, registry)
            if activate:
                service.ensure_enabled(actor_id=workspace.actor_id)
            return ledger._connection.execute('SELECT 1 FROM ' + table).fetchone() is not None

    def call(self, token, entity_id, method, *args):
        if method in METHOD_ACTIONS:
            method, args = 'action', (METHOD_ACTIONS[method], *args)
        if method == 'action':
            if len(args) != 2 or type(args[0]) is not str:
                raise AccessDenied()
            action, data = args
            operation = ACTION_OPERATIONS.get(action)
            if action == 'bank-timing' and type(data) is dict and data.get('role') == 'withdraw':
                operation = 'withdraw_timing'
        else:
            operation = READ_METHODS.get(method)
        if operation is None:
            raise AccessDenied()
        if method == 'action' and action == 'run':
            return self._run(token, entity_id, data)
        if method == 'action' and action == 'qbo-read':
            return self._qbo_read(token, entity_id, data)
        if method == 'action' and action == 'agent-proposals':
            return self._agent_run(token, entity_id, data)
        def perform(principal):
            workspace = self._workspace(principal)
            if method == 'action':
                if action == 'activate-account':
                    from accounting_harness.workspace import fields
                    fields(data, dict(account=str))
                    return dict(account=data['account'], active=self._activation(workspace, data['account'], activate=True))
                account = IMPLICIT_ACTIVATIONS.get(action)
                if account and not self._activation(workspace, account):
                    if 'activate_accounts' not in principal.capabilities:
                        raise AccessDenied()
                return workspace.action(action, data)
            return getattr(workspace, method)(*args)
        return self.access.perform(token, entity_id, operation, perform)

    def _qbo_read(self, token, entity, data):
        # Authorize briefly; transport calls happen outside the identity lock and
        # every staging commit rechecks current authority (revocation stops writes).
        workspace = self.access.perform(token, entity, 'stage_external', self._workspace)
        workspace.authority_guard = lambda: self._guard(token, entity, 'stage_external')
        return workspace.action('qbo-read', data)

    def _agent_run(self, token, entity, data):
        from accounting_harness.operational_agent import continue_run, start_run
        # Validate and bind the run under the identity lock; provider calls happen
        # outside it, and every run transaction and tool effect rechecks authority.
        def begin(principal):
            workspace = self._workspace(principal)
            return workspace, start_run(workspace, data)
        workspace, adapter = self.access.perform(token, entity, 'start_run', begin)
        workspace.authority_guard = lambda: self._guard(token, entity, 'start_run')
        return continue_run(workspace, data['run_id'], adapter)

    def _run(self, token, entity, data):
        from accounting_harness.workspace import fields
        from accounting_harness.local_providers import OfflineExpenseProvider, OllamaExpenseProvider
        from accounting_harness.provider import OpenAIExpenseProvider
        from accounting_harness.runs import RunLimits
        def start(principal):
            fields(data, dict(source_id=str, provider=str, run_id=str))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', data['run_id']):
                raise ValueError('invalid run ID')
            workspace = self._workspace(principal)
            with workspace.storage() as (registry, ledger, _, _, engine):
                source = registry.get(data['source_id'])
                if json.loads(source.canonical_content)['schema_version'] != 1:
                    raise ValueError('provider runs require original schema v1 receipt evidence')
                if data['source_id'] not in ledger.known_source_ids():
                    raise ValueError('receipt enrollment pending; retry registration first')
                if data['provider'] == 'offline' and data['source_id'] not in workspace.sources:
                    raise ValueError('offline playback supports only the original sample receipts')
                if not any(p['id'] == data['provider'] and p['available'] for p in workspace.providers()):
                    raise ValueError('provider disabled or not configured; offline demo is available')
                adapter = (OfflineExpenseProvider(data['source_id']) if data['provider'] == 'offline' else
                           OllamaExpenseProvider(data['source_id'], workspace.ollama_model) if data['provider'] == 'ollama' else
                           OpenAIExpenseProvider(data['source_id']))
                engine.start(data['run_id'], task_id=data['source_id'], provider=adapter,
                    actor_id='workspace-agent', initiator_id=principal.user_id,
                    limits=RunLimits(5, adapter.timeout_ms + 10000, adapter.identity['reservation'], 0))
            return workspace, adapter
        workspace, adapter = self.access.perform(token, entity, 'start_run', start)
        workspace.authority_guard = lambda: self._guard(token, entity, 'start_run')
        with workspace.storage() as (_, _, _, _, engine):
            result = engine.run(data['run_id'], adapter)
            return dict(run_id=result.run_id, state=result.state, reason=result.reason)


def demo_authenticated_workspace():
    """Temporary synthetic identities, native preparation, separate approval and restart."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from accounting_harness.access import AccessStore, provision_synthetic_workspace
    with TemporaryDirectory(prefix='accounting-authenticated-') as directory:
        root = Path(directory)
        access = AccessStore(root / 'access.sqlite3')
        for entity in ('alpha', 'beta'):
            provision_synthetic_workspace(root / entity, entity)
            access.register_entity(entity, root / entity, reason='Synthetic demonstration')
        tokens, users = {}, {}
        for role in ('preparer', 'reviewer'):
            password = 'Temporary synthetic passphrase ' + role
            users[role] = access.create_user(role, password, reason='Synthetic demonstration')
            access.bootstrap_grant(users[role], 'alpha', role, reason='Synthetic demonstration', retry_key=role)
            tokens[role] = access.login(role, password)
        app = AuthenticatedWorkspace(access)
        common = dict(schema_version=2, synthetic=True, entity_id='alpha', currency='USD',
            document_date='2026-01-05', amount='125.00', event_id='rent', counterparty='Fictional landlord',
            counterparty_id='landlord', description='Synthetic January rent')
        documents = [dict(common, document_id='rent-cash', kind='cash_movement', direction='out', purpose='incurred_expense'),
            dict(common, document_id='rent-fact', kind='incurred_expense', incurred_date='2026-01-05', expense_account='5000')]
        for document in documents:
            result = app.call(tokens['preparer'], 'alpha', 'action', 'operation-sources', dict(document=document))
            assert result['registration']['actor_id'] == users['preparer']
        draft = app.call(tokens['preparer'], 'alpha', 'action', 'cash-proposals',
            dict(operation='cash_expense', cash_source_id='rent-cash', recognition_source_id='rent-fact'))
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])
        for entity, method, args in [('alpha', 'action', ('approve-post', confirmation)), ('beta', 'state', ())]:
            try:
                app.call(tokens['preparer'], entity, method, *args)
            except AccessDenied:
                pass
            else:
                raise AssertionError('unauthorized action succeeded')
        posted = app.call(tokens['reviewer'], 'alpha', 'action', 'approve-post', confirmation)
        reopened = AuthenticatedWorkspace(AccessStore(access.path))
        assert reopened.call(tokens['reviewer'], 'alpha', 'action', 'approve-post', confirmation) == posted
        state = reopened.call(tokens['reviewer'], 'alpha', 'state')
        assert state['journal_count'] == 1 and state['trial_balance']['total_debits'] == '125.00'
        assert state['drafts'][0]['history'][0]['actor'] == users['preparer']
        assert state['drafts'][0]['audit']['approval']['actor_id'] == users['reviewer']
        access.bootstrap_revoke(users['preparer'], 'alpha', reason='Synthetic revocation', retry_key='revoke')
        access.logout(tokens['reviewer'])
        for token in tokens.values():
            try:
                reopened.call(token, 'alpha', 'state')
            except AccessDenied:
                pass
            else:
                raise AssertionError('revoked/logout token accepted')
        print('Authenticated preparer -> separate reviewer -> one 125.00 USD journal; exact user actors.')
        print('Preparer posting and cross-entity reads denied. Restart/retry preserves one journal.')
        print('Revocation and logout deny further access. Temporary synthetic data; zero model calls.')
