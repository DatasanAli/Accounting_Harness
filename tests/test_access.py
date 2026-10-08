"""Synthetic local identity, lifecycle and authorization boundary checks."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


from accounting_harness.access import (AccessStore, AccessDenied, AuthenticationFailed,
    LoginThrottled, AccessBusy, CredentialError, provision_synthetic_workspace)


PASSWORD = 'Synthetic passphrase only 29a!'


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


class AccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.root = Path(cls.fixture.name).resolve()
        provision_synthetic_workspace(cls.root / 'a', 'synthetic-entity-a')
        provision_synthetic_workspace(cls.root / 'b', 'synthetic-entity-b')
        store = AccessStore(cls.root / 'template.sqlite3', clock=Clock())
        cls.user = store.create_user('preparer', PASSWORD, reason='synthetic setup')
        cls.owner = store.create_user('owner', PASSWORD, reason='synthetic setup')
        cls.reviewer = store.create_user('reviewer', PASSWORD, reason='synthetic setup')
        for entity in ('a', 'b'):
            store.register_entity('synthetic-entity-' + entity, cls.root / entity, reason='synthetic setup')
        for user, role in ((cls.user, 'preparer'), (cls.owner, 'owner'), (cls.reviewer, 'reviewer')):
            store.bootstrap_grant(user, 'synthetic-entity-a', role, reason='synthetic setup', retry_key=role)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'access.sqlite3'
        shutil.copyfile(self.root / 'template.sqlite3', self.path)
        self.clock = Clock()
        self.store = AccessStore(self.path, clock=self.clock)

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            return connection.execute(sql, params).fetchall()

    def token(self, username='preparer'):
        return self.store.login(username, PASSWORD)

    def test_preparer_can_prepare_but_not_approve_or_access_other_entity(self):
        token = self.token()
        effects = []
        result = self.store.perform(token, 'synthetic-entity-a', 'prepare_proposal',
                                    lambda principal: effects.append(principal.user_id) or 'prepared')
        self.assertEqual(result, 'prepared')
        self.assertEqual(effects, [self.user])
        for entity, operation in [('synthetic-entity-a', 'approve_post'),
                                  ('synthetic-entity-b', 'read_reports'),
                                  ('synthetic-entity-b', 'prepare_proposal'),
                                  ('synthetic-entity-a', 'unknown')]:
            with self.subTest(entity=entity, operation=operation), self.assertRaises(AccessDenied):
                self.store.perform(token, entity, operation, lambda _: effects.append('forbidden'))
        self.assertEqual(effects, [self.user])

    def test_reviewer_and_owner_fixed_policy(self):
        reviewer, owner = self.token('reviewer'), self.token('owner')
        for operation in ('read_evidence', 'read_drafts', 'read_reports', 'read_audit',
                          'reject_proposal', 'approve_post', 'confirm_reconciliation', 'confirm_close', 'authorize_export'):
            self.assertEqual(self.store.authorize(reviewer, 'synthetic-entity-a', operation).role, 'reviewer')
        for operation in ('prepare_proposal', 'register_evidence', 'activate_accounts', 'manage_grants'):
            with self.assertRaises(AccessDenied):
                self.store.authorize(reviewer, 'synthetic-entity-a', operation)
            self.assertEqual(self.store.authorize(owner, 'synthetic-entity-a', operation).user_id, self.owner)

    def test_forged_principals_and_unknown_roles_deny(self):
        for forged in ({'user_id': self.owner, 'role': 'owner'}, None, '', 'bad-token'):
            with self.subTest(forged=type(forged)), self.assertRaises(AccessDenied):
                self.store.authorize(forged, 'synthetic-entity-a', 'approve_post')
        with self.assertRaises(ValueError):
            self.store.bootstrap_grant(self.user, 'synthetic-entity-b', 'superuser', reason='test', retry_key='bad')

    def test_new_user_has_no_implicit_grants(self):
        user = self.store.create_user('new', PASSWORD, reason='synthetic new user')
        token = self.token('new')
        self.assertNotEqual(user, self.user)
        with self.assertRaises(AccessDenied):
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')

    def test_verifiers_are_salted_real_scrypt_and_tokens_are_never_stored(self):
        rows = self.query('SELECT password_record FROM users ORDER BY user_id')
        records = [json.loads(row[0]) for row in rows]
        self.assertEqual(len({record['salt'] for record in records}), 3)
        record = records[0]
        self.assertEqual({k: record[k] for k in ('algorithm', 'n', 'r', 'p', 'dklen')},
                         dict(algorithm='scrypt', n=131072, r=8, p=1, dklen=32))
        derived = hashlib.scrypt(PASSWORD.encode(), salt=bytes.fromhex(record['salt']),
                                n=131072, r=8, p=1, dklen=32, maxmem=268435456)
        self.assertEqual(derived.hex(), record['verifier'])
        token = self.token()
        self.assertEqual(len(bytes.fromhex(token)), 32)
        self.assertEqual(self.query('SELECT token_hash FROM sessions'), [(hashlib.sha256(token.encode()).hexdigest(),)])
        raw = self.path.read_bytes()
        self.assertNotIn(PASSWORD.encode(), raw)
        self.assertNotIn(token.encode(), raw)

    def test_wrong_and_unknown_passwords_have_same_failure(self):
        failures = []
        for username in ('preparer', 'absent'):
            with self.assertRaises(AuthenticationFailed) as caught:
                self.store.login(username, 'Incorrect synthetic password')
            failures.append((str(caught.exception), caught.exception.retry_at))
        self.assertEqual(failures[0], failures[1])
        self.assertEqual(self.query('SELECT count(*) FROM sessions'), [(0,)])

    def test_malformed_verifiers_fail_closed_without_accepting_changed_parameters(self):
        original = self.query('SELECT password_record FROM users WHERE user_id=?', (self.user,))[0][0]
        for change in ({'algorithm': 'plain'}, {'n': 2}, {'n': True}, {'salt': '00'},
                       {'verifier': 'z' * 64}, {'dklen': 16}, {'p': 0}):
            with self.subTest(change=change):
                record = json.loads(original)
                record.update(change)
                self.query('UPDATE users SET password_record=? WHERE user_id=?', (json.dumps(record), self.user))
                with self.assertRaises(AuthenticationFailed):
                    self.store.login('preparer', PASSWORD)
                self.clock.advance(minutes=5)
        self.assertEqual(self.query('SELECT count(*) FROM sessions'), [(0,)])

    def test_passphrase_bounds_and_no_trimming_or_normalization(self):
        for password in ('short', 'x'*257, '\ud800'*15):
            with self.subTest(length=len(password)), self.assertRaises(CredentialError):
                self.store.create_user('invalid', password, reason='synthetic test')
        exact = '  Synthetic café passphrase  '
        self.store.create_user('unicode', exact, reason='synthetic test')
        self.store.login('unicode', exact)
        for changed in (exact.strip(), exact.replace('é', 'e\u0301')):
            with self.assertRaises(AuthenticationFailed):
                self.store.login('unicode', changed)

    def test_missing_scrypt_fails_clearly(self):
        with patch('accounting_harness.access.hashlib.scrypt', None):
            with self.assertRaisesRegex(CredentialError, 'scrypt'):
                self.store.create_user('unavailable', PASSWORD, reason='test')

    def test_sessions_rotate_on_each_login_and_logout_revokes(self):
        first, second = self.token(), self.token()
        self.assertNotEqual(first, second)
        self.store.logout(first)
        with self.assertRaises(AccessDenied):
            self.store.authorize(first, 'synthetic-entity-a', 'read_reports')
        self.store.authorize(second, 'synthetic-entity-a', 'read_reports')
        self.store.logout(first)  # An exact logout retry remains safe.

    def test_idle_expiry_and_activity_extension(self):
        token = self.token()
        self.clock.advance(minutes=29)
        self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        self.clock.advance(minutes=29)
        self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        self.clock.advance(minutes=30)
        with self.assertRaises(AccessDenied):
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')

    def test_absolute_expiry_cannot_be_extended_by_activity(self):
        token = self.token()
        for _ in range(16):
            self.clock.advance(minutes=29)
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        self.clock.advance(minutes=16)
        with self.assertRaises(AccessDenied):
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')

    def test_reset_and_disable_revoke_existing_sessions(self):
        token = self.token()
        replacement = 'Replacement synthetic phrase!'
        self.store.reset_password(self.user, replacement, reason='synthetic reset')
        with self.assertRaises(AccessDenied):
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        with self.assertRaises(AuthenticationFailed):
            self.token()
        token = self.store.login('preparer', replacement)
        self.store.disable_user(self.user, reason='synthetic disabled')
        with self.assertRaises(AccessDenied):
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        with self.assertRaises(AuthenticationFailed):
            self.store.login('preparer', replacement)
        events = self.query('SELECT action, actor_id, reason FROM access_audit ORDER BY sequence')
        self.assertIn(('reset_password', 'local-bootstrap', 'synthetic reset'), events)
        self.assertIn(('disable_user', 'local-bootstrap', 'synthetic disabled'), events)

    def test_revoked_grant_blocks_existing_session_and_old_retry(self):
        owner = self.token('owner')
        self.store.grant(owner, self.user, 'synthetic-entity-a', 'preparer', reason='test', retry_key='grant')
        token = self.token()
        self.store.bootstrap_revoke(self.user, 'synthetic-entity-a', reason='test', retry_key='remove')
        with self.assertRaises(AccessDenied):
            self.store.perform(token, 'synthetic-entity-a', 'prepare_proposal', lambda _: 'old receipt')
        self.store.bootstrap_revoke(self.owner, 'synthetic-entity-a', reason='test', retry_key='remove-owner')
        with self.assertRaises(AccessDenied):
            self.store.grant(owner, self.user, 'synthetic-entity-a', 'preparer', reason='test', retry_key='grant')

    def test_only_current_owner_can_change_grants_and_retry_keys_are_scoped(self):
        preparer, owner = self.token(), self.token('owner')
        with self.assertRaises(AccessDenied):
            self.store.grant(preparer, self.user, 'synthetic-entity-a', 'owner', reason='self promotion', retry_key='no')
        first = self.store.grant(owner, self.user, 'synthetic-entity-a', 'reviewer', reason='test', retry_key='change')
        repeated = self.store.grant(owner, self.user, 'synthetic-entity-a', 'reviewer', reason='test', retry_key='change')
        self.assertEqual(first, repeated)
        with self.assertRaises(ValueError):
            self.store.grant(owner, self.user, 'synthetic-entity-a', 'owner', reason='test', retry_key='change')
        self.store.bootstrap_grant(self.user, 'synthetic-entity-b', 'preparer', reason='test', retry_key='change')
        with self.assertRaises(AccessDenied):
            self.store.authorize(preparer, 'synthetic-entity-a', 'prepare_proposal')
        self.store.authorize(preparer, 'synthetic-entity-a', 'approve_post')
        audit = self.query("SELECT actor_id, reason FROM access_audit WHERE action='grant' AND retry_key='change' AND entity_id='synthetic-entity-a'")
        self.assertEqual(audit, [(self.owner, 'test')])

    def test_per_username_throttle_is_persisted_and_window_expires(self):
        for _ in range(5):
            with self.assertRaises(AuthenticationFailed):
                self.store.login('absent', PASSWORD)
        reopened = AccessStore(self.path, clock=self.clock)
        with self.assertRaises(LoginThrottled) as caught:
            reopened.login('absent', PASSWORD)
        self.assertEqual(caught.exception.retry_at, self.clock() + timedelta(minutes=5))
        self.clock.advance(minutes=5)
        with self.assertRaises(AuthenticationFailed) as caught:
            reopened.login('absent', PASSWORD)
        self.assertIsNone(caught.exception.retry_at)

    def test_global_throttle_bounds_unknown_usernames(self):
        for i in range(30):
            with self.assertRaises(AuthenticationFailed):
                self.store.login('unknown-' + str(i), PASSWORD)
        with self.assertRaises(LoginThrottled) as caught:
            self.token()
        self.assertEqual(caught.exception.retry_at, self.clock() + timedelta(minutes=5))

    def test_concurrent_issuance_has_distinct_tokens(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = list(pool.map(lambda _: self.token(), range(2)))
        self.assertEqual(len(set(tokens)), 2)
        for token in tokens:
            self.store.authorize(token, 'synthetic-entity-a', 'read_reports')

    def test_at_most_two_kdfs_are_admitted_without_waiting(self):
        entered = threading.Barrier(3)
        release = threading.Event()
        original = hashlib.scrypt
        def controlled(*args, **kwargs):
            entered.wait(timeout=10)
            self.assertTrue(release.wait(10))
            return original(*args, **kwargs)
        with patch('accounting_harness.access.hashlib.scrypt', controlled), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.token) for _ in range(2)]
            entered.wait(timeout=10)
            try:
                with self.assertRaises(AccessBusy):
                    self.token()
            finally:
                release.set()
            self.assertEqual(len({f.result() for f in futures}), 2)

    def test_privileged_callback_commits_before_waiting_revocation(self):
        token = self.token('reviewer')
        entered, release, revoked = threading.Event(), threading.Event(), threading.Event()
        order = []
        def effect(principal):
            entered.set()
            self.assertTrue(release.wait(10))
            order.append('commit')
            return principal.user_id
        def revoke():
            self.store.bootstrap_revoke(self.reviewer, 'synthetic-entity-a', reason='race', retry_key='race')
            order.append('revoke')
            revoked.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            work = pool.submit(self.store.perform, token, 'synthetic-entity-a', 'approve_post', effect)
            self.assertTrue(entered.wait(10))
            removal = pool.submit(revoke)
            self.assertFalse(revoked.wait(.05))
            release.set()
            self.assertEqual(work.result(), self.reviewer)
            removal.result()
        self.assertEqual(order, ['commit', 'revoke'])
        with self.assertRaises(AccessDenied):
            self.store.perform(token, 'synthetic-entity-a', 'approve_post', lambda _: order.append('late'))

    def test_external_work_does_not_hold_authorization_lock_and_resume_rechecks(self):
        token = self.token()
        self.store.authorize(token, 'synthetic-entity-a', 'start_run')
        # Provider work happens after authorize returns; no connection or lock is retained.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(self.store.bootstrap_revoke, self.user, 'synthetic-entity-a', reason='network interval', retry_key='interval').result(timeout=5)
        effects = []
        with self.assertRaises(AccessDenied):
            self.store.perform(token, 'synthetic-entity-a', 'prepare_proposal', lambda _: effects.append('saved'))
        self.assertEqual(effects, [])

    def test_future_schema_fails_without_edits(self):
        self.query('PRAGMA user_version=999')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            AccessStore(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_audit_write_failure_rolls_back_grant_and_retry(self):
        self.query("CREATE TRIGGER fail_audit BEFORE INSERT ON access_audit BEGIN SELECT RAISE(ABORT, 'synthetic fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.bootstrap_grant(self.user, 'synthetic-entity-b', 'owner', reason='fault', retry_key='fault')
        self.assertEqual(self.query("SELECT * FROM grants WHERE entity_id='synthetic-entity-b'"), [])
        self.assertEqual(self.query("SELECT * FROM access_audit WHERE retry_key='fault'"), [])

    def test_two_real_entity_contexts_and_mapping_do_not_edit_financial_files(self):
        from accounting_harness.workspace import Workspace
        for entity in ('a', 'b'):
            path = self.root / entity
            before = {p.name: p.read_bytes() for p in path.glob('*.sqlite3')}
            self.store.register_entity('synthetic-entity-' + entity, path, reason='exact remap')
            self.assertEqual(before, {p.name: p.read_bytes() for p in path.glob('*.sqlite3')})
            workspace = Workspace(path)
            self.assertEqual(workspace.catalog.entity_id, 'synthetic-entity-' + entity)
            with workspace.storage() as (registry, ledger, _, _, _):
                self.assertEqual({s.entity_id for s in registry.list_documents()}, {'synthetic-entity-' + entity})
                self.assertEqual(ledger.snapshot.catalog.entity_id, 'synthetic-entity-' + entity)
        with self.assertRaises(ValueError):
            self.store.register_entity('synthetic-entity-b', self.root / 'a', reason='wrong entity')
        with self.assertRaises(ValueError):
            provision_synthetic_workspace(self.root / 'a', 'rename-attempt')
        with self.assertRaises(ValueError):
            Workspace(self.root / 'a', entity_id='rename-attempt')

    def test_denied_mapping_never_creates_requested_directory(self):
        missing = Path(self.temp.name) / 'missing'
        with self.assertRaises(ValueError):
            self.store.register_entity('missing', missing, reason='test')
        self.assertFalse(missing.exists())

    def test_authorization_returns_only_stored_mapping_and_detects_replaced_context(self):
        token = self.token()
        principal = self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        self.assertEqual(principal.workspace_path, self.root / 'a')
        # Replace only this test's registered mapping with another real entity; verify before callback.
        self.query("UPDATE entities SET context_digest=? WHERE entity_id='synthetic-entity-a'", ('0'*64,))
        with self.assertRaises(AccessDenied):
            self.store.perform(token, 'synthetic-entity-a', 'read_reports', lambda _: self.fail('opened wrong workspace'))

    def test_initialization_failure_rolls_back_all_schema_and_reopens(self):
        from accounting_harness import access
        path = Path(self.temp.name) / 'failed-init.sqlite3'
        with patch.object(access, 'SCHEMA', access.SCHEMA + ('INVALID SQL',)):
            with self.assertRaises(sqlite3.OperationalError):
                AccessStore(path)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(connection.execute('PRAGMA application_id').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT name FROM sqlite_master').fetchall(), [])
        AccessStore(path)

    def test_unknown_stored_role_and_operation_deny_without_callback(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('PRAGMA ignore_check_constraints=ON')
            connection.execute("UPDATE grants SET role='superuser' WHERE user_id=?", (self.user,))
        token = self.token()
        with self.assertRaises(AccessDenied):
            self.store.perform(token, 'synthetic-entity-a', 'read_reports', lambda _: self.fail('unknown role allowed'))

    def test_user_and_session_binding_cannot_be_rewritten(self):
        token = self.token()
        for sql, params in [('UPDATE users SET username=? WHERE user_id=?', ('renamed',self.user)),
                            ('UPDATE sessions SET user_id=? WHERE token_hash=?', (self.owner,hashlib.sha256(token.encode()).hexdigest()))]:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.query(sql, params)

    def test_reset_rollback_preserves_old_password_and_session(self):
        token = self.token()
        self.query("CREATE TRIGGER fail_audit BEFORE INSERT ON access_audit BEGIN SELECT RAISE(ABORT, 'synthetic fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.reset_password(self.user, 'Replacement synthetic password', reason='fault')
        self.store.authorize(token, 'synthetic-entity-a', 'read_reports')
        self.token()

    def test_disable_wins_during_login_and_prevents_session_issuance(self):
        entered, release = threading.Event(), threading.Event()
        original = hashlib.scrypt
        def controlled(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return original(*args, **kwargs)
        with patch('accounting_harness.access.hashlib.scrypt', controlled), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.token)
            self.assertTrue(entered.wait(10))
            self.store.disable_user(self.user, reason='disable during login')
            release.set()
            with self.assertRaises(AuthenticationFailed):
                future.result()
        self.assertEqual(self.query('SELECT count(*) FROM sessions'), [(0,)])

    def test_identity_store_cannot_be_mapped_inside_financial_workspace(self):
        root = Path(self.temp.name) / 'books'
        provision_synthetic_workspace(root, 'synthetic-nested')
        store = AccessStore(root / 'access.sqlite3')
        with self.assertRaises(ValueError):
            store.register_entity('synthetic-nested', root, reason='bad location')

    def test_authenticated_owner_revoke_is_audited_and_immediate(self):
        owner, preparer = self.token('owner'), self.token()
        first = self.store.revoke(owner, self.user, 'synthetic-entity-a', reason='owner removal', retry_key='owner-revoke')
        self.assertEqual(first, self.store.revoke(owner, self.user, 'synthetic-entity-a', reason='owner removal', retry_key='owner-revoke'))
        with self.assertRaises(AccessDenied):
            self.store.authorize(preparer, 'synthetic-entity-a', 'read_reports')
        self.assertEqual(self.query('SELECT actor_id,reason FROM access_audit WHERE sequence=?', (first,)), [(self.owner,'owner removal')])


class AccessCLITests(unittest.TestCase):
    def test_interactive_create_grant_revoke_and_no_password_argument(self):
        from accounting_harness.__main__ import main
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store_path = root / 'identities.sqlite3'
            common = ['--access-db',str(store_path)]
            with contextlib.redirect_stdout(io.StringIO()), patch('getpass.getpass', side_effect=[PASSWORD,PASSWORD]):
                self.assertEqual(main(['access-create-user',*common,'--username','synthetic-cli','--reason','CLI test']), 0)
            store = AccessStore(store_path)
            user = store.user_id('synthetic-cli')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['access-provision',*common,'--workspace',str(root/'books'),'--entity','synthetic-cli-entity','--reason','CLI test']), 0)
            with contextlib.redirect_stdout(io.StringIO()), patch('builtins.input', return_value='GRANT'):
                self.assertEqual(main(['access-grant',*common,'--username','synthetic-cli','--entity','synthetic-cli-entity','--role','preparer','--reason','CLI test','--retry-key','grant']), 0)
            token = store.login('synthetic-cli', PASSWORD)
            self.assertEqual(store.authorize(token, 'synthetic-cli-entity', 'prepare_proposal').user_id, user)
            with contextlib.redirect_stdout(io.StringIO()), patch('builtins.input', return_value='REVOKE'):
                self.assertEqual(main(['access-revoke',*common,'--username','synthetic-cli','--entity','synthetic-cli-entity','--reason','CLI test','--retry-key','revoke']), 0)
            with self.assertRaises(AccessDenied):
                store.authorize(token, 'synthetic-cli-entity', 'read_reports')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(['access-create-user',*common,'--username','forbidden','--reason','test','--password',PASSWORD])
            self.assertEqual(caught.exception.code, 2)

    def test_demo_access_exercises_three_boundaries(self):
        from accounting_harness.__main__ import main
        import contextlib
        import io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['demo-access']), 0)
        for text in ('ALLOWED preparation', 'DENIED approval', 'DENIED cross-entity read', 'DENIED revoked session', 'DENIED expired session', 'Saved reviewable revision 1; 0 posted journals'):
            self.assertIn(text, output.getvalue())
        self.assertNotIn(PASSWORD, output.getvalue())
