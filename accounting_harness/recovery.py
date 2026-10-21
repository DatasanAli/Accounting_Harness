"""Bounded offline group recovery for the known local SQLite workspace roster.

The file-owning administrator is the trust boundary. A manifest detects damage,
not an adversarially authored backup. Local HMAC receipts prevent caller aliases
from becoming run authority; historical rows and logical retry identities survive.
"""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import ctypes
import sys
import hashlib
import hmac
import json
import re
from functools import lru_cache
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import time

from accounting_harness.maintenance import maintenance_lock, workspace_lock, access_lock
from accounting_harness.persistence import PersistenceBusy

REQUIRED = ('sources.sqlite3', 'ledger.sqlite3', 'runs.sqlite3')
OPTIONAL = ('agent-runs.sqlite3', 'qbo-staging.sqlite3', 'qbo-outbox.sqlite3', 'qbo-simulator.sqlite3')
ROSTER = REQUIRED + OPTIONAL
RELOCATION = 'recovery-relocation.json'
RECEIPT = 'recovery-receipt.json'
BACKUP_RECEIPT = 'recovery-backup-receipt.json'
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_MANIFEST = 2 * 1024 * 1024
# Current delivered schemas only. Recovery never performs migration.
SCHEMAS = {'access.sqlite3': (1, 0x41484341), 'sources.sqlite3': (1, 0x41485352),
    'ledger.sqlite3': (6, 0), 'runs.sqlite3': (1, 0x4148524E), 'agent-runs.sqlite3': (1, 0x4148524E),
    'qbo-staging.sqlite3': (1, 0x41485142), 'qbo-outbox.sqlite3': (1, 0x41485145),
    'qbo-simulator.sqlite3': (1, 0x41485153)}
SUBSCHEMAS = {'review_schema':12, 'approval_schema':1, 'payables_schema':3,
    'receivables_schema':2, 'advances_schema':2, 'bank_schema':2, 'bank_fee_schema':1,
    'prepaid_schema':1, 'expense_accrual_schema':1, 'revenue_accrual_schema':1,
    'period_close_schema':1, 'project_dimensions_schema':1, 'project_time_schema':1,
    'project_cost_schema':1, 'budget_schema':1, 'indicator_schema':1, 'reconciliation_schema':1}

SUBTABLES = {
    'review_schema': 'draft_revisions review_events review_requests draft_operation_intents operation_claims',
    'approval_schema': 'approvals approval_requests review_postings approved_post_requests',
    'payables_schema': 'payables_context vendor_bills vendor_bill_payments',
    'receivables_schema': 'receivables_context customer_invoices customer_invoice_collections',
    'advances_schema': 'advances_context customer_advances customer_advance_earnings',
    'bank_schema': 'bank_accounts bank_statements bank_transactions bank_membership bank_receipts bank_match_events bank_match_receipts',
    'bank_fee_schema': 'bank_fee_effects',
    'prepaid_schema': 'prepaid_policies prepaid_claims prepaid_effects',
    'expense_accrual_schema': 'expense_accrual_preparations expense_accrual_effects',
    'revenue_accrual_schema': 'revenue_accrual_preparations revenue_accrual_effects',
    'period_close_schema': 'period_closes',
    'project_dimensions_schema': 'management_projects project_assignment_revisions',
    'project_time_schema': 'project_time_records project_time_voids',
    'project_cost_schema': 'project_cost_versions', 'budget_schema': 'budget_versions',
    'indicator_schema': 'indicator_versions',
    'reconciliation_schema': 'reconciliation_timing reconciliation_completions reconciliation_receipts',
}
TABLES = {
    'access.sqlite3': 'access_audit entities grants login_attempts sessions users',
    'sources.sqlite3': 'registration_events registry_context source_documents',
    'runs.sqlite3': 'run_checkpoints run_context runs', 'agent-runs.sqlite3': 'run_checkpoints run_context runs',
    'qbo-outbox.sqlite3': 'context exports export_events', 'qbo-simulator.sqlite3': 'context receipts',
    'qbo-staging.sqlite3': 'staging_context qbo_batches qbo_events qbo_observations',
    'ledger.sqlite3': 'ledger_context accounts sources source_enrollments journals lines journal_sources posting_events idempotency reversals account_extensions',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate recovery JSON key')
        result[key] = value
    return result


def _load(path, maximum=MAX_MANIFEST):
    _safe(path, file=True)
    if path.stat().st_size > maximum: raise ValueError('Recovery JSON exceeds bound')
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=_object,
                          parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid recovery JSON') from error


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError('Unexpected recovery manifest fields')


def _safe(path, *, file=False):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink(): raise ValueError('Recovery refuses symlink paths')
    if file and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('Recovery requires a regular, singly linked file')
    return path


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def _disjoint(paths):
    for i, a in enumerate(paths):
        if any(_overlap(a,b) for b in paths[i+1:]):
            raise ValueError('Recovery paths overlap')


def _readonly(path):
    return sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=0, isolation_level=None)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, 'x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())


