"""Offline synthetic release rehearsal. No live calls and no trusted month seeding.

Ordinary accounting goes through the authenticated application, with distinct
preparer/reviewer identities. Older isolated examples retain their explicitly
labelled fixture scope; their successful assertions are not authentication proof.
"""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest.mock import patch

from accounting_harness.access import AccessDenied, AccessStore, provision_synthetic_workspace
from accounting_harness.authenticated import AuthenticatedWorkspace
from accounting_harness.adjusted_month import REFERENCE, DATE_VARIANT, fixture_inputs
from accounting_harness.report_export import export_report_package, read_report_package

ENTITY = 'demo-service-001'
CUTOFF = '2026-01-31'


class Rehearsal:
    """Small synthetic client of the same authority boundary used by HTTP."""
    def __init__(self, directory):
        self.root = Path(directory)
        if self.root.exists():
            raise ValueError('Acceptance rehearsal requires a new directory')
        self.root.mkdir(parents=True, mode=0o700)
        self.access = AccessStore(self.root / 'access.sqlite3')
        self.entity = ENTITY
        self.users, self.tokens, self.credentials = {}, {}, {}
        self.add_entity(ENTITY, 'primary')
        self.add_entity('ungranted', 'secondary')
        for role in ('owner', 'preparer', 'reviewer'):
            password = secrets.token_urlsafe(24)
            self.credentials[role] = dict(username=role, password=password)
            self.users[role] = self.access.create_user(role, password, reason='Synthetic release rehearsal')
            self.access.bootstrap_grant(self.users[role], ENTITY, role,
                reason='Synthetic local provisioning', retry_key=role)
            self.tokens[role] = self.access.login(role, password)
        self.app = AuthenticatedWorkspace(self.access)

    def add_entity(self, entity, directory):
        provision_synthetic_workspace(self.root / directory, entity)
        self.access.register_entity(entity, self.root / directory, reason='Synthetic release rehearsal')

    def read(self, method='state', *args, role='reviewer'):
        return self.app.call(self.tokens[role], self.entity, method, *args)

    def act(self, action, data, role='preparer'):
        return self.app.call(self.tokens[role], self.entity, 'action', action, data)

    def enroll(self, document):
        result = self.act('operation-sources', dict(document=document))
        assert result['registration']['actor_id'] == self.users['preparer']
        return document['document_id']

    def prepare(self, action, data):
        before = self.read()['journals']
        draft = self.act(action, data)
        assert self.read()['journals'] == before, 'Preparation must never post'
        return draft

    @staticmethod
    def confirmation(draft):
        return dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])

    def post(self, draft):
        receipt = self.act('approve-post', self.confirmation(draft), role='reviewer')
        saved = next(d for d in self.read()['drafts'] if d['draft_id'] == draft['draft_id'])
        assert saved['audit']['approval']['actor_id'] == self.users['reviewer']
        return dict(boundary='authenticated_separate_review', preparer=self.users['preparer'],
            reviewer=self.users['reviewer'], journal_delta_before_review=0, **receipt,
            draft_id=draft['draft_id'], revision=draft['revision'], draft_digest=draft['content_digest'],
            sources=saved['evidence'], intent=saved['operation_intent'])


def nonoperating_facts(alias, amount, date, classification, *, entity=ENTITY):
    common = dict(schema_version=2, synthetic=True, entity_id=entity, currency='USD',
        document_date=date, amount=amount, event_id='acceptance:'+alias, counterparty='Fictional owner or insurer',
        counterparty_id='acceptance-party:'+alias, description='Synthetic '+classification)
    return [dict(common, document_id=alias+'-cash', kind='cash_movement',
                 direction='in' if classification == 'owner_contribution' else 'out', purpose=classification),
            dict(common, document_id=alias+'-basis', kind='nonoperating_cash_basis', classification=classification)]


