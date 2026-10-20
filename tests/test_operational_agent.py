"""Bounded operational agent runs: versioned read/propose tools over delivered services."""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from accounting_harness import operational_agent as agent
from accounting_harness.access import AccessDenied, AccessStore, provision_synthetic_workspace
from accounting_harness.authenticated import AuthenticatedWorkspace
from accounting_harness.provider import MODEL, ProviderFailure
from accounting_harness.runs import FakeProvider
from accounting_harness.workspace import Workspace

CORPUS = json.loads(agent.CASES.read_text())


def document(source_id, entity):
    return dict(CORPUS['documents'][source_id], document_id=source_id, entity_id=entity)


def openai_payload(tool, arguments, **extra):
    return dict(status='completed', model=MODEL, usage=dict(input_tokens=900, output_tokens=40), output=[dict(
        type='function_call', id='fc_1', call_id='call_1', name=tool, arguments=json.dumps(arguments))], **extra)


class LocalRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.workspace = Workspace(self.directory.name, actor_id='synthetic-preparer')
        self.entity = self.workspace.catalog.entity_id

    def register(self, *source_ids):
        for source_id in source_ids:
            self.workspace.action('operation-sources', dict(document=document(source_id, self.entity)))

    def run_agent(self, run_id, adapter, sources=('drawing-cash', 'drawing-basis'), workflow='nonoperating_cash'):
        agent.start(self.workspace, run_id=run_id, workflow=workflow, source_ids=list(sources), target_ids=[],
                    operator={}, adapter=adapter)
        return agent.continue_run(self.workspace, run_id, adapter)

    def agent_run(self, run_id):
        return next(r for r in self.workspace.state()['agent_runs'] if r['run_id'] == run_id)

    def test_contract_corpus_matches_independent_expectations(self):
        results = agent.evaluate(self.directory.name)
        self.assertEqual([r['id'] for r in results if not r['matched']], [])
        self.assertTrue(all(r['journals_posted_by_run'] == 0 for r in results))
        self.assertEqual({r['workflow'] for r in results if r['category'] == 'reference'}, set(agent.WORKFLOWS))
        self.assertEqual(sorted({r['category'] for r in results}), ['handoff', 'protocol', 'provider', 'reference'])
        state = self.workspace.state()
        # Only the five simulated human approvals posted; every agent draft is a separate pending review item.
        self.assertEqual(state['journal_count'], 5)
        self.assertEqual({d['history'][0]['actor'] for d in state['drafts']}, {agent.AGENT_ACTOR})
        posted = [d for d in state['drafts'] if d['status'] == 'posted']
        self.assertEqual({d['audit']['approval']['actor_id'] for d in posted}, {'synthetic-reviewer'})
        hostile = self.agent_run('hostile-model-handoff')['review']['unverified_explanation']
        self.assertEqual((hostile['label'], hostile['citations']), (agent.UNVERIFIED, ['hostile-cash']))

    def test_fresh_inactive_accrual_account_hands_off_without_activation(self):
        self.register('cleaning-fact', 'cleaning-cutoff')
        result = self.run_agent('accrual', agent.OfflinePlayback(), ('cleaning-fact', 'cleaning-cutoff'), 'expense_accrual')
        self.assertEqual((result['state'], result['reason']), ('awaiting_review', 'account_activation_required'))
        state = self.workspace.state()
        self.assertEqual((state['journal_count'], state['drafts']), (0, []))
        with self.workspace.storage() as (_, ledger, _, _, _):
            self.assertIsNone(ledger.expense_accrual_account_activation())

    def test_crash_after_draft_commit_recovers_exactly_one_draft(self):
        self.register('drawing-cash', 'drawing-basis', 'owner-cash', 'owner-basis')
        original = agent.OperationalRunEngine._result
        def crash(engine, current, config, outcome, *, recovered=False):
            if outcome[2] and outcome[2].get('kind') == 'draft' and not recovered:
                raise RuntimeError('simulated process stop after the draft commit, before its checkpoint')
            return original(engine, current, config, outcome, recovered=recovered)
        for run_id, (cash, basis) in (('crash-resume', ('drawing-cash', 'drawing-basis')), ('crash-cancel', ('owner-cash', 'owner-basis'))):
            adapter = FakeProvider([dict(tool='propose_operation', arguments=dict(cash_source_id=cash, basis_source_id=basis))])
            agent.start(self.workspace, run_id=run_id, workflow='nonoperating_cash', source_ids=[cash, basis],
                        target_ids=[], operator={}, adapter=adapter)
            with patch.object(agent.OperationalRunEngine, '_result', crash), self.assertRaises(RuntimeError):
                agent.continue_run(self.workspace, run_id, adapter)
            self.assertEqual(self.agent_run(run_id)['state'], 'executing_tool')
            if run_id == 'crash-resume':
                reopened = Workspace(self.directory.name, actor_id='synthetic-preparer')
                self.assertEqual(agent.continue_run(reopened, run_id, adapter)['reason'], 'tool_result_recovered')
            else:
                self.assertEqual(agent.cancel_run(self.workspace, dict(run_id=run_id))['state'], 'cancelled')
            run = self.agent_run(run_id)
            self.assertIn('tool_result_recovered', [c['reason'] for c in run['trace']])
            self.assertEqual(run['review']['policy_version'], 'nonoperating-cash-v1')
        state = self.workspace.state()
        self.assertEqual((state['journal_count'], len(state['drafts'])), (0, 2))

    def test_human_changed_draft_is_visible_and_old_handoff_cannot_post(self):
        self.register('drawing-cash', 'drawing-basis')
        self.run_agent('handoff', agent.OfflinePlayback())
        review = self.agent_run('handoff')['review']
        human = self.workspace.action('nonoperating-cash-proposals', dict(cash_source_id='drawing-cash', basis_source_id='drawing-basis',
                                                                          expected_revision=1))
        run = self.agent_run('handoff')
        self.assertEqual((run['review']['revision'], run['draft_now']), (1, dict(revision=2, status='awaiting_approval')))
        with self.assertRaises(ValueError):
            self.workspace.action('approve-post', dict(draft_id=review['draft_id'], revision=1, confirmed_digest=review['content_digest']))
        self.workspace.action('approve-post', dict(draft_id=human['draft_id'], revision=2, confirmed_digest=human['content_digest']))
        self.assertEqual(self.agent_run('handoff')['draft_now'], dict(revision=2, status='posted'))
        self.assertEqual(self.workspace.state()['journal_count'], 1)

    def test_cancel_during_live_request_and_immutable_contracts(self):
        self.register('drawing-cash', 'drawing-basis')
        def transport(body, *, timeout_ms, cancelled):
            # A human cancels while the provider request is outstanding; the late response is discarded.
            agent.cancel_run(self.workspace, dict(run_id='live'))
            self.assertTrue(cancelled())
            return openai_payload('propose_operation', dict(cash_source_id='drawing-cash', basis_source_id='drawing-basis'))
        adapter = agent.OpenAIOperationalProvider(transport=transport)
        self.assertEqual(self.run_agent('live', adapter)['state'], 'cancelled')
        self.assertEqual(self.workspace.state()['drafts'], [])
        with self.assertRaisesRegex(ValueError, 'different configuration'):
            agent.start(self.workspace, run_id='live', workflow='cash_expense', source_ids=['drawing-cash', 'drawing-basis'],
                        target_ids=[], operator={}, adapter=adapter)
        # The stored per-run schemas bind the toolset; a changed contract cannot reopen the log.
        self.assertEqual(self.agent_run('live')['contract'], agent.CONTRACT)
        with patch.object(agent, 'SPEC_DIGEST', '0' * 64), self.assertRaisesRegex(ValueError, 'scope differs'):
            self.workspace.state()
        # Legacy expense runs keep their own file, scope and contract alongside.
        from accounting_harness.agent_tools import AgentTools
        from accounting_harness.runs import SQLiteRunEngine
        self.assertEqual(SQLiteRunEngine._tool_contract(), AgentTools.schemas())
        sample = next(source for source, case in self.workspace.sources.items() if case['id'] == 'rent-standard')
        legacy = self.workspace.action('run', dict(source_id=sample, provider='offline', run_id='legacy'))
        self.assertEqual(legacy['state'], 'awaiting_review')
        self.assertEqual([r['run_id'] for r in self.workspace.state()['agent_runs']], ['live'])

    def test_adapters_parse_strictly_without_secrets_or_raw_traces(self):
        self.register('drawing-cash', 'drawing-basis')
        bodies = []
        frames = iter([openai_payload('read_evidence', dict(source_id='drawing-cash'), id='resp_RAW_TRACE_MARKER'),
                       openai_payload('propose_operation', dict(cash_source_id='drawing-cash', basis_source_id='drawing-basis'))])
        def transport(body, *, timeout_ms, cancelled):
            bodies.append(json.loads(body)); return next(frames)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-synthetic-SECRET-SENTINEL'}):
            result = self.run_agent('openai', agent.OpenAIOperationalProvider(transport=transport))
        self.assertEqual((result['state'], result['reason']), ('awaiting_review', 'draft_prepared'))
        first = bodies[0]
        self.assertEqual((first['tool_choice'], first['parallel_tool_calls'], first['store'], first['model']), ('required', False, False, MODEL))
        self.assertTrue(all(t['strict'] and t['parameters']['additionalProperties'] is False for t in first['tools']))
        self.assertEqual(sorted(t['name'] for t in first['tools']),
                         ['handoff_review', 'propose_operation', 'read_accounts', 'read_evidence', 'read_report'])
        self.assertEqual(json.loads(bodies[1]['input'])['transcript'][0]['result']['source_id'], 'drawing-cash')
        stored = (Path(self.directory.name) / agent.FILE).read_bytes() + json.dumps(self.workspace.state()).encode()
        for secret in (b'SECRET-SENTINEL', b'RAW_TRACE_MARKER', agent.PROMPT[:40].encode()):
            self.assertNotIn(secret, stored)
        self.assertEqual(self.agent_run('openai')['provider']['model'], MODEL)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(Path(self.directory.name) / agent.FILE)) as db:
            reads = [json.loads(json.loads(row[0])['result_json']) for row in db.execute('SELECT checkpoint_json FROM run_checkpoints')
                     if json.loads(row[0])['reason'] == 'tool_completed']
        self.assertEqual(reads[0]['references']['source_id'], 'drawing-cash')
        self.assertRegex(reads[0]['references']['content_digest'], '^[0-9a-f]{64}$')
        schemas = agent.tool_schemas('prepaid_consumption', ['coverage'], [], '2026-01')
        self.assertEqual(schemas['propose_operation']['properties']['allocation_month'], dict(type='string', enum=['2026-01']))
        explanation = schemas['handoff_review']['properties']['explanation']
        from accounting_harness.agent_tools import ToolError, _check
        _check(explanation, 'x' * 1000)
        for text in ('Basis missing.\n', 'x' * 1001, ' padded'):
            with self.subTest(text=text[:20]), self.assertRaises(ToolError):
                _check(explanation, text)
        valid = openai_payload('read_accounts', {})
        self.assertEqual(agent.parse_openai(valid)[0], dict(tool='read_accounts', arguments={}))
        broken = [dict(valid, model='other-model'), dict(valid, output=valid['output'] * 2),
                  dict(valid, output=[dict(type='message', content=[])]), dict(valid, usage=dict(input_tokens=10**9, output_tokens=1)),
                  dict(valid, output=[dict(valid['output'][0], arguments='{not json')])]
        for payload in broken:
            with self.subTest(payload=payload), self.assertRaisesRegex(ProviderFailure, 'invalid_provider_output'):
                agent.parse_openai(payload)
        ollama = dict(done=True, done_reason='stop', model='local-model', prompt_eval_count=10, eval_count=5,
                      message=dict(role='assistant', content='', tool_calls=[dict(function=dict(name='read_accounts', arguments={}))]))
        self.assertEqual(agent.parse_ollama(ollama, 'local-model')[0]['tool'], 'read_accounts')
        for payload in (dict(ollama, done=False), dict(ollama, message=dict(role='assistant', content='{"tool":"read_accounts"}')),
                        dict(ollama, message=dict(ollama['message'], tool_calls=[dict(function=dict(name='read_accounts', arguments='{}'))]))):
            with self.subTest(payload=payload), self.assertRaises(ProviderFailure):
                agent.parse_ollama(payload, 'local-model')
        def timeout(body, *, timeout_ms, cancelled):
            self.assertIn('"tools"', body.decode()); raise ProviderFailure('provider_timeout')
        ran = self.run_agent('ollama-timeout', agent.OllamaOperationalProvider('local-model', transport=timeout))
        self.assertEqual((ran['state'], ran['reason']), ('failed', 'provider_retry_exhausted'))
        bad = self.run_agent('ollama-invalid', agent.OllamaOperationalProvider('local-model', transport=lambda *a, **k: dict(done=False)))
        self.assertEqual((bad['state'], bad['reason']), ('failed', 'invalid_provider_output'))
        with self.assertRaises(ValueError):
            agent.OllamaOperationalProvider('remote:cloud')
        with self.assertRaisesRegex(ValueError, 'provider disabled'):
            agent.start_run(self.workspace, dict(run_id='live-default', workflow='nonoperating_cash', provider='openai',
                            source_ids=['drawing-cash', 'drawing-basis'], target_ids=[], operator={}))

    def test_start_refuses_out_of_scope_selection_without_creating_runs(self):
        self.register('drawing-cash', 'drawing-basis')
        other = tempfile.TemporaryDirectory(); self.addCleanup(other.cleanup)
        foreign = Workspace(other.name)
        foreign.action('operation-sources', dict(document=document('owner-cash', foreign.catalog.entity_id)))
        receipt = next(iter(self.workspace.sources))
        good = dict(run_id='scope', workflow='nonoperating_cash', provider='offline', source_ids=['drawing-cash', 'drawing-basis'],
                    target_ids=[], operator={})
        for change, message in ((dict(workflow='journal_entry'), 'unsupported workflow'),
                                (dict(target_ids=['bill:1']), 'do not match'),
                                (dict(source_ids=['drawing-cash', 'owner-cash']), 'not registered'),
                                (dict(source_ids=['drawing-cash', receipt]), 'schema-v2'),
                                (dict(source_ids=['drawing-cash', 'drawing-cash']), 'distinct'),
                                (dict(source_ids=['s%d' % i for i in range(9)]), 'at most'),
                                (dict(operator=dict(reason='Agent says so')), 'operator inputs'),
                                (dict(run_id='bad id'), 'invalid run ID'),
                                (dict(workflow='bill_payment', source_ids=['drawing-cash'], target_ids=['bill:unknown']), 'existing posted'),
                                (dict(workflow='bank_fee', source_ids=[], target_ids=['monthly-fee', 'rent-wire'],
                                      operator=dict(bank_account_id='fictional-bank', reason='Monthly fee')), 'one target'),
                                (dict(provider='ollama'), 'provider disabled')):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                self.workspace.action('agent-proposals', dict(good, **change))
        self.assertEqual(self.workspace.state()['agent_runs'], [])
        result = self.workspace.action('agent-proposals', good)
        self.assertEqual(result['reason'], 'draft_prepared')
        self.assertEqual(self.workspace.action('agent-proposals', good), result)  # Same request resumes, never re-proposes.

    def test_http_ui_and_demo(self):
        from auth_fixture import make_server
        self.register('drawing-cash', 'drawing-basis')
        server = make_server(self.directory.name, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        def call(method, path, data=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
            connection.request(method, path, json.dumps(data) if data is not None else None, dict(server.test_headers, **{
                'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{server.server_port}', 'X-CSRF-Token': server.csrf_token}))
            response = connection.getresponse(); result = (response.status, json.loads(response.read())); connection.close()
            return result
        request = dict(run_id='http', workflow='nonoperating_cash', provider='offline', source_ids=['drawing-cash', 'drawing-basis'],
                       target_ids=[], operator={})
        self.assertEqual(call('POST', '/api/agent-proposals', request), (200, dict(run_id='http', state='awaiting_review', reason='draft_prepared')))
        self.assertEqual(call('POST', '/api/agent-proposals', dict(request, run_id='forged', actor_id='reviewer'))[0], 409)
        status, state = call('GET', '/api/state')
        run = state['agent_runs'][0]
        self.assertEqual((status, run['initiator_id'], run['provider']['model']), (200, server.test_user_id, 'reference-playback'))
        self.assertIn('agent-proposals', state['allowed_actions'])
        static = Path(__file__).resolve().parents[1] / 'accounting_harness' / 'static'
        for text in ('id="agent-run-form" action="/api/agent-proposals"', 'Offline playback is a deterministic reference script, not a model'):
            self.assertIn(text, (static / 'index.html').read_text())
        for text in ('function renderAgentRuns()', "'/api/agent-cancel'", 'unverified_explanation', 'crypto.randomUUID()', 'run.draft_now'):
            self.assertIn(text, (static / 'app.js').read_text())
        demo = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-operational-agent'], capture_output=True, text=True)
        self.assertEqual(demo.returncode, 0, demo.stderr)
        for text in ('31/31', 'every run posted 0 journals', 'model accuracy remains unmeasured'):
            self.assertIn(text, demo.stdout)


class AuthenticatedRunTests(unittest.TestCase):
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
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(self.template_path, self.root / 'access.sqlite3')
        self.access = AccessStore(self.root / 'access.sqlite3')
        provision_synthetic_workspace(self.root / 'alpha', 'alpha')
        self.access.register_entity('alpha', self.root / 'alpha', reason='fixture')
        for role, user in self.users.items():
            self.access.bootstrap_grant(user, 'alpha', role, reason='fixture', retry_key=role)
        self.facade = AuthenticatedWorkspace(self.access)

    def call(self, role, action, data):
        return self.facade.call(self.tokens[role], 'alpha', 'action', action, data)

    def start(self, role, run_id, sources, workflow='nonoperating_cash'):
        for source_id in sources:
            self.call(role, 'operation-sources', dict(document=document(source_id, 'alpha')))
        return self.call(role, 'agent-proposals', dict(run_id=run_id, workflow=workflow, provider='offline',
                                                       source_ids=list(sources), target_ids=[], operator={}))

    def test_attribution_roles_owner_activation_and_revocation(self):
        with self.assertRaises(AccessDenied):
            self.call('reviewer', 'agent-proposals', dict(run_id='x', workflow='nonoperating_cash', provider='offline',
                                                          source_ids=[], target_ids=[], operator={}))
        self.assertEqual(self.start('preparer', 'drawing', ['drawing-cash', 'drawing-basis'])['reason'], 'draft_prepared')
        state = self.facade.call(self.tokens['reviewer'], 'alpha', 'state')
        run, draft = state['agent_runs'][0], state['drafts'][0]
        self.assertEqual((run['initiator_id'], draft['history'][0]['actor']), (self.users['preparer'], agent.AGENT_ACTOR))
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])
        with self.assertRaises(AccessDenied):
            self.call('preparer', 'approve-post', confirmation)
        self.call('reviewer', 'approve-post', confirmation)
        # An owner may activate accounts as a human, but the agent run still hands off.
        self.assertEqual(self.start('owner', 'accrual', ['cleaning-fact', 'cleaning-cutoff'], 'expense_accrual')['reason'],
                         'account_activation_required')
        self.assertFalse(self.facade._activation(self.facade._workspace(self.access.perform(
            self.tokens['owner'], 'alpha', 'read_audit', lambda principal: principal)), '2050'))
        # Revocation after authorization stops the run before any further tool effect.
        for source_id in ('owner-cash', 'owner-basis'):
            self.call('preparer', 'operation-sources', dict(document=document(source_id, 'alpha')))
        original = agent.OfflinePlayback.frame
        def revoke_then_answer(playback, context, **options):
            if context['transcript']:
                self.access.bootstrap_revoke(self.users['preparer'], 'alpha', reason='Synthetic revocation', retry_key='revoke')
            return original(playback, context, **options)
        with patch.object(agent.OfflinePlayback, 'frame', revoke_then_answer), self.assertRaises(AccessDenied):
            self.call('preparer', 'agent-proposals', dict(run_id='revoked', workflow='nonoperating_cash', provider='offline',
                                                           source_ids=['owner-cash', 'owner-basis'], target_ids=[], operator={}))
        state = self.facade.call(self.tokens['reviewer'], 'alpha', 'state')
        self.assertEqual((state['journal_count'], len(state['drafts'])), (1, 1))
        self.assertNotEqual(next(r for r in state['agent_runs'] if r['run_id'] == 'revoked')['state'], 'awaiting_review')
        with self.assertRaises(AccessDenied):
            self.call('preparer', 'agent-cancel', dict(run_id='revoked'))


if __name__ == '__main__':
    unittest.main()