def _replace_receipt(path, value):
    temporary = path.parent / ('.recovery-receipt-' + secrets.token_hex(8) + '.json')
    try:
        _write(temporary, value)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _hit(fault, label):
    if fault: fault(label)


def relocation_record(root):
    """Read only the internally located, physically bound recovery receipt."""
    root = Path(root).resolve()
    path = root / RELOCATION
    if not path.exists(): return None
    value = _load(path)
    _fields(value, 'record seal')
    record = value['record']
    _fields(record, 'version backup_id physical_root logical_root entity_id context_digest ledger_context transports_disabled')
    key_path = root.parent.parent / '.recovery-key'
    _safe(key_path, file=True)
    key = key_path.read_bytes()
    if len(key) != 32 or type(value['seal']) is not str or not hmac.compare_digest(
            hmac.new(key, canonical(record).encode(), hashlib.sha256).hexdigest(), value['seal']):
        raise ValueError('Unverified recovery relocation')
    if type(record['version']) is not int or record['version'] != 1 or record['physical_root'] != str(root) or record['transports_disabled'] is not True:
        raise ValueError('Recovery relocation physical binding differs')
    logical = record['logical_root']
    if type(logical) is not str or not Path(logical).is_absolute() or str(Path(logical)) != logical:
        raise ValueError('Invalid logical recovery origin')
    from accounting_harness.access import stored_entity_context
    if stored_entity_context(root) != (record['entity_id'], record['context_digest']):
        raise ValueError('Recovery relocation entity/context differs')
    return record


def relocated_run_identity(physical_path, scope):
    physical = Path(physical_path)
    record = relocation_record(physical.parent)
    if record is None: return physical_path, scope
    if physical.name not in ('runs.sqlite3', 'agent-runs.sqlite3'):
        raise ValueError('Recovery run file outside verified roster')
    value = json.loads(scope)
    if (value['entity_id'] != record['entity_id'] or value['ledger_context'] != record['ledger_context'] or
        value['ledger_path'] != str(physical.parent / 'ledger.sqlite3') or
        value['registry_path'] != str(physical.parent / 'sources.sqlite3')):
        raise ValueError('Recovery run scope differs')
    value['ledger_path'] = str(Path(record['logical_root']) / 'ledger.sqlite3')
    value['registry_path'] = str(Path(record['logical_root']) / 'sources.sqlite3')
    return str(Path(record['logical_root']) / physical.name), canonical(value)


def _schema_structure(db):
    # SQL token comparison preserves literals, checks, indexes and trigger bodies.
    # Ignore presentation whitespace and identifier quoting introduced by SQLite's
    # delivered ALTER TABLE migrations; this is not a SQL equivalence checker.
    result = {}
    for kind, name, table, sql in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'):
        tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]", sql or '')
        normalized = tuple(t if t.startswith("'") else t.strip('"').lower() for t in tokens)
        result[(kind,name,table)] = normalized
    return result