def nonoperating(client, alias, amount, date, classification):
    cash, basis = [client.enroll(d) for d in nonoperating_facts(alias, amount, date, classification, entity=client.entity)]
    data = dict(cash_source_id=cash, basis_source_id=basis, expected_revision=0)
    return client.prepare('nonoperating-cash-proposals', data)


def reference_month(client):
    inputs = fixture_inputs()
    docs = inputs['documents']
    reference = json.loads(REFERENCE.read_text())
    transactions = {t['id']: t for t in reference['transactions']}
    traces = {}
    for account in ('1100', '2000', '2100'):
        client.act('activate-account', dict(account=account), role='owner')

    def source(alias):
        return client.enroll(docs[alias])

    def save(alias, action, **data):
        draft = client.prepare(action, data)
        trace = traces[alias] = client.post(draft)
        assert next(d for d in client.read()['drafts'] if d['draft_id'] == draft['draft_id'])['history'][0]['actor'] == client.users['preparer']
        return trace

    for alias, classification in [('T01', 'owner_contribution'), ('T02', None), ('T03', 'prepaid_insurance'),
            ('T04', None), ('T05', None), ('T06', None), ('T07', None), ('T08', None), ('T09', 'owner_draw')]:
        if classification:
            old = docs[alias]
            draft = nonoperating(client, alias, old['amount'], old['document_date'], classification)
            traces[alias] = client.post(draft)
        elif alias == 'T02':
            save(alias, 'cash-proposals', operation='cash_expense', cash_source_id=source('T02-cash'), recognition_source_id=source('T02-incurrence'))
        elif alias == 'T04':
            save(alias, 'invoice-proposals', invoice_source_id=source('T04-invoice'), completion_source_id=source('T04-completion'))
        elif alias == 'T05':
            save(alias, 'invoice-collection-proposals', invoice_id=traces['T04']['intent']['invoice_id'], cash_source_id=source('T05-cash'))
        elif alias == 'T06':
            save(alias, 'bill-proposals', bill_source_id=source('T06-bill'), incurrence_source_id=source('T06-incurrence'))
        elif alias == 'T07':
            save(alias, 'bill-payment-proposals', bill_id=traces['T06']['intent']['bill_id'], cash_source_id=source('T07-cash'))
        elif alias == 'T08':
            save(alias, 'advance-proposals', prepayment_source_id=source('T08-prepayment'), cash_source_id=source('T08-cash'))
    docs['A01-coverage'].update(original_journal_id=traces['T03']['journal_id'], original_source_id='T03-cash')
    save('A01', 'prepaid-proposals', coverage_source_id=source('A01-coverage'), allocation_month='2026-01', expected_revision=0)
    save('A02', 'advance-earning-proposals', advance_id=traces['T08']['intent']['advance_id'], completion_source_id=source('A02-completion'))
    state = client.read()
    assert state['journal_count'] == 11
    for alias, trace in traces.items():
        journal = next(j for j in state['journals'] if j['id'] == trace['journal_id'])
        saved=next(d for d in state['drafts'] if d['draft_id']==trace['draft_id'])
        assert saved['history'][0]['actor']==client.users['preparer']
        expected = transactions[alias]
        key = lambda line: (line['account'], line['side'], line['amount'])
        assert sorted(map(key, journal['lines'])) == sorted(map(key, expected['lines'])), alias
        assert journal['effective_date'] == ('2026-01-01' if alias == 'T03' else expected['date'])
        assert set(journal['source_ids']) == set(trace['sources'])
    check_trial_balance(state['trial_balance'], reference['expected']['adjusted_trial_balance'])
    controls = {key: state[key]['unassigned_control_cents'] for key in ('payables','receivables','advances','prepaid')}
    assert all(value == 0 for value in controls.values())
    statements, cash = client.read('financial_statements', CUTOFF), client.read('cash_flow', CUTOFF)
    for report in ('income_statement', 'owners_equity', 'balance_sheet'):
        for key, expected in reference['expected'][report].items():
            assert statements[report][key+'_amount'] == expected, (report, key)
    for key, expected in reference['expected']['cash_flows'].items():
        assert cash[key+'_amount'] == expected, key
    assert statements['balance_sheet']['reconciled'] and cash['classification_complete']
    return dict(reference='data/fixtures/service-business-month.json', reference_sha256=inputs['reference_sha256'],
        date_variant=DATE_VARIANT, transactions=traces, journal_count=11, trial_balance=state['trial_balance'],
        statements=statements, cash_flow=cash, control_residual_cents=controls)


