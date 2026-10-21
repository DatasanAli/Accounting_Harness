"""Redacted, read-only local operational captures; no transports or business constructors.

Each store has its own SQLite read transaction. The capture is a bounded collection
interval, not an atomic ledger snapshot. Local file ownership is the trust boundary
for persisted recovery receipts. Authentication may update session activity.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import time

from accounting_harness.recovery import SCHEMAS, BACKUP_RECEIPT, RECEIPT, _safe, relocated_run_identity
from accounting_harness.review import digest

THRESHOLD = 900000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
STATES = {'ready', 'requesting_provider', 'pending_tool', 'executing_tool', 'completed', 'failed', 'exhausted', 'cancelled', 'awaiting_review'}
TERMINAL = {'completed', 'failed', 'exhausted', 'cancelled', 'awaiting_review'}
ACTIONS = {
    'run_failed': 'Inspect the saved run before deciding whether to retry.',
    'run_exhausted': 'Inspect the saved run and its execution limits.',
    'run_stalled': 'Inspect the saved checkpoint; confirm the worker stopped before recovery.',
    'enrollment_pending': 'Review the source and explicitly retry registration to enroll it.',
    'source_binding_drift': 'Inspect source binding integrity before further processing.',
    'read_resumable': 'Inspect the staged read before explicitly resuming the same batch.',
    'read_rate_limited': 'Inspect the recorded backoff before explicitly resuming the same batch.',
    'read_incomplete': 'Review the page limit; this batch does not prove a complete import.',
    'read_blocked': 'Inspect the rejected read and reconcile its evidence.',
    'export_uncertain': 'Explicitly check the existing export identity before considering a retry.',
    'export_exception': 'Reconcile the recorded exception; do not assume the remote effect failed.',
    'export_drift': 'Reconcile the recorded divergence with the approved local journal.',
    'backup_verified': 'Review this verified backup checkpoint and plan the next backup.',
    'restore_verified': 'Review this successful restore checkpoint and retain the drill evidence.',
    'backup_unavailable': 'Create and verify a workspace backup.',
    'restore_unavailable': 'Perform a verified restore drill into a new location.',
    'metadata_invalid': 'Inspect local metadata integrity with the workspace administrator.',
    'clock_invalid': 'Check the application clock and recorded checkpoint time.',
    'store_unavailable': 'Ask the workspace administrator to inspect the unavailable store.',
    'record_current': 'Review this current record; no local alert is recorded.',
}
ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError, OSError, sqlite3.Error)


def _integer(value):
    if type(value) is not int or not 0 <= value <= 253402300799999: raise ValueError('metadata_invalid')
    return value


def _json(raw):
    if type(raw) is not str or len(raw) > 8 * 1024 * 1024: raise ValueError('metadata_invalid')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('metadata_invalid')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique, parse_float=lambda _: (_ for _ in ()).throw(ValueError('metadata_invalid')), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('metadata_invalid')))
    if type(value) is not dict: raise ValueError('metadata_invalid')
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64: raise ValueError('metadata_invalid')
        if type(item) in (dict, list):
            pending.extend((child, depth+1) for child in (item.values() if type(item) is dict else item))
    return value


def _utc(value):
    if type(value) is not str or len(value) > 40: raise ValueError('metadata_invalid')
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0): raise ValueError('metadata_invalid')
    return parsed.astimezone(timezone.utc)


def _timestamp(value, now):
    parsed = _utc(value)
    if parsed > now: raise ValueError('clock_invalid')
    return parsed.isoformat()


def _ref(entity, kind, native):
    return 'status-' + digest([entity, kind, native])


def _row(entity, kind, native, code, *, at=None, elapsed=None, idle=None, uncertain=False):
    reference = _ref(entity, kind, native)
    return dict(reference=reference, kind=kind, code=code, recorded_at=at, elapsed_ms=elapsed,
                idle_ms=idle, uncertain=uncertain, next_action=ACTIONS[code], href='#operations/' + reference)


def _category(rows, *, unavailable=False):
    bad = any(row['code'] in ('metadata_invalid', 'clock_invalid', 'store_unavailable') for row in rows)
    return dict(availability='unavailable' if unavailable else 'partial' if bad else 'available',
                count=None if bad or unavailable else len(rows), rows=rows)


@contextmanager
def _database(root, name, entity):
    path = _safe(root/name, file=True)
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=0, isolation_level=None)
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        if (db.execute('PRAGMA user_version').fetchone()[0], db.execute('PRAGMA application_id').fetchone()[0]) != SCHEMAS[name]:
            raise ValueError('metadata_invalid')
        table = {'ledger.sqlite3':'ledger_context', 'sources.sqlite3':'registry_context', 'qbo-staging.sqlite3':'staging_context', 'qbo-outbox.sqlite3':'context'}.get(name)
        if table and db.execute('SELECT entity_id FROM '+table).fetchall() != [(entity,)]: raise ValueError('metadata_invalid')
        yield db
    finally:
        db.close()


def _error(entity, kind, native, error):
    # Exception strings from files, providers or SQLite never cross this boundary.
    code = 'clock_invalid' if type(error) is ValueError and error.args == ('clock_invalid',) else 'metadata_invalid'
    return _row(entity, kind, native, code)


def _runs(root, entity, now):
    from accounting_harness.runs import SQLiteRunEngine
    from accounting_harness.operational_agent import OperationalRunEngine
    now_ms = (now-EPOCH)//timedelta(milliseconds=1)
    rows, records = [], []
    for name, engine in (('runs.sqlite3', SQLiteRunEngine), ('agent-runs.sqlite3', OperationalRunEngine)):
        kind = 'run' if name == 'runs.sqlite3' else 'agent_run'
        if not (root/name).exists() and not (root/name).is_symlink():
            if name == 'runs.sqlite3': rows.append(_row(entity, kind, 'store', 'store_unavailable'))
            continue
        try:
            with _database(root, 'ledger.sqlite3', entity) as ledger:
                context = ledger.execute('SELECT canonical FROM ledger_context').fetchone()[0]
            expected = dict(entity_id=entity, ledger_path=str(root/'ledger.sqlite3'), registry_path=str(root/'sources.sqlite3'),
                            ledger_context=context, policy_version='review-v1', tool_schema_digest=digest(engine._tool_contract()), allowed_tools=sorted(engine._tool_contract()))
            _, canonical_scope = relocated_run_identity(str(root/name), json.dumps(expected))
            with _database(root, name, entity) as db:
                scope_rows = db.execute('SELECT canonical FROM run_context').fetchall()
                if len(scope_rows) != 1 or _json(scope_rows[0][0]) != _json(canonical_scope): raise ValueError('metadata_invalid')
                for native, config_raw in db.execute('SELECT run_id,config_json FROM runs ORDER BY run_id'):
                    try:
                        if _json(_json(config_raw)['scope']) != _json(canonical_scope): raise ValueError('metadata_invalid')
                        checkpoint = db.execute('SELECT sequence,checkpoint_json FROM run_checkpoints WHERE run_id=? ORDER BY sequence DESC LIMIT 1', (native,)).fetchone()
                        sequence, raw = checkpoint
                        c = _json(raw)
                        if c['run_id'] != native or type(c['sequence']) is not int or c['sequence'] != sequence or c['state'] not in STATES: raise ValueError('metadata_invalid')
                        recorded, elapsed = _integer(c['recorded_at_ms']), _integer(c['elapsed_ms'])
                        if recorded > now_ms: raise ValueError('clock_invalid')
                        age = now_ms-recorded
                        code = 'run_'+c['state'] if c['state'] in ('failed', 'exhausted') else 'run_stalled' if c['state'] not in TERMINAL and age >= THRESHOLD else 'record_current'
                        row = _row(entity, kind, native, code, at=(EPOCH+timedelta(milliseconds=recorded)).isoformat(), elapsed=elapsed, idle=age)
                    except ERRORS as error: row = _error(entity, kind, native, error)
                    records.append(row)
                    if row['code'] != 'record_current': rows.append(row)
        except ERRORS as error: rows.append(_error(entity, kind, 'store', error))
    return _category(rows), records


def _sources(root, entity, now):
    rows, records = [], []
    try:
        with _database(root, 'ledger.sqlite3', entity) as ledger, _database(root, 'sources.sqlite3', entity) as registry:
            known = {r[0] for r in ledger.execute('SELECT id FROM sources')}
            enrolled = {r[0]:r[1:] for r in ledger.execute('SELECT source_id,entity_id,content_digest FROM source_enrollments')}
            for native, source_entity, content_digest, at in registry.execute('SELECT d.document_id,d.entity_id,d.content_digest,e.recorded_at FROM source_documents d LEFT JOIN registration_events e USING(entity_id,document_id) ORDER BY d.document_id'):
                try:
                    if source_entity != entity: raise ValueError('metadata_invalid')
                    at = _timestamp(at, now)
                    code = 'enrollment_pending' if native not in known else 'source_binding_drift' if native in enrolled and enrolled[native] != (entity, content_digest) else 'record_current'
                    row = _row(entity, 'source', native, code, at=at)
                except ERRORS as error: row = _error(entity, 'source', native, error)
                records.append(row)
                if row['code'] != 'record_current': rows.append(row)
    except ERRORS as error: rows.append(_error(entity, 'source', 'store', error))
    return _category(rows), records


def _reads(root, entity, now):
    from accounting_harness.qbo_read import replay, POLICY, _config
    rows, records = [], []
    if not (root/'qbo-staging.sqlite3').exists() and not (root/'qbo-staging.sqlite3').is_symlink(): return _category([]), []
    try:
        with _database(root, 'qbo-staging.sqlite3', entity) as db:
            for native, batch_entity, scope_digest, raw, created in db.execute('SELECT batch_id,entity_id,scope_digest,scope_json,created_at FROM qbo_batches ORDER BY batch_id'):
                try:
                    scope = _json(raw)
                    if batch_entity != entity or scope['entity_id'] != entity or scope['policy'] != POLICY or digest(scope) != scope_digest: raise ValueError('metadata_invalid')
                    _config(scope['connector'], set(scope['connector']['account_map']['accounts'].values()))
                    at = _timestamp(created, now); events = []
                    for sequence, kind, position, detail, recorded in db.execute('SELECT sequence,kind,position,detail_json,recorded_at FROM qbo_events WHERE batch_id=? ORDER BY sequence', (native,)):
                        if sequence != len(events)+1 or kind not in ('page','rate_limited','transport_failure','rejected'): raise ValueError('metadata_invalid')
                        at = _timestamp(recorded, now); detail = _json(detail)
                        if kind == 'rate_limited': _utc(detail['not_before'])
                        if kind == 'page':
                            for field in ('position','page_number','row_count','next_position'): _integer(detail[field])
                            if type(detail['records']) is not list: raise ValueError('metadata_invalid')
                        events.append(dict(sequence=sequence, kind=kind, position=position, detail=detail))
                    state = replay(events, scope, scope_digest)
                    for page in state['pages']:
                        for item in page['records']:
                            observation = db.execute('SELECT content_digest,record_json FROM qbo_observations WHERE scope_digest=? AND remote_id=? AND sync_token=?', (scope_digest,item['remote_id'],item['sync_token'])).fetchone()
                            if observation is None or observation[0] != item['content_digest'] or digest(_json(observation[1])) != item['content_digest']: raise ValueError('metadata_invalid')
                    terminal = state['terminal']
                    code = 'record_current' if terminal == 'complete' else 'read_'+terminal if terminal else 'read_rate_limited' if state['last'] == 'rate_limited' else 'read_resumable'
                    row = _row(entity, 'read', native, code, at=at)
                except ERRORS as error: row = _error(entity, 'read', native, error)
                records.append(row)
                if row['code'] != 'record_current': rows.append(row)
    except ERRORS as error: rows.append(_error(entity, 'read', 'store', error))
    return _category(rows), records


def _exports(root, entity, now):
    from accounting_harness.qbo_export import POLICY
    rows, records = [], []
    if not (root/'qbo-outbox.sqlite3').exists() and not (root/'qbo-outbox.sqlite3').is_symlink(): return _category([]), []
    try:
        with _database(root, 'qbo-outbox.sqlite3', entity) as db:
            for native, preview_digest, raw, created in db.execute('SELECT export_id,preview_digest,preview_json,created_at FROM exports ORDER BY export_id'):
                try:
                    preview = _json(raw)
                    if preview.get('entity_id') != entity or preview.get('export_id') != native or preview.get('policy') != POLICY or digest(preview) != preview_digest: raise ValueError('metadata_invalid')
                    at = _timestamp(created, now); uncertain = exception = drift = False; confirmation = None
                    for expected, (sequence, kind, detail, recorded) in enumerate(db.execute('SELECT sequence,kind,detail_json,recorded_at FROM export_events WHERE export_id=? ORDER BY sequence', (native,)), 1):
                        if sequence != expected or kind not in ('authorized','attempted','uncertain','exception','rate_limited','confirmed','checked','receipt'): raise ValueError('metadata_invalid')
                        at = _timestamp(recorded, now); detail = _json(detail)
                        if kind == 'authorized' and detail.get('preview_digest') != preview_digest: raise ValueError('metadata_invalid')
                        if kind in ('attempted','rate_limited'): _utc(detail['next_attempt_at'])
                        if kind in ('uncertain','exception') and type(detail.get('reason')) is not str: raise ValueError('metadata_invalid')
                        if kind in ('receipt','confirmed') and (type(detail.get('remote_id')) is not str or not detail['remote_id']): raise ValueError('metadata_invalid')
                        if kind == 'receipt' and type(detail.get('body')) is not str: raise ValueError('metadata_invalid')
                        if kind in ('confirmed','checked'):
                            observation = detail.get('observation')
                            if type(observation) is not dict or type(observation.get('http_status')) is not int or observation['http_status'] != 200 or type(observation.get('body')) is not str or type(observation.get('realm_id')) is not str: raise ValueError('metadata_invalid')
                            if kind == 'confirmed':
                                normalized = detail.get('normalized')
                                if type(normalized) is not dict or normalized.get('remote_id') != detail['remote_id'] or normalized.get('status') != 'supported': raise ValueError('metadata_invalid')
                                confirmation = observation
                            elif confirmation is None or confirmation != observation: raise ValueError('metadata_invalid')
                        if kind in ('attempted','uncertain','receipt'): uncertain = True
                        if kind in ('confirmed','checked'): uncertain = False
                        if kind == 'rate_limited':
                            if detail.get('status') not in ('authorized','uncertain'): raise ValueError('metadata_invalid')
                            uncertain = detail['status'] == 'uncertain'
                        if kind == 'exception':
                            exception = True
                            reason = detail.get('reason')
                            drift |= reason in ('remote readback drift or invalid record', 'remote observation changed after confirmation') or (type(reason) is str and reason.startswith('local divergence: '))
                    code = 'export_drift' if drift else 'export_exception' if exception else 'export_uncertain' if uncertain else 'record_current'
                    row = _row(entity, 'export', native, code, at=at, uncertain=uncertain)
                except ERRORS as error: row = _error(entity, 'export', native, error)
                records.append(row)
                if row['code'] != 'record_current': rows.append(row)
    except ERRORS as error: rows.append(_error(entity, 'export', 'store', error))
    return _category(rows), records


def _recovery(root, entity, now, kind):
    name = BACKUP_RECEIPT if kind == 'backup' else RECEIPT
    if not (root/name).exists() and not (root/name).is_symlink(): return _category([_row(entity, kind, 'receipt', kind+'_unavailable')], unavailable=True), []
    try:
        path = _safe(root/name, file=True)
        if path.stat().st_size > 65536: raise ValueError('metadata_invalid')
        receipt = _json(path.read_text())
        if type(receipt['version']) is not int or receipt['version'] != 1 or receipt['entity_id'] != entity or not re.fullmatch('[0-9a-f]{64}', receipt['backup_id']): raise ValueError('metadata_invalid')
        at = _timestamp(receipt['verified_at'], now)
        if _utc(receipt['captured_at']) > _utc(at): raise ValueError('metadata_invalid')
        for key in ('verification_ms',kind+'_ms','bytes','entity_count'): _integer(receipt[key])
        if kind == 'restore' and receipt.get('transports_disabled') is not True: raise ValueError('metadata_invalid')
        row = _row(entity, kind, receipt['backup_id'], kind+'_verified', at=at, elapsed=receipt[kind+'_ms'])
    except ERRORS as error: row = _error(entity, kind, 'receipt', error)
    return _category([row]), [row]


def _capture(root, entity, now):
    started = time.monotonic_ns()
    root = Path(root).resolve()
    moment = now()
    if not isinstance(moment, datetime) or moment.utcoffset() != timedelta(0): raise ValueError('Invalid status clock')
    moment = moment.astimezone(timezone.utc)
    categories, records = {}, []
    for kind, reader in (('runs',_runs), ('enrollment',_sources), ('reads',_reads), ('exports',_exports)):
        categories[kind], found = reader(root, entity, moment); records.extend(found)
    for kind in ('backup','restore'):
        categories[kind], found = _recovery(root, entity, moment, kind); records.extend(found)
    result = dict(policy='operations-status-v1', captured_at=moment.isoformat(),
                  consistency='bounded_collection_per_store_snapshot', collection_ms=(time.monotonic_ns()-started)//1_000_000,
                  stall_threshold_ms=THRESHOLD, drift_coverage='recorded_local_exceptions_only', categories=categories)
    result['capture_digest'] = digest(result)
    return result, records


def capture_status(root, entity, *, now=lambda: datetime.now(timezone.utc)):
    """Trusted local primitive. Public callers must authorize read_audit first."""
    return _capture(root, entity, now)[0]


def status_detail(root, entity, reference, *, now=lambda: datetime.now(timezone.utc)):
    if type(reference) is not str or not re.fullmatch('status-[0-9a-f]{64}', reference): raise ValueError('Status reference unavailable')
    capture, records = _capture(root, entity, now)
    for row in records + [r for category in capture['categories'].values() for r in category['rows']]:
        if row['reference'] == reference:
            return dict(captured_at=capture['captured_at'], capture_digest=capture['capture_digest'], record=row)
    raise ValueError('Status reference unavailable')
