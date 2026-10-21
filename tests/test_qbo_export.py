"""Offline export: actual approved journals, durable independent simulator, no network."""
import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from contextlib import closing
import test_authenticated_workspace as helpers
from accounting_harness import workspace
from accounting_harness.access import AccessDenied


class ExportTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ApplicationBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.ApplicationBoundaryTests.tearDownClass.__func__)
    setUp = helpers.ApplicationBoundaryTests.setUp
    call = helpers.ApplicationBoundaryTests.call
    native_draft = helpers.ApplicationBoundaryTests.native_draft

    def posted(self):
        self.call('reviewer', 'approve-post', self.native_draft())
        return self.facade.call(self.tokens['reviewer'], 'alpha', 'state')['drafts'][0]['audit']['journal_id']

    def preview(self):
        return self.call('reviewer', 'qbo-export-preview', dict(journal_id=self.posted()))

    def authorize(self, preview):
        return self.call('reviewer', 'qbo-export-authorize', dict(export_id=preview['export_id'], confirmed_digest=preview['preview_digest'], confirmed=True))

    def test_lost_response_restart_same_identity_and_exact_readback(self):
        from accounting_harness.authenticated import ACTION_OPERATIONS
        self.assertIn('qbo-export-preview', ACTION_OPERATIONS, 'Separate export preview is required')
        from accounting_harness.qbo_export import SimulatedExportQBO, ExportService
        preview = self.preview()
        self.assertEqual(preview['status'], 'prepared')
        with self.assertRaises(ValueError): self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.authorize(preview)
        original = SimulatedExportQBO.create
        def lost(sim, request):
            original(sim, request)
            raise TimeoutError('lost response with secret must not be persisted')
        with patch.object(SimulatedExportQBO, 'create', lost):
            result = self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.assertEqual(result['status'], 'uncertain')
        self.assertIsNone(result['remote_id'])
        self.assertNotIn('secret', json.dumps(result))
        now = datetime.now(timezone.utc) + timedelta(minutes=2)
        self.facade = workspace.AuthenticatedWorkspace(self.access)
        with patch.object(ExportService, 'now', return_value=now):
            result = self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['total_debits'], '125.00')
        self.assertEqual(result['total_credits'], '125.00')
        self.assertEqual(result['request'], preview['request'])
        with closing(sqlite3.connect(self.root / 'alpha' / 'qbo-simulator.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM receipts').fetchone()[0], 1)
        state = self.facade.call(self.tokens['reviewer'], 'alpha', 'state')
        self.assertEqual(state['journal_count'], 1)

    def test_permission_confirmation_scope_and_preview_reuse(self):
        preview = self.preview()
        for action, data in [('qbo-export-authorize', dict(export_id=preview['export_id'], confirmed_digest=preview['preview_digest'], confirmed=True)), ('qbo-export-send', dict(export_id=preview['export_id']))]:
            with self.assertRaises(AccessDenied): self.call('preparer', action, data)
            with self.assertRaises(AccessDenied): self.facade.call(self.tokens['owner'], 'beta', 'action', action, data)
        for changed in [dict(confirmed=False), dict(confirmed_digest='0'*64)]:
            with self.assertRaises(ValueError): self.call('reviewer', 'qbo-export-authorize', {**dict(export_id=preview['export_id'], confirmed_digest=preview['preview_digest'], confirmed=True), **changed})
        same = self.call('reviewer', 'qbo-export-preview', dict(journal_id=preview['journal_id']))
        self.assertEqual(same['export_id'], preview['export_id'])
        self.assertEqual(same['request'], preview['request'])
        with self.assertRaises(ValueError): self.call('reviewer', 'qbo-export-preview', dict(journal_id=preview['journal_id'], retry_key='another'))
        self.authorize(preview)
        self.access.bootstrap_revoke(self.users['reviewer'], 'alpha', reason='fixture', retry_key='revoked-export')
        with self.assertRaises(AccessDenied): self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))

    def test_reversal_after_confirmation_preserves_confirmed_observation(self):
        preview = self.preview(); self.authorize(preview)
        confirmed = self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.assertEqual(confirmed['status'], 'confirmed')
        local = workspace.Workspace(self.root / 'alpha')
        with local.storage() as (_, ledger, _, _, _):
            ledger.reverse(preview['journal_id'], reversal_id='reverse-export', entity_id='alpha', effective_date='2026-01-06', reason='Synthetic correction', source_ids=['native-fact'], actor_id='trusted-fixture', idempotency_key='reverse-export')
        result = self.call('reviewer', 'qbo-export-check', dict(export_id=preview['export_id']))
        self.assertEqual(result['status'], 'exception')
        self.assertEqual(result['confirmed_receipt'], confirmed['confirmed_receipt'])
        self.assertIn('local', result['events'][-1]['detail']['reason'])

    def test_exact_number_serialization_has_no_float_or_string_amount(self):
        from accounting_harness.qbo_export import build_body
        body = build_body(dict(effective_date='2026-01-05', lines=[dict(account='5000', side='debit', cents=9007199254740993), dict(account='1000', side='credit', cents=9007199254740993)]), {'5000':'57','1000':'35'})
        self.assertIn('"Amount":90071992547409.93', body)
        from accounting_harness.qbo_read import _decode, _cents
        self.assertEqual(_cents(_decode(body.encode())['Line'][0]['Amount']), 9007199254740993)

    def test_readback_wrong_amount_realm_schema_and_later_drift(self):
        from accounting_harness.qbo_export import SimulatedExportQBO
        preview = self.preview(); self.authorize(preview)
        confirmed = self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        original = SimulatedExportQBO.read
        for mutation in ('amount', 'unbalanced', 'realm', 'deleted', 'schema', 'currency', 'date', 'identity', 'account', 'precision'):
            def changed(sim, realm, remote_id):
                status, headers, body = original(sim, realm, remote_id)
                if mutation == 'amount': body = body.replace(b'125.00', b'126.00')
                if mutation == 'unbalanced': body = body.replace(b'125.00', b'126.00', 1)
                if mutation == 'currency': body = body.replace(b'USD', b'EUR')
                if mutation == 'date': body = body.replace(b'2026-01-05', b'2026-01-06')
                if mutation == 'identity': body = body.replace(b'"Id":"1"', b'"Id":"999"', 1)
                if mutation == 'account': body = body.replace(b'"value":"57"', b'"value":"61"')
                if mutation == 'precision': body = body.replace(b'125.00', b'125.001')
                if mutation == 'realm': headers = dict(headers, realm_id='999')
                if mutation == 'deleted': status, body = 404, b'{}'
                if mutation == 'schema': body = b'{"JournalEntry": {"Id":"x"}}'
                return status, headers, body
            with patch.object(SimulatedExportQBO, 'read', changed):
                result = self.call('reviewer', 'qbo-export-check', dict(export_id=preview['export_id']))
            self.assertEqual(result['status'], 'exception', mutation)
            self.assertEqual(result['confirmed_receipt'], confirmed['confirmed_receipt'])

    def test_retry_rate_limit_cap_and_definitive_refusal(self):
        from accounting_harness.qbo_export import SimulatedExportQBO, ExportService
        preview = self.preview(); self.authorize(preview)
        with patch.object(SimulatedExportQBO, 'create', return_value=(429, {'retry-after':'120'}, b'{}')):
            result = self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.assertEqual(result['status'], 'authorized')
        with self.assertRaises(ValueError): self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        now = datetime.now(timezone.utc)
        for minutes in (3, 6):
            with patch.object(ExportService, 'now', return_value=now+timedelta(minutes=minutes)), patch.object(SimulatedExportQBO, 'create', side_effect=TimeoutError):
                result = self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.assertEqual(result['status'], 'uncertain')
        with patch.object(ExportService, 'now', return_value=now+timedelta(hours=1)), self.assertRaises(ValueError):
            self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        self.assertIsNone(result['remote_id'])

    def test_unposted_mapping_change_and_immutable_audit(self):
        from accounting_harness import qbo_export
        confirmation = self.native_draft()
        with self.assertRaises((ValueError, KeyError)):
            self.call('reviewer', 'qbo-export-preview', dict(journal_id=confirmation['draft_id']))
        self.call('reviewer', 'approve-post', confirmation)
        journal = self.facade.call(self.tokens['reviewer'], 'alpha', 'state')['drafts'][0]['audit']['journal_id']
        preview = self.call('reviewer', 'qbo-export-preview', dict(journal_id=journal)); self.authorize(preview)
        changed = json.loads(json.dumps(qbo_export.CONNECTOR)); changed['account_map']['version']='changed'
        with patch.object(qbo_export, 'CONNECTOR', changed), self.assertRaises(ValueError):
            self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        with closing(sqlite3.connect(self.root / 'alpha' / 'qbo-outbox.sqlite3')) as db:
            for sql in ('DELETE FROM exports', 'UPDATE export_events SET actor_id="forged"'):
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)

    def test_crashes_before_send_after_remote_commit_and_before_local_receipt(self):
        from accounting_harness.qbo_export import ExportService, SimulatedExportQBO
        preview = self.preview(); self.authorize(preview)
        original = SimulatedExportQBO.create
        class Crash(BaseException): pass
        def crash_before(sim, request): raise Crash()
        with patch.object(SimulatedExportQBO, 'create', crash_before), self.assertRaises(Crash):
            self.call('reviewer', 'qbo-export-send', dict(export_id=preview['export_id']))
        result = self.facade.call(self.tokens['reviewer'], 'alpha', 'external_exports')['exports'][0]
        self.assertEqual(result['status'], 'attempted'); self.assertIsNone(result['remote_id'])
        def crash_after(sim, request): original(sim,request); raise Crash()
        now = datetime.now(timezone.utc)
        with patch.object(ExportService,'now',return_value=now+timedelta(minutes=2)), patch.object(SimulatedExportQBO,'create',crash_after), self.assertRaises(Crash):
            self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        with patch.object(ExportService,'now',return_value=now+timedelta(minutes=4)):
            result=self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(result['attempts'],3)
        with __import__('contextlib').closing(sqlite3.connect(self.root/'alpha'/'qbo-simulator.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM receipts').fetchone()[0],1)

    def test_concurrent_retry_and_failed_authorization_commit(self):
        from accounting_harness.qbo_export import ExportService
        from concurrent.futures import ThreadPoolExecutor
        preview=self.preview()
        original=ExportService._event
        def fault(service,db,export_id,kind,detail):
            original(service,db,export_id,kind,detail)
            if kind=='authorized': raise RuntimeError('commit fault')
        with patch.object(ExportService,'_event',fault), self.assertRaises(RuntimeError): self.authorize(preview)
        self.assertEqual(self.facade.call(self.tokens['reviewer'],'alpha','external_exports')['exports'][0]['status'],'prepared')
        self.authorize(preview)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id'])),range(2)))
        self.assertEqual([r['status'] for r in results],['confirmed','confirmed'])
        self.assertEqual(results[0]['remote_id'],results[1]['remote_id'])
        self.assertEqual(results[1]['attempts'],1)

    def test_reversal_before_first_send_and_agent_denied(self):
        preview=self.preview(); self.authorize(preview)
        local=workspace.Workspace(self.root/'alpha')
        local.run_key='agent-run'
        with self.assertRaises(ValueError): local.action('qbo-export-send',dict(export_id=preview['export_id']))
        local.run_key=None
        with local.storage() as (_,ledger,_,_,_):
            ledger.reverse(preview['journal_id'],reversal_id='reverse-before',entity_id='alpha',effective_date='2026-01-06',reason='Synthetic correction',source_ids=['native-fact'],actor_id='fixture',idempotency_key='reverse-before')
        with self.assertRaises(ValueError): self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        self.assertFalse((self.root/'alpha'/'qbo-simulator.sqlite3').exists())

    def test_unreviewed_journal_and_initial_remote_refusal(self):
        from accounting_harness.qbo_export import SimulatedExportQBO
        local=workspace.Workspace(self.root/'alpha')
        with local.storage() as (_,ledger,_,_,_):
            ledger.admit(dict(id='unreviewed',entity_id='alpha',currency='USD',effective_date='2026-01-05',description='Synthetic',source_ids=['synthetic-receipt-002'],lines=[dict(account='5000',side='debit',amount='125.00'),dict(account='1000',side='credit',amount='125.00')]),actor_id='fixture',idempotency_key='unreviewed')
        with self.assertRaises(ValueError): self.call('reviewer','qbo-export-preview',dict(journal_id='unreviewed'))
        preview=self.preview(); self.authorize(preview)
        with patch.object(SimulatedExportQBO,'create',return_value=(403,{},b'{"secret":"do not store"}')):
            result=self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        self.assertEqual(result['status'],'exception')
        self.assertNotIn('secret',json.dumps(result))
        with self.assertRaises(ValueError): self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))

    def test_reviewed_cash_income_and_owner_capital_are_unsupported(self):
        cash, recognition = helpers.cash_evidence()
        cash.update(direction='in',purpose='earned_service')
        recognition.update(kind='service_completion',completion_date=recognition.pop('incurred_date'))
        recognition.pop('expense_account')
        for document in (cash,recognition): self.call('preparer','operation-sources',dict(document=document))
        draft=self.call('preparer','cash-proposals',dict(operation='earned_cash',cash_source_id='native-cash',recognition_source_id='native-fact'))
        posted=self.call('reviewer','approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        with self.assertRaisesRegex(ValueError,'Cash credit'):
            self.call('reviewer','qbo-export-preview',dict(journal_id=posted['journal_id']))
        common=dict(schema_version=2,synthetic=True,entity_id='alpha',currency='USD',document_date='2026-01-05',amount='100.00',event_id='capital',counterparty_id='owner',counterparty='Fictional owner',description='Synthetic capital')
        for document in (dict(common,document_id='capital-cash',kind='cash_movement',direction='in',purpose='owner_contribution'),dict(common,document_id='capital-basis',kind='nonoperating_cash_basis',classification='owner_contribution')):
            self.call('preparer','operation-sources',dict(document=document))
        draft=self.call('preparer','nonoperating-cash-proposals',dict(cash_source_id='capital-cash',basis_source_id='capital-basis',expected_revision=0))
        posted=self.call('reviewer','approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        with self.assertRaisesRegex(ValueError,'only reviewed cash expenses'):
            self.call('reviewer','qbo-export-preview',dict(journal_id=posted['journal_id']))

    def _assert_sticky_readback_exception(self, initially_confirmed):
        from accounting_harness.qbo_export import SimulatedExportQBO
        preview=self.preview(); self.authorize(preview)
        args=dict(export_id=preview['export_id'])
        original=SimulatedExportQBO.read
        def drift(sim,realm,remote_id):
            status,headers,body=original(sim,realm,remote_id)
            return status,headers,body.replace(b'125.00',b'126.00')
        if initially_confirmed:
            confirmed=self.call('reviewer','qbo-export-send',args)
            original_receipt=confirmed['confirmed_receipt']
            with patch.object(SimulatedExportQBO,'read',drift):
                drifted=self.call('reviewer','qbo-export-check',args)
        else:
            original_receipt=None
            with patch.object(SimulatedExportQBO,'read',drift):
                drifted=self.call('reviewer','qbo-export-send',args)
        self.assertEqual(drifted['status'],'exception')
        immutable_prefix=drifted['events']
        for _ in range(2):
            with patch.object(SimulatedExportQBO,'read',side_effect=TimeoutError):
                unavailable=self.call('reviewer','qbo-export-check',args)
            self.assertEqual(unavailable['status'],'exception','transport failure cannot clear unresolved drift')
            self.assertEqual(unavailable['confirmed_receipt'],original_receipt)
        self.facade=workspace.AuthenticatedWorkspace(self.access)
        for _ in range(2):
            recovered=self.call('reviewer','qbo-export-check',args)
            self.assertEqual(recovered['status'],'exception','matching observation is not explicit reconciliation')
            self.assertEqual(recovered['confirmed_receipt'],original_receipt)
            self.assertEqual(recovered['events'][:len(immutable_prefix)],immutable_prefix)
        later=recovered['events'][len(immutable_prefix):]
        self.assertFalse(any(event['kind'] in ('confirmed','checked') for event in later))

    def test_confirmed_drift_stays_exception_through_timeouts_and_matching_reads(self):
        self._assert_sticky_readback_exception(initially_confirmed=True)

    def test_initial_invalid_readback_cannot_be_confirmed_after_timeouts(self):
        self._assert_sticky_readback_exception(initially_confirmed=False)

    def test_readback_recovery_preserves_original_confirmation(self):
        from accounting_harness.qbo_export import SimulatedExportQBO
        preview=self.preview(); self.authorize(preview)
        confirmed=self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        with patch.object(SimulatedExportQBO,'read',side_effect=TimeoutError):
            result=self.call('reviewer','qbo-export-check',dict(export_id=preview['export_id']))
        self.assertEqual(result['status'],'uncertain')
        recovered=self.call('reviewer','qbo-export-check',dict(export_id=preview['export_id']))
        self.assertEqual(recovered['status'],'confirmed')
        self.assertEqual(recovered['confirmed_receipt'],confirmed['confirmed_receipt'])

    def test_demo_and_native_confirmation_reset(self):
        import subprocess
        result=subprocess.run(['python3','-m','accounting_harness','demo-sandbox-export'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('one simulated remote journal',result.stdout)
        self.assertIn('125.00',result.stdout)
        source=__import__('pathlib').Path('accounting_harness/static/app.js').read_text()
        script = source[source.index('function renderExports('):source.index('function lockWorkspace(')]
        harness = """
const assert=require('node:assert/strict');let exportReports=[], actions=[],nodes=[];
class Node {constructor(tag,text){this.tag=tag;this.textContent=text;this.dataset={};this.children=[];nodes.push(this);}
append(...children){this.children.push(...children);} replaceChildren(){this.children=[];}addEventListener(name,fn){this[name]=fn;}}
const root=new Node('div');const $=()=>root,el=(tag,text)=>new Node(tag,text),add=(n,...children)=>{n.append(...children);return n;};
const metadata=()=>new Node('metadata'),traceLink=()=>new Node('a'),table=()=>new Node('table'),digest=()=>{},jsonDetails=()=>new Node('details'),human=x=>x,can=()=>true;
const actionButton=(action,text,fn)=>{const node=el('button',text);node.click=fn;return node;};
const exportAction=(action,data)=>actions.push([action,data]);
const report={audit_json:'{\"total_cents\":9007199254740993}',binding:{approval:{draft_id:'draft'},journal:{source_ids:[],effective_date:'2026-01-05'}},connector:{environment:'sandbox',realm_id:'realm',account_map:{version:'v1',accounts:{'35':'1000'}}},request:{method:'POST',url:'sandbox',headers:{},body:'{"Amount":90071992547409.93}'},status:'prepared',export_id:'stable',preview_digest:'digest',events:[],total_debits:'90071992547409.93',total_credits:'90071992547409.93'};
""" + script + """
renderExports([report]);let checkbox=nodes.find(n=>n.tag==='input'),approve=nodes.find(n=>n.tag==='button');
assert.equal(checkbox.checked,false);assert.equal(approve.disabled,true);
checkbox.checked=true;checkbox.change();assert.equal(approve.disabled,false);approve.click();
assert.deepEqual(actions,[['qbo-export-authorize',{export_id:'stable',confirmed_digest:'digest',confirmed:true}]]);
assert(nodes.some(n=>n.tag==='pre'&&n.textContent.includes('90071992547409.93')));
assert(nodes.some(n=>n.tag==='pre'&&n.textContent.includes('9007199254740993')),'immutable audit cents must be rendered verbatim');
renderExports([report]);assert.equal(nodes.filter(n=>n.tag==='input').at(-1).checked,false);
"""
        result=subprocess.run(['node','-e',harness],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_large_journal_roundtrip_preserves_all_original_databases(self):
        for document in helpers.cash_evidence():
            document['amount']='90071992547409.93'
            self.call('preparer','operation-sources',dict(document=document))
        draft=self.call('preparer','cash-proposals',dict(operation='cash_expense',cash_source_id='native-cash',recognition_source_id='native-fact'))
        self.call('reviewer','approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        state=self.facade.call(self.tokens['reviewer'],'alpha','state')
        before=helpers.financial_dump(self.root)
        preview=self.call('reviewer','qbo-export-preview',dict(journal_id=state['drafts'][0]['audit']['journal_id']))
        self.authorize(preview)
        confirmed=self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        self.assertEqual(confirmed['status'],'confirmed')
        self.assertEqual(confirmed['total_debits'],'90071992547409.93')
        self.assertEqual(confirmed['confirmed_receipt']['normalized']['total_cents'],9007199254740993)
        self.assertIn('9007199254740993',confirmed['audit_json'])
        after=helpers.financial_dump(self.root)
        self.assertEqual(before,{name:after[name] for name in before})
        self.assertEqual(self.facade.call(self.tokens['reviewer'],'alpha','state'),state)

    def test_revoke_before_uncertain_retry(self):
        from accounting_harness.qbo_export import SimulatedExportQBO
        preview=self.preview(); self.authorize(preview)
        original=SimulatedExportQBO.create
        def lost(sim,request): original(sim,request); raise TimeoutError()
        with patch.object(SimulatedExportQBO,'create',lost):
            self.assertEqual(self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))['status'],'uncertain')
        self.access.bootstrap_revoke(self.users['reviewer'],'alpha',reason='fixture',retry_key='revoke-uncertain')
        with self.assertRaises(AccessDenied): self.call('reviewer','qbo-export-send',dict(export_id=preview['export_id']))
        history=self.facade.call(self.tokens['owner'],'alpha','external_exports')
        self.assertEqual(history['exports'][0]['attempts'],1)


class ExportHTTPTests(unittest.TestCase):
    setUpClass=classmethod(helpers.AuthenticatedHTTPTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.AuthenticatedHTTPTests.tearDownClass.__func__)
    setUp=helpers.AuthenticatedHTTPTests.setUp
    tearDown=helpers.AuthenticatedHTTPTests.tearDown
    request=helpers.AuthenticatedHTTPTests.request
    login=helpers.AuthenticatedHTTPTests.login
    selected=helpers.AuthenticatedHTTPTests.selected
    call=helpers.ApplicationBoundaryTests.call
    native_draft=helpers.ApplicationBoundaryTests.native_draft

    def test_separate_http_authorization_readback_and_cross_entity_denial(self):
        self.call('reviewer','approve-post',self.native_draft())
        journal=self.facade.call(self.tokens['reviewer'],'alpha','state')['drafts'][0]['audit']['journal_id']
        cookie,session=self.selected('reviewer')
        def post(action,data,entity='alpha'):
            return self.request('POST','/api/'+action,data,cookie=cookie,csrf=session['csrf_token'],entity=entity)
        code,preview,_=post('qbo-export-preview',dict(journal_id=journal)); self.assertEqual(code,200,preview)
        self.assertEqual(post('qbo-export-send',dict(export_id=preview['export_id']))[0],409)
        self.assertEqual(post('qbo-export-authorize',dict(export_id=preview['export_id'],confirmed_digest=preview['preview_digest'],confirmed=False))[0],409)
        self.assertEqual(post('qbo-export-authorize',dict(export_id=preview['export_id'],confirmed_digest=preview['preview_digest'],confirmed=True),entity='beta')[0],403)
        code,authorized,_=post('qbo-export-authorize',dict(export_id=preview['export_id'],confirmed_digest=preview['preview_digest'],confirmed=True));self.assertEqual(code,200,authorized)
        code,result,_=post('qbo-export-send',dict(export_id=preview['export_id'])); self.assertEqual(code,200,result)
        self.assertEqual(result['status'],'confirmed');self.assertEqual(result['total_debits'],'125.00')
        code,history,_=self.request('GET','/api/external-exports',cookie=cookie,entity='alpha')
        self.assertEqual(code,200,history);self.assertEqual(history['exports'][0]['remote_id'],result['remote_id'])
        self.assertEqual(post('qbo-export-check',dict(export_id=preview['export_id']))[1]['status'],'confirmed')