def check_trial_balance(actual, expected):
    assert [{k: row[k] for k in ('account','debit','credit')} for row in actual['rows']] == expected['rows']
    assert actual['total_debits'] == expected['total_debits']
    assert actual['total_credits'] == expected['total_credits']


def denied(client, label, operation, denials, error=AccessDenied, contains=None, *, approval_may_persist=False):
    before = client.read()
    try:
        operation()
    except error as exc:
        if contains is not None:
            assert contains.lower() in str(exc).lower(), (label, str(exc))
        denials.append(dict(case=label, exception=type(exc).__name__))
    else:
        raise AssertionError('Forbidden action succeeded: '+label)
    after = client.read()
    for key in ('journals','drafts','payables','receivables','advances','prepaid'):
        if key == 'drafts' and approval_may_persist:
            assert [(d['draft_id'],d['revision'],d['proposal']) for d in before[key]] == [(d['draft_id'],d['revision'],d['proposal']) for d in after[key]]
        else:
            assert before[key] == after[key], (label,key)


def close_month(client, month, denials):
    package = client.read('report_package', CUTOFF)
    frozen = {kind: export_report_package(package, kind) for kind in ('json','zip')}
    for raw in frozen.values():
        assert read_report_package(raw) == package
    pending = nonoperating(client, 'locked-drawing', '1.00', '2026-01-30', 'owner_draw')
    data = dict(period_start='2026-01-01', period_end=CUTOFF, selections=[])
    preview = client.act('close-preview', data, role='reviewer')
    assert preview['can_close']
    confirmation = dict(data, confirmed=True, confirmed_digest=preview['digest'], idempotency_key='acceptance-close')
    receipt = client.act('close-confirm', confirmation, role='reviewer')
    denied(client, 'closed-period-post', lambda: client.act('approve-post', client.confirmation(pending), role='reviewer'),
           denials, ValueError, 'clos', approval_may_persist=True)
    client.app = AuthenticatedWorkspace(AccessStore(client.access.path))
    assert client.act('close-confirm', confirmation, role='reviewer') == receipt
    first = month['transactions']['T01']
    retry = dict(draft_id=first['draft_id'], revision=first['revision'], confirmed_digest=first['draft_digest'])
    assert client.act('approve-post', retry, role='reviewer')['journal_id'] == first['journal_id']
    state = client.read()
    check_trial_balance(state['trial_balance'], json.loads(REFERENCE.read_text())['expected']['post_closing_trial_balance'])
    assert state['journal_count'] == 12
    assert client.read('financial_statements', CUTOFF)['income_statement']['net_income_amount'] == '1100.00'
    assert all(export_report_package(package, kind) == raw for kind, raw in frozen.items())
    for kind, raw in frozen.items():
        (client.root.parent / ('preclose.'+kind)).write_bytes(raw)
    return dict(trial_balance=state['trial_balance'], journal_count=12, captured_bytes_unchanged=True,
        package_digest=hashlib.sha256(frozen['json']).hexdigest(), retry_no_duplicate=True,
        refused_post_draft_status=next(d['status'] for d in state['drafts'] if d['draft_id']==pending['draft_id']))


