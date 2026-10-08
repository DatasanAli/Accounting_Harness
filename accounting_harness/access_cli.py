"""Trusted local identity administration: interactive secrets, explicit grants."""
import getpass
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.access import AccessStore, AccessDenied, CredentialError, provision_synthetic_workspace


def add_access_commands(commands):
    commands.add_parser('demo-access', help='demonstrate synthetic identities, sessions and entity boundaries; HTTP protection follows separately')
    for name, help_text in (
        ('create-user', 'create a local user with an interactive passphrase and no grants'),
        ('reset-password', 'reset a local password interactively and revoke all sessions'),
        ('disable-user', 'disable a local user and revoke all sessions'),
        ('provision', 'provision a NEW synthetic entity workspace and register its identity'),
        ('map-entity', 'register an EXISTING workspace after reading its immutable identity'),
        ('grant', 'grant one local user an explicit entity role'),
        ('revoke', 'revoke one local user entity membership')):
        command = commands.add_parser('access-' + name, help=help_text)
        command.add_argument('--access-db', required=True, help='identity database outside financial workspaces')
        command.add_argument('--reason', required=True, help='audit reason; never include secrets')
        if name in ('provision', 'map-entity'):
            command.add_argument('--workspace', required=True)
            command.add_argument('--entity', required=True)
        else:
            command.add_argument('--username', required=True)
        if name in ('grant', 'revoke'):
            command.add_argument('--entity', required=True)
            command.add_argument('--retry-key', required=True)
        if name == 'grant':
            command.add_argument('--role', choices=('preparer', 'reviewer', 'owner'), required=True)


def _interactive_password():
    # Fail instead of getpass's fallback that can echo a secret in noninteractive logs.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            password = getpass.getpass('Passphrase: ')
            repeated = getpass.getpass('Repeat passphrase: ')
        except (getpass.GetPassWarning, EOFError) as error:
            raise CredentialError('A terminal with hidden passphrase entry is required') from error
    if password != repeated:
        raise CredentialError('Passphrases do not match')
    return password


def access_command(args):
    store = AccessStore(args.access_db)
    name = args.command.removeprefix('access-')
    if name == 'create-user':
        user_id = store.create_user(args.username, _interactive_password(), reason=args.reason)
        print(f'Created {user_id}; no entity grants assigned.')
    elif name in ('provision', 'map-entity'):
        if name == 'provision':
            root = Path(args.workspace).resolve()
            if store.path.is_relative_to(root):
                raise ValueError('Identity storage must be outside the financial workspace')
            provision_synthetic_workspace(root, args.entity)
        store.register_entity(args.entity, args.workspace, reason=args.reason)
        print(f'Registered entity {args.entity}.')
    else:
        user_id = store.user_id(args.username)
        if name == 'reset-password':
            store.reset_password(user_id, _interactive_password(), reason=args.reason)
        else:
            confirmation = name.upper()
            if input(f'Type {confirmation} to {name} {args.username}: ') != confirmation:
                raise ValueError('Administration cancelled; no user/grant changes made')
            if name == 'disable-user':
                store.disable_user(user_id, reason=args.reason)
            elif name == 'grant':
                store.bootstrap_grant(user_id, args.entity, args.role, reason=args.reason, retry_key=args.retry_key)
            elif name == 'revoke':
                store.bootstrap_revoke(user_id, args.entity, reason=args.reason, retry_key=args.retry_key)
        print(f'Completed {name} for {user_id}.')


def demo_access():
    with TemporaryDirectory(prefix='accounting-access-') as directory:
        root = Path(directory)
        now = [datetime(2026, 10, 8, 12, tzinfo=timezone.utc)]
        store = AccessStore(root / 'identities.sqlite3', clock=lambda: now[0])
        for entity in ('synthetic-access-a', 'synthetic-access-b'):
            provision_synthetic_workspace(root / entity, entity)
            store.register_entity(entity, root / entity, reason='synthetic demo')
        # Constructed temporary fixture only; no default application credential.
        password = 'Temporary synthetic access demonstration ' + root.name
        user = store.create_user('synthetic-preparer', password, reason='synthetic demo')
        store.create_user('synthetic-other', password + ' other', reason='synthetic demo')
        store.bootstrap_grant(user, 'synthetic-access-a', 'preparer', reason='synthetic demo', retry_key='preparer')
        token = store.login('synthetic-preparer', password)
        def prepare(principal):
            from accounting_harness.workspace import Workspace
            workspace = Workspace(principal.workspace_path, entity_id=principal.entity_id)
            document = next(c['document'] for c in workspace.cases if c['id'] == 'rent-standard')
            proposal = dict(id='access-rent-journal', entity_id=principal.entity_id, currency='USD',
                effective_date=document['document_date'], description='Synthetic authenticated rent proposal',
                source_ids=[document['document_id']], lines=[
                    dict(account='5000', side='debit', amount=document['amount']),
                    dict(account='1000', side='credit', amount=document['amount'])])
            with workspace.storage() as (registry, ledger, reviews, _, _):
                source = registry.get(document['document_id'])
                revision = reviews.save('access-rent', proposal,
                    evidence={source.document_id: source.content_digest}, expected_revision=0,
                    actor_id=principal.user_id, idempotency_key='access-rent', reason='Synthetic authenticated preparation')
                assert revision.reviewable and revision.actor_id == user
                assert ledger.counts()['journals'] == 0
                return revision
        revision = store.perform(token, 'synthetic-access-a', 'prepare_proposal', prepare)
        assert revision.revision == 1
        print('Saved reviewable revision 1; 0 posted journals; authenticated actor retained.')
        print('ALLOWED preparation in entity A with server-derived preparer identity.')
        def denied(label, session, entity, operation):
            try:
                store.perform(session, entity, operation, lambda _: (_ for _ in ()).throw(AssertionError('Unauthorized callback ran')))
            except AccessDenied:
                print('DENIED ' + label + '.')
            else:
                raise AssertionError('Expected denial')
        denied('approval', token, 'synthetic-access-a', 'approve_post')
        denied('cross-entity read', token, 'synthetic-access-b', 'read_reports')
        store.logout(token)
        denied('revoked session', token, 'synthetic-access-a', 'read_reports')
        token = store.login('synthetic-preparer', password)
        now[0] += timedelta(minutes=30)
        denied('expired session', token, 'synthetic-access-a', 'read_reports')
        print('Two distinct synthetic entity catalogs and evidence registries; temporary credentials removed.')
        print('Identity core only; existing HTTP workspace protection is the separate Step 29b delivery.')