@lru_cache(maxsize=256)
def _supported_structure(name, subsidiaries):
    """Build trusted empty schemas using shipped initializers, never input SQL.

    The bounded optional-service set selects the exact delivered schema. Temporary
    synthetic stores avoid initializing/migrating the artifact under inspection.
    Fresh creation itself traverses delivered migrations; no duplicated DDL/schema
    language or shipped credential/database artifact is needed.
    """
    from accounting_harness.workspace import Workspace
    from accounting_harness.access import AccessStore
    from accounting_harness.qbo_read import QBOStagingStore
    from accounting_harness.qbo_export import database
    with tempfile.TemporaryDirectory(prefix='recovery-schema-') as directory:
        root = Path(directory)
        if name == 'access.sqlite3':
            path = root / name
            AccessStore(path)
        else:
            workspace = Workspace(root / 'entity')
            path = workspace.root / name
            if name == 'ledger.sqlite3':
                from accounting_harness.payables import PayablesService
                from accounting_harness.receivables import ReceivablesService
                from accounting_harness.advances import AdvancesService
                from accounting_harness.bank import BankStatementService
                from accounting_harness.bank_fees import BankFeeService
                from accounting_harness.prepaid import PrepaidService
                from accounting_harness.reconciliation import ReconciliationService
                with workspace.storage() as (registry,ledger,_,_,_):
                    for schema, initialize in (
                        ('payables_schema', lambda: PayablesService(ledger,registry)),
                        ('receivables_schema', lambda: ReceivablesService(ledger,registry)),
                        ('advances_schema', lambda: AdvancesService(ledger,registry)),
                        ('bank_schema', lambda: BankStatementService(ledger)),
                        ('bank_fee_schema', lambda: BankFeeService(ledger,registry)),
                        ('prepaid_schema', lambda: PrepaidService(ledger,registry)),
                        ('reconciliation_schema', lambda: ReconciliationService(ledger))):
                        if schema in subsidiaries: initialize()
            elif name == 'agent-runs.sqlite3':
                path = workspace.root / 'runs.sqlite3'  # Identical inherited schema, separate scope/data.
            elif name == 'qbo-staging.sqlite3':
                with QBOStagingStore(path,workspace.catalog.entity_id): pass
            elif name in ('qbo-outbox.sqlite3','qbo-simulator.sqlite3'):
                with database(path,workspace.catalog.entity_id,simulator=name=='qbo-simulator.sqlite3'): pass
        with closing(_readonly(path.resolve())) as db:
            return _schema_structure(db)


def _inspect(path, name, entity=None):
    _safe(path, file=True)
    if path.stat().st_size > MAX_FILE: raise ValueError('Recovery file exceeds bound')
    with closing(_readonly(path)) as db:
        if tuple(db.execute('PRAGMA '+p).fetchone()[0] for p in ('user_version','application_id')) != SCHEMAS[name]:
            raise ValueError('Unsupported recovery schema/application')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Recovery SQLite integrity/foreign key failure')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        expected = set(TABLES[name].split())
        if name == 'ledger.sqlite3':
            for schema, names in SUBTABLES.items():
                if schema in tables: expected.update([schema, *names.split()])
        if set(tables) != expected:
            raise ValueError('Missing or unknown recovery schema table')
        subsidiaries = tuple(table for table in tables if table.endswith('_schema'))
        if _schema_structure(db) != _supported_structure(name, subsidiaries):
            raise ValueError('Unsupported recovery schema structure')
        summaries = {}
        for table in tables:
            quoted = '"' + table.replace('"','""') + '"'
            rows = db.execute('SELECT * FROM '+quoted).fetchall()
            summaries[table] = dict(count=len(rows), digest=sha(canonical(sorted(rows, key=canonical)).encode()))
        if name == 'ledger.sqlite3':
            actual = {t:db.execute('SELECT version FROM "'+t+'"').fetchall() for t in tables if t.endswith('_schema')}
            for table, rows in actual.items():
                if table not in SUBSCHEMAS or rows != [(SUBSCHEMAS[table],)]:
                    raise ValueError('Unsupported subsidiary schema '+table)
            required_schemas = set(SUBSCHEMAS) - {'payables_schema','receivables_schema','advances_schema','bank_schema','bank_fee_schema','prepaid_schema','reconciliation_schema'}
            if not required_schemas <= actual.keys():
                raise ValueError('Missing required subsidiary schema')
            rows = db.execute('SELECT entity_id,canonical FROM ledger_context').fetchall()
            if len(rows) != 1 or rows[0][0] != entity: raise ValueError('Wrong ledger entity')
            if json.loads(rows[0][1])['catalog']['entity_id'] != entity: raise ValueError('Wrong catalog entity')
            totals = {}
            for journal, side, cents in db.execute('SELECT journal_id,side,cents FROM lines'):
                totals[journal] = totals.get(journal,0) + (cents if side == 'debit' else -cents)
            if any(totals.values()) or set(totals) != {r[0] for r in db.execute('SELECT id FROM journals')}:
                raise ValueError('Unbalanced or empty journal')
        elif name in ('sources.sqlite3','qbo-staging.sqlite3','qbo-outbox.sqlite3','qbo-simulator.sqlite3'):
            table = {'sources.sqlite3':'registry_context','qbo-staging.sqlite3':'staging_context'}.get(name,'context')
            if db.execute('SELECT entity_id FROM '+table).fetchall() != [(entity,)]: raise ValueError('Wrong store entity')
        summaries['_schema_identity'] = dict(count=1,digest=sha(canonical(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()).encode()))
        return summaries


