"""Authenticated loopback-only HTTP application; no accounting files open at startup."""

import json
import secrets
import sqlite3
import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from accounting_harness.access import AccessStore, AccessDenied, AccessBusy, AuthenticationFailed
from accounting_harness.authenticated import AuthenticatedWorkspace, ACTION_OPERATIONS
from accounting_harness.persistence import PersistenceBusy
from accounting_harness.workspace import Workspace, EnrollmentPending

STATIC = Path(__file__).with_name('static')
ASSETS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css')}
# Fixed route -> facade method + exact query fields. Unknown routes never dispatch.
GET_ROUTES = {
    '/api/state': ('state', ()), '/api/sources': ('list_sources', ()),
    '/api/report-export': ('report_package', ('as_of', 'format')),
    '/api/budget': ('budget', ('version_id',)), '/api/budget-inputs': ('budget_inputs', ('month',)),
    '/api/variance': ('variance', ('version_id',)), '/api/indicators': ('indicators', ('version_id',)),
    '/api/indicator-inputs': ('indicator_inputs', ('month',)),
    '/api/external-reads': ('external_reads', ()),
    '/api/external-exports': ('external_exports', ()),
    '/api/project-cost': ('project_cost', ('version_id',)),
    '/api/financial-statements': ('financial_statements', ('as_of',)),
    '/api/cash-flow': ('cash_flow', ('as_of',)),
    '/api/project-dimensions': ('project_dimensions', ('as_of',)),
    '/api/project-time': ('project_time', ('as_of',)),
    '/api/project-cost-inputs': ('project_cost_inputs', ('as_of',)),
    '/api/bank-statements': ('list_bank_statements', ()),
    '/api/bank-matches': ('bank_matches', ('bank_account_id',)),
    '/api/bank-reconciliation': ('bank_reconciliation', ('bank_account_id', 'statement_id')),
}
POST_ROUTES = {'/api/' + action: action for action in ACTION_OPERATIONS}
SESSION_COOKIE = 'ah_session'
LOGIN_COOKIE = 'ah_login'


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
        pass  # Never log bodies, credentials, paths or evidence.

    def respond(self, status, value, kind='application/json', *, filename=None, package_digest=None, cookies=()):
        body = json.dumps(value).encode() if kind == 'application/json' and not isinstance(value, bytes) else value
        self.send_response(status)
        self.send_header('Content-Type', kind + ('; charset=utf-8' if kind != 'application/zip' else ''))
        if filename:
            self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        if package_digest:
            self.send_header('X-Report-Package-Digest', package_digest)
        for cookie in cookies:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def trusted_host(self):
        return self.headers.get_all('Host', []) in [[host] for host in self.server.allowed_hosts]

    def cookie(self, name):
        found = []
        for header in self.headers.get_all('Cookie', []):
            for item in header.split(';'):
                key, separator, value = item.strip().partition('=')
                if key == name:
                    if not separator:
                        raise AccessDenied()
                    found.append(value)
        if len(found) != 1:
            raise AccessDenied()
        return found[0]

    @staticmethod
    def cookie_header(name, value, *, clear=False):
        return name + '=' + value + '; HttpOnly; SameSite=Strict; Path=/' + ('; Max-Age=0' if clear else '')

    def session(self):
        token = self.cookie(SESSION_COOKIE)
        identity = self.server.access.session(token)
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.server.browser_lock:
            browser = self.server.browsers.setdefault(key, dict(entity_id=None, csrf_token=secrets.token_urlsafe(32)))
            if browser['entity_id'] is not None and browser['entity_id'] not in [g['entity_id'] for g in identity['entities']]:
                browser.update(entity_id=None, csrf_token=secrets.token_urlsafe(32))
            result = dict(identity, **browser)
        return token, key, result

    def scope(self, *, mutate=False):
        token, key, identity = self.session()
        entity = identity['entity_id']
        if not entity or self.headers.get_all('X-Entity-ID', []) != [entity]:
            raise AccessDenied()
        if mutate:
            self.csrf(identity['csrf_token'])
        return token, entity, identity

    def csrf(self, expected):
        supplied = self.headers.get_all('X-CSRF-Token', [])
        if len(supplied) != 1 or not secrets.compare_digest(supplied[0].encode(), expected.encode()):
            raise AccessDenied()

    def do_GET(self):
        if not self.trusted_host():
            return self.respond(403, dict(error='untrusted host'))
        if self.path in ASSETS:
            name, kind = ASSETS[self.path]
            return self.respond(200, (STATIC / name).read_bytes(), kind)
        try:
            if self.path == '/api/login-challenge':
                challenge = secrets.token_urlsafe(32)
                with self.server.browser_lock:
                    now = time.monotonic()
                    self.server.challenges = {k:v for k,v in self.server.challenges.items() if v > now}
                    if len(self.server.challenges) >= 256:
                        raise AccessBusy('Login challenge capacity busy')
                    self.server.challenges[challenge] = now + 300
                return self.respond(200, dict(csrf_token=challenge), cookies=[self.cookie_header(LOGIN_COOKIE, challenge)])
            if self.path == '/api/session':
                return self.respond(200, self.session()[2])
            token, entity, identity = self.scope()
            parsed = urlsplit(self.path)
            if parsed.path not in GET_ROUTES:
                return self.respond(404, dict(error='not found'))
            method, names = GET_ROUTES[parsed.path]
            if parsed.path == '/api/bank-statements' and parsed.query:
                method, names = 'bank_statement_detail', ('bank_account_id','statement_id')
            values = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True, max_num_fields=len(names)) if parsed.query else {}
            if set(values) != set(names) or any(len(v) != 1 for v in values.values()):
                raise ValueError('request requires exactly: ' + ', '.join(names))
            if parsed.path == '/api/report-export':
                from accounting_harness.report_export import export_report_package
                kind = values['format'][0]
                if kind not in ('json','zip'):
                    raise ValueError('report format must be json or zip')
                package = self.server.application.call(token, entity, method, values['as_of'][0])
                return self.respond(200, export_report_package(package, kind),
                    'application/json' if kind == 'json' else 'application/zip',
                    filename='report.json' if kind == 'json' else 'reports.zip', package_digest=package['package_digest'])
            result = self.server.application.call(token, entity, method, *(values[n][0] for n in names))
            if method == 'state':
                result = dict(result, csrf_token=identity['csrf_token'], identity=identity,
                              allowed_actions=sorted(action for action, op in ACTION_OPERATIONS.items()
                                  if op in next(g['capabilities'] for g in identity['entities'] if g['entity_id'] == entity)))
            return self.respond(200, result)
        except AccessDenied:
            return self.respond(403, dict(error='Access denied'))
        except KeyError:
            return self.respond(404, dict(error='record not found'))
        except (ValueError, TypeError) as error:
            return self.respond(409, dict(error=str(error)))
        except (sqlite3.Error, PersistenceBusy, AccessBusy):
            return self.respond(503, dict(error='workspace busy or unavailable; retry'))

    def do_POST(self):
        host = self.headers.get('Host', '')
        if not self.trusted_host() or self.headers.get_all('Origin', []) != ['http://' + host]:
            return self.respond(403, dict(error='local browser origin required'))
        if self.headers.get_all('Content-Type', []) != ['application/json']:
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
        try:
            if self.path == '/api/login':
                challenge = self.cookie(LOGIN_COOKIE)
                self.csrf(challenge)
                with self.server.browser_lock:
                    if self.server.challenges.pop(challenge, 0) <= time.monotonic():
                        raise AccessDenied()
                if set(data) != {'username','password'}:
                    raise ValueError('login requires username and password')
                token = self.server.access.login(data['username'], data['password'])
                return self.respond(200, dict(authenticated=True), cookies=[self.cookie_header(SESSION_COOKIE, token), self.cookie_header(LOGIN_COOKIE,'',clear=True)])
            token, key, identity = self.session()
            self.csrf(identity['csrf_token'])
            if self.path == '/api/logout':
                if data != {}:
                    raise ValueError('logout accepts no fields')
                self.server.access.logout(token)
                with self.server.browser_lock:
                    self.server.browsers.pop(key, None)
                return self.respond(200, dict(authenticated=False), cookies=[self.cookie_header(SESSION_COOKIE,'',clear=True)])
            if self.path == '/api/entity':
                if set(data) != {'entity_id'}:
                    raise ValueError('entity selection requires entity_id')
                self.server.access.authorize(token, data['entity_id'], 'read_audit')
                with self.server.browser_lock:
                    self.server.browsers[key] = dict(entity_id=data['entity_id'], csrf_token=secrets.token_urlsafe(32))
                return self.respond(200, self.session()[2])
            if self.path not in POST_ROUTES:
                return self.respond(404, dict(error='not found'))
            token, entity, _ = self.scope(mutate=True)
            result = self.server.application.call(token, entity, 'action', POST_ROUTES[self.path], data)
            return self.respond(200, result)
        except AuthenticationFailed as error:
            return self.respond(403, dict(error='Login failed', retry_at=error.retry_at.isoformat() if error.retry_at else None))
        except AccessDenied:
            return self.respond(403, dict(error='Access denied'))
        except EnrollmentPending as error:
            return self.respond(503, error.result)
        except (ValueError, TypeError, KeyError) as error:
            return self.respond(409, dict(error=str(error)))
        except (sqlite3.Error, PersistenceBusy, AccessBusy):
            return self.respond(503, dict(error='workspace busy or unavailable; retry with the same request'))


