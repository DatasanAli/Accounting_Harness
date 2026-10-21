"""Authentication boundary tests over real synthetic identities and workspaces."""
import tempfile
import unittest
import json
import sqlite3
import shutil
import inspect
import ast
import textwrap
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from accounting_harness.access import AccessStore, AccessDenied, provision_synthetic_workspace
from accounting_harness import workspace


def financial_dump(root):
    result = {}
    for path in sorted(root.glob('*/*.sqlite3')):
        with closing(sqlite3.connect(path)) as connection:
            result[str(path.relative_to(root))] = '\n'.join(connection.iterdump())
    return result


def cash_evidence(entity='alpha'):
    common = dict(schema_version=2, synthetic=True, entity_id=entity, currency='USD',
        document_date='2026-01-05', amount='125.00', event_id='native-rent',
        counterparty='Fictional landlord', counterparty_id='landlord', description='Synthetic January rent')
    return (dict(common, document_id='native-cash', kind='cash_movement', direction='out', purpose='incurred_expense'),
            dict(common, document_id='native-fact', kind='incurred_expense', incurred_date='2026-01-05', expense_account='5000'))


class ApplicationBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory()
        cls.template_path = Path(cls.template.name) / 'access.sqlite3'
        access = AccessStore(cls.template_path)
        cls.users = {role: access.create_user(role, 'Synthetic fixture passphrase ' + role, reason='fixture')
                     for role in ('preparer', 'reviewer', 'owner')}
        cls.tokens = {role: access.login(role, 'Synthetic fixture passphrase ' + role) for role in cls.users}

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(self.template_path, self.root / 'access.sqlite3')
        self.access = AccessStore(self.root / 'access.sqlite3')
        for entity in ('alpha', 'beta'):
            provision_synthetic_workspace(self.root / entity, entity)
            self.access.register_entity(entity, self.root / entity, reason='fixture')
        for role, user in self.users.items():
            self.access.bootstrap_grant(user, 'alpha', role, reason='fixture', retry_key=role)
        self.facade = workspace.AuthenticatedWorkspace(self.access)

    def call(self, role, action, data):
        return self.facade.call(self.tokens[role], 'alpha', 'action', action, data)

    def native_draft(self):
        for document in cash_evidence():
            result = self.call('preparer', 'operation-sources', dict(document=document))
            self.assertEqual(result['registration']['actor_id'], self.users['preparer'])
            self.assertEqual(result['enrollment']['actor_id'], self.users['preparer'])
        draft = self.call('preparer', 'cash-proposals', dict(operation='cash_expense',
            cash_source_id='native-cash', recognition_source_id='native-fact'))
        return dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])

    def test_session_status_polling_does_not_prevent_idle_expiry(self):
        now = datetime.now(timezone.utc)
        self.access.clock = lambda: now
        for _ in range(3):
            now += timedelta(minutes=9)
            self.assertEqual(self.access.session(self.tokens['preparer'])['user_id'], self.users['preparer'])
        now += timedelta(minutes=4)
        with self.assertRaises(AccessDenied):
            self.access.session(self.tokens['preparer'])

    def test_every_public_workspace_method_and_action_is_inventoried(self):
        from accounting_harness.authenticated import READ_METHODS, METHOD_ACTIONS, TRUSTED_ONLY_METHODS, ACTION_OPERATIONS
        methods = {name for name, method in inspect.getmembers(workspace.Workspace, inspect.isfunction) if not name.startswith('_')}
        self.assertEqual(methods, set(READ_METHODS) | set(METHOD_ACTIONS) | TRUSTED_ONLY_METHODS | {'action'})
        # Discover action branches rather than silently relying on the mapping under test.
        tree = ast.parse(textwrap.dedent(inspect.getsource(workspace.Workspace.action)))
        actions = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == 'action':
                for value in ast.walk(node.comparators[0]):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        actions.add(value.value)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'schemas' for t in node.targets):
                actions.update(k.value for k in node.value.keys)
        self.assertEqual(actions | {'activate-account'}, set(ACTION_OPERATIONS))

    def test_all_role_denials_and_unknown_methods_leave_financial_files_unchanged(self):
        from accounting_harness.authenticated import ACTION_OPERATIONS, READ_METHODS
        from accounting_harness.access import ROLE_OPERATIONS
        before = financial_dump(self.root)
        with patch.object(workspace, 'Workspace', side_effect=AssertionError('denied operation opened workspace')):
            for role in self.users:
                for action, permission in ACTION_OPERATIONS.items():
                    if permission not in ROLE_OPERATIONS[role]:
                        with self.subTest(role=role, action=action), self.assertRaises(AccessDenied):
                            self.call(role, action, dict(actor_id=self.users['owner'], role='owner', entity_id='alpha'))
                for method in (*READ_METHODS, 'unmapped', 'storage'):
                    with self.subTest(role=role, method=method), self.assertRaises(AccessDenied):
                        self.facade.call(self.tokens[role], 'beta', method)
            with self.assertRaises(AccessDenied):
                self.call('owner', 'unmapped', {})
        self.assertEqual(financial_dump(self.root), before)

    def test_native_preparer_reviewer_exact_actors_and_retry_authorization(self):
        confirmation = self.native_draft()
        before = financial_dump(self.root)
        with self.assertRaises(AccessDenied):
            self.call('preparer', 'approve-post', confirmation)
        with self.assertRaises(ValueError):
            self.call('reviewer', 'approve-post', dict(confirmation, actor_id=self.users['owner']))
        with self.assertRaises(ValueError):
            self.call('reviewer', 'approve-post', dict(confirmation, confirmed_digest='0' * 64))
        self.assertEqual(financial_dump(self.root), before)
        posted = self.call('reviewer', 'approve-post', confirmation)
        self.facade = workspace.AuthenticatedWorkspace(AccessStore(self.access.path))
        self.assertEqual(self.call('reviewer', 'approve-post', confirmation), posted)
        state = self.facade.call(self.tokens['reviewer'], 'alpha', 'state')
        self.assertEqual(state['journal_count'], 1)
        self.assertEqual(state['trial_balance']['total_debits'], '125.00')
        draft = next(d for d in state['drafts'] if d['draft_id'] == confirmation['draft_id'])
        self.assertEqual(draft['history'][0]['actor'], self.users['preparer'])
        self.assertEqual(draft['audit']['approval']['actor_id'], self.users['reviewer'])
        before = financial_dump(self.root)
        self.access.bootstrap_grant(self.users['reviewer'], 'alpha', 'preparer', reason='downgrade', retry_key='downgrade')
        with self.assertRaises(AccessDenied):
            self.call('reviewer', 'approve-post', confirmation)
        self.assertEqual(financial_dump(self.root), before)

    def test_owner_activation_is_separate_and_reads_do_not_activate(self):
        from accounting_harness.authenticated import IMPLICIT_ACTIVATIONS
        self.facade.call(self.tokens['reviewer'], 'alpha', 'state')
        for action, account in IMPLICIT_ACTIVATIONS.items():
            with self.subTest(action=action):
                before = financial_dump(self.root)
                with self.assertRaises(AccessDenied):
                    self.call('preparer', action, {})
                self.assertEqual(financial_dump(self.root), before)
                self.assertEqual(self.call('owner', 'activate-account', dict(account=account)), dict(account=account, active=True))
                # Authorization now permits the proposal; missing evidence still fails validation.
                with self.assertRaises((ValueError, TypeError)):
                    self.call('preparer', action, {})
        with workspace.Workspace(self.root / 'alpha').storage() as (_, ledger, _, _, _):
            self.assertEqual(ledger.expense_accrual_account_activation().actor_id, self.users['owner'])
            self.assertEqual(ledger.revenue_accrual_account_activation().actor_id, self.users['owner'])
            self.assertEqual(ledger.counts()['journals'], 0)

    def test_revocation_during_provider_request_blocks_late_tool_effect(self):
        from accounting_harness.local_providers import OfflineExpenseProvider
        original = OfflineExpenseProvider.request
        def revoke_then_return(adapter, *args, **kwargs):
            self.access.bootstrap_revoke(self.users['preparer'], 'alpha', reason='revoked during provider', retry_key='revoke')
            return original(adapter, *args, **kwargs)
        with patch.object(OfflineExpenseProvider, 'request', revoke_then_return):
            with self.assertRaises(AccessDenied):
                self.call('preparer', 'run', dict(source_id='synthetic-receipt-002', provider='offline', run_id='revoked-run'))
        state = self.facade.call(self.tokens['owner'], 'alpha', 'state')
        self.assertEqual(state['drafts'], [])
        self.assertEqual(state['journal_count'], 0)
        self.assertEqual(state['runs'][0]['state'], 'requesting_provider')
        with self.assertRaises(AccessDenied):
            self.call('preparer', 'cancel', dict(run_id='revoked-run'))

    def test_run_cannot_be_resumed_or_cancelled_by_other_initiator(self):
        request = dict(source_id='synthetic-receipt-002', provider='offline', run_id='owned-run')
        self.call('preparer', 'run', request)
        before = financial_dump(self.root)
        with self.assertRaises((AccessDenied, ValueError)):
            self.call('owner', 'run', request)
        with self.assertRaises(AccessDenied):
            self.call('owner', 'cancel', dict(run_id='owned-run'))
        self.assertEqual(financial_dump(self.root), before)

    def test_demo_command_is_runnable(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-authenticated-workspace'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('125.00', result.stdout)

    def test_historical_records_and_report_digests_survive_authenticated_reads(self):
        legacy = workspace.Workspace(self.root / 'alpha')
        legacy.action('run', dict(source_id='synthetic-receipt-002', provider='offline', run_id='legacy'))
        draft = legacy.state()['drafts'][0]
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])
        legacy.action('approve-post', confirmation)
        reports = legacy.financial_statements('2026-01-31')
        package = legacy.report_package('2026-01-31')
        before = financial_dump(self.root)
        state = self.facade.call(self.tokens['reviewer'], 'alpha', 'state')
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'], 'local-operator')
        self.assertIsNone(state['runs'][0]['initiator_id'])
        self.assertEqual(self.facade.call(self.tokens['reviewer'], 'alpha', 'financial_statements', '2026-01-31'), reports)
        self.assertEqual(self.facade.call(self.tokens['preparer'], 'alpha', 'report_package', '2026-01-31'), package)
        self.assertEqual(financial_dump(self.root), before)

    def test_foreign_source_draft_run_and_report_ids_cannot_cross_selected_entity(self):
        confirmation = self.native_draft()
        self.call('preparer', 'run', dict(source_id='synthetic-receipt-002', provider='offline', run_id='alpha-run'))
        self.access.bootstrap_grant(self.users['owner'], 'beta', 'owner', reason='second entity', retry_key='beta')
        self.facade.call(self.tokens['owner'], 'beta', 'state')
        before = financial_dump(self.root)
        for method, args in [('action', ('approve-post', confirmation)),
                ('action', ('cancel', dict(run_id='alpha-run'))),
                ('action', ('cash-proposals', dict(operation='cash_expense', cash_source_id='native-cash', recognition_source_id='native-fact'))),
                ('budget', ('alpha-only-report',))]:
            with self.subTest(method=method), self.assertRaises((KeyError, ValueError, AccessDenied)):
                self.facade.call(self.tokens['owner'], 'beta', method, *args)
        state = self.facade.call(self.tokens['owner'], 'beta', 'state')
        self.assertEqual(state['drafts'], [])
        self.assertEqual(state['runs'], [])
        self.assertEqual(state['journals'], [])
        self.assertNotIn('native-cash', [s['source_id'] for s in state['sources']])
        self.assertEqual(financial_dump(self.root), before)

    def test_real_post_commits_before_waiting_revocation_then_retry_denies(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from accounting_harness.approval import ReviewApplication
        confirmation = self.native_draft()
        entered, release, revoking = threading.Event(), threading.Event(), threading.Event()
        original = ReviewApplication.post
        def delayed_post(app, *args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test release timed out')
            return original(app, *args, **kwargs)
        def revoke():
            revoking.set()
            self.access.bootstrap_revoke(self.users['reviewer'], 'alpha', reason='concurrent revocation', retry_key='revoke')
        with patch.object(ReviewApplication, 'post', delayed_post), ThreadPoolExecutor(2) as pool:
            posted = pool.submit(self.call, 'reviewer', 'approve-post', confirmation)
            self.assertTrue(entered.wait(5))
            revoked = pool.submit(revoke)
            self.assertTrue(revoking.wait(5))
            try:
                self.assertFalse(revoked.done())
            finally:
                release.set()
            self.assertIn('journal_id', posted.result(timeout=5))
            revoked.result(timeout=5)
        with self.assertRaises(AccessDenied):
            self.call('reviewer', 'approve-post', confirmation)
        self.assertEqual(self.facade.call(self.tokens['owner'], 'alpha', 'state')['journal_count'], 1)

    def test_download_discards_body_arriving_after_scope_change(self):
        import subprocess
        source = Path('accounting_harness/static/app.js').read_text()
        handler = source[source.index("$('report-export-form').addEventListener"):source.index('let projectReport =')]
        script = '''
const assert = require('node:assert/strict');
let submit, finishBody, scopeGeneration = 0, clicked = 0;
let identity = {entity_id: 'alpha'};
const nodes = {};
const $ = id => nodes[id] ||= {value: 'json', addEventListener: (_, fn) => { submit = fn; }};
const document = {createElement: () => ({click: () => clicked++, remove() {}}), body: {appendChild() {}}};
const response = {ok: true, status: 200, headers: {get() {return 'digest';}}, blob: () => new Promise(resolve => finishBody = resolve)};
const fetch = async () => response;
''' + handler + '''
(async () => {
  const pending = submit({preventDefault() {}});
  await Promise.resolve();
  scopeGeneration++;
  finishBody(new Blob(['old entity financial report']));
  await pending;
  assert.equal(clicked, 0, 'old entity download must be discarded');
})();
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_status_poll_cannot_interrupt_logout_or_entity_switch(self):
        import subprocess
        source = Path('accounting_harness/static/app.js').read_text()
        callback = source[source.rindex('setInterval(async () => {'):]
        script = '''
const assert = require('node:assert/strict');
let poll, complete, fail, reloads = 0, identity = {user_id:'a'}, scopeGeneration = 0;
const setInterval = fn => poll = fn;
const sessionRequest = () => new Promise((r,j) => {complete=r;fail=j;});
const location = {reload() {reloads++;}};
const lockWorkspace = () => {identity=null;scopeGeneration++;};
''' + callback + '''
(async () => {
  const pending = poll(); lockWorkspace(); complete({user_id:'a'}); await pending;
  assert.equal(reloads,0,'stale success must not interrupt transition');
  identity={user_id:'a'};
  const failure = poll(); lockWorkspace(); fail(new Error('old request failed')); await failure;
  assert.equal(reloads,0,'stale failure must not interrupt transition');
})();
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reload_restores_only_matching_authenticated_pending_run(self):
        import subprocess
        source = Path('accounting_harness/static/app.js').read_text()
        refresh = source[source.index('async function refresh()'):source.index('function render()')]
        script = '''
const assert = require('node:assert/strict');
const location={hash:'#evidence'}; let activeView='evidence';
let refreshBusy=false, bankDetail=null, pendingRun=null, state=null;
let identity={user_id:'user-a',entity_id:'alpha'};
let saved={user_id:'user-a',entity_id:'alpha',request:{run_id:'original',source_id:'receipt',provider:'offline'}};
const settled=new Set(['completed','failed','exhausted','cancelled','awaiting_review']);
const request=async()=>({entity_id:'alpha',runs:[]});
const $=()=>({}), render=()=>{}, notify=()=>{};
const recall=()=>saved, remember=(_,v)=>saved=v;
''' + refresh + '''
(async () => {
  await refresh(); assert.equal(pendingRun.run_id,'original');
  pendingRun=null; identity={user_id:'user-b',entity_id:'alpha'};
  await refresh(); assert.equal(pendingRun,null,'other user must not inherit pending request');
  saved={user_id:'user-a',entity_id:'alpha',request:{run_id:'original',source_id:'receipt',provider:'offline'}};
  identity={user_id:'user-a',entity_id:'beta'};
  await refresh(); assert.equal(pendingRun,null,'other entity must not inherit pending request');
})();
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cancel_controls_are_limited_to_owned_runs(self):
        import subprocess
        source = Path('accounting_harness/static/app.js').read_text()
        render = source[source.index('function renderRuns()'):source.index('function renderProviders()')]
        script = '''
const assert = require('node:assert/strict');
let actions=[], identity={user_id:'me'}, busy=false, runBusy=false;
const run=initiator_id=>({run_id:initiator_id||'legacy',initiator_id,state:'ready',provider:{},trace:[]});
const state={runs:[run('me'),run('other'),run(null)]}, settled=new Set();
const node=()=>({append(){},replaceChildren(){}}), $=node,el=node,metadata=node,status=node,jsonDetails=node;
const add=(n)=>n,human=x=>x,can=()=>true,cancelRun=()=>{};
const actionButton=(action)=>{actions.push(action);return node();};
''' + render + '''
renderRuns(); assert.deepEqual(actions,['cancel']);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class AuthenticatedWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.access = AccessStore(cls.root / 'access.sqlite3')
        for entity in ('alpha', 'beta'):
            provision_synthetic_workspace(cls.root / entity, entity)
            cls.access.register_entity(entity, cls.root / entity, reason='Synthetic fixture')
        cls.tokens, cls.users = {}, {}
        for role in ('preparer', 'reviewer', 'owner'):
            cls.users[role] = cls.access.create_user(role, 'Synthetic fixture passphrase ' + role, reason='Synthetic fixture')
            cls.access.bootstrap_grant(cls.users[role], 'alpha', role, reason='Synthetic fixture', retry_key=role)
            cls.tokens[role] = cls.access.login(role, 'Synthetic fixture passphrase ' + role)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_facade_exists_and_denies_before_workspace_open(self):
        self.assertTrue(hasattr(workspace, 'AuthenticatedWorkspace'), 'Authenticated facade required')
        facade = workspace.AuthenticatedWorkspace(self.access)
        with patch.object(workspace, 'Workspace', side_effect=AssertionError('unauthorized open')):
            for token, entity, method, args in ((None,'alpha','state',()),
                    (self.tokens['preparer'],'beta','state',()),
                    (self.tokens['preparer'],'alpha','action',('approve-post', {})),
                    (self.tokens['owner'],'alpha','unmapped',())):
                with self.assertRaises(AccessDenied):
                    facade.call(token, entity, method, *args)

    def test_run_and_distinct_reviewer_record_exact_actor(self):
        facade = workspace.AuthenticatedWorkspace(self.access)
        result = facade.call(self.tokens['preparer'], 'alpha', 'action', 'run',
            dict(source_id='synthetic-receipt-002', provider='offline', run_id='auth-run'))
        state = facade.call(self.tokens['reviewer'], 'alpha', 'state')
        self.assertEqual(state['runs'][0]['initiator_id'], self.users['preparer'])
        draft = state['drafts'][0]
        confirmation = dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        with self.assertRaises(AccessDenied):
            facade.call(self.tokens['preparer'], 'alpha', 'action', 'approve-post', confirmation)
        facade.call(self.tokens['reviewer'], 'alpha', 'action', 'approve-post', confirmation)
        state = facade.call(self.tokens['reviewer'], 'alpha', 'state')
        self.assertEqual(state['journal_count'], 1)
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'], self.users['reviewer'])
        self.assertEqual(state['drafts'][0]['history'][0]['actor'], 'workspace-agent')

    def test_http_cannot_open_without_identity_configuration(self):
        from accounting_harness.web import make_server
        with self.assertRaises(ValueError):
            make_server(self.root / 'unconfigured', port=0)
        self.assertFalse((self.root / 'unconfigured').exists())

class AuthenticatedHTTPTests(unittest.TestCase):
    setUpClass = classmethod(ApplicationBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(ApplicationBoundaryTests.tearDownClass.__func__)

    def setUp(self):
        ApplicationBoundaryTests.setUp(self)
        import threading
        from accounting_harness.web import make_server
        self.server = make_server(access_db=self.access.path, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, method, path, data=None, *, cookie='', csrf='', entity='', extra=None):
        import http.client, json
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Cookie': cookie, 'X-Entity-ID': entity, 'X-CSRF-Token': csrf,
                   'Origin': self.origin, 'Content-Type': 'application/json', **(extra or {})}
        connection.request(method,path,json.dumps(data) if data is not None else None,headers)
        response = connection.getresponse(); raw = response.read()
        result = response.status, json.loads(raw) if 'application/json' in response.getheader('Content-Type','') else raw, response.getheaders()
        connection.close(); return result

    def login(self, role='preparer'):
        status, challenge, headers = self.request('GET','/api/login-challenge')
        cookie = next(v.split(';')[0] for k,v in headers if k == 'Set-Cookie')
        status, result, headers = self.request('POST','/api/login',dict(username=role,password='Synthetic fixture passphrase '+role),cookie=cookie,csrf=challenge['csrf_token'])
        self.assertEqual(status,200,result)
        session_cookie = next(v.split(';')[0] for k,v in headers if k == 'Set-Cookie' and v.startswith('ah_session='))
        return session_cookie, headers

    def selected(self, role='preparer'):
        cookie, _ = self.login(role)
        status, session, _ = self.request('GET','/api/session',cookie=cookie)
        status, selected, _ = self.request('POST','/api/entity',dict(entity_id='alpha'),cookie=cookie,csrf=session['csrf_token'])
        self.assertEqual(status,200,selected)
        return cookie, selected

    def test_login_selection_has_stable_preselection_csrf_and_rotates_on_selection(self):
        cookie, headers = self.login()
        status, session, _ = self.request('GET','/api/session',cookie=cookie)
        status, again, _ = self.request('GET','/api/session',cookie=cookie)
        self.assertEqual(session['csrf_token'],again['csrf_token'])
        self.assertIsNone(session['entity_id'])
        status, selected, _ = self.request('POST','/api/entity',dict(entity_id='alpha'),cookie=cookie,csrf=session['csrf_token'])
        self.assertEqual(status,200,selected)
        self.assertNotEqual(selected['csrf_token'],session['csrf_token'])
        self.assertEqual(self.request('GET','/api/state',cookie=cookie,entity='alpha')[0],200)
        self.assertEqual(self.request('POST','/api/entity',dict(entity_id='alpha'),cookie=cookie,csrf=session['csrf_token'])[0],403)

    def test_all_accounting_routes_require_cookie_and_selected_entity_before_open(self):
        from accounting_harness.web import GET_ROUTES, POST_ROUTES
        before = financial_dump(self.root)
        with patch.object(workspace, 'Workspace', side_effect=AssertionError('unauthenticated workspace open')):
            for path in GET_ROUTES:
                self.assertEqual(self.request('GET', path)[0], 403, path)
            for path in POST_ROUTES:
                self.assertEqual(self.request('POST', path, {})[0], 403, path)
        cookie, _ = self.login()
        self.assertEqual(self.request('GET', '/api/state', cookie=cookie, entity='alpha')[0], 403)
        self.assertEqual(financial_dump(self.root), before)

    def test_role_checks_apply_to_every_http_mutation(self):
        from accounting_harness.web import POST_ROUTES
        from accounting_harness.authenticated import ACTION_OPERATIONS
        from accounting_harness.access import ROLE_OPERATIONS
        for role in ('preparer', 'reviewer'):
            cookie, session = self.selected(role)
            before = financial_dump(self.root)
            with patch.object(workspace, 'Workspace', side_effect=AssertionError('forbidden workspace open')):
                for path, action in POST_ROUTES.items():
                    if ACTION_OPERATIONS[action] not in ROLE_OPERATIONS[role]:
                        status, result, _ = self.request('POST', path, dict(actor_id=self.users['owner'], role='owner'),
                            cookie=cookie, csrf=session['csrf_token'], entity='alpha')
                        self.assertEqual((status, result), (403, {'error': 'Access denied'}), path)
            self.assertEqual(financial_dump(self.root), before)

    def test_cookie_flags_duplicates_url_credentials_and_logout_replay(self):
        cookie, headers = self.login()
        header = next(v for k, v in headers if k == 'Set-Cookie' and v.startswith('ah_session='))
        for protection in ('HttpOnly', 'SameSite=Strict', 'Path=/'):
            self.assertIn(protection, header)
        self.assertNotIn('Domain=', header)
        status, session, _ = self.request('GET', '/api/session', cookie=cookie)
        self.assertEqual(status, 200)
        for ambiguous in (cookie + '; ' + cookie, cookie + '; ah_session=bad', 'ah_session'):
            self.assertEqual(self.request('GET', '/api/session', cookie=ambiguous)[0], 403)
        self.assertEqual(self.request('GET', '/api/state?token=' + cookie.split('=')[1], entity='alpha')[0], 403)
        status, _, headers = self.request('POST', '/api/logout', {}, cookie=cookie, csrf=session['csrf_token'])
        self.assertEqual(status, 200)
        self.assertTrue(any('Max-Age=0' in value for key, value in headers if key == 'Set-Cookie'))
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 403)

    def test_cross_session_csrf_and_ungranted_entity_never_open_books(self):
        first, session = self.selected()
        second, other = self.selected('reviewer')
        before = financial_dump(self.root)
        with patch.object(workspace, 'Workspace', side_effect=AssertionError('forbidden workspace open')):
            self.assertEqual(self.request('POST', '/api/sources', {}, cookie=first,
                csrf=other['csrf_token'], entity='alpha')[0], 403)
            self.assertEqual(self.request('POST', '/api/entity', dict(entity_id='beta'), cookie=first,
                csrf=session['csrf_token'])[0], 403)
            self.assertEqual(self.request('GET', '/api/state', cookie=first, entity='beta')[0], 403)
            self.assertEqual(self.request('POST', '/api/entity', dict(entity_id='../secret'), cookie=second,
                csrf=other['csrf_token'])[0], 403)
        self.assertEqual(financial_dump(self.root), before)

    def test_login_challenge_is_one_use_and_host_origin_are_strict(self):
        status, challenge, headers = self.request('GET', '/api/login-challenge')
        cookie = next(v.split(';')[0] for k, v in headers if k == 'Set-Cookie')
        payload = dict(username='preparer', password='Synthetic fixture passphrase preparer')
        self.assertEqual(self.request('POST', '/api/login', payload, cookie=cookie,
            csrf=challenge['csrf_token'], extra={'Origin': 'http://attacker.invalid'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', payload, cookie=cookie,
            csrf=challenge['csrf_token'])[0], 200)
        self.assertEqual(self.request('POST', '/api/login', payload, cookie=cookie,
            csrf=challenge['csrf_token'])[0], 403)
        self.assertEqual(self.request('GET', '/', extra={'Host': 'attacker.invalid'})[0], 403)
        status, _, headers = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(('Cache-Control', 'no-store'), headers)

    def test_revoked_role_and_idle_session_deny_before_financial_open(self):
        cookie, session = self.selected('reviewer')
        self.access.bootstrap_revoke(self.users['reviewer'], 'alpha', reason='fixture revocation', retry_key='revoke')
        before = financial_dump(self.root)
        with patch.object(workspace, 'Workspace', side_effect=AssertionError('revoked workspace open')):
            self.assertEqual(self.request('GET', '/api/state', cookie=cookie, entity='alpha')[0], 403)
            self.assertEqual(self.request('POST', '/api/approve-post', {}, cookie=cookie,
                csrf=session['csrf_token'], entity='alpha')[0], 403)
        cookie, session = self.selected('preparer')
        now = datetime.now(timezone.utc)
        self.server.access.clock = lambda: now
        for _ in range(3):
            now += timedelta(minutes=9)
            self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 200)
        now += timedelta(minutes=4)
        with patch.object(workspace, 'Workspace', side_effect=AssertionError('expired workspace open')):
            self.assertEqual(self.request('GET', '/api/state', cookie=cookie, entity='alpha')[0], 403)
        self.assertEqual(financial_dump(self.root), before)

    def test_native_http_preparation_and_distinct_reviewer_post_after_restart(self):
        cookie, preparer = self.selected()
        def post(path, data, session=preparer, session_cookie=cookie):
            return self.request('POST', '/api/' + path, data, cookie=session_cookie,
                                csrf=session['csrf_token'], entity='alpha')
        for document in cash_evidence():
            status, result, _ = post('operation-sources', dict(document=document))
            self.assertEqual(status, 200, result)
            self.assertEqual(result['registration']['actor_id'], self.users['preparer'])
        status, draft, _ = post('cash-proposals', dict(operation='cash_expense', cash_source_id='native-cash', recognition_source_id='native-fact'))
        self.assertEqual(status, 200, draft)
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])
        self.assertEqual(post('approve-post', confirmation)[0], 403)
        reviewer_cookie, reviewer = self.selected('reviewer')
        self.assertEqual(post('approve-post', dict(confirmation, revision=2), reviewer, reviewer_cookie)[0], 409)
        self.assertEqual(post('approve-post', confirmation, reviewer, reviewer_cookie)[0], 200)
        # A new server has no in-memory selection/CSRF but recognizes the durable session.
        from accounting_harness.web import make_server
        with make_server(access_db=self.access.path, port=0) as restarted:
            self.assertEqual(restarted.access.session(reviewer_cookie.split('=')[1])['user_id'], self.users['reviewer'])
            state = restarted.application.call(reviewer_cookie.split('=')[1], 'alpha', 'state')
        self.assertEqual(state['journal_count'], 1)
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'], self.users['reviewer'])