def _entity_check(root, entry):
    from accounting_harness.access import stored_entity_context
    if stored_entity_context(root) != (entry['entity_id'], entry['context_digest']):
        raise ValueError('Entity/context digest mismatch')
    with closing(_readonly(root/'ledger.sqlite3')) as ledger, closing(_readonly(root/'sources.sqlite3')) as registry:
        context = ledger.execute('SELECT canonical FROM ledger_context').fetchone()[0]
        if context != entry['ledger_context']: raise ValueError('Ledger context mismatch')
        docs = {r[0]:(r[1],r[2]) for r in registry.execute('SELECT document_id,content_digest,canonical_content FROM source_documents')}
        for document, (digest, content) in docs.items():
            if sha(content.encode()) != digest:
                raise ValueError('Source digest/entity mismatch')
        if any(row[0] not in docs for row in ledger.execute('SELECT source_id FROM journal_sources')):
            raise ValueError('Posted journal evidence missing from registry')
        for row in ledger.execute('SELECT source_id,content_digest,canonical_content FROM source_enrollments'):
            if docs.get(row[0]) != tuple(row[1:]): raise ValueError('Source enrollment differs from registered evidence')
    from accounting_harness.runs import SQLiteRunEngine
    from accounting_harness.operational_agent import OperationalRunEngine
    from accounting_harness.review import digest
    for name, engine in (('runs.sqlite3',SQLiteRunEngine), ('agent-runs.sqlite3',OperationalRunEngine)):
        if not (root/name).exists(): continue
        expected = dict(entity_id=entry['entity_id'], ledger_path=str(Path(entry['logical_root'])/'ledger.sqlite3'),
            registry_path=str(Path(entry['logical_root'])/'sources.sqlite3'), ledger_context=context,
            policy_version='review-v1', tool_schema_digest=digest(engine._tool_contract()), allowed_tools=sorted(engine._tool_contract()))
        with closing(_readonly(root/name)) as runs:
            if runs.execute('SELECT canonical FROM run_context').fetchall() != [(canonical(expected),)]:
                raise ValueError('Run scope/entity/tool policy mismatch')
            for (config,) in runs.execute('SELECT config_json FROM runs'):
                if json.loads(config)['scope'] != canonical(expected): raise ValueError('Historical run configuration scope differs')


