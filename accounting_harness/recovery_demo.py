"""Persistent or temporary synthetic recovery drill; all transport calls are fake."""
from contextlib import closing
import json
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from accounting_harness import recovery
from accounting_harness.access import AccessStore, AccessDenied, provision_synthetic_workspace
from accounting_harness.authenticated import AuthenticatedWorkspace
from accounting_harness.workspace import Workspace


def interrupt_legacy(workspace):
    """A real saved draft followed by simulated process death before its checkpoint."""
    from accounting_harness.runs import SQLiteRunEngine
    original=SQLiteRunEngine._insert
    def crash(engine, checkpoint):
        if checkpoint.run_id=='recovery-legacy' and checkpoint.reason=='tool_completed':
            raise RuntimeError('Synthetic stop after draft commit')
        return original(engine,checkpoint)
    source=next(s for s,c in workspace.sources.items() if c['id']=='rent-standard')
    data=dict(source_id=source,provider='offline',run_id='recovery-legacy')
    with patch.object(SQLiteRunEngine,'_insert',crash):
        try: workspace.action('run',data)
        except RuntimeError: pass
        else: raise AssertionError('Legacy interruption did not occur')
    return data


def interrupt_operational(workspace):
    from accounting_harness import operational_agent as agent
    corpus=json.loads(agent.CASES.read_text())
    sources=['drawing-cash','drawing-basis']
    for source in sources:
        workspace.action('operation-sources',dict(document=dict(corpus['documents'][source],
            entity_id=workspace.catalog.entity_id,document_id=source)))
    adapter=agent.OfflinePlayback()
    agent.start(workspace,run_id='recovery-operational',workflow='nonoperating_cash',source_ids=sources,
                target_ids=[],operator={},adapter=adapter)
    original=agent.OperationalRunEngine._result
    def crash(engine,current,config,outcome,*,recovered=False):
        if outcome[2] and outcome[2].get('kind')=='draft' and not recovered:
            raise RuntimeError('Synthetic stop after operational draft commit')
        return original(engine,current,config,outcome,recovered=recovered)
    with patch.object(agent.OperationalRunEngine,'_result',crash):
        try: agent.continue_run(workspace,'recovery-operational',adapter)
        except RuntimeError: pass
        else: raise AssertionError('Operational interruption did not occur')


