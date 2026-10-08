"""Local identity/session policy. Financial primitives remain trusted internal APIs.

Only token + registered entity + fixed operation is authority. ``perform`` holds
an SQLite write lock through a SHORT application callback and its financial commit.
Never put provider/network work in that callback: authorize, release, call provider,
then perform/recheck each resulting tool effect. HTTP wiring is a separate layer.
Bootstrap methods are exclusively for the local file-owning administrative CLI.
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

READ = frozenset({'read_evidence', 'read_drafts', 'read_reports', 'read_audit'})
PREPARE = frozenset({'register_evidence', 'prepare_proposal', 'revise_proposal',
    'import_bank_csv', 'classify_bank', 'match_bank', 'withdraw_bank_match',
    'record_timing', 'withdraw_timing', 'manage_scenarios', 'manage_time',
    'manage_allocations', 'start_run', 'cancel_run'})
REVIEW = frozenset({'reject_proposal', 'approve_post', 'confirm_reconciliation',
                    'confirm_close', 'authorize_export'})
ROLE_OPERATIONS = MappingProxyType({'preparer': READ | PREPARE,
    'reviewer': READ | REVIEW, 'owner': READ | PREPARE | REVIEW | {'activate_accounts', 'manage_grants'}})
SCHEMA_VERSION = 1
APPLICATION_ID = 0x41484341
PARAMETERS = dict(algorithm='scrypt', n=2**17, r=8, p=1, dklen=32)
MAXMEM = 256 * 1024 * 1024
_KDF_SLOTS = threading.BoundedSemaphore(2)
SCHEMA = (
    """CREATE TABLE users (user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
        password_record TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)),
        credential_version INTEGER NOT NULL DEFAULT 1 CHECK(credential_version > 0)) STRICT""",
    """CREATE TABLE entities (entity_id TEXT PRIMARY KEY, workspace_path TEXT NOT NULL UNIQUE,
        context_digest TEXT NOT NULL CHECK(length(context_digest)=64)) STRICT""",
    """CREATE TABLE grants (user_id TEXT NOT NULL REFERENCES users(user_id),
        entity_id TEXT NOT NULL REFERENCES entities(entity_id),
        role TEXT NOT NULL CHECK(role IN ('preparer','reviewer','owner')),
        PRIMARY KEY(user_id,entity_id)) STRICT""",
    """CREATE TABLE sessions (token_hash TEXT PRIMARY KEY CHECK(length(token_hash)=64),
        user_id TEXT NOT NULL REFERENCES users(user_id), issued_at INTEGER NOT NULL,
        last_activity INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
        CHECK(last_activity >= issued_at), CHECK(expires_at=issued_at+28800)) STRICT""",
    """CREATE TABLE login_attempts (sequence INTEGER PRIMARY KEY, username TEXT NOT NULL,
        attempted_at INTEGER NOT NULL) STRICT""",
    "CREATE INDEX login_window ON login_attempts(attempted_at)",
    """CREATE TABLE access_audit (sequence INTEGER PRIMARY KEY, action TEXT NOT NULL,
        user_id TEXT, entity_id TEXT, role TEXT, actor_id TEXT NOT NULL,
        recorded_at INTEGER NOT NULL, reason TEXT NOT NULL CHECK(length(trim(reason))>0),
        retry_key TEXT, request_digest TEXT,
        UNIQUE(entity_id,action,retry_key)) STRICT""",
    """CREATE TRIGGER immutable_access_audit_update BEFORE UPDATE ON access_audit
        BEGIN SELECT RAISE(ABORT, 'access audit is immutable'); END""",
    """CREATE TRIGGER immutable_access_audit_delete BEFORE DELETE ON access_audit
        BEGIN SELECT RAISE(ABORT, 'access audit is immutable'); END""",
    """CREATE TRIGGER immutable_session_identity
        BEFORE UPDATE OF token_hash,user_id,issued_at,expires_at ON sessions
        BEGIN SELECT RAISE(ABORT, 'session identity is immutable'); END""",
    """CREATE TRIGGER immutable_user_identity BEFORE UPDATE OF user_id, username ON users
        BEGIN SELECT RAISE(ABORT, 'user identity is immutable'); END""",
)


class AccessDenied(PermissionError):
    def __init__(self):
        super().__init__('Access denied')


class AuthenticationFailed(AccessDenied):
    def __init__(self, retry_at=None):
        self.retry_at = retry_at
        PermissionError.__init__(self, 'Login failed')


class LoginThrottled(AuthenticationFailed):
    """The persisted attempt window supplies retry_at; no handler sleeps."""


class AccessBusy(RuntimeError):
    """A bounded identity lock/KDF admission was unavailable; retry later."""


class CredentialError(ValueError):
    """Unsupported credential format, passphrase or unavailable scrypt."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Server-derived information, never a reusable authorization credential."""
    user_id: str
    entity_id: str
    role: str
    capabilities: frozenset[str]
    workspace_path: Path