def _manifest(bundle):
    value = _load(bundle / 'manifest.json')
    _fields(value, 'version backup_id captured_at access_origin entities files')
    if type(value['version']) is not int or value['version'] != 1: raise ValueError('Unsupported recovery version')
    body = {k:v for k,v in value.items() if k != 'backup_id'}
    if type(value['backup_id']) is not str or sha(canonical(body).encode()) != value['backup_id']:
        raise ValueError('Manifest digest mismatch')
    try:
        if type(value['captured_at']) is not str or datetime.fromisoformat(value['captured_at']).utcoffset().total_seconds() != 0:
            raise ValueError('Invalid capture time')
    except (TypeError, AttributeError, OverflowError) as error:
        raise ValueError('Invalid capture time') from error
    if type(value['entities']) is not list or not 1 <= len(value['entities']) <= 100:
        raise ValueError('Invalid recovery entity count')
    expected = {'access.sqlite3'}; ids = set(); roots = []
    for i, entry in enumerate(value['entities']):
        _fields(entry, 'entity_id context_digest ledger_context physical_root logical_root directory presence')
        if type(entry['entity_id']) is not str or not entry['entity_id'] or entry['entity_id'] in ids: raise ValueError('Duplicate/invalid entity')
        ids.add(entry['entity_id'])
        if entry['directory'] != f'entities/{i:04d}': raise ValueError('Invalid archive entity directory')
        _fields(entry['presence'], ' '.join(ROSTER))
        if any(type(v) is not bool for v in entry['presence'].values()) or not all(entry['presence'][n] for n in REQUIRED):
            raise ValueError('Missing required store')
        for field in ('physical_root','logical_root'):
            p = entry[field]
            if type(p) is not str or not Path(p).is_absolute() or str(Path(p)) != p or '..' in Path(p).parts:
                raise ValueError('Invalid original root')
        roots.append(Path(entry['physical_root']))
        expected.update(entry['directory']+'/'+name for name,present in entry['presence'].items() if present)
    _disjoint(roots)
    if type(value['access_origin']) is not str or not Path(value['access_origin']).is_absolute(): raise ValueError('Invalid access origin')
    _disjoint([Path(value['access_origin']), *roots])
    if type(value['files']) is not dict or set(value['files']) != expected: raise ValueError('Recovery roster differs')
    total = 0
    for name, info in value['files'].items():
        _fields(info,'size sha256 tables')
        if type(info['size']) is not int or not 0 < info['size'] <= MAX_FILE: raise ValueError('Invalid file size')
        total += info['size']
        if type(info['sha256']) is not str or len(info['sha256']) != 64 or type(info['tables']) is not dict:
            raise ValueError('Invalid file digest/summary')
    if total > MAX_TOTAL: raise ValueError('Recovery group exceeds bound')
    return value


def verify_backup(directory):
    started = time.monotonic_ns(); bundle = _safe(directory)
    value = _manifest(bundle)
    actual = set()
    for path in bundle.rglob('*'):
        _safe(path)
        if path.is_file(): actual.add(path.relative_to(bundle).as_posix())
        elif not path.is_dir(): raise ValueError('Unexpected recovery payload')
    if actual != set(value['files']) | {'manifest.json'}: raise ValueError('Unknown/missing recovery files')
    for relative, info in value['files'].items():
        path = bundle / relative; _safe(path,file=True)
        if path.stat().st_size != info['size'] or sha(path.read_bytes()) != info['sha256']:
            raise ValueError('Recovery payload size/digest mismatch')
        entity = next((e['entity_id'] for e in value['entities'] if relative.startswith(e['directory']+'/')),None)
        if _inspect(path,path.name,entity) != info['tables']: raise ValueError('Recovery table summary mismatch')
    with closing(_readonly(bundle/'access.sqlite3')) as access:
        mappings = access.execute('SELECT entity_id,workspace_path,context_digest FROM entities ORDER BY entity_id').fetchall()
    if mappings != [(e['entity_id'],e['physical_root'],e['context_digest']) for e in value['entities']]:
        raise ValueError('Incomplete or mismatched access mappings')
    for entry in value['entities']: _entity_check(bundle/entry['directory'],entry)
    return dict(manifest=value, verification_ms=(time.monotonic_ns()-started)//1_000_000,
                bytes=sum(v['size'] for v in value['files'].values()))


def _stage(destination):
    destination = _safe(destination)
    if destination.exists(): raise ValueError('Recovery destination must be new and absent')
    if not destination.parent.is_dir(): raise ValueError('Recovery destination parent must exist')
    return Path(tempfile.mkdtemp(prefix='.'+destination.name+'-staging-',dir=destination.parent))