def security_and_agent(client, denials):
    for role, action in [('preparer','approve-post'),('preparer','activate-account'),('preparer','close-confirm'),
            ('preparer','qbo-export-authorize'),('reviewer','cash-proposals'),('reviewer','agent-proposals')]:
        denied(client, role+':'+action, lambda r=role,a=action: client.act(a, {}, role=r), denials)
    for method, args in [('state',()), ('action',('operation-sources',{}))]:
        denied(client, 'cross-entity:'+method, lambda m=method,a=args: client.app.call(client.tokens['preparer'], 'ungranted', m,*a), denials)
    denied(client, 'unsupported-agent-post', lambda: client.act('post-journal',{}), denials)
    # The second granted entity is deliberately separate from the reference books.
    for role in client.users:
        client.access.bootstrap_grant(client.users[role], 'ungranted', role, reason='Separate synthetic agent scenario',retry_key='agent-'+role)
    client.entity = 'ungranted'
    sources = [client.enroll(d) for d in nonoperating_facts('agent-drawing','200.00','2026-01-25','owner_draw',entity=client.entity)]
    data = dict(run_id='acceptance-agent',workflow='nonoperating_cash',provider='offline',source_ids=sources,target_ids=[],operator={})
    missing=dict(data,run_id='acceptance-missing',source_ids=sources[:1])
    client.act('agent-proposals',missing)
    missing_run=next(r for r in client.read()['agent_runs'] if r['run_id']==missing['run_id'])
    assert missing_run['review']['kind']=='handoff' and missing_run['review']['reason']=='missing_evidence' and missing_run['review']['findings'][0]['code']=='agent_handoff'
    assert client.read()['journal_count']==0
    before = client.read()['journal_count']
    client.act('agent-proposals',data)
    state = client.read()
    assert state['journal_count'] == before == 0
    pending_drafts = sum(d['status']=='awaiting_approval' for d in state['drafts'])
    assert pending_drafts == 1
    run = next(r for r in state['agent_runs'] if r['run_id'] == data['run_id'])
    assert run['review']['kind'] == 'draft' and run['initiator_id'] == client.users['preparer']
    draft = next(d for d in state['drafts'] if d['draft_id'] == run['review']['draft_id'])
    revised = client.prepare('nonoperating-cash-proposals',dict(cash_source_id=sources[0],basis_source_id=sources[1],expected_revision=1))
    denied(client, 'stale-human-approval', lambda: client.act('approve-post',client.confirmation(draft),role='reviewer'),denials,ValueError,'revision')
    client.post(revised)
    client.app = AuthenticatedWorkspace(AccessStore(client.access.path))
    client.act('agent-proposals',data)
    after_review = client.read()['journal_count']
    assert after_review == 1
    # Provision a distinct browser preparer; revoked identity remains revoked.
    password=secrets.token_urlsafe(24)
    user=client.access.create_user('browser-preparer',password,reason='Synthetic browser rehearsal')
    client.access.bootstrap_grant(user,client.entity,'preparer',reason='Synthetic browser rehearsal',retry_key='browser-preparer')
    client.credentials['browser-preparer']=dict(username='browser-preparer',password=password)
    browser_token=client.access.login(**client.credentials['browser-preparer'])
    # Fault injection stops after the real authenticated proposal commits, before checkpoint.
    from accounting_harness.operational_agent import OperationalRunEngine
    interrupted_sources = [client.enroll(d) for d in nonoperating_facts('interrupted','25.00','2026-01-26','owner_draw',entity=client.entity)]
    interrupted = dict(data,run_id='acceptance-interrupted',source_ids=interrupted_sources)
    original = OperationalRunEngine._result
    def crash(engine,current,config,outcome,*,recovered=False):
        if outcome[2] and outcome[2].get('kind') == 'draft' and not recovered:
            raise RuntimeError('Synthetic process stop after committed draft')
        return original(engine,current,config,outcome,recovered=recovered)
    with patch.object(OperationalRunEngine,'_result',crash):
        try: client.app.call(browser_token,client.entity,'action','agent-proposals',interrupted)
        except RuntimeError as exc: assert str(exc) == 'Synthetic process stop after committed draft'
        else: raise AssertionError('Fault hook did not stop run')
    # Retain a pending real draft for the browser; do not post it during setup.
    client.access.revoke(client.tokens['owner'],client.users['preparer'],client.entity,
        reason='Synthetic persisted revocation check',retry_key='acceptance-revoke')
    client.app = AuthenticatedWorkspace(AccessStore(client.access.path))
    for action in ('state','operation-sources','agent-cancel'):
        denied(client,'revoked:'+action,lambda a=action: client.read(role='preparer') if a=='state' else client.act(a,{}),denials)
    client.entity=ENTITY
    return interrupted, dict(agent_journals_before_review=before,
        agent_pending_drafts_before_review=pending_drafts, agent_journals_after_review=after_review)