def _text(value, label, maximum=256):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError(f'{label} must be nonblank bounded text without surrounding whitespace')
    return value


def _password(value):
    try:
        if type(value) is not str or not 15 <= len(value) <= 256:
            raise CredentialError('Passphrase must contain 15–256 Unicode characters and at most 1024 UTF-8 bytes')
        encoded = value.encode('utf-8')
        if len(encoded) > 1024:
            raise CredentialError('Passphrase exceeds 1024 UTF-8 bytes')
        return encoded
    except UnicodeError as error:
        raise CredentialError('Passphrase must be valid Unicode') from error


def _record(raw):
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate credential key')
                result[key] = value
            return result
        record = json.loads(raw, object_pairs_hook=unique)
        if type(record) is not dict or set(record) != set(PARAMETERS) | {'salt', 'verifier'}:
            raise ValueError('credential fields')
        for key, value in PARAMETERS.items():
            if type(record[key]) is not type(value) or record[key] != value:
                raise ValueError('credential parameters')
        for key, size in (('salt', 32), ('verifier', 64)):
            if type(record[key]) is not str or not re.fullmatch('[0-9a-f]{' + str(size) + '}', record[key]):
                raise ValueError('credential bytes')
        return record
    except (TypeError, ValueError) as error:
        raise CredentialError('Unsupported or malformed password verifier') from error


def _token_hash(token):
    if type(token) is not str or not re.fullmatch('[0-9a-f]{64}', token):
        raise AccessDenied()
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def _utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