def _rename_new(source, destination):
    # os.rename replaces an empty directory on POSIX. Kernel exclusion is needed
    # even with our gate, since an administrator can concurrently create a target.
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux'):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise ValueError('Recovery publication requires macOS or Linux no-replace rename')
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _publish(stage, destination, fault):
    _hit(fault,'before_publish')
    # Our persistent destination gate serializes application publishers. Refuse
    # an existing directory even if empty; no overwrite of operator-owned paths.
    if destination.exists(): raise ValueError('Recovery destination appeared during staging')
    # SQLite commits already use FULL synchronization; sync copied files and the
    # staged directory entries too, before the single publication operation.
    for path in stage.rglob('*'):
        descriptor = os.open(path, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    descriptor = os.open(stage, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    _rename_new(stage,destination)
    descriptor = os.open(destination.parent,os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    _hit(fault,'after_publish')  # Already committed: fully verified output remains.


def backup_group(access_db, destination, *, fault=None):
    started=time.monotonic_ns(); access_db=_safe(access_db,file=True); destination=_safe(destination)
    stage=None
    with ExitStack() as locks:
        locks.enter_context(maintenance_lock(access_lock(access_db),exclusive=True))
        locks.enter_context(maintenance_lock(access_lock(destination),exclusive=True))
        with closing(_readonly(access_db)) as access:
            rows=access.execute('SELECT entity_id,workspace_path,context_digest FROM entities ORDER BY entity_id').fetchall()
        if not 1 <= len(rows) <= 100: raise ValueError('Recovery requires 1..100 configured entities')
        roots=[_safe(row[1]) for row in rows]
        _disjoint([access_db,destination,*roots])
        for root in sorted(roots): locks.enter_context(maintenance_lock(workspace_lock(root),exclusive=True))
        entries=[]; files={'access.sqlite3':access_db}
        for i,((entity,_,context_digest),root) in enumerate(zip(rows,roots)):
            for path in root.iterdir():
                _safe(path)
                if path.name in ROSTER or not path.is_file(): continue
                with path.open('rb') as stream: header = stream.read(16)
                if path.suffix in ('.sqlite3','.sqlite','.db') or header == b'SQLite format 3\x00':
                    raise ValueError('Unknown workspace database')
            presence={name:(root/name).exists() for name in ROSTER}
            if not all(presence[n] for n in REQUIRED): raise ValueError('Missing required workspace store')
            record=relocation_record(root)
            with closing(_readonly(root/'ledger.sqlite3')) as db: context=db.execute('SELECT canonical FROM ledger_context').fetchone()[0]
            entry=dict(entity_id=entity,context_digest=context_digest,ledger_context=context,physical_root=str(root),
                       logical_root=record['logical_root'] if record else str(root),directory=f'entities/{i:04d}',presence=presence)
            entries.append(entry)
            for name,present in presence.items():
                if present: files[entry['directory']+'/'+name]=_safe(root/name,file=True)
        # Access first, then canonical entity directory/file order. Reserve every
        # writer before copying the first DB; read connections do the backups.
        for path in [access_db]+sorted(p for p in files.values() if p != access_db):
            guard=locks.enter_context(closing(sqlite3.connect(path,timeout=0,isolation_level=None)))
            try: guard.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error: raise PersistenceBusy('Recovery SQLite writer busy') from error
        if any(path.stat().st_size > MAX_FILE for path in files.values()) or sum(path.stat().st_size for path in files.values()) > MAX_TOTAL:
            raise ValueError('Recovery source group exceeds byte bounds')
        stage=_stage(destination)
        try:
            summaries={}
            for relative,path in files.items():
                _hit(fault,'before_snapshot:'+relative)
                target=stage/relative; target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with closing(_readonly(path)) as source, closing(sqlite3.connect(target)) as target_db: source.backup(target_db)
                os.chmod(target,0o600)
                _hit(fault,'after_snapshot:'+relative)
                entity=next((e['entity_id'] for e in entries if relative.startswith(e['directory']+'/')),None)
                summaries[relative]=dict(size=target.stat().st_size,sha256=sha(target.read_bytes()),tables=_inspect(target,target.name,entity))
            body=dict(version=1,captured_at=datetime.now(timezone.utc).isoformat(),access_origin=str(access_db),entities=entries,files=summaries)
            manifest=dict(body,backup_id=sha(canonical(body).encode()))
            _hit(fault,'before_manifest'); _write(stage/'manifest.json',manifest); _hit(fault,'after_manifest')
            verified=verify_backup(stage)
            _publish(stage,destination,fault)
            receipt=dict(version=1,backup_id=manifest['backup_id'],captured_at=manifest['captured_at'],
                verified_at=datetime.now(timezone.utc).isoformat(),verification_ms=verified['verification_ms'],
                backup_ms=(time.monotonic_ns()-started)//1_000_000,bytes=verified['bytes'],entity_count=len(entries))
            for root, entry in zip(roots,entries):
                _replace_receipt(root/BACKUP_RECEIPT,dict(receipt,entity_id=entry['entity_id']))
            return dict(manifest,backup_ms=(time.monotonic_ns()-started)//1_000_000,verification_ms=verified['verification_ms'],bytes=verified['bytes'])
        finally:
            if stage.exists(): shutil.rmtree(stage)


def restore_group(backup, destination, *, activate=False, fault=None):
    if activate is not True: raise ValueError('Explicit local recovery activation is required')
    started=time.monotonic_ns(); backup=_safe(backup); destination=_safe(destination)
    verified=verify_backup(backup); manifest=verified['manifest']
    _disjoint([backup,destination])
    for original in [Path(manifest['access_origin']),*[Path(e['physical_root']) for e in manifest['entities']]]:
        if _overlap(destination,original) or _overlap(backup,original): raise ValueError('Recovery overlaps original workspace')
    with maintenance_lock(access_lock(destination),exclusive=True):
        stage=_stage(destination)
        try:
            for relative in manifest['files']:
                _hit(fault,'before_file:'+relative)
                target=stage/relative; target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copyfile(backup/relative,target); os.chmod(target,0o600)
                _hit(fault,'after_file:'+relative)
            _hit(fault,'before_manifest'); _write(stage/'manifest.json',manifest); _hit(fault,'after_manifest')
            # Verify the copies, not merely the source; race/corruption aborts before activation.
            verify_backup(stage)
            (stage/'manifest.json').unlink()
            key=secrets.token_bytes(32)
            descriptor=os.open(stage/'.recovery-key',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as stream: stream.write(key); stream.flush(); os.fsync(stream.fileno())
            _hit(fault,'before_activation')
            now=int(time.time())
            with closing(sqlite3.connect(stage/'access.sqlite3')) as access:
                with access:
                    for entry in manifest['entities']:
                        access.execute('UPDATE entities SET workspace_path=? WHERE entity_id=?',(str(destination/entry['directory']),entry['entity_id']))
                    access.execute('UPDATE sessions SET revoked_at=coalesce(revoked_at,?)',(now,))
                    access.execute('INSERT INTO access_audit(action,actor_id,recorded_at,reason,request_digest) VALUES(?,?,?,?,?)',
                        ('recovery-activation','local-recovery-operator',now,'Verified recovery; sessions revoked; transports disabled',manifest['backup_id']))
            for entry in manifest['entities']:
                record=dict(version=1,backup_id=manifest['backup_id'],physical_root=str(destination/entry['directory']),
                    logical_root=entry['logical_root'],entity_id=entry['entity_id'],context_digest=entry['context_digest'],
                    ledger_context=entry['ledger_context'],transports_disabled=True)
                _write(stage/entry['directory']/RELOCATION,dict(record=record,seal=hmac.new(key,canonical(record).encode(),hashlib.sha256).hexdigest()))
            _hit(fault,'after_activation')
            receipt=dict(version=1,backup_id=manifest['backup_id'],captured_at=manifest['captured_at'],
                verified_at=datetime.now(timezone.utc).isoformat(),verification_ms=verified['verification_ms'],
                restore_ms=(time.monotonic_ns()-started)//1_000_000,bytes=verified['bytes'],entity_count=len(manifest['entities']),
                transports_disabled=True)
            _write(stage/RECEIPT,receipt)
            # Each entity gets a redacted status receipt; no credentials or paths.
            for entry in manifest['entities']: _write(stage/entry['directory']/RECEIPT,dict(receipt,entity_id=entry['entity_id']))
            _publish(stage,destination,fault)
            receipt['restore_ms']=(time.monotonic_ns()-started)//1_000_000
            _replace_receipt(destination/RECEIPT,receipt)
            for entry in manifest['entities']:
                _replace_receipt(destination/entry['directory']/RECEIPT,dict(receipt,entity_id=entry['entity_id']))
            return receipt
        finally:
            if stage.exists(): shutil.rmtree(stage)