def uncertain_export(client, journal):
    from accounting_harness.qbo_export import SimulatedExportQBO
    before = client.read('report_package', CUTOFF)
    preview=client.act('qbo-export-preview',dict(journal_id=journal),role='reviewer')
    client.act('qbo-export-authorize',dict(export_id=preview['export_id'],confirmed_digest=preview['preview_digest'],confirmed=True),role='reviewer')
    create=SimulatedExportQBO.create
    def lost(sim,request):
        create(sim,request)
        raise TimeoutError('Synthetic lost response')
    with patch.object(SimulatedExportQBO,'create',lost):
        result=client.act('qbo-export-send',dict(export_id=preview['export_id']),role='reviewer')
    assert result['status']=='uncertain'
    assert client.read('report_package',CUTOFF)==before
    return result


def create_acceptance_drill(destination):
    """Return private credentials and server-ready original/restored synthetic groups.

    The caller must keep credentials and databases local. Ordinary demo output
    prints only ``report``. Existing destinations are refused, never overwritten.
    """
    root=Path(destination).resolve()
    if root.exists(): raise ValueError('Acceptance drill requires a new directory')
    root.mkdir(parents=True,mode=0o700)
    client=Rehearsal(root/'original')
    denials=[]
    month=reference_month(client)
    closed=close_month(client,month,denials)
    interrupted,agent_evidence=security_and_agent(client,denials)
    uncertain=uncertain_export(client,month['transactions']['T02']['journal_id'])
    client.act('qbo-read',dict(batch_id='acceptance-read'))
    before=client.read(); package=client.read('report_package',CUTOFF)
    old_exports=client.read('external_exports')
    secondary_before=client.app.call(client.tokens['reviewer'],'ungranted','state')
    status=client.read('operations_status')
    assert status['categories']['backup']['availability']=='unavailable'
    from accounting_harness import recovery
    backup=recovery.backup_group(client.access.path,root/'backup')
    recovery.verify_backup(root/'backup')
    restored=recovery.restore_group(root/'backup',root/'restored',activate=True)
    assert client.read('operations_status')['categories']['backup']['availability']=='available'
    access=AccessStore(root/'restored/access.sqlite3')
    for token in client.tokens.values():
        try: access.session(token)
        except AccessDenied: pass
        else: raise AssertionError('Old session survived verified restore')
    app=AuthenticatedWorkspace(access,enable_providers=True)
    token=access.login(**client.credentials['reviewer'])
    read=lambda name,*args: app.call(token,ENTITY,name,*args)
    after=read('state')
    comparisons={key:before[key]==after[key] for key in ('journals','trial_balance','sources','drafts','runs','agent_runs','bank_statements','period_close')}
    comparisons['report_package']=package==read('report_package',CUTOFF)
    comparisons['uncertain_export']=old_exports==read('external_exports')
    secondary_after=app.call(token,'ungranted','state')
    for key in ('journals','sources','drafts','runs','agent_runs','trial_balance'):
        comparisons['secondary_'+key]=secondary_before[key]==secondary_after[key]
    assert all(comparisons.values()),comparisons
    assert after['recovery']['transports_disabled']
    assert read('operations_status')['categories']['restore']['availability']=='available'
    # Fresh login for the original run initiator resumes its persisted draft.
    browser_token=access.login(**client.credentials['browser-preparer'])
    second_before=app.call(browser_token,'ungranted','state')
    app.call(browser_token,'ungranted','action','agent-proposals',interrupted)
    second_after=app.call(browser_token,'ungranted','state')
    assert next(r for r in second_after['agent_runs'] if r['run_id']==interrupted['run_id'])['reason']=='tool_result_recovered'
    assert second_before['drafts']==second_after['drafts'] and second_before['journals']==second_after['journals']
    report=dict(scope='synthetic_offline_authenticated_acceptance',month=month,close=closed,
        security=dict(unauthorized_successes=0,denials=denials,**agent_evidence,missing_evidence_handoff=True),
        recovery=dict(comparisons=comparisons,transports_disabled=True,resume_no_duplicate=True,
            backup_id=backup['backup_id'],uncertain_export_id=uncertain['export_id']),
        deferred=['Live model quality','Live external accounting compatibility','Actual entity policies and real-data pilot'])
    (root/'acceptance-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return dict(report=report,original_access_db=str(client.access.path),access_db=str(access.path),
        credentials=client.credentials,entity_id=ENTITY,browser_entity='ungranted',restored=str(root/'restored'))


