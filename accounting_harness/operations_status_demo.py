"""Synthetic status demonstration; fixture construction is separate from status reads."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from accounting_harness.access import AccessStore, provision_synthetic_workspace
from accounting_harness.authenticated import AuthenticatedWorkspace


def seed_status_fixture(directory):
    """Return a local synthetic browser fixture; no real credentials or transports."""
    from dataclasses import replace
    from accounting_harness.runs import FakeProvider, RunLimits
    from accounting_harness.workspace import Workspace
    from accounting_harness.sources import SQLiteSourceRegistry
    from accounting_harness.qbo_read import QBOStagingStore, POLICY, CONNECTOR
    from accounting_harness.recovery import backup_group
    root = Path(directory).resolve(); root.mkdir(parents=True, exist_ok=True)
    access = AccessStore(root/'access.sqlite3'); entity = 'status-demo'
    provision_synthetic_workspace(root/entity, entity)
    access.register_entity(entity, root/entity, reason='Synthetic status demo')
    username, password = 'status-owner', 'Synthetic status demonstration passphrase'
    user = access.create_user(username, password, reason='Synthetic status demo')
    access.bootstrap_grant(user, entity, 'owner', reason='Synthetic status demo', retry_key='owner')
    now = datetime.now(timezone.utc); old = now-timedelta(minutes=16)
    workspace = Workspace(root/entity)
    with workspace.storage() as (_, _, _, _, engine):
        engine._clock_ms = lambda: (old-datetime(1970,1,1,tzinfo=timezone.utc))//timedelta(milliseconds=1)
        for state in ('ready','failed','awaiting_review'):
            native = 'SECRET_STATUS_ID_'+state
            c = engine.start(native,task_id='synthetic-status',provider=FakeProvider([]),actor_id='synthetic-agent',limits=RunLimits(5,1000,5,0))
            if state != 'ready':
                with engine._transaction(): engine._insert(replace(c,sequence=1,state=state,reason='SECRET_STATUS_PROVIDER_REASON'))
    # Real approved synthetic exports: one unknown outcome and one recorded drift.
    from accounting_harness.qbo_export import ExportService
    token = access.login(username,password); app = AuthenticatedWorkspace(access)
    try:
        for name in ('uncertain','drift'):
            common = dict(schema_version=2,synthetic=True,entity_id=entity,currency='USD',document_date='2026-01-05',
                amount='125.00',event_id=name,counterparty='Synthetic landlord',counterparty_id='landlord',description='SECRET_STATUS_EXPORT_DESCRIPTION')
            for document in (dict(common,document_id=name+'-cash',kind='cash_movement',direction='out',purpose='incurred_expense'),
                             dict(common,document_id=name+'-fact',kind='incurred_expense',incurred_date='2026-01-05',expense_account='5000')):
                app.call(token,entity,'action','operation-sources',dict(document=document))
            draft=app.call(token,entity,'action','cash-proposals',dict(operation='cash_expense',cash_source_id=name+'-cash',recognition_source_id=name+'-fact'))
            posted=app.call(token,entity,'action','approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
            service=ExportService(Workspace(root/entity,actor_id=user))
            preview=service.preview(posted['journal_id'])
            service.authorize(preview['export_id'],preview['preview_digest'],True)
            if name == 'uncertain':
                def lost(request): raise TimeoutError('SECRET_STATUS_TRANSPORT')
                service.simulator.create=lost
                service.send(preview['export_id'])
            else:
                service.send(preview['export_id'])
                service.simulator.read=lambda realm,remote: (200,dict(realm_id=realm),b'{}')
                service.check(preview['export_id'])
    finally: access.logout(token)
    # Capture a real successful backup before deliberately pending enrollment.
    backup_group(access.path, root/'verified-backup')
    with SQLiteSourceRegistry(root/entity/'sources.sqlite3',entity) as registry:
        registry.register(dict(schema_version=1,synthetic=True,entity_id=entity,document_id='SECRET_STATUS_SOURCE_ID',
            kind='receipt',document_date='2026-01-05',currency='USD',amount='10.00',counterparty='Synthetic supplier',description='SECRET_STATUS_BODY'),actor_id='synthetic-importer')
    with QBOStagingStore(root/entity/'qbo-staging.sqlite3',entity) as store:
        store.open_batch('SECRET_STATUS_BATCH_ID',dict(policy=POLICY,entity_id=entity,connector=CONNECTOR),'fixture',now)
    return dict(root=root,access_db=access.path,workspace=root/entity,entity=entity,username=username,password=password)


def demo_operations_status():
    with TemporaryDirectory(prefix='accounting-status-') as directory:
        fixture=seed_status_fixture(directory)
        root=fixture['workspace']
        def dump():
            result={}
            for path in root.glob('*.sqlite3'):
                with closing(sqlite3.connect(path)) as db: result[path.name]='\n'.join(db.iterdump())
            return result
        before=dump()
        access=AccessStore(fixture['access_db'])
        token=access.login(fixture['username'],fixture['password'])
        try: captured=AuthenticatedWorkspace(access).call(token,fixture['entity'],'operations_status')
        finally: access.logout(token)
        assert before==dump()
        codes=[r['code'] for c in captured['categories'].values() for r in c['rows']]
        assert all(code in codes for code in ('run_failed','run_stalled','enrollment_pending','read_resumable','backup_verified','restore_unavailable','export_uncertain','export_drift'))
        assert 'SECRET_STATUS' not in json.dumps(captured)
        assert captured['categories']['runs']['count']==2
        print(json.dumps(captured,indent=2))
        print('Read-only status: failed/stalled runs, pending enrollment, incomplete read and verified backup; zero transport calls.')
        print('Review handoff is not stalled. Accounting/workflow SQL unchanged. Missing restore is unavailable.')