def create_recovery_drill(directory):
    """Build, restore and verify; leave a fresh-login server-ready local artifact.

    Returns paths, synthetic login credentials and observed comparisons. Credentials
    stay in the caller's local memory; this helper never writes them to Git files.
    """
    root=Path(directory).resolve()
    if root.exists(): raise ValueError('Recovery drill needs a new directory')
    root.mkdir(parents=True,mode=0o700)
    original=root/'original'; original.mkdir(mode=0o700)
    primary=Workspace(original/'primary')
    entity=primary.catalog.entity_id
    provision_synthetic_workspace(original/'secondary','z-secondary')
    access=AccessStore(original/'access.sqlite3')
    access.register_entity(entity,primary.root,reason='Synthetic recovery drill')
    access.register_entity('z-secondary',original/'secondary',reason='Synthetic recovery drill')
    users={};tokens={}
    for role in ('owner','preparer','reviewer'):
        password='Synthetic recovery drill passphrase '+role
        users[role]=access.create_user(role,password,reason='Synthetic recovery drill')
        access.bootstrap_grant(users[role],entity,role,reason='Synthetic recovery drill',retry_key=role)
        tokens[role]=access.login(role,password)
    access.bootstrap_grant(users['owner'],'z-secondary','owner',reason='Synthetic recovery drill',retry_key='secondary')
    from accounting_harness.adjusted_month import build_adjusted_month
    build_adjusted_month(primary)
    primary.actor_id=users['preparer']
    # Capture every cash movement into an exact synthetic bank statement and match
    # it using the application's existing binding/reconciliation actions.
    from accounting_harness.bank import CSV_HEADERS
    from accounting_harness.domain.money import Money
    rows=[];balance=0
    with primary.storage() as (_,ledger,_,_,_):
        for entry in ledger.snapshot.entries:
            cash=[line for line in entry.lines if line.account=='1000']
            if not cash: continue
            amount=sum(line.amount.cents if line.side=='debit' else -line.amount.cents for line in cash)
            balance+=amount
            rows.append(','.join(['recovery-bank',entry.id,entry.effective_date.isoformat(),
                ('-' if amount<0 else '')+str(Money(abs(amount))), 'USD',entry.id,'Synthetic drill transaction']))
    primary.import_bank_statement(dict(bank_account_id='recovery-bank',statement_id='january',period_start='2026-01-01',
        period_end='2026-01-31',currency='USD',opening_balance='0.00',closing_balance=str(Money(balance)),
        csv_content=','.join(CSV_HEADERS)+'\n'+'\n'.join(rows)+'\n'))
    for transaction in [r['transaction_id'] for r in primary.bank_matches('recovery-bank')['rows']]:
        row=next(r for r in primary.bank_matches('recovery-bank')['rows'] if r['transaction_id']==transaction)
        primary.action('bank-match',dict(bank_account_id='recovery-bank',transaction_id=row['transaction_id'],
            journal_id=row['candidates'][0]['journal_id'],binding=row['binding'],idempotency_key='drill:'+row['transaction_id']))
    report=primary.bank_reconciliation('recovery-bank','january')['report']
    primary.action('bank-reconcile',dict(bank_account_id='recovery-bank',statement_id='january',binding=report['digest'],idempotency_key='drill-complete'))
    primary.action('budget',dict(entity_id=entity,currency='USD',scenario_id='recovery-budget',name='Synthetic recovery budget',month='2026-01',
        planned_minutes=0,opening_cash='1000.00',operating_lines=[],cash_rows=[],prior_version_id=None,
        reason='Synthetic recovery scenario',explanation='',idempotency_key='recovery-budget'))
    from accounting_harness.indicators import MENU
    primary.action('indicators',dict(entity_id=entity,currency='USD',scenario_id='recovery-indicators',name='Synthetic service',month='2026-01',
        price='100.00',variable_cost='40.00',fixed_cost='1200.00',minimum_units=0,maximum_units=100,quantity=20,
        selected_indicators=list(MENU),prior_version_id=None,reason='Synthetic recovery assumptions',explanation='',idempotency_key='recovery-indicators'))
    primary.action('qbo-read',dict(batch_id='recovery-read'))
    # Completed historical run with a rejected human review.
    software=next(s for s,c in primary.sources.items() if c['id']=='software-standard')
    primary.action('run',dict(source_id=software,provider='offline',run_id='recovery-completed'))
    from accounting_harness.local_providers import OfflineExpenseProvider
    with primary.storage() as (_,_,store,_,engine):
        engine.resume('recovery-completed',OfflineExpenseProvider(software))
    draft=next(d for d in primary.state()['drafts'] if d['status']=='awaiting_approval')
    primary.action('reject',dict(draft_id=draft['draft_id'],revision=draft['revision'],reason='Synthetic reviewer rejection'))
    legacy_data=interrupt_legacy(primary)
    interrupt_operational(primary)
    # Approved local expense, separate human export authorization, remote effect,
    # lost response. Restoration must retain uncertainty without another send.
    from accounting_harness.qbo_export import SimulatedExportQBO
    reviewer=Workspace(primary.root,actor_id=users['reviewer'])
    journal=next(d['audit']['journal_id'] for d in reviewer.state()['drafts'] if d['status']=='posted' and d['policy_version']=='cash-v1')
    preview=reviewer.action('qbo-export-preview',dict(journal_id=journal))
    reviewer.action('qbo-export-authorize',dict(export_id=preview['export_id'],confirmed_digest=preview['preview_digest'],confirmed=True))
    send=SimulatedExportQBO.create
    def lost(sim,request): send(sim,request); raise TimeoutError('Synthetic lost acknowledgment')
    with patch.object(SimulatedExportQBO,'create',lost):
        uncertain=reviewer.action('qbo-export-send',dict(export_id=preview['export_id']))
    assert uncertain['status']=='uncertain'
    # Register after original constructors: restored startup must preserve this gap.
    with primary.storage() as (registry,_,_,_,_):
        sample=primary.cases[0]['document']
        registry.register(dict(sample,document_id='recovery-pending-final',description='Synthetic final enrollment gap'),actor_id=users['preparer'])
    before=primary.state(); package=primary.report_package('2026-01-31'); exports=primary.external_exports()
    backup=root/'backup'; restored=root/'restored'
    backup_result=recovery.backup_group(access.path,backup)
    restore_result=recovery.restore_group(backup,restored,activate=True)
    restored_access=AccessStore(restored/'access.sqlite3')
    for token in tokens.values():
        try: restored_access.session(token)
        except AccessDenied: pass
        else: raise AssertionError('Old session survived recovery')
    fresh=restored_access.login('owner','Synthetic recovery drill passphrase owner')
    after=AuthenticatedWorkspace(restored_access,enable_providers=True).call(fresh,entity,'state')
    relocated=Workspace(restored/'entities/0000',actor_id=users['preparer'],enable_providers=True)
    keys=('journals','journal_count','trial_balance','sources','drafts','runs','agent_runs','bank_statements')
    comparisons={key:before[key]==after[key] for key in keys}
    comparisons['report_package']=package==relocated.report_package('2026-01-31')
    comparisons['uncertain_export']=exports==relocated.external_exports()
    # Hash every original financial table against restored reopened tables, including
    # exact JSON bytes for approvals/checkpoints/captured management scenarios.
    for relative,info in backup_result['files'].items():
        if relative=='access.sqlite3': continue
        target=restored/relative
        ent=next(e['entity_id'] for e in backup_result['entities'] if relative.startswith(e['directory']+'/'))
        comparisons[relative]=recovery._inspect(target,target.name,ent)==info['tables']
    assert all(comparisons.values()),comparisons
    draft_ids=[(d['draft_id'],d['revision']) for d in after['drafts']]
    relocated.action('run',legacy_data)
    from accounting_harness import operational_agent as agent
    resumed=agent.continue_run(relocated,'recovery-operational',agent.OfflinePlayback())
    assert resumed['reason']=='tool_result_recovered'
    final=relocated.state()
    assert [(d['draft_id'],d['revision']) for d in final['drafts']]==draft_ids
    assert final['journals']==before['journals']
    return dict(original=str(original),backup=str(backup),restored=str(restored),access_db=str(restored/'access.sqlite3'),
        username='owner',password='Synthetic recovery drill passphrase owner',entity_id=entity,
        backup_result={k:backup_result[k] for k in ('backup_id','backup_ms','verification_ms','bytes')},restore_result=restore_result,
        comparisons=comparisons,resume_no_duplicate=True,journal_count=final['journal_count'],draft_count=len(final['drafts']),
        uncertain_export_id=preview['export_id'],environment=dict(python=platform.python_version(),sqlite=sqlite3.sqlite_version,system=platform.system()))


def demo_recovery():
    with TemporaryDirectory(prefix='recovery-demo-') as directory:
        result=create_recovery_drill(Path(directory)/'drill')
        print('Coherent two-entity recovery: exact financial/source/review/report/run history; fresh login; prior sessions revoked.')
        print(json.dumps({k:result[k] for k in ('backup_result','restore_result','journal_count','draft_count','resume_no_duplicate','environment')},indent=2))
        print('Both interrupted draft effects recovered without duplicate drafts; uncertain export unchanged; transports disabled.')
        print('Observed synthetic local timings only; no recovery SLA or live integration claim.')