def bank_scenario(directory):
    from accounting_harness.bank import CSV_HEADERS
    client=Rehearsal(directory)
    journals={}
    for alias, amount, day, classification in [('funding','950.00','01','owner_contribution'),
            ('deposit','200.00','20','owner_contribution'),('payment','150.00','21','owner_draw')]:
        journals[alias]=client.post(nonoperating(client,alias,amount,'2026-01-'+day,classification))['journal_id']
    csv=','.join(CSV_HEADERS)+'\nfictional-bank,funding,2026-01-01,950.00,USD,,Fictional funding\nfictional-bank,fee,2026-01-05,-10.00,USD,,Fictional fee\n'
    statement=dict(bank_account_id='fictional-bank',statement_id='january',period_start='2026-01-01',period_end=CUTOFF,
        currency='USD',opening_balance='0.00',closing_balance='940.00',csv_content=csv)
    client.act('bank-statements',statement)
    client.act('bank-fee-account',{},role='owner')
    client.post(client.prepare('bank-fee-proposals',dict(bank_account_id='fictional-bank',transaction_id='fee',classification='bank_fee',reason='Reviewed synthetic fee',expected_revision=0)))
    for transaction in ('funding','fee'):
        row=next(r for r in client.read('bank_matches','fictional-bank')['rows'] if r['transaction_id']==transaction)
        client.act('bank-match',dict(bank_account_id='fictional-bank',transaction_id=transaction,journal_id=row['candidates'][0]['journal_id'],binding=row['binding'],idempotency_key=transaction))
    def timing(statement_id):
        for alias,role in [('deposit','deposit_in_transit'),('payment','outstanding_payment')]:
            report=client.read('bank_reconciliation','fictional-bank',statement_id)['report']
            client.act('bank-timing',dict(bank_account_id='fictional-bank',statement_id=statement_id,journal_id=journals[alias],role=role,
                reason='Reviewed synthetic timing',binding=report['digest'],idempotency_key=alias))
        return client.read('bank_reconciliation','fictional-bank',statement_id)['report']
    report=timing('january')
    keys=('bank_closing','book_balance','deposits_in_transit','outstanding_payments','adjusted_bank_balance','unexplained_difference')
    assert [report[k] for k in keys]==['940.00','990.00','200.00','150.00','990.00','0.00']
    client.act('bank-reconcile',dict(bank_account_id='fictional-bank',statement_id='january',binding=report['digest'],idempotency_key='complete'),role='reviewer')
    client.act('bank-statements',dict(statement,statement_id='offset',csv_content=csv+'fictional-bank,plus,2026-01-10,7.00,USD,,Unresolved\nfictional-bank,minus,2026-01-10,-7.00,USD,,Unresolved\n'))
    offset=timing('offset')
    assert offset['unexplained_difference']=='0.00' and not offset['can_complete'] and len(offset['bank_exceptions'])==2
    denials=[]
    denied(client,'zero-difference-unresolved-bank',lambda: client.act('bank-reconcile',dict(bank_account_id='fictional-bank',statement_id='offset',binding=offset['digest'],idempotency_key='offset'),role='reviewer'),denials,ValueError,'exceptions block completion')
    assert client.read()['journal_count']==4
    return dict(scope='authenticated_separate_scenario',**{k:report[k] for k in keys},zero_difference_exceptions=len(offset['bank_exceptions']),denials=denials)


