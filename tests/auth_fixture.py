"""Real synthetic sessions for legacy accounting HTTP tests; no auth bypass."""
import atexit
import hashlib
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from accounting_harness.access import AccessStore
from accounting_harness.workspace import Workspace
from accounting_harness.web import make_server as authenticated_server

_fixtures = {}


def make_server(directory, **options):
    root = str(Path(directory).resolve())
    workspace = Workspace(directory)
    if root not in _fixtures:
        temp = TemporaryDirectory(prefix='accounting-http-identities-')
        atexit.register(temp.cleanup)
        access = AccessStore(Path(temp.name) / 'access.sqlite3')
        user = access.create_user('synthetic-owner', 'Synthetic HTTP fixture passphrase', reason='Synthetic HTTP test')
        access.register_entity(workspace.catalog.entity_id, directory, reason='Synthetic HTTP test')
        access.bootstrap_grant(user, workspace.catalog.entity_id, 'owner', reason='Synthetic HTTP test', retry_key='owner')
        token = access.login('synthetic-owner', 'Synthetic HTTP fixture passphrase')
        _fixtures[root] = temp, access, user, token
    _, access, user, token = _fixtures[root]
    server = authenticated_server(directory, access_db=access.path, **options)
    server.workspace = workspace  # Trusted fixture construction, never a HTTP fallback.
    server.test_user_id = user
    server.csrf_token = secrets.token_urlsafe(32)
    server.browsers[hashlib.sha256(token.encode()).hexdigest()] = dict(entity_id=workspace.catalog.entity_id, csrf_token=server.csrf_token)
    server.test_headers = {'Cookie': 'ah_session=' + token, 'X-Entity-ID': workspace.catalog.entity_id}
    return server
