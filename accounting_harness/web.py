"""Loopback-only HTTP interface for one local synthetic-workspace operator."""

import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from accounting_harness.persistence import PersistenceBusy
from accounting_harness.workspace import Workspace, EnrollmentPending

STATIC = Path(__file__).with_name('static')
ASSETS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css')}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass  # No request bodies, paths or evidence in terminal access logs.

    def respond(self, status, value, kind='application/json'):
        body = json.dumps(value).encode() if kind == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def trusted_host(self):
        return self.headers.get_all('Host', []) in [[host] for host in self.server.allowed_hosts]

    def do_GET(self):
        if not self.trusted_host():
            return self.respond(403, dict(error='untrusted host'))
        if self.path in ASSETS:
            name, kind = ASSETS[self.path]
            return self.respond(200, (STATIC / name).read_bytes(), kind)
        if self.path in ('/api/state', '/api/sources'):
            try:
                if self.path == '/api/sources':
                    return self.respond(200, self.server.workspace.list_sources())
                state = self.server.workspace.state()
                return self.respond(200, dict(state, csrf_token=self.server.csrf_token))
            except (sqlite3.Error, PersistenceBusy):
                return self.respond(503, dict(error='workspace busy or unavailable; retry refresh'))
        self.respond(404, dict(error='not found'))

    def do_POST(self):
        host = self.headers.get('Host', '')
        if (not self.trusted_host() or self.headers.get_all('Origin', []) != ['http://' + host]
                or not secrets.compare_digest(self.headers.get('X-CSRF-Token', '').encode(),
                                              self.server.csrf_token.encode())):
            return self.respond(403, dict(error='local browser session required; refresh the page'))
        if self.headers.get('Content-Type') != 'application/json':
            return self.respond(415, dict(error='application/json required'))
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            return self.respond(400, dict(error='one bounded Content-Length required'))
        try:
            length = int(self.headers['Content-Length'])
            if not 0 < length <= 16384:
                return self.respond(413, dict(error='request size must be 1 through 16384 bytes'))
            data = json.loads(self.rfile.read(length), object_pairs_hook=unique_object)
            if type(data) is not dict:
                raise ValueError('JSON object required')
        except (ValueError, UnicodeError, TimeoutError):
            return self.respond(400, dict(error='invalid JSON request'))
        if self.path not in ('/api/run', '/api/cancel', '/api/reject', '/api/approve-post', '/api/sources',
                             '/api/operation-sources', '/api/cash-proposals', '/api/bill-proposals'):
            return self.respond(404, dict(error='not found'))
        try:
            result = self.server.workspace.action(self.path.removeprefix('/api/'), data)
            self.respond(200, result)
        except EnrollmentPending as error:
            self.respond(503, error.result)
        except (ValueError, TypeError, KeyError) as error:
            self.respond(409, dict(error=str(error)))
        except (sqlite3.Error, PersistenceBusy):
            self.respond(503, dict(error='workspace busy or unavailable; retry with the same request'))


def make_server(directory, *, port=8765, enable_providers=False, ollama_model=None):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be between 0 and 65535')
    workspace = Workspace(directory, enable_providers=enable_providers, ollama_model=ollama_model)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.workspace = workspace
    server.allowed_hosts = {f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}'}
    server.csrf_token = secrets.token_urlsafe(32)
    return server


def serve(args):
    with make_server(args.workspace, port=args.port, enable_providers=args.enable_providers,
                     ollama_model=args.ollama_model) as server:
        print(f'Accounting Harness: http://127.0.0.1:{server.server_port}', flush=True)
        print(f'Fictional workspace: {server.workspace.root}', flush=True)
        print('Provider calls enabled by operator.' if args.enable_providers else
              'Offline mode. No provider connections or model calls.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nStopped. Workspace records are preserved.')


def demo_web():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-workspace-') as directory:
        workspace = Workspace(directory)
        workspace.action('run', dict(source_id='synthetic-receipt-002', provider='offline', run_id='demo'))
        before = workspace.state()
        assert before['journal_count'] == 0
        draft = before['drafts'][0]
        confirmation = {k: draft[k] for k in ('draft_id', 'revision')}
        confirmation['confirmed_digest'] = draft['content_digest']
        workspace.action('approve-post', confirmation)  # Separate simulated human action.
        reopened = Workspace(directory)
        reopened.action('approve-post', confirmation)
        after = reopened.state()
        assert after['journal_count'] == 1
        assert after['trial_balance']['total_debits'] == after['trial_balance']['total_credits'] == '1200.00'
        print('Local workspace: offline proposal -> separate simulated human approval -> one journal.')
        print('Reopen/retry: one journal; trial balance 1200.00 USD per column; zero model calls.')