def regression_scenarios():
    """Observe returned computed values while reusing isolated delivered demos.

    No fixture/demo implementation is copied or modified. These wrappers only
    record real return values; original assertions and production logic still run.
    """
    from contextlib import ExitStack
    from accounting_harness.workspace import Workspace
    modules={'expense_accrual':'expense_accrual','revenue_accrual':'revenue_accrual','project_cost':'project_cost',
        'budget':'budget','variance':'variance','indicators':'indicators','sandbox_read':'qbo_read','sandbox_export':'qbo_export'}
    results={}
    for name,module in modules.items():
        observed={}
        def observe(method, original):
            def wrapper(*args,**kwargs):
                result=original(*args,**kwargs)
                observed.setdefault(method,[]).append(result)
                return result
            return wrapper
        with ExitStack() as stack:
            for method in ('action','state','report_package','variance'):
                stack.enter_context(patch.object(Workspace,method,observe(method,getattr(Workspace,method))))
            loaded=importlib.import_module('accounting_harness.'+module)
            if name=='sandbox_read':
                stack.enter_context(patch.object(loaded,'read_batch',observe('read_batch',loaded.read_batch)))
            with redirect_stdout(io.StringIO()):
                getattr(loaded,'demo_'+name)()
        if name in ('expense_accrual','revenue_accrual'):
            state=observed['state'][-1]
            actual=state[name+'s']
            expected=15000 if name=='expense_accrual' else 25000
            assert actual['principal_cents']==actual['control_cents']==expected and actual['unassigned_control_cents']==0
            assert state['journal_count']==1
            evidence=dict(principal_cents=actual['principal_cents'],control_residual=actual['unassigned_control_cents'])
        elif name=='project_cost':
            actual=next(r['cost_sheet'] for r in observed['action'] if 'cost_sheet' in r)
            assert [actual[k+'_amount'] for k in ('labor','direct_nonlabor','overhead','total_cost','revenue','margin')]==['400.00','100.00','200.00','700.00','1000.00','300.00']
            evidence=actual
        elif name=='budget':
            actual=[r['report'] for r in observed['action'] if 'version_id' in r]
            assert [r['ending_cash_amount'] for r in actual[:2]]==['1300.00','-200.00']
            assert actual[1]['funding_gap_amount']=='200.00'
            assert (actual[2]['revenue_amount'],actual[2]['expense_amount'])==('1000.00','500.00')
            evidence=dict(versions=actual[:3])
        elif name=='variance':
            actual=observed['variance'][-1]
            for column,expected in [('static_amount',['1000.00','500.00','500.00']),('flexible_amount',['1250.00','600.00','650.00']),('actual_amount',['1100.00','600.00','500.00'])]:
                assert [actual['totals'][k][column] for k in ('revenue','expense','income')]==expected
            assert actual['reconciled']
            evidence=dict(totals=actual['totals'],reconciled=actual['reconciled'])
        elif name=='indicators':
            actual=next(r['report'] for r in observed['action'] if 'version_id' in r)
            assert actual['contribution']['contribution_amount']=='60.00' and actual['contribution']['break_even']['whole_units']=='20'
            rows={r['id']:r for r in actual['indicators']}
            for key,numerator,denominator,display in [('current_ratio','1150000','60000','19.17'),('quick_ratio','1040000','60000','17.33'),('net_profit_margin','110000','270000','40.74%')]:
                assert (rows[key]['numerator'],rows[key]['denominator'],rows[key]['display'])==(numerator,denominator,display)
            assert rows['recorded_service_minutes']['display']=='0' and rows['revenue_per_service_hour']['display'] is None
            evidence=actual
        elif name=='sandbox_read':
            actual=observed['read_batch'][-1]
            assert actual['total_debits']==actual['total_credits']=='600.00' and len(actual['accepted'])==3
            evidence=dict(total_debits=actual['total_debits'],total_credits=actual['total_credits'],accepted=len(actual['accepted']))
        else:
            actual=next(r for r in observed['action'] if r.get('status')=='confirmed')
            assert actual['total_debits']==actual['total_credits']=='125.00'
            evidence=dict(total_debits=actual['total_debits'],total_credits=actual['total_credits'],status=actual['status'])
        packages=observed.get('report_package',[])
        if packages:
            assert packages[0]==packages[-1],name
        results[name]=dict(scope='isolated_delivered_fixture_regression',computed=evidence,
            actual_package_unchanged=bool(packages))
    return results