def make_server(directory=None, *, access_db=None, port=8765, enable_providers=False, ollama_model=None):
    if access_db is None:
        raise ValueError('An explicitly provisioned --access-db is required; run local access setup first')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be between 0 and 65535')
    if not Path(access_db).is_file():
        raise ValueError('Access database must already exist; run local access setup first')
    access = AccessStore(access_db)
    if directory is not None:
        with access._transaction() as connection:
            if not connection.execute('SELECT 1 FROM entities WHERE workspace_path=?', (str(Path(directory).resolve()),)).fetchone():
                raise ValueError('--workspace must be an existing registered path')
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.access = access
    server.application = AuthenticatedWorkspace(access, enable_providers=enable_providers, ollama_model=ollama_model)
    server.allowed_hosts = {f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}'}
    server.browser_lock = threading.RLock()
    server.browsers, server.challenges = {}, {}
    return server


def serve(args):
    with make_server(args.workspace, access_db=args.access_db, port=args.port, enable_providers=args.enable_providers,
                     ollama_model=args.ollama_model) as server:
        print(f'Accounting Harness: http://127.0.0.1:{server.server_port}', flush=True)
        print('Login required. Entity access comes from current local grants.', flush=True)
        print('Loopback HTTP only; remote/TLS hosting is unavailable.', flush=True)
        print('Provider calls requested by operator; recovered workspaces remain disabled.' if args.enable_providers else
              'Offline mode. No provider connections or model calls.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\\nStopped. Workspace records are preserved.')


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
