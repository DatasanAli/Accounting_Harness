"""Offline QuickBooks Online JournalEntry read contract into a separate staging mirror.

The local ledger remains the authoritative book. Staged remote observations live in
their own SQLite file: they never open the ledger, post, approve or become local
actuals. Only an injected transport is called; this slice ships a deterministic
in-process simulator and no network transport, credentials or OAuth handshake.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS, PersistenceBusy, _canonical
from accounting_harness.review import digest, protect_table

POLICY = 'qbo-journal-read-v1'
LABEL = 'Offline contract simulation'
OWNERSHIP = ('The local accounting ledger is the authoritative book. Staged QuickBooks observations are a separate mirror: '
             'they never post, approve or become local actuals. No external or local-ledger writes are performed.')
LOCAL_EFFECTS = 'No local journals, approvals, evidence or reports are created or changed.'
FILE = 'qbo-staging.sqlite3'
HOST = 'sandbox-quickbooks.api.intuit.com'
SCHEMA_VERSION = 1
APPLICATION_ID = 0x41485142  # AHQB: a staging mirror, never a ledger file.
MAX_BODY = 4 * 1024 * 1024
FIXTURE = Path(__file__).resolve().parents[1] / 'data/fixtures/qbo-journal-entries.json'
# Server-owned, versioned connector policy captured in every batch scope. A browser
# chooses only a batch ID; host, realm, map, window and limits are never request data.
# The query shape/minor version are an implementation contract, unverified against a live sandbox.
CONNECTOR = dict(connector_id='qbo-sandbox-synthetic', environment='sandbox', realm_id='9341450000000001',
    home_currency='USD', multicurrency_enabled=False, minor_version='75',
    account_map=dict(version='synthetic-qbo-map-v1', accounts={'35': '1000', '57': '5000', '61': '5100', '79': '4000'}),
    window=dict(start='2026-01-01', end='2026-01-31'), page_size=100, max_pages=100)
# Anything outside these fields is unsupported detail: preserved as a finding, never flattened.
ENTRY_FIELDS = {'Id', 'SyncToken', 'TxnDate', 'CurrencyRef', 'Line', 'DocNumber', 'PrivateNote', 'MetaData', 'domain', 'sparse', 'Adjustment'}
LINE_FIELDS = {'Id', 'Amount', 'DetailType', 'JournalEntryLineDetail', 'Description', 'LineNum'}
_AMOUNT = re.compile(r'(0|[1-9][0-9]{0,16})(\.[0-9]{1,2})?')
_BATCH = re.compile(r'[A-Za-z0-9_-]{1,80}')
SCHEMA = (
    '''CREATE TABLE staging_context(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        entity_id TEXT NOT NULL UNIQUE CHECK(length(trim(entity_id))>0)) STRICT''',
    '''CREATE TABLE qbo_batches(batch_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES staging_context(entity_id),
        scope_digest TEXT NOT NULL CHECK(length(scope_digest)=64), scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
        actor_id TEXT NOT NULL CHECK(length(trim(actor_id))>0), created_at TEXT NOT NULL CHECK(created_at GLOB '*T*+00:00')) STRICT, WITHOUT ROWID''',
    '''CREATE TABLE qbo_observations(scope_digest TEXT NOT NULL, remote_id TEXT NOT NULL, sync_token TEXT NOT NULL,
        content_digest TEXT NOT NULL CHECK(length(content_digest)=64), record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        PRIMARY KEY(scope_digest,remote_id,sync_token)) STRICT, WITHOUT ROWID''',
    '''CREATE TABLE qbo_events(batch_id TEXT NOT NULL REFERENCES qbo_batches(batch_id), sequence INTEGER NOT NULL CHECK(sequence>0),
        kind TEXT NOT NULL CHECK(kind IN ('page','rate_limited','transport_failure','rejected')),
        position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 10001), detail_json TEXT NOT NULL CHECK(json_valid(detail_json)),
        actor_id TEXT NOT NULL CHECK(length(trim(actor_id))>0), recorded_at TEXT NOT NULL CHECK(recorded_at GLOB '*T*+00:00'),
        PRIMARY KEY(batch_id,sequence)) STRICT, WITHOUT ROWID''',
    "CREATE UNIQUE INDEX qbo_one_page_per_cursor ON qbo_events(batch_id,position) WHERE kind='page'",
    "CREATE UNIQUE INDEX qbo_one_rejection ON qbo_events(batch_id) WHERE kind='rejected'",
)
PROTECTED = (('staging_context', '1'), ('qbo_batches', 'batch_id=NEW.batch_id'),
             ('qbo_observations', 'scope_digest=NEW.scope_digest AND remote_id=NEW.remote_id AND sync_token=NEW.sync_token'),
             ('qbo_events', '''batch_id=NEW.batch_id AND (sequence=NEW.sequence OR (NEW.kind='page' AND kind='page' AND position=NEW.position)
                 OR (NEW.kind='rejected' AND kind='rejected'))'''))


class PageError(ValueError):
    """Schema, identity, mapping or conflict: the page is refused and its cursor stays put."""


class TransportError(RuntimeError):
    """A bounded transport failure; the batch remains resumable at the same cursor."""


class _Number(str):
    """The exact lexical form of a JSON number; never converted through float."""


def _config(config, account_codes):
    try:
        if type(config) is not dict or set(config) != set(CONNECTOR): raise ValueError('connector configuration must contain exactly the policy fields')
        if config['environment'] != 'sandbox': raise ValueError('only the QuickBooks sandbox environment is supported')
        if type(config['realm_id']) is not str or not re.fullmatch('[0-9]{1,20}', config['realm_id']): raise ValueError('invalid sandbox realm ID')
        if config['home_currency'] != 'USD' or type(config['multicurrency_enabled']) is not bool:
            raise ValueError('connector must capture USD home currency and its multicurrency setting')
        if type(config['connector_id']) is not str or not _BATCH.fullmatch(config['connector_id']): raise ValueError('invalid connector ID')
        if type(config['minor_version']) is not str or not re.fullmatch('[0-9]{1,3}', config['minor_version']): raise ValueError('invalid minor version')
        mapping = config['account_map']
        if (type(mapping) is not dict or set(mapping) != {'version', 'accounts'} or type(mapping['version']) is not str or not mapping['version'].strip()
                or type(mapping['accounts']) is not dict or not mapping['accounts']):
            raise ValueError('account map requires a version and explicit account IDs')
        for remote, local in mapping['accounts'].items():
            if not re.fullmatch('[0-9]{1,20}', remote) or local not in account_codes:
                raise ValueError('account map must bind QuickBooks account IDs to existing local account codes')
        window = config['window']
        if type(window) is not dict or set(window) != {'start', 'end'} or accounting_date(window['start']) > accounting_date(window['end']):
            raise ValueError('query window must be an inclusive start/end date range')
        for key in ('page_size', 'max_pages'):
            if type(config[key]) is not int or not 1 <= config[key] <= 100: raise ValueError(key + ' must be 1 through 100')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('malformed connector configuration') from error
    return json.loads(_canonical(config))


def build_request(config, position):
    """Server-built bounded sandbox query; STARTPOSITION follows the accepted rows."""
    window = config['window']
    query = (f"SELECT * FROM JournalEntry WHERE TxnDate >= '{window['start']}' AND TxnDate <= '{window['end']}' "
             f"ORDERBY Id STARTPOSITION {position} MAXRESULTS {config['page_size']}")
    return dict(method='GET', headers={'Accept': 'application/json'},
        url=f"https://{HOST}/v3/company/{config['realm_id']}/query?query={quote(query, safe='')}&minorversion={config['minor_version']}")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise PageError('duplicate JSON field ' + key[:80])
        result[key] = value
    return result


def _nonfinite(value):
    raise PageError('nonfinite JSON number')


def _decode(body):
    if len(body) > MAX_BODY: raise PageError('response body must be at most 4 MiB')
    try:
        return json.loads(body.decode('utf-8'), object_pairs_hook=_unique, parse_float=_Number, parse_int=_Number, parse_constant=_nonfinite)
    except PageError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise PageError('malformed JSON response') from error


def _text(value, label, maximum=80):
    # isprintable() also rejects lone surrogates, which would crash SQLite binding mid-batch.
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > maximum or not value.isprintable():
        raise PageError(f'{label} must be nonblank printable text of at most {maximum} characters')
    return value


def _note(value, label):
    # Inert display text only; it never selects an account or changes a total.
    if value is not None and (type(value) is not str or len(value) > 4000 or '\x00' in value): raise PageError(label + ' must be bounded text')
    return value


def _count(value, label):
    if type(value) is not _Number or not re.fullmatch('0|[1-9][0-9]{0,5}', value): raise PageError(label + ' must be a nonnegative integer')
    return int(value)


def _cents(value):
    if type(value) is not _Number or not _AMOUNT.fullmatch(value):
        raise PageError('line Amount must be a positive JSON number with at most two decimals')
    whole, _, fraction = value.partition('.')
    cents = int(whole) * 100 + int((fraction + '00')[:2])
    if not 0 < cents <= MAX_CENTS: raise PageError('line Amount must be positive and within the exact cents limit')
    return cents


def normalize(entry, config):
    """One remote JournalEntry -> an exact normalized record or an explicit unsupported finding."""
    if type(entry) is not dict: raise PageError('JournalEntry must be an object')
    for key in ('Id', 'SyncToken', 'TxnDate', 'Line'):
        if key not in entry: raise PageError('JournalEntry missing ' + key)
    remote_id, sync = _text(entry['Id'], 'JournalEntry Id'), entry['SyncToken']
    if type(sync) is not str or not re.fullmatch('0|[1-9][0-9]{0,19}', sync): raise PageError('SyncToken must be a nonnegative integer string')
    try:
        date = accounting_date(entry['TxnDate']).isoformat()
    except ValueError:
        raise PageError(f'JournalEntry {remote_id} TxnDate must be a YYYY-MM-DD calendar date') from None
    if not config['window']['start'] <= date <= config['window']['end']: raise PageError(f'JournalEntry {remote_id} TxnDate is outside the fixed query window')
    if 'CurrencyRef' in entry:
        ref = entry['CurrencyRef']
        if type(ref) is not dict or 'value' not in ref or not set(ref) <= {'value', 'name'}: raise PageError('malformed CurrencyRef')
        if ref['value'] != 'USD': raise PageError(f'JournalEntry {remote_id} currency is not USD')
        basis = 'CurrencyRef USD'
    elif config['home_currency'] == 'USD' and config['multicurrency_enabled'] is False:
        basis = 'captured USD home currency; multicurrency disabled'
    else:
        raise PageError(f'JournalEntry {remote_id} lacks CurrencyRef and captured USD-only knowledge')
    lines = entry['Line']
    if type(lines) is not list or not 1 <= len(lines) <= 1000 or any(type(line) is not dict for line in lines):
        raise PageError('Line must be a list of 1 through 1000 objects')
    record = dict(remote_id=remote_id, sync_token=sync, txn_date=date, currency='USD', currency_basis=basis,
                  doc_number=_note(entry.get('DocNumber'), 'DocNumber'), memo=_note(entry.get('PrivateNote'), 'PrivateNote'))
    reasons = ['unsupported field ' + key for key in sorted(set(entry) - ENTRY_FIELDS)]
    if entry.get('Adjustment', False) is not False: reasons.append('adjusting-entry flag')
    parsed, seen = [], set()
    for line in lines:
        line_id = _text(line.get('Id'), 'line Id')
        if line_id in seen: raise PageError(f'JournalEntry {remote_id} repeats line Id {line_id}')
        seen.add(line_id)
        reasons += [f'line {line_id} unsupported field {key}' for key in sorted(set(line) - LINE_FIELDS)]
        if line.get('DetailType') != 'JournalEntryLineDetail':
            # Never totaled, but a malformed amount (exponent, excess precision) still refuses the page.
            if 'Amount' in line and (type(line['Amount']) is not _Number or not _AMOUNT.fullmatch(line['Amount'])):
                raise PageError(f'JournalEntry {remote_id} line {line_id} Amount must be an exact JSON number with at most two decimals')
            reasons.append(f'line {line_id} DetailType ' + str(line.get('DetailType'))[:80])
            continue
        detail = line.get('JournalEntryLineDetail')
        if type(detail) is not dict or detail.get('PostingType') not in ('Debit', 'Credit'):
            raise PageError(f'JournalEntry {remote_id} line {line_id} PostingType must be Debit or Credit')
        reasons += [f'line {line_id} unsupported detail {key}' for key in sorted(set(detail) - {'PostingType', 'AccountRef'})]
        ref = detail.get('AccountRef')
        if type(ref) is not dict or 'value' not in ref or not set(ref) <= {'value', 'name'}: raise PageError('malformed AccountRef')
        account = _text(ref['value'], 'AccountRef value')
        # Only the captured server-provided ID map selects a local account; names are never guessed.
        local = config['account_map']['accounts'].get(account)
        if local is None: raise PageError(f'JournalEntry {remote_id} uses unmapped QuickBooks account ID {account}')
        parsed.append(dict(line_id=line_id, side=detail['PostingType'].lower(), amount_cents=_cents(line.get('Amount')),
                           remote_account_id=account, local_account=local, description=_note(line.get('Description'), 'line Description')))
    if reasons:
        # Unsupported detail is preserved, never flattened or totaled. The source digest keeps
        # a same-version change in that detail a conflict rather than an identical observation.
        source = {k: v for k, v in entry.items() if k != 'MetaData'}
        return dict(record, status='unsupported', reasons=reasons, lines=parsed, source_digest=digest(source), total_cents=0)
    debits = sum(line['amount_cents'] for line in parsed if line['side'] == 'debit')
    if len(parsed) < 2 or debits != sum(line['amount_cents'] for line in parsed if line['side'] == 'credit'):
        raise PageError(f'JournalEntry {remote_id} must have at least two positive lines and balance exactly')
    return dict(record, status='supported', reasons=[], lines=parsed, total_cents=debits)


def parse_page(body, config, position):
    data = _decode(body)
    if type(data) is not dict or 'QueryResponse' not in data or not set(data) <= {'QueryResponse', 'time'}:
        raise PageError('response must be a JournalEntry QueryResponse')
    response = data['QueryResponse']
    if type(response) is not dict or not set(response) <= {'JournalEntry', 'startPosition', 'maxResults', 'totalCount'}:
        raise PageError('unexpected QueryResponse fields')
    rows = response.get('JournalEntry', [])
    if type(rows) is not list: raise PageError('JournalEntry must be a list')
    if (rows or 'startPosition' in response) and _count(response.get('startPosition'), 'startPosition') != position:
        raise PageError('nonadvancing or misplaced page: startPosition differs from the requested cursor')
    if (rows or 'maxResults' in response) and _count(response.get('maxResults'), 'maxResults') != len(rows):
        raise PageError('maxResults differs from the returned row count')
    if len(rows) > config['page_size']: raise PageError('page exceeds MAXRESULTS')
    records = [normalize(row, config) for row in rows]
    if len({r['remote_id'] for r in records}) != len(records): raise PageError('duplicate JournalEntry Id within one page')
    return records


def _now(clock):
    now = clock()
    if not isinstance(now, datetime) or now.utcoffset() != timedelta(0): raise ValueError('clock must return an aware UTC datetime')
    return now.astimezone(timezone.utc)


def _retry_at(headers, now):
    """At least 60 seconds, or a later valid Retry-After (delta-seconds or HTTP-date)."""
    value, later = headers.get('retry-after'), None
    if type(value) is str and re.fullmatch('[0-9]{1,6}', value.strip()):
        later = now + timedelta(seconds=int(value.strip()))
    elif type(value) is str:
        try:
            later = parsedate_to_datetime(value)
            later = later.astimezone(timezone.utc) if later.tzinfo else None
        except (TypeError, ValueError, IndexError, OverflowError):
            later = None
    # A hostile or broken header cannot lock a batch for more than one day.
    return max([now + timedelta(seconds=60)] + ([min(later, now + timedelta(days=1))] if later else []))


def _terminal(config, number, rows):
    # Empty/short pages end the batch; a full page at the cap cannot claim a complete total.
    return 'complete' if rows < config['page_size'] else 'incomplete' if number == config['max_pages'] else None


def replay(events, scope, scope_digest):
    """Current cursor/terminal state from append-only events, re-deriving every page checkpoint."""
    state = dict(position=1, pages=[], terminal=None, not_before=None, checkpoint_digest=scope_digest, attempts=[], rejection=None, last=None)
    for event in events:
        detail = event['detail']
        if event['kind'] == 'page':
            receipt = {k: v for k, v in detail.items() if k not in ('receipt_digest', 'checkpoint_digest')}
            number, rows = len(state['pages']) + 1, len(detail['records'])
            if (event['position'] != state['position'] or state['terminal'] or detail['position'] != event['position']
                    or detail['page_number'] != number or detail['row_count'] != rows or detail['next_position'] != event['position'] + rows
                    or detail['terminal'] != _terminal(scope['connector'], number, rows) or digest(receipt) != detail['receipt_digest']
                    or digest([state['checkpoint_digest'], detail['receipt_digest']]) != detail['checkpoint_digest']):
                raise ValueError('page receipt or checkpoint chain mismatch')
            state['pages'].append(detail)
            state.update(position=detail['next_position'], terminal=detail['terminal'], checkpoint_digest=detail['checkpoint_digest'], not_before=None)
        else:
            state['attempts'].append(event)
            if event['kind'] == 'rate_limited':
                # Keep the later wait: a concurrent failure must not erase a recorded 429 backoff.
                state['not_before'] = max(filter(None, (state['not_before'], detail['not_before'])), key=datetime.fromisoformat)
            if event['kind'] == 'rejected': state.update(terminal='blocked', rejection=dict(detail, position=event['position']))
        state['last'] = event['kind']
    return state


class QBOStagingStore:
    """One entity per separate staging file; append-only observations and checkpoint events."""

    def __init__(self, path, entity_id, *, authority=None, busy_timeout_ms=2000):
        if type(entity_id) is not str or not entity_id.strip(): raise ValueError('entity ID required')
        self.entity_id, self.authority = entity_id, authority
        self.db = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, isolation_level=None)
        try:
            self.db.execute('PRAGMA foreign_keys=ON'); self.db.execute('PRAGMA synchronous=FULL')
            with self._transaction():
                self._initialize()
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def _transaction(self, write=True):
        try:
            self.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield
            self.db.commit()
        except BaseException as error:
            self.db.rollback()
            if isinstance(error, sqlite3.OperationalError) and getattr(error, 'sqlite_errorcode', 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise PersistenceBusy('staging database busy; resume the same batch') from error
            raise

    @contextmanager
    def _write(self):
        # Authority (when supplied) is rechecked and held through each staging commit.
        with (self.authority() if self.authority else nullcontext()), self._transaction():
            yield

    def _initialize(self):
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        application = self.db.execute('PRAGMA application_id').fetchone()[0]
        if (version, application) == (SCHEMA_VERSION, APPLICATION_ID):
            if self.db.execute('SELECT entity_id FROM staging_context').fetchall() != [(self.entity_id,)]:
                raise ValueError('staging mirror belongs to a different entity')
            return
        if version or application or self.db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
            raise ValueError('unsupported or unversioned staging database')
        for statement in SCHEMA:
            self.db.execute(statement)
        self.db.execute('INSERT INTO staging_context VALUES(1,?)', (self.entity_id,))
        for table, conflict in PROTECTED:
            protect_table(self.db, table, conflict)
        self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def _events(self, batch_id):
        return [dict(sequence=s, kind=k, position=p, detail=json.loads(d), actor_id=a, recorded_at=r) for s, k, p, d, a, r in self.db.execute(
            'SELECT sequence,kind,position,detail_json,actor_id,recorded_at FROM qbo_events WHERE batch_id=? ORDER BY sequence', (batch_id,))]

    def _scope(self, batch_id):
        row = self.db.execute('SELECT scope_json,scope_digest FROM qbo_batches WHERE batch_id=?', (batch_id,)).fetchone()
        if row is None: raise KeyError(batch_id)
        return json.loads(row[0]), row[1]

    def open_batch(self, batch_id, scope, actor_id, now):
        with self._write():
            row = self.db.execute('SELECT scope_digest FROM qbo_batches WHERE batch_id=?', (batch_id,)).fetchone()
            if row is None:
                self.db.execute('INSERT INTO qbo_batches VALUES(?,?,?,?,?,?)',
                                (batch_id, self.entity_id, digest(scope), _canonical(scope), actor_id, now.isoformat()))
            elif row[0] != digest(scope):
                raise ValueError('batch already binds a different connector scope; start a new batch')

    def state(self, batch_id):
        with self._transaction(write=False):
            return replay(self._events(batch_id), *self._scope(batch_id))

    def record(self, batch_id, kind, position, detail, actor_id, now, records=()):
        """Append one event only while its cursor is current; a page adds observations atomically."""
        with self._write():
            scope, scope_digest = self._scope(batch_id)
            events = self._events(batch_id)
            state = replay(events, scope, scope_digest)
            if state['terminal'] or state['position'] != position:
                return False  # A concurrent attempt already advanced or ended this batch; reuse its records.
            if kind == 'page':
                problem = self._page_problem(scope_digest, state, records)
                if problem:
                    kind, detail = 'rejected', dict(reason=problem, response_sha256=detail['response_sha256'])
                else:
                    detail = self._receipt(scope, state, position, detail, records)
                    for record in records:
                        if not self._observation(scope_digest, record):
                            self.db.execute('INSERT INTO qbo_observations VALUES(?,?,?,?,?)', (scope_digest, record['remote_id'],
                                            record['sync_token'], digest(record), _canonical(record)))
            self.db.execute('INSERT INTO qbo_events VALUES(?,?,?,?,?,?,?)',
                            (batch_id, len(events) + 1, kind, position, _canonical(detail), actor_id, now.isoformat()))
            return True

    def _observation(self, scope_digest, record):
        row = self.db.execute('SELECT record_json FROM qbo_observations WHERE scope_digest=? AND remote_id=? AND sync_token=?',
                              (scope_digest, record['remote_id'], record['sync_token'])).fetchone()
        return row and row[0]

    def _page_problem(self, scope_digest, state, records):
        accepted = {item['remote_id']: item['sync_token'] for page in state['pages'] for item in page['records']}
        for record in records:
            remote_id, token = record['remote_id'], record['sync_token']
            # Offset pagination is not a snapshot: surface movement instead of double counting.
            if remote_id in accepted:
                return (f'JournalEntry {remote_id} repeated during batch' if accepted[remote_id] == token else
                        f'JournalEntry {remote_id} changed during batch (SyncToken {accepted[remote_id]} -> {token})')
            stored = self._observation(scope_digest, record)
            # Compare content itself, so even a digest collision cannot overwrite evidence.
            if stored and stored != _canonical(record):
                return f'JournalEntry {remote_id} SyncToken {token} conflicts with previously observed content'
        return None

    @staticmethod
    def _receipt(scope, state, position, detail, records):
        number = len(state['pages']) + 1
        terminal = _terminal(scope['connector'], number, len(records))
        receipt = dict(page_number=number, position=position, row_count=len(records), next_position=position + len(records),
                       response_sha256=detail['response_sha256'], terminal=terminal,
                       records=[dict(remote_id=r['remote_id'], sync_token=r['sync_token'], content_digest=digest(r), status=r['status']) for r in records])
        receipt['receipt_digest'] = digest(receipt)
        receipt['checkpoint_digest'] = digest([state['checkpoint_digest'], receipt['receipt_digest']])
        return receipt

    def batch_ids(self):
        return [row[0] for row in self.db.execute('SELECT batch_id FROM qbo_batches ORDER BY created_at,batch_id')]

    def capture(self, batch_id):
        with self._transaction(write=False):
            row = self.db.execute('SELECT entity_id,scope_json,scope_digest,actor_id,created_at FROM qbo_batches WHERE batch_id=?', (batch_id,)).fetchone()
            if row is None: raise KeyError(batch_id)
            events = self._events(batch_id)
            keys = sorted({(item['remote_id'], item['sync_token']) for e in events if e['kind'] == 'page' for item in e['detail']['records']})
            observations = [json.loads(self._observation(row[2], dict(remote_id=k[0], sync_token=k[1]))) for k in keys]
        capture = dict(policy=POLICY, events=events, observations=observations, batch=dict(batch_id=batch_id, entity_id=row[0],
            scope=json.loads(row[1]), scope_digest=row[2], actor_id=row[3], created_at=row[4]))
        capture['input_digest'] = digest(capture)
        return capture

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def batch_report(capture):
    """Pure rehydration of one captured batch; digests are consistency checks, not signatures."""
    try:
        if set(capture) != {'policy', 'batch', 'events', 'observations', 'input_digest'} or capture['policy'] != POLICY:
            raise ValueError('unsupported staging capture')
        if digest({k: v for k, v in capture.items() if k != 'input_digest'}) != capture['input_digest']: raise ValueError('staging capture digest mismatch')
        batch = capture['batch']; scope = batch['scope']; connector = scope['connector']
        if digest(scope) != batch['scope_digest'] or scope['policy'] != POLICY or scope['entity_id'] != batch['entity_id']:
            raise ValueError('staging scope digest mismatch')
        state = replay(capture['events'], scope, batch['scope_digest'])
        observed = {(r['remote_id'], r['sync_token']): r for r in capture['observations']}
        accepted = [observed[(item['remote_id'], item['sync_token'])] for page in state['pages'] for item in page['records']]
        if [digest(r) for r in accepted] != [item['content_digest'] for page in state['pages'] for item in page['records']]:
            raise ValueError('observation does not match its page receipt')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('malformed staging capture') from error
    accounts = {}
    for record in (r for r in accepted if r['status'] == 'supported'):
        for line in record['lines']:
            accounts.setdefault((line['local_account'], line['remote_account_id']), [0, 0])[line['side'] == 'credit'] += line['amount_cents']
    debits, credits = sum(v[0] for v in accounts.values()), sum(v[1] for v in accounts.values())
    exceptions = [dict(kind='rejected', position=state['rejection']['position'], reason=state['rejection']['reason'])] if state['rejection'] else []
    exceptions += [dict(kind='unsupported', remote_id=r['remote_id'], sync_token=r['sync_token'], reason='; '.join(r['reasons']))
                   for r in accepted if r['status'] == 'unsupported']
    complete = state['terminal'] == 'complete'
    reconciled = complete and not exceptions and debits == credits
    report = dict(label=LABEL, ownership=OWNERSHIP, local_effects=LOCAL_EFFECTS, policy=POLICY, batch_id=batch['batch_id'], entity_id=scope['entity_id'],
        connector_id=connector['connector_id'], environment=connector['environment'], realm_id=connector['realm_id'],
        account_map=connector['account_map'], window=connector['window'], page_size=connector['page_size'], max_pages=connector['max_pages'],
        scope_digest=batch['scope_digest'], started_by=batch['actor_id'], started_at=batch['created_at'],
        status=state['terminal'] or ('rate_limited' if state['last'] == 'rate_limited' else 'resumable'), complete=complete, reconciled=reconciled,
        totals_basis='Reconciled full batch total' if reconciled else 'Accepted supported records only; not a reconciled full total',
        next_position=None if state['terminal'] else state['position'], next_attempt_at=state['not_before'], accepted_count=len(accepted),
        accepted=[dict(remote_id=r['remote_id'], sync_token=r['sync_token'], content_digest=digest(r), status=r['status'], txn_date=r['txn_date'],
                       doc_number=r['doc_number'], total_amount=str(Money(r['total_cents'])) if r['status'] == 'supported' else None) for r in accepted],
        accounts=[dict(local_account=a, remote_account_id=r, debit_cents=d, credit_cents=c, debit_amount=str(Money(d)), credit_amount=str(Money(c)))
                  for (a, r), (d, c) in sorted(accounts.items())],
        total_debit_cents=debits, total_credit_cents=credits, total_debits=str(Money(debits)), total_credits=str(Money(credits)),
        pages=[{k: p[k] for k in ('page_number', 'position', 'row_count', 'next_position', 'terminal', 'response_sha256', 'receipt_digest', 'checkpoint_digest')}
               for p in state['pages']],
        checkpoint_digest=state['checkpoint_digest'], exceptions=exceptions,
        attempts=[dict(e['detail'], kind=e['kind'], position=e['position'], actor_id=e['actor_id'], recorded_at=e['recorded_at']) for e in state['attempts']],
        snapshot_digest=capture['input_digest'])
    report['report_digest'] = digest(report)
    return report


def read_batch(path, *, entity_id, account_codes, batch_id, actor_id, transport, config=CONNECTOR, clock=None, authority=None):
    """Start or resume one batch. Returns control at completion, a cap, a refusal, 429 or a transport failure; never sleeps."""
    if type(batch_id) is not str or not _BATCH.fullmatch(batch_id): raise ValueError('batch ID must be 1-80 letters, digits, _ or -')
    if type(actor_id) is not str or not actor_id.strip(): raise ValueError('actor ID required')
    config = _config(config, account_codes)
    clock = clock or (lambda: datetime.now(timezone.utc))
    with QBOStagingStore(path, entity_id, authority=authority) as store:
        store.open_batch(batch_id, dict(policy=POLICY, entity_id=entity_id, connector=config), actor_id, _now(clock))
        while True:
            state, now = store.state(batch_id), _now(clock)
            if state['terminal'] or (state['not_before'] and now < datetime.fromisoformat(state['not_before'])):
                break
            position = state['position']
            try:
                result = transport(build_request(config, position))
            except (OSError, TransportError) as error:
                # Only the failure class is retained; transport messages could carry raw trace data.
                store.record(batch_id, 'transport_failure', position, dict(reason=type(error).__name__), actor_id, _now(clock))
                break
            now = _now(clock)  # Measure waits from the response, not from before a slow request.
            if (type(result) is not tuple or len(result) != 3 or type(result[0]) is not int or not isinstance(result[1], dict)
                    or type(result[2]) is not bytes):
                store.record(batch_id, 'transport_failure', position, dict(reason='invalid transport response'), actor_id, now)
                break
            status, headers, body = result
            headers = {str(k).lower(): v for k, v in headers.items()}
            if status == 429:
                store.record(batch_id, 'rate_limited', position, dict(status=429, not_before=_retry_at(headers, now).isoformat()), actor_id, now)
                break
            if 500 <= status <= 599:
                store.record(batch_id, 'transport_failure', position, dict(reason=f'HTTP {status}'), actor_id, now)
                break
            fingerprint = hashlib.sha256(body).hexdigest()
            try:
                if status != 200: raise PageError(f'unexpected HTTP status {status}; correct the request and start a new batch')
                if 'application/json' not in str(headers.get('content-type', '')).lower(): raise PageError('response must be application/json')
                records = parse_page(body, config, position)
            except PageError as error:
                store.record(batch_id, 'rejected', position, dict(reason=str(error), response_sha256=fingerprint), actor_id, now)
                break
            store.record(batch_id, 'page', position, dict(response_sha256=fingerprint), actor_id, now, records)
        return batch_report(store.capture(batch_id))


def staged_batches(path, entity_id):
    result = dict(label=LABEL, ownership=OWNERSHIP, local_effects=LOCAL_EFFECTS, policy=POLICY, connector=json.loads(_canonical(CONNECTOR)), batches=[])
    if not Path(path).exists():
        return result  # Reading never creates the staging mirror.
    with QBOStagingStore(path, entity_id) as store:
        result['batches'] = [batch_report(store.capture(batch_id)) for batch_id in store.batch_ids()]
    return result


def reference_journals():
    return json.loads(FIXTURE.read_text(encoding='utf-8'), parse_float=Decimal)['journal_entries']


def _dump(value):
    """Serialize fixture JSON keeping Decimal amounts in their exact lexical form."""
    if isinstance(value, dict): return '{' + ','.join(json.dumps(k) + ':' + _dump(v) for k, v in value.items()) + '}'
    if isinstance(value, list): return '[' + ','.join(map(_dump, value)) + ']'
    return str(value) if isinstance(value, Decimal) else json.dumps(value)


class SimulatedQBO:
    """Deterministic in-process stand-in for the sandbox query endpoint; opens no sockets.

    It serves its journal list in order for any valid bounded query, so tests can
    model a misbehaving remote (wrong dates, repeats, changed versions).
    """

    def __init__(self, journals=None, *, realm_id=CONNECTOR['realm_id']):
        self.journals = reference_journals() if journals is None else journals
        self.realm_id, self.requests = realm_id, []

    def __call__(self, request):
        self.requests.append(request)
        url = urlsplit(request['url'])
        query = parse_qs(url.query).get('query', [''])[0]
        match = re.fullmatch(r"SELECT \* FROM JournalEntry WHERE TxnDate >= '[0-9-]{10}' AND TxnDate <= '[0-9-]{10}' "
                             r"ORDERBY Id STARTPOSITION ([1-9][0-9]*) MAXRESULTS ([1-9][0-9]*)", query)
        if request['method'] != 'GET' or (url.scheme, url.netloc, url.path) != ('https', HOST, f'/v3/company/{self.realm_id}/query') or not match:
            return 400, {'Content-Type': 'application/json'}, b'{"Fault":{"type":"ValidationFault"}}'
        start, size = int(match[1]), int(match[2])
        rows = self.journals[start - 1:start - 1 + size]
        page = {'JournalEntry': rows, 'startPosition': start, 'maxResults': len(rows)} if rows else {}
        return 200, {'Content-Type': 'application/json;charset=UTF-8'}, _dump({'QueryResponse': page, 'time': '2026-02-01T00:00:00.000-08:00'}).encode()


def demo_sandbox_read():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='qbo-read-demo-') as directory:
        workspace = Workspace(directory)
        files = lambda: {name: hashlib.sha256((workspace.root / name).read_bytes()).hexdigest() for name in ('ledger.sqlite3', 'sources.sqlite3', 'runs.sqlite3')}
        before, package = files(), workspace.report_package('2026-01-31')
        print(LABEL + ': synthetic QuickBooks sandbox contract; no credentials, OAuth, network, external write or local-ledger write.')
        simulator, calls, now = SimulatedQBO(), [], [datetime(2026, 2, 1, tzinfo=timezone.utc)]
        def transport(request):
            calls.append(request)
            return (429, {'Retry-After': '120'}, b'') if len(calls) == 1 else simulator(request)
        read = lambda: read_batch(workspace.root / FILE, entity_id=workspace.catalog.entity_id, batch_id='january', actor_id='synthetic-preparer',
            account_codes={a.code for a in workspace.catalog.list_accounts()}, transport=transport, clock=lambda: now[0],
            config=dict(CONNECTOR, page_size=2))  # Injected test page size; production limits stay 100 rows x 100 pages.
        limited = read()
        assert limited['status'] == 'rate_limited' and limited['next_position'] == 1
        print('First request rate limited (429, Retry-After 120): cursor 1 kept; next attempt', limited['next_attempt_at'])
        now[0] += timedelta(seconds=60)
        assert read() == limited and len(calls) == 1
        print('Resume after 60 seconds: still before the persisted time; no request made, no sleeping.')
        now[0] += timedelta(seconds=60)
        report = read()
        assert report['reconciled'] and [p['row_count'] for p in report['pages']] == [2, 1] and report['total_debits'] == report['total_credits'] == '600.00'
        print('Pages:', ' / '.join(f"start {p['position']} rows {p['row_count']}" for p in report['pages']), '; checkpoint', report['checkpoint_digest'][:16])
        print('Accepted IDs:', ', '.join(f"{r['remote_id']}@{r['sync_token']} {r['total_amount']}" for r in report['accepted']))
        for row in report['accounts']:
            print(f"  QuickBooks {row['remote_account_id']} -> local {row['local_account']}: debit {row['debit_amount']} credit {row['credit_amount']}")
        print('Reconciled staged total:', report['total_debits'], '/', report['total_credits'], 'USD.')
        assert read() == report and len(calls) == 3
        assert files() == before and workspace.report_package('2026-01-31') == package
        print('Exact resume reuses the mirror (no new request). Local ledger, evidence, runs and report package unchanged.')
        print(OWNERSHIP)