def lost_export_scenario(directory):
    """Authenticated 125.00 expense; one simulator commit despite a lost reply."""
    from accounting_harness.qbo_export import ExportService, database, SIMULATOR_FILE
    client=Rehearsal(directory)
    common=dict(schema_version=2,synthetic=True,entity_id=ENTITY,currency='USD',document_date='2026-01-05',amount='125.00',
        event_id='lost-export',counterparty='Fictional landlord',counterparty_id='landlord',description='Synthetic expense')
    cash=client.enroll(dict(common,document_id='lost-cash',kind='cash_movement',direction='out',purpose='incurred_expense'))
    fact=client.enroll(dict(common,document_id='lost-fact',kind='incurred_expense',incurred_date='2026-01-05',expense_account='5000'))
    journal=client.post(client.prepare('cash-proposals',dict(operation='cash_expense',cash_source_id=cash,recognition_source_id=fact)))['journal_id']
    before=client.read('report_package',CUTOFF)
    uncertain=uncertain_export(client,journal)
    client.app=AuthenticatedWorkspace(AccessStore(client.access.path))
    with patch.object(ExportService,'now',return_value=datetime.now(timezone.utc)+timedelta(minutes=2)):
        result=client.act('qbo-export-send',dict(export_id=uncertain['export_id']),role='reviewer')
    assert result['status']=='confirmed' and result['total_debits']==result['total_credits']=='125.00'
    assert result['request']==uncertain['request'] and result['export_id']==uncertain['export_id']
    with database(client.root/'primary'/SIMULATOR_FILE,ENTITY,simulator=True) as db:
        count=db.execute('SELECT count(*) FROM receipts').fetchone()[0]
    assert count==1 and client.read('report_package',CUTOFF)==before
    return dict(scope='authenticated_offline_contract_simulation',first_status=uncertain['status'],final_status=result['status'],
        total_debits=result['total_debits'],total_credits=result['total_credits'],remote_receipts=count,actual_package_unchanged=True)


def secondary_scenarios(directory):
    from accounting_harness.operational_agent import evaluate
    root=Path(directory)
    cases=evaluate(root/'corpus')
    assert len(cases)==31 and all(c['matched'] and c['journals_posted_by_run']==0 for c in cases)
    return dict(bank=bank_scenario(root/'bank'),regressions=regression_scenarios(),
        lost_export=lost_export_scenario(root/'lost-export'),
        corpus=dict(scope='offline_mock_trusted_fixture',cases=len(cases),results=cases))


def demo_acceptance():
    with TemporaryDirectory(prefix='accounting-acceptance-') as directory:
        root=Path(directory)
        result=create_acceptance_drill(root/'drill')['report']
        result['separate_scenarios']=secondary_scenarios(root)
        print(json.dumps(result,indent=2,sort_keys=True))
