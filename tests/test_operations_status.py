"""Read-only operational visibility over synthetic durable metadata."""
import importlib.util
import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import test_authenticated_workspace as helpers

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
NOW_MS = 1893456000000
SECRET = 'SECRET_EVIDENCE_PROVIDER_SENTINEL'


class OperationsStatusTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ApplicationBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.ApplicationBoundaryTests.tearDownClass.__func__)
    setUp = helpers.ApplicationBoundaryTests.setUp

    def capture(self):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.operations_status'), 'Read-only status projection must exist')
        from accounting_harness.operations_status import capture_status
        return capture_status(self.root / 'alpha', 'alpha', now=lambda: NOW)

    def run_row(self, identity, state, age, **changes):
        with closing(sqlite3.connect(self.root / 'alpha/runs.sqlite3')) as db, db:
            scope = db.execute('SELECT canonical FROM run_context').fetchone()[0]
            db.execute('INSERT INTO runs VALUES (?,?)', (identity, json.dumps(dict(scope=scope))))
            checkpoint = dict(run_id=identity, sequence=0, state=state, recorded_at_ms=NOW_MS-age, elapsed_ms=7, reason=SECRET)
            checkpoint.update(changes)
            db.execute('INSERT INTO run_checkpoints VALUES (?,?,?)', (identity, 0, json.dumps(checkpoint)))

    def test_exact_stall_threshold_terminal_handoff_and_secret_redaction(self):
        for i, age in enumerate((899999, 900000, 900001)):
            self.run_row(SECRET+str(i), 'ready', age)
        for state in ('completed', 'failed', 'exhausted', 'cancelled', 'awaiting_review'):
            self.run_row(state, state, 900001)
        result = self.capture()
        rows = result['categories']['runs']['rows']
        self.assertEqual([r['code'] for r in rows].count('run_stalled'), 2)
        self.assertEqual([r['code'] for r in rows].count('run_failed'), 1)
        self.assertEqual([r['code'] for r in rows].count('run_exhausted'), 1)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(result['stall_threshold_ms'], 900000)

    def test_future_and_malformed_checkpoints_are_unavailable_not_healthy(self):
        self.run_row('future', 'ready', -1)
        self.run_row('invalid', 'made_up', 0)
        result = self.capture()['categories']['runs']
        self.assertIsNone(result['count'])
        self.assertEqual(result['availability'], 'partial')
        self.assertEqual({r['code'] for r in result['rows']}, {'clock_invalid', 'metadata_invalid'})

    def test_read_preserves_all_stores_and_does_not_initialize_optional_files(self):
        before = helpers.financial_dump(self.root)
        paths = set((self.root/'alpha').iterdir())
        result = self.capture()
        self.assertEqual(before, helpers.financial_dump(self.root))
        self.assertEqual(paths, set((self.root/'alpha').iterdir()))
        for kind in ('backup', 'restore'):
            self.assertEqual(result['categories'][kind]['availability'], 'unavailable')
            self.assertIsNone(result['categories'][kind]['count'])

    def test_authorized_dispatch_bypasses_workspace_and_denies_other_entities(self):
        from accounting_harness.access import AccessDenied
        with patch.object(self.facade, '_workspace', side_effect=AssertionError('status must never initialize workspace')):
            result = self.facade.call(self.tokens['preparer'], 'alpha', 'operations_status')
            self.assertIn('capture_digest', result)
            for token, entity in (('invalid', 'alpha'), (self.tokens['preparer'], 'beta')):
                with self.assertRaises(AccessDenied):
                    self.facade.call(token, entity, 'operations_status')

    def test_new_capture_does_not_change_old_capture_and_details_resolve_scoped_reference(self):
        self.run_row(SECRET, 'failed', 1000)
        original = self.capture(); frozen = json.dumps(original, sort_keys=True)
        self.run_row('later', 'failed', 0)
        updated = self.capture()
        self.assertEqual(json.dumps(original, sort_keys=True), frozen)
        self.assertNotEqual(original['capture_digest'], updated['capture_digest'])
        ref = original['categories']['runs']['rows'][0]['reference']
        detail = self.facade.call(self.tokens['owner'], 'alpha', 'operations_status_detail', ref)
        self.assertEqual(detail['record']['reference'], ref)
        self.assertNotIn(SECRET, json.dumps(detail))

    def test_pending_source_is_visible_without_enrollment_and_legacy_known_sources_are_not_pending(self):
        from accounting_harness.sources import SQLiteSourceRegistry
        document = dict(helpers.cash_evidence()[0], document_id=SECRET, description=SECRET)
        with SQLiteSourceRegistry(self.root/'alpha/sources.sqlite3', 'alpha') as registry:
            registry.register(document, actor_id='fixture')
        before = helpers.financial_dump(self.root)
        result = self.capture()
        self.assertEqual(result['categories']['enrollment']['count'], 1)
        self.assertEqual(result['categories']['enrollment']['rows'][0]['code'], 'enrollment_pending')
        self.assertEqual(before, helpers.financial_dump(self.root))
        self.assertNotIn(SECRET, json.dumps(result))

    def test_staged_read_states_and_observation_chain_are_read_only(self):
        from accounting_harness import qbo_read as q
        path = self.root/'alpha'/q.FILE
        scope = dict(policy=q.POLICY, entity_id='alpha', connector=q.CONNECTOR)
        with q.QBOStagingStore(path, 'alpha') as store:
            store.open_batch('empty', scope, 'fixture', NOW)
        transports = {
            'limited': lambda request: (429, {}, b''),
            'blocked': lambda request: (400, {}, SECRET.encode()),
            'complete': q.SimulatedQBO(),
        }
        for name, transport in transports.items():
            q.read_batch(path, entity_id='alpha', account_codes={'1000','5000','5100','4000'}, batch_id=name,
                         actor_id='fixture', transport=transport, clock=lambda: NOW)
        q.read_batch(path, entity_id='alpha', account_codes={'1000','5000','5100','4000'}, batch_id='capped',
                     actor_id='fixture', transport=q.SimulatedQBO(), config=dict(q.CONNECTOR,page_size=1,max_pages=1), clock=lambda: NOW)
        before = helpers.financial_dump(self.root)
        with patch.object(q.SimulatedQBO, '__call__', side_effect=AssertionError('status must not call transport')):
            result = self.capture()
        category = result['categories']['reads']
        self.assertEqual(category['availability'], 'available')
        self.assertEqual({r['code'] for r in category['rows']}, {'read_resumable','read_rate_limited','read_blocked','read_incomplete'})
        self.assertEqual(before, helpers.financial_dump(self.root))
        self.assertNotIn(SECRET, json.dumps(result))

    def test_export_uncertainty_confirmation_and_sticky_drift(self):
        from accounting_harness.qbo_export import database, POLICY
        from accounting_harness.review import digest
        path = self.root/'alpha/qbo-outbox.sqlite3'
        observation=dict(http_status=200,body='{}',realm_id='realm')
        confirmed=dict(remote_id='remote',normalized=dict(remote_id='remote',status='supported'),observation=observation)
        with database(path, 'alpha') as db:
            for native, events in [('attempt',[('attempted',dict(next_attempt_at=NOW.isoformat()))]),('receipt',[('receipt',dict(remote_id=SECRET,body='{}'))]),
                ('resolved',[('uncertain',dict(reason=SECRET)),('confirmed',confirmed)]),
                ('drift',[('confirmed',confirmed),('exception',dict(reason='remote readback drift or invalid record')),('checked',dict(observation=observation))]),
                ('unknown',[('uncertain',dict(reason=SECRET)),('exception',dict(reason=SECRET))])]:
                preview = dict(entity_id='alpha',export_id=native,policy=POLICY,secret=SECRET)
                db.execute('INSERT INTO exports VALUES (?,?,?,?,?,?,?)',(native,native,'realm',digest(preview),json.dumps(preview),'fixture',NOW.isoformat()))
                for i,(kind,detail) in enumerate(events,1):
                    db.execute('INSERT INTO export_events VALUES (?,?,?,?,?,?)',(native,i,kind,json.dumps(detail),'fixture',NOW.isoformat()))
        result = self.capture(); rows = result['categories']['exports']['rows']
        self.assertEqual([r['code'] for r in rows].count('export_uncertain'),2)
        self.assertEqual([r['code'] for r in rows].count('export_drift'),1)
        self.assertTrue(next(r for r in rows if r['code']=='export_exception')['uncertain'])
        self.assertNotIn(SECRET,json.dumps(result))

    def test_recovery_receipts_are_separate_scoped_and_strict(self):
        from accounting_harness.recovery import BACKUP_RECEIPT, RECEIPT
        receipt = dict(version=1,entity_id='alpha',backup_id='a'*64,captured_at=NOW.isoformat(),verified_at=NOW.isoformat(),verification_ms=5,backup_ms=10,bytes=20,entity_count=2)
        (self.root/'alpha'/BACKUP_RECEIPT).write_text(json.dumps(receipt))
        result=self.capture()['categories']
        self.assertEqual(result['backup']['rows'][0]['elapsed_ms'],10)
        self.assertEqual(result['restore']['availability'],'unavailable')
        (self.root/'alpha'/RECEIPT).write_text(json.dumps(dict(receipt,entity_id='beta',restore_ms=12,transports_disabled=True)))
        self.assertEqual(self.capture()['categories']['restore']['rows'][0]['code'],'metadata_invalid')
        (self.root/'alpha'/RECEIPT).write_text(json.dumps(dict(receipt,restore_ms=True,transports_disabled=True)))
        self.assertEqual(self.capture()['categories']['restore']['rows'][0]['code'],'metadata_invalid')

    def test_cli_demo_and_ui_have_status_entry_points(self):
        import subprocess, sys
        from pathlib import Path
        result=subprocess.run([sys.executable,'-m','accounting_harness','demo-operations-status'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('zero transport calls',result.stdout)
        self.assertIn('id="view-operations"',Path('accounting_harness/static/index.html').read_text())
        self.assertIn("request('/api/operations-status')",Path('accounting_harness/static/app.js').read_text())

    def test_malformed_confirmation_and_duplicate_json_never_report_healthy(self):
        from accounting_harness.qbo_export import database, POLICY
        from accounting_harness.review import digest
        with database(self.root/'alpha/qbo-outbox.sqlite3','alpha') as db:
            preview=dict(policy=POLICY,entity_id='alpha',export_id='bad')
            db.execute('INSERT INTO exports VALUES (?,?,?,?,?,?,?)',('bad','bad','realm',digest(preview),json.dumps(preview),'fixture',NOW.isoformat()))
            db.execute('INSERT INTO export_events VALUES (?,?,?,?,?,?)',('bad',1,'confirmed','{}','fixture',NOW.isoformat()))
        result=self.capture()['categories']['exports']
        self.assertEqual(result['availability'],'partial')
        self.assertIsNone(result['count'])

    def test_revoked_identity_and_foreign_reference_cannot_read_details(self):
        from accounting_harness.access import AccessDenied
        from accounting_harness.operations_status import status_detail
        self.run_row('failed','failed',0)
        ref=self.capture()['categories']['runs']['rows'][0]['reference']
        with self.assertRaisesRegex(ValueError,'Status reference unavailable'):
            status_detail(self.root/'beta','beta',ref,now=lambda:NOW)
        self.access.bootstrap_revoke(self.users['preparer'],'alpha',reason='fixture',retry_key='revoke-status')
        with patch.object(self.facade,'_workspace',side_effect=AssertionError('denied request initialized')):
            with self.assertRaises(AccessDenied): self.facade.call(self.tokens['preparer'],'alpha','operations_status_detail',ref)

    def test_symlinked_optional_store_and_corrupt_scope_cannot_be_healthy(self):
        path=self.root/'alpha/qbo-staging.sqlite3'
        path.symlink_to(self.root/'absent')
        result=self.capture()['categories']['reads']
        self.assertEqual(result['availability'],'partial')
        self.assertIsNone(result['count'])

    def test_checkpoint_metadata_shape_boundaries_and_all_nonterminal_states(self):
        for state in ('requesting_provider','pending_tool','executing_tool'):
            self.run_row(state,state,900000)
        for i,change in enumerate((dict(recorded_at_ms=True),dict(recorded_at_ms=-1),dict(elapsed_ms=True),dict(sequence=True),dict(run_id=SECRET),dict(recorded_at_ms=SECRET))):
            self.run_row('invalid-'+str(i),'ready',0,**change)
        rows=self.capture()['categories']['runs']['rows']
        self.assertEqual(sum(r['code']=='run_stalled' for r in rows),3)
        self.assertEqual(sum(r['code']=='metadata_invalid' for r in rows),6)
        self.assertNotIn(SECRET,json.dumps(rows))

    def test_missing_checkpoint_and_duplicate_json_keys_are_explicit(self):
        with closing(sqlite3.connect(self.root/'alpha/runs.sqlite3')) as db,db:
            scope=db.execute('SELECT canonical FROM run_context').fetchone()[0]
            for name in ('missing','duplicate'):
                db.execute('INSERT INTO runs VALUES (?,?)',(name,json.dumps(dict(scope=scope))))
            db.execute('INSERT INTO run_checkpoints VALUES (?,?,?)',('duplicate',0,'{"state":"ready","state":"failed"}'))
        rows=self.capture()['categories']['runs']['rows']
        self.assertEqual(len(rows),2)
        self.assertEqual({r['code'] for r in rows},{'metadata_invalid'})

    def test_corrupt_optional_context_is_unavailable_without_foreign_counts(self):
        from accounting_harness import qbo_read as q
        with q.QBOStagingStore(self.root/'alpha'/q.FILE,'beta') as store:
            store.open_batch(SECRET,dict(policy=q.POLICY,entity_id='beta',connector=q.CONNECTOR),'fixture',NOW)
        capture=self.capture()
        self.assertIsNone(capture['categories']['reads']['count'])
        self.assertNotIn(SECRET,json.dumps(capture))

    def test_real_recovery_receipt_and_relocated_runs_remain_valid(self):
        from accounting_harness.recovery import backup_group,restore_group
        from accounting_harness.operations_status import capture_status
        self.root=self.root.resolve()
        backup_group(self.access.path,self.root/'backup')
        restore_group(self.root/'backup',self.root/'restored',activate=True)
        result=capture_status(self.root/'restored/entities/0000','alpha',now=lambda:NOW)
        self.assertEqual(result['categories']['runs']['availability'],'available')
        self.assertEqual(result['categories']['restore']['rows'][0]['code'],'restore_verified')
        self.assertEqual(result['categories']['backup']['availability'],'unavailable')

    def test_authenticated_cli_uses_same_capture_without_credential_arguments(self):
        from accounting_harness.__main__ import main
        from io import StringIO
        output=StringIO()
        with patch('getpass.getpass',return_value='Synthetic fixture passphrase preparer'),patch('sys.stdout',output):
            self.assertEqual(main(['operations-status','--access-db',str(self.access.path),'--entity','alpha','--username','preparer']),0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['policy'],'operations-status-v1')
        self.assertIn('categories',result)

    def test_cli_refuses_echo_fallback_and_prompts_once_for_login(self):
        import getpass
        from io import StringIO
        from accounting_harness.__main__ import main
        args=['operations-status','--access-db',str(self.access.path),'--entity','alpha','--username','preparer']
        with patch('getpass.getpass',side_effect=getpass.GetPassWarning('unavailable')),patch('sys.stderr',StringIO()) as stderr:
            with self.assertRaises(SystemExit): main(args)
            self.assertIn('hidden passphrase entry',stderr.getvalue())
        with patch('getpass.getpass',return_value='Synthetic fixture passphrase preparer') as prompt,patch('sys.stdout',StringIO()):
            main(args)
            self.assertEqual(prompt.call_count,1)

    def test_overflow_json_number_in_metadata_is_not_accepted(self):
        with closing(sqlite3.connect(self.root/'alpha/runs.sqlite3')) as db,db:
            scope=db.execute('SELECT canonical FROM run_context').fetchone()[0]
            db.execute('INSERT INTO runs VALUES (?,?)',('overflow',json.dumps(dict(scope=scope))))
            raw=json.dumps(dict(run_id='overflow',sequence=0,state='ready',recorded_at_ms=NOW_MS,elapsed_ms=0))[:-1]+',"extra":1e999}'
            db.execute('INSERT INTO run_checkpoints VALUES (?,?,?)',('overflow',0,raw))
        self.assertEqual(self.capture()['categories']['runs']['availability'],'partial')

    def test_skip_link_then_global_refresh_and_remembered_startup_preserve_pending_enrollment(self):
        """Replay routes chosen by actual shipped JS against real authenticated stores."""
        import subprocess
        from pathlib import Path
        from accounting_harness.sources import SQLiteSourceRegistry
        source=Path('accounting_harness/static/app.js').read_text()
        refresh=source[source.index('async function refresh()'):source.index('function render()')]
        route=source[source.index('function followRoute('):source.index('function focusTarget(')]
        click=source[source.index("$('refresh').addEventListener('click'"):source.index('setInterval(() => {',source.index("$('refresh').addEventListener('click'"))]
        script='''
const handlers={},calls=[],location={hash:'#operations'},identity={user_id:'owner',entity_id:'alpha'};
let activeView='operations',visibleView='evidence',refreshBusy=false,pendingRun=null,state={},bankDetail=null;
const nodes={};const $=id=>nodes[id] ||= {disabled:false,focus(){},addEventListener(event,fn){handlers[id+':'+event]=fn;}};
const document={querySelector(){return null;}};
const showView=name=>{activeView=name;visibleView=name;};
const request=async path=>{calls.push(path);return {entity_id:'alpha',runs:[]};};
const loadOperations=async()=>{await request('/api/operations-status');return true;};
const notify=()=>{},render=()=>{},recall=()=>null,remember=()=>{},settled=new Set();
''' + refresh + route + click + '''
(async()=>{
 location.hash='#main';followRoute();await handlers['refresh:click']();
 const afterSkip=calls.splice(0);const skipView=visibleView;
 // Browser reload keeps the focus-only hash and the remembered operational view.
 state=null;activeView='operations';visibleView='evidence';
 await refresh();followRoute(false);
 const afterReload=calls.splice(0),reloadView=visibleView;
 state={};location.hash='#evidence';followRoute();await handlers['refresh:click']();
 console.log(JSON.stringify({afterSkip,afterReload,skipView,reloadView,afterOrdinary:calls,ordinaryView:visibleView}));
})();
'''
        result=subprocess.run(['node'],input=script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        routes=json.loads(result.stdout)
        for phase in ('afterSkip','afterReload'):
            with self.subTest(phase=phase):
                native='pending-'+phase
                with SQLiteSourceRegistry(self.root/'alpha/sources.sqlite3','alpha') as registry:
                    registry.register(dict(helpers.cash_evidence()[0],document_id=native),actor_id='fixture')
                before=helpers.financial_dump(self.root)
                for path in routes[phase]:
                    method={'/api/operations-status':'operations_status','/api/state':'state'}[path]
                    self.facade.call(self.tokens['owner'],'alpha',method)
                with closing(sqlite3.connect(self.root/'alpha/ledger.sqlite3')) as db:
                    enrolled=db.execute('SELECT count(*) FROM source_enrollments WHERE source_id=?',(native,)).fetchone()[0]
                self.assertEqual(enrolled,0,'focus-only navigation must preserve pending enrollment')
                self.assertEqual(helpers.financial_dump(self.root),before)
                self.assertEqual(routes[phase],['/api/operations-status'])
        self.assertEqual(routes['skipView'],'operations')
        self.assertEqual(routes['reloadView'],'operations')
        self.assertEqual(routes['afterOrdinary'],['/api/state'])
        self.assertEqual(routes['ordinaryView'],'evidence')
