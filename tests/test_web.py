"""Real loopback HTTP and SQLite integration; synthetic data and no model calls."""

import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from accounting_harness.web import make_server


class WorkspaceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.start()

    def start(self):
        self.server = make_server(self.directory.name, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.origin = f'http://127.0.0.1:{self.port}'
        self.token = self.request('GET', '/api/state')[1]['csrf_token']

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.directory.cleanup()

    def request(self, method, path, data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        actual = dict(headers or {})
        if method == 'POST':
            actual = {'Content-Type': 'application/json', 'Origin': self.origin,
                      'X-CSRF-Token': getattr(self, 'token', ''), **actual}
        body = raw if raw is not None else json.dumps(data) if data is not None else None
        connection.request(method, path, body, actual)
        response = connection.getresponse()
        payload = response.read()
        status = response.status
        kind = response.getheader('Content-Type', '')
        connection.close()
        return status, json.loads(payload) if 'application/json' in kind else payload.decode()

    def propose(self, run_id='first'):
        status, result = self.request('POST', '/api/run',
            dict(source_id='synthetic-receipt-002', provider='offline', run_id=run_id))
        self.assertEqual(status, 200, result)
        state = self.request('GET', '/api/state')[1]
        self.assertEqual(state['journal_count'], 0)
        return state['drafts'][0]

    def confirmation(self, draft):
        return dict(draft_id=draft['draft_id'], revision=draft['revision'],
                    confirmed_digest=draft['content_digest'])

    def test_end_to_end_human_post_retry_restart_and_exact_snapshot(self):
        draft = self.propose()
        for _ in range(2):
            status, result = self.request('POST', '/api/approve-post', self.confirmation(draft))
            self.assertEqual(status, 200, result)
        state = self.request('GET', '/api/state')[1]
        self.assertEqual(state['journal_count'], 1)
        self.assertEqual(state['journals'][0]['lines'][0]['amount'], '1200.00')
        self.assertNotIn('cents', state['journals'][0]['lines'][0])
        self.assertEqual(state['trial_balance']['total_debits'], '1200.00')
        self.assertEqual(state['trial_balance']['total_credits'], '1200.00')
        cash = next(row for row in state['trial_balance']['rows'] if row['account'] == '1000')
        self.assertEqual(cash['credit'], '1200.00')
        self.assertEqual(state['drafts'][0]['status'], 'posted')
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'], 'local-operator')
        snapshot = state['trial_balance']['snapshot_digest']
        self.stop()
        self.start()
        reopened = self.request('GET', '/api/state')[1]
        self.assertEqual(reopened['journal_count'], 1)
        self.assertEqual(reopened['trial_balance']['snapshot_digest'], snapshot)

    def test_stale_confirmation_and_rejected_draft_cannot_post(self):
        draft = self.propose()
        bad = dict(self.confirmation(draft), confirmed_digest='stale')
        self.assertEqual(self.request('POST', '/api/approve-post', bad)[0], 409)
        reject = dict(draft_id=draft['draft_id'], revision=draft['revision'], reason='Needs correction')
        self.assertEqual(self.request('POST', '/api/reject', reject)[0], 200)
        self.assertEqual(self.request('POST', '/api/approve-post', self.confirmation(draft))[0], 409)
        self.assertEqual(self.request('GET', '/api/state')[1]['journal_count'], 0)

    def test_run_retry_and_new_duplicate_run_do_not_duplicate_drafts(self):
        self.propose()
        self.propose()
        self.propose('second')
        state = self.request('GET', '/api/state')[1]
        self.assertEqual(len(state['drafts']), 1)
        self.assertEqual(len(state['runs']), 2)
        self.assertEqual(state['runs'][-1]['reason'], 'duplicate')

    def test_live_providers_disabled_and_unknown_input_does_not_create_run(self):
        for name in ['ollama', 'openai', 'unknown']:
            status, _ = self.request('POST', '/api/run',
                dict(source_id='synthetic-receipt-002', provider=name, run_id='forbidden'))
            self.assertEqual(status, 409)
        self.assertEqual(self.request('GET', '/api/state')[1]['runs'], [])

    def test_host_origin_and_csrf_enforced_before_mutation(self):
        data = dict(source_id='synthetic-receipt-002', provider='offline', run_id='attack')
        for headers in [{'Origin': 'https://evil.example'}, {'X-CSRF-Token': ''},
                        {'Host': 'evil.example'}, {'Origin': 'null'}]:
            self.assertEqual(self.request('POST', '/api/run', data, headers)[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state')[1]['runs'], [])

    def test_request_limits_and_paths(self):
        for raw in ['[]', '{"provider":"offline","provider":"openai"}', '{broken', 'x'*20000]:
            self.assertIn(self.request('POST', '/api/run', raw=raw)[0], (400, 413))
        self.assertEqual(self.request('GET', '/../.env')[0], 404)
        self.assertEqual(self.request('GET', '/workspace/ledger.sqlite3')[0], 404)
        self.assertEqual(self.request('POST', '/api/run', {}, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('GET', '/api/state')[1]['runs'], [])

    def test_ui_and_assets_are_served(self):
        status, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('Accounting Harness', html)
        self.assertEqual(self.request('GET', '/app.js')[0], 200)
        self.assertEqual(self.request('GET', '/style.css')[0], 200)

    def test_abstention_visible_without_draft(self):
        state = self.request('GET', '/api/state')[1]
        source = next(s for s in state['sources'] if s['sample_id'] == 'missing-1')
        status, result = self.request('POST', '/api/run',
            dict(source_id=source['source_id'], provider='offline', run_id='review'))
        self.assertEqual(status, 200, result)
        state = self.request('GET', '/api/state')[1]
        self.assertEqual(state['drafts'], [])
        self.assertEqual(state['runs'][0]['state'], 'awaiting_review')
        self.assertEqual(state['runs'][0]['reason'], 'missing_facts')