def stored_entity_context(directory):
    """Inspect provisioned financial identity read-only, without constructing Workspace."""
    root = Path(directory).resolve()
    try:
        with closing(sqlite3.connect((root / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)) as connection:
            rows = connection.execute('SELECT entity_id, canonical FROM ledger_context WHERE singleton=1').fetchall()
        if len(rows) != 1:
            raise ValueError('Missing immutable ledger identity')
        entity, canonical = rows[0]
        context = json.loads(canonical)
        if context['catalog']['entity_id'] != entity:
            raise ValueError('Ledger identity disagrees with catalog')
        with closing(sqlite3.connect((root / 'sources.sqlite3').as_uri() + '?mode=ro', uri=True)) as connection:
            sources = connection.execute('SELECT entity_id FROM registry_context').fetchall()
        if sources != [(entity,)]:
            raise ValueError('Source identity disagrees with ledger')
        return entity, hashlib.sha256(canonical.encode()).hexdigest()
    except (sqlite3.Error, KeyError, TypeError, OSError) as error:
        raise ValueError('Workspace must have a valid provisioned ledger and source identity') from error


def provision_synthetic_workspace(directory, entity_id):
    """Trusted local provisioning only: a NEW directory, entity catalog and evidence."""
    from accounting_harness.workspace import Workspace
    _text(entity_id, 'entity ID')
    root = Path(directory).resolve()
    if root.exists():
        raise ValueError('Synthetic provisioning requires a new directory; existing books cannot be renamed')
    root.mkdir(parents=True)
    return Workspace(root, entity_id=entity_id)


class AccessStore:
    """One connection per operation; safe across threads/processes sharing this file."""
    def __init__(self, path, *, clock=None):
        self.path = Path(path).resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._transaction() as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            application = connection.execute('PRAGMA application_id').fetchone()[0]
            if version == SCHEMA_VERSION and application == APPLICATION_ID:
                return
            if version or application:
                raise ValueError('Unsupported access schema/application version')
            if connection.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
                raise ValueError('Refusing nonempty unversioned access database')
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
            connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException as error:
            connection.rollback()
            if isinstance(error, sqlite3.OperationalError) and getattr(error, 'sqlite_errorcode', 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise AccessBusy('Identity database busy; retry later') from error
            raise
        finally:
            connection.close()

    def _now(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset().total_seconds() != 0:
            raise ValueError('Identity clock must return an aware UTC datetime')
        return int(now.timestamp())

    @contextmanager
    def _kdf_slot(self):
        # ponytail: two process-wide slots plus two advisory file locks per store;
        # deployment is local Unix (macOS/Linux), not an internet identity service.
        if not _KDF_SLOTS.acquire(blocking=False):
            raise AccessBusy('Credential capacity busy; retry later')
        descriptor = None
        try:
            for slot in range(2):
                candidate = os.open(str(self.path) + f'-kdf-{slot}', os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(candidate)
                else:
                    descriptor = candidate
                    break
            if descriptor is None:
                raise AccessBusy('Credential capacity busy; retry later')
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)  # OS releases the slot even after process death.
            _KDF_SLOTS.release()

    def _derive(self, password, salt):
        if not callable(getattr(hashlib, 'scrypt', None)):
            raise CredentialError('This Python requires hashlib.scrypt support')
        with self._kdf_slot():
            return hashlib.scrypt(password, salt=salt, n=2**17, r=8, p=1, dklen=32, maxmem=MAXMEM)

    def _new_password(self, password):
        encoded = _password(password)
        salt = secrets.token_bytes(16)
        verifier = self._derive(encoded, salt)
        return json.dumps(dict(PARAMETERS, salt=salt.hex(), verifier=verifier.hex()), sort_keys=True)

    @staticmethod
    def _audit(connection, action, actor_id, now, reason, *, user_id=None, entity_id=None,
               role=None, retry_key=None, request_digest=None):
        cursor = connection.execute('''INSERT INTO access_audit
            (action,user_id,entity_id,role,actor_id,recorded_at,reason,retry_key,request_digest)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (action,user_id,entity_id,role,actor_id,now,reason,retry_key,request_digest))
        return cursor.lastrowid

    def create_user(self, username, password, *, reason):
        """Trusted local bootstrap; no implicit entity grant."""
        _text(username, 'username', 128)
        _text(reason, 'reason', 1000)
        record = self._new_password(password)
        user_id = 'user-' + secrets.token_hex(16)
        with self._transaction() as connection:
            connection.execute('INSERT INTO users(user_id,username,password_record) VALUES(?,?,?)',
                               (user_id,username,record))
            self._audit(connection, 'create_user', 'local-bootstrap', self._now(), reason, user_id=user_id)
        return user_id

    def user_id(self, username):
        """Trusted CLI lookup; never exposed as an unauthenticated user-discovery API."""
        _text(username, 'username', 128)
        with self._transaction() as connection:
            row = connection.execute('SELECT user_id FROM users WHERE username=?', (username,)).fetchone()
            if row is None:
                raise ValueError('Unknown local user')
            return row['user_id']

    def register_entity(self, entity_id, directory, *, reason):
        _text(entity_id, 'entity ID')
        _text(reason, 'reason', 1000)
        root = Path(directory).resolve()
        if self.path.is_relative_to(root):
            raise ValueError('Identity storage must be outside the financial workspace')
        stored_id, context_digest = stored_entity_context(root)
        if stored_id != entity_id:
            raise ValueError('Requested entity does not match immutable workspace identity')
        with self._transaction() as connection:
            prior = connection.execute('SELECT workspace_path, context_digest FROM entities WHERE entity_id=?', (entity_id,)).fetchone()
            if prior is not None:
                if tuple(prior) != (str(root),context_digest):
                    raise ValueError('Entity mapping is immutable')
                return entity_id
            connection.execute('INSERT INTO entities VALUES(?,?,?)', (entity_id,str(root),context_digest))
            self._audit(connection, 'register_entity', 'local-bootstrap', self._now(), reason, entity_id=entity_id)
        return entity_id

    def _retry_at(self, connection, username, now):
        rows = connection.execute('SELECT username,attempted_at FROM login_attempts WHERE attempted_at>? ORDER BY attempted_at,sequence', (now-300,)).fetchall()
        user_times = [row['attempted_at'] for row in rows if row['username'] == username]
        deadlines = []
        if len(rows) >= 30:
            deadlines.append(rows[len(rows)-30]['attempted_at']+300)
        if len(user_times) >= 5:
            deadlines.append(user_times[len(user_times)-5]+300)
        return _utc(max(deadlines)) if deadlines else None

    def login(self, username, password):
        # Bound text before storage/KDF; malformed input has the generic login error.
        try:
            _text(username, 'username', 128)
            encoded = _password(password)
        except (TypeError, ValueError):
            raise AuthenticationFailed() from None
        with self._transaction() as connection:
            now = self._now()
            retry_at = self._retry_at(connection, username, now)
            if retry_at is not None:
                raise LoginThrottled(retry_at)
            connection.execute('DELETE FROM login_attempts WHERE attempted_at<=?', (now-300,))
            connection.execute('INSERT INTO login_attempts(username,attempted_at) VALUES(?,?)', (username,now))
            row = connection.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            retry_at = self._retry_at(connection, username, now)
        # Reserve the attempt durably before the expensive operation, without a DB lock.
        valid_record = True
        try:
            record = _record(row['password_record']) if row else None
        except CredentialError:
            record, valid_record = None, False
        salt = bytes.fromhex(record['salt']) if record else bytes(16)
        expected = bytes.fromhex(record['verifier']) if record else bytes(32)
        derived = self._derive(encoded, salt)
        matches = secrets.compare_digest(derived, expected)
        if row is None or not valid_record or not matches or row['disabled']:
            raise AuthenticationFailed(retry_at)
        token = secrets.token_hex(32)
        with self._transaction() as connection:
            # Reset/disable may have won while the KDF ran. Never mint a stale session.
            current = connection.execute('SELECT disabled,credential_version FROM users WHERE user_id=?', (row['user_id'],)).fetchone()
            if current is None or current['disabled'] or current['credential_version'] != row['credential_version']:
                raise AuthenticationFailed(retry_at)
            now = self._now()
            connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?,NULL)',
                               (_token_hash(token),row['user_id'],now,now,now+28800))
        return token

    def logout(self, token):
        token_hash = _token_hash(token)
        with self._transaction() as connection:
            connection.execute('UPDATE sessions SET revoked_at=COALESCE(revoked_at,?) WHERE token_hash=?', (self._now(),token_hash))

    def reset_password(self, user_id, password, *, reason):
        _text(reason, 'reason', 1000)
        record = self._new_password(password)
        with self._transaction() as connection:
            if not connection.execute('UPDATE users SET password_record=?, credential_version=credential_version+1 WHERE user_id=?', (record,user_id)).rowcount:
                raise ValueError('Unknown local user')
            now = self._now()
            connection.execute('UPDATE sessions SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?', (now,user_id))
            self._audit(connection, 'reset_password', 'local-bootstrap', now, reason, user_id=user_id)

    def disable_user(self, user_id, *, reason):
        _text(reason, 'reason', 1000)
        with self._transaction() as connection:
            if not connection.execute('UPDATE users SET disabled=1,credential_version=credential_version+1 WHERE user_id=?', (user_id,)).rowcount:
                raise ValueError('Unknown local user')
            now = self._now()
            connection.execute('UPDATE sessions SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?', (now,user_id))
            self._audit(connection, 'disable_user', 'local-bootstrap', now, reason, user_id=user_id)

    def _authorize(self, connection, token, entity_id, operation):
        token_hash = _token_hash(token)
        if type(entity_id) is not str or type(operation) is not str:
            raise AccessDenied()
        now = self._now()
        row = connection.execute('''SELECT s.*,u.disabled,g.role,e.workspace_path,e.context_digest
            FROM sessions s JOIN users u USING(user_id)
            JOIN grants g ON g.user_id=u.user_id AND g.entity_id=?
            JOIN entities e ON e.entity_id=g.entity_id WHERE s.token_hash=?''', (entity_id,token_hash)).fetchone()
        if (row is None or row['disabled'] or row['revoked_at'] is not None
            or not row['issued_at'] <= row['last_activity'] <= now
            or now >= row['expires_at'] or now-row['last_activity'] >= 1800
            or operation not in ROLE_OPERATIONS.get(row['role'], frozenset())):
            raise AccessDenied()
        path = Path(row['workspace_path'])
        try:
            identity = stored_entity_context(path)
        except ValueError:
            raise AccessDenied() from None
        if identity != (entity_id,row['context_digest']):
            raise AccessDenied()
        connection.execute('UPDATE sessions SET last_activity=? WHERE token_hash=?', (now,token_hash))
        return Principal(row['user_id'],entity_id,row['role'],ROLE_OPERATIONS[row['role']],path)

    def authorize(self, token, entity_id, operation):
        """Resolve current authority. Recheck with perform before any later effect."""
        with self._transaction() as connection:
            return self._authorize(connection, token, entity_id, operation)

    def perform(self, token, entity_id, operation, callback):
        """Trusted application callback only; lock lasts through its commit/return.

        Do not accept callbacks/operation strings from model output or dispatch a
        request-selected method. The application chooses one fixed operation per
        handler. No network, provider calls, or recursive AccessStore mutations.
        """
        # ponytail: one per-store SQLite writer serializes local privilege changes;
        # move to finer-grained authority coordination only if throughput demands it.
        with self._transaction() as connection:
            principal = self._authorize(connection, token, entity_id, operation)
            return callback(principal)

    def _change_grant(self, token, user_id, entity_id, role, reason, retry_key, *, bootstrap):
        for value, label in ((user_id,'user ID'), (entity_id,'entity ID'), (retry_key,'retry key')):
            _text(value, label)
        _text(reason, 'reason', 1000)
        if role is not None and (type(role) is not str or role not in ROLE_OPERATIONS):
            raise ValueError('Unknown entity role')
        action = 'revoke' if role is None else 'grant'
        with self._transaction() as connection:
            actor = 'local-bootstrap' if bootstrap else self._authorize(connection, token, entity_id, 'manage_grants').user_id
            request_digest = hashlib.sha256(json.dumps([user_id,entity_id,role,reason,actor]).encode()).hexdigest()
            previous = connection.execute('SELECT sequence,request_digest FROM access_audit WHERE entity_id=? AND action=? AND retry_key=?', (entity_id,action,retry_key)).fetchone()
            if previous:
                if previous['request_digest'] != request_digest:
                    raise ValueError('Grant retry key conflicts with original request')
                return previous['sequence']
            if not connection.execute('SELECT 1 FROM users WHERE user_id=?', (user_id,)).fetchone() or not connection.execute('SELECT 1 FROM entities WHERE entity_id=?', (entity_id,)).fetchone():
                raise ValueError('Unknown local user or registered entity')
            if role is None:
                connection.execute('DELETE FROM grants WHERE user_id=? AND entity_id=?', (user_id,entity_id))
            else:
                connection.execute('INSERT INTO grants VALUES(?,?,?) ON CONFLICT(user_id,entity_id) DO UPDATE SET role=excluded.role', (user_id,entity_id,role))
            return self._audit(connection, action, actor, self._now(), reason, user_id=user_id,
                               entity_id=entity_id, role=role, retry_key=retry_key, request_digest=request_digest)

    def bootstrap_grant(self, user_id, entity_id, role, *, reason, retry_key):
        return self._change_grant(None, user_id, entity_id, role, reason, retry_key, bootstrap=True)

    def bootstrap_revoke(self, user_id, entity_id, *, reason, retry_key):
        return self._change_grant(None, user_id, entity_id, None, reason, retry_key, bootstrap=True)

    def grant(self, token, user_id, entity_id, role, *, reason, retry_key):
        return self._change_grant(token, user_id, entity_id, role, reason, retry_key, bootstrap=False)

    def revoke(self, token, user_id, entity_id, *, reason, retry_key):
        return self._change_grant(token, user_id, entity_id, None, reason, retry_key, bootstrap=False)
