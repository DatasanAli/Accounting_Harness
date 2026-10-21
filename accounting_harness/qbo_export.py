"""Bounded offline journal export. Neither this outbox nor its simulator is a ledger.

No network transport exists. Authorization is an authenticated application action;
core methods are trusted local primitives, just like the existing ledger services.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from accounting_harness.domain.money import Money
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest, protect_table
from accounting_harness.qbo_read import CONNECTOR, HOST, LABEL, _config, _decode, _retry_at, normalize, PageError

FILE = 'qbo-outbox.sqlite3'
SIMULATOR_FILE = 'qbo-simulator.sqlite3'
POLICY = 'qbo-cash-expense-export-v1'
MAX_ATTEMPTS = 3
APPLICATION_ID = 0x41485145
SIMULATOR_APPLICATION_ID = 0x41485153
SCHEMA_VERSION = 1


def build_body(journal, mapping):
    """Only Amount is emitted as a number: integer cents -> decimal literal, never float."""
    lines = []
    for index, line in enumerate(journal['lines'], 1):
        detail = _canonical(dict(PostingType=line['side'].title(), AccountRef=dict(value=mapping[line['account']])))
        lines.append('{"Id":' + json.dumps(str(index)) + ',"Amount":' + str(Money(line['cents'])) +
            ',"DetailType":"JournalEntryLineDetail","JournalEntryLineDetail":' + detail + '}')
    return '{"TxnDate":' + json.dumps(journal['effective_date']) + ',"CurrencyRef":{"value":"USD"},"Line":[' + ','.join(lines) + ']}'


@contextmanager
def database(path, entity, *, simulator=False):
    """Separate versioned, entity-bound stores; all schema creation is atomic."""
    db = sqlite3.connect(path, timeout=2, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        app_id = SIMULATOR_APPLICATION_ID if simulator else APPLICATION_ID
        existing = db.execute('PRAGMA application_id').fetchone()[0]
        if existing not in (0, app_id): raise ValueError('wrong export database kind')
        if not existing:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone(): raise ValueError('unrecognized export database')
            db.execute(f'PRAGMA application_id={app_id}')
            db.execute('PRAGMA user_version=1')
            db.execute('CREATE TABLE context(entity_id TEXT PRIMARY KEY) STRICT')
            db.execute('INSERT INTO context VALUES (?)', (entity,))
            protect_table(db, 'context', '1')
            if simulator:
                db.execute('''CREATE TABLE receipts(realm_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    request_json TEXT NOT NULL, remote_id TEXT NOT NULL UNIQUE, response_body TEXT NOT NULL,
                    PRIMARY KEY(realm_id,request_id)) STRICT''')
                protect_table(db, 'receipts', 'realm_id=NEW.realm_id AND request_id=NEW.request_id OR remote_id=NEW.remote_id')
            else:
                db.execute('''CREATE TABLE exports(export_id TEXT PRIMARY KEY, journal_id TEXT NOT NULL,
                    realm_id TEXT NOT NULL, preview_digest TEXT NOT NULL, preview_json TEXT NOT NULL,
                    actor_id TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(journal_id,realm_id)) STRICT''')
                db.execute('''CREATE TABLE export_events(export_id TEXT NOT NULL REFERENCES exports(export_id),
                    sequence INTEGER NOT NULL, kind TEXT NOT NULL, detail_json TEXT NOT NULL,
                    actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY(export_id,sequence)) STRICT''')
                protect_table(db, 'exports', 'export_id=NEW.export_id OR (journal_id=NEW.journal_id AND realm_id=NEW.realm_id)')
                protect_table(db, 'export_events', 'export_id=NEW.export_id AND sequence=NEW.sequence')
        if db.execute('PRAGMA user_version').fetchone()[0] != 1 or db.execute('SELECT entity_id FROM context').fetchall() != [(entity,)]:
            raise ValueError('export database scope/version mismatch')
        db.commit()
        yield db
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


class SimulatedExportQBO:
    """Independent durable request replay; synthetic contract, not Intuit retention proof."""
    def __init__(self, path, entity):
        self.path, self.entity = Path(path), entity

    def create(self, request):
        from urllib.parse import parse_qs, urlsplit
        url = urlsplit(request['url'])
        parts, query = url.path.split('/'), parse_qs(url.query)
        if (request['method'] != 'POST' or url.scheme != 'https' or url.netloc != HOST or
                len(parts) != 5 or parts[1:3] != ['v3','company'] or parts[4] != 'journalentry' or
                set(query) != {'requestid'} or len(query['requestid']) != 1 or len(query['requestid'][0]) > 50):
            return 400, {}, b'{}'
        realm, request_id = parts[3], query['requestid'][0]
        with database(self.path, self.entity, simulator=True) as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT request_json, response_body FROM receipts WHERE realm_id=? AND request_id=?', (realm,request_id)).fetchone()
            if prior:
                if prior[0] != _canonical(request): return 409, {}, b'{}'
                return 200, dict(realm_id=realm), prior[1].encode()
            body = _decode(request['body'].encode())
            if set(body) != {'TxnDate','CurrencyRef','Line'}: return 400, {}, b'{}'
            remote_id = str(db.execute('SELECT count(*) FROM receipts').fetchone()[0] + 1)
            # Preserve every amount lexeme instead of round-tripping decoded numbers.
            response = '{"JournalEntry":{"Id":' + json.dumps(remote_id) + ',"SyncToken":"0",' + request['body'][1:] + '}'
            db.execute('INSERT INTO receipts VALUES (?,?,?,?,?)', (realm,request_id,_canonical(request),remote_id,response))
            db.commit()
            return 200, dict(realm_id=realm), response.encode()

    def read(self, realm, remote_id):
        with database(self.path, self.entity, simulator=True) as db:
            row = db.execute('SELECT response_body FROM receipts WHERE realm_id=? AND remote_id=?', (realm,remote_id)).fetchone()
            return (200, dict(realm_id=realm), row[0].encode()) if row else (404, dict(realm_id=realm), b'{}')


class ExportService:
    def __init__(self, workspace):
        self.workspace = workspace
        self.entity = workspace.catalog.entity_id
        self.actor = workspace.actor_id or 'trusted-local-operator'
        self.path = workspace.root / FILE
        self.simulator = SimulatedExportQBO(workspace.root / SIMULATOR_FILE, self.entity)
        self.config = _config(CONNECTOR, {a.code for a in workspace.catalog.list_accounts()})

    def now(self):
        return datetime.now(timezone.utc)

    def binding(self, ledger, journal_id):
        receipt = ledger._receipt(journal_id)
        entry = receipt.entry
        row = ledger._connection.execute('''SELECT a.approval_id,a.draft_id,a.revision,a.binding_json,a.actor_id,a.recorded_at
            FROM review_postings p JOIN approvals a USING(approval_id) WHERE p.journal_id=?''', (journal_id,)).fetchone()
        if (not row or entry.currency != 'USD' or receipt.original_entry_id or
                ledger._connection.execute('SELECT 1 FROM reversals WHERE original_id=?', (journal_id,)).fetchone()):
            raise ValueError('local journal must be reviewed, posted, ordinary and unreversed')
        approval = dict(zip(('approval_id','draft_id','revision','binding_json','actor_id','recorded_at'),row))
        bound = json.loads(approval['binding_json'])
        if bound['policy_version'] not in ('review-v1','cash-v1'):
            raise ValueError('export supports only reviewed cash expenses')
        lines = entry.lines
        if (len(lines) != 2 or len([l for l in lines if l.account == '1000' and l.side == 'credit']) != 1 or
                len([l for l in lines if l.account in ('5000','5100') and l.side == 'debit']) != 1):
            raise ValueError('export supports only Cash credit and Rent or Software Expense debit')
        if not self.config['window']['start'] <= entry.effective_date.isoformat() <= self.config['window']['end']:
            raise ValueError('journal is outside the fixed connector window')
        return json.loads(_canonical(dict(journal=ledger._entry_payload(entry), approval=approval)))

    def _load(self, db, export_id):
        row = db.execute('SELECT preview_digest,preview_json,actor_id,created_at FROM exports WHERE export_id=?', (export_id,)).fetchone()
        if row is None: raise ValueError('unknown export identity in this entity')
        preview = json.loads(row[1])
        if digest(preview) != row[0]: raise ValueError('export preview integrity mismatch')
        events = [dict(sequence=r[0], kind=r[1], detail=json.loads(r[2]), actor_id=r[3], recorded_at=r[4])
            for r in db.execute('SELECT sequence,kind,detail_json,actor_id,recorded_at FROM export_events WHERE export_id=? ORDER BY sequence', (export_id,))]
        status, remote_id, confirmed, next_at, attempts = 'prepared', None, None, None, 0
        for event in events:
            kind, detail = event['kind'], event['detail']
            if kind == 'authorized': status = 'authorized'
            elif kind == 'attempted': status, attempts, next_at = 'attempted', attempts+1, detail['next_attempt_at']
            elif kind in ('uncertain','exception'): status = kind
            elif kind == 'rate_limited': status = detail['status']
            elif kind == 'confirmed': status, remote_id, confirmed, next_at = 'confirmed', detail['remote_id'], detail, None
            elif kind == 'checked': status, next_at = 'confirmed', None
            elif kind == 'receipt': remote_id = detail['remote_id']
            if detail.get('next_attempt_at'): next_at = detail['next_attempt_at']
        # There is no reconciliation action in this bounded policy. An observed
        # exception remains unresolved even when later transport/read events occur.
        if any(event['kind'] == 'exception' for event in events): status = 'exception'
        # attempted is a durable crash checkpoint: effect may have occurred.
        result = dict(preview, preview_digest=row[0], prepared_by=row[2], prepared_at=row[3], events=events,
            status=status, remote_id=remote_id, confirmed_receipt=confirmed, attempts=attempts, next_attempt_at=next_at,
            label=LABEL, total_debits=str(Money(preview['total_cents'])), total_credits=str(Money(preview['total_cents'])))
        result['audit_json'] = _canonical(result)
        return result

    def _event(self, db, export_id, kind, detail):
        sequence = db.execute('SELECT coalesce(max(sequence),0)+1 FROM export_events WHERE export_id=?', (export_id,)).fetchone()[0]
        db.execute('INSERT INTO export_events VALUES (?,?,?,?,?,?)', (export_id,sequence,kind,_canonical(detail),self.actor,self.now().isoformat()))

    def preview(self, journal_id):
        with self.workspace.storage() as (_,ledger,_,_,_), ledger._transaction(write=True):
            binding = self.binding(ledger, journal_id)
            reverse = {}
            for remote, local in self.config['account_map']['accounts'].items():
                if local in reverse: raise ValueError('export account mapping must be unambiguous')
                reverse[local] = remote
            if any(l['account'] not in reverse for l in binding['journal']['lines']): raise ValueError('unmapped local account')
            with database(self.path, self.entity) as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT export_id FROM exports WHERE journal_id=? AND realm_id=?', (journal_id,self.config['realm_id'])).fetchone()
                if existing:
                    result = self._load(db, existing[0])
                    if result['connector'] != self.config or result['binding'] != binding:
                        raise ValueError('existing identity binds different destination/mapping or local approval; explicit reconciliation required')
                    return result
                export_id = str(uuid4())
                request = dict(method='POST', url=f'https://{HOST}/v3/company/{self.config["realm_id"]}/journalentry?requestid={export_id}',
                    headers={'Accept':'application/json','Content-Type':'application/json'}, body=build_body(binding['journal'], reverse))
                preview = dict(policy=POLICY, entity_id=self.entity, export_id=export_id, journal_id=journal_id,
                    connector=self.config, binding=binding, request=request, total_cents=sum(l['cents'] for l in binding['journal']['lines'] if l['side']=='debit'))
                db.execute('INSERT INTO exports VALUES (?,?,?,?,?,?,?)', (export_id,journal_id,self.config['realm_id'],digest(preview),_canonical(preview),self.actor,self.now().isoformat()))
                db.commit()
                return self._load(db, export_id)

    def _current(self, ledger, record):
        if record['connector'] != self.config: raise ValueError('destination/mapping changed; new explicit authorization required')
        if self.binding(ledger, record['journal_id']) != record['binding']: raise ValueError('local approval or journal binding changed')

    def authorize(self, export_id, confirmed_digest, confirmed):
        if confirmed is not True: raise ValueError('explicit export confirmation is required')
        with self.workspace.storage() as (_,ledger,_,_,_), ledger._transaction(write=True), database(self.path,self.entity) as db:
            db.execute('BEGIN IMMEDIATE')
            record = self._load(db, export_id)
            self._current(ledger,record)
            if confirmed_digest != record['preview_digest']: raise ValueError('export preview confirmation changed')
            prior = next((e for e in record['events'] if e['kind']=='authorized'),None)
            if prior:
                if prior['actor_id'] != self.actor: raise ValueError('export authorization already belongs to another actor')
            else:
                self._event(db,export_id,'authorized',dict(preview_digest=confirmed_digest))
            db.commit()
            return self._load(db,export_id)

    def _readback(self, db, record):
        remote_id = record['remote_id']
        try:
            status, headers, body = self.simulator.read(record['connector']['realm_id'],remote_id)
        except (TimeoutError, OSError):
            self._event(db,record['export_id'],'uncertain',dict(reason='readback unavailable; reconcile the existing remote identity'))
            return
        # Capture bounded raw observation before interpreting it, preserving original receipt.
        observation = dict(http_status=status, realm_id=headers.get('realm_id'), body=body[:4*1024*1024].decode('utf-8',errors='replace'))
        try:
            if status != 200 or headers.get('realm_id') != record['connector']['realm_id']: raise ValueError('readback status or realm mismatch')
            decoded = _decode(body)
            if type(decoded) is not dict or set(decoded) != {'JournalEntry'}: raise ValueError('readback must contain one JournalEntry')
            remote = normalize(decoded['JournalEntry'],record['connector'])
            expected = record['binding']['journal']
            actual_lines = sorted((l['local_account'],l['side'],l['amount_cents']) for l in remote['lines'])
            expected_lines = sorted((l['account'],l['side'],l['cents']) for l in expected['lines'])
            if (remote['status'] != 'supported' or remote['remote_id'] != remote_id or remote['txn_date'] != expected['effective_date'] or
                    remote['currency'] != expected['currency'] or actual_lines != expected_lines or remote['total_cents'] != record['total_cents']):
                raise ValueError('readback differs from the authorized journal')
        except (ValueError, TypeError, KeyError):
            self._event(db,record['export_id'],'exception',dict(reason='remote readback drift or invalid record', observation=observation))
            return
        if record['confirmed_receipt'] and record['confirmed_receipt']['observation'] != observation:
            self._event(db,record['export_id'],'exception',dict(reason='remote observation changed after confirmation',observation=observation))
        elif record['status'] == 'exception':
            self._event(db,record['export_id'],'exception',dict(reason='prior exception requires explicit reconciliation; matching observation retained',observation=observation))
        elif record['confirmed_receipt']:
            self._event(db,record['export_id'],'checked',dict(observation=observation))
        else:
            self._event(db,record['export_id'],'confirmed',dict(remote_id=remote_id, observation=observation, normalized=remote))

    def send(self, export_id):
        # ponytail: access facade serializes offline effects; no network transport exists.
        # Ledger lock makes the first eligibility check and simulated send atomic with reversals.
        with self.workspace.storage() as (_,ledger,_,_,_), ledger._transaction(write=True), database(self.path,self.entity) as db:
            db.execute('BEGIN IMMEDIATE')
            record = self._load(db,export_id)
            self._current(ledger,record)
            if record['status'] == 'confirmed': return record
            if record['status'] in ('prepared','exception'): raise ValueError('export must have separate authorization and no exception')
            if record['remote_id']:
                self._readback(db,record); db.commit(); return self._load(db,export_id)
            if record['attempts'] >= MAX_ATTEMPTS: raise ValueError('bounded attempts exhausted; explicit reconciliation required')
            if record['next_attempt_at'] and self.now() < datetime.fromisoformat(record['next_attempt_at']): raise ValueError('export retry is rate limited until next_attempt_at')
            next_at = (self.now()+timedelta(seconds=60)).isoformat()
            self._event(db,export_id,'attempted',dict(next_attempt_at=next_at))
            db.commit()  # Crash after here is attempted/uncertain; request identity already durable.
            db.execute('BEGIN IMMEDIATE')
            try:
                status, headers, body = self.simulator.create(record['request'])
            except (TimeoutError, OSError):
                self._event(db,export_id,'uncertain',dict(reason='transport outcome unknown; retry only the same request',next_attempt_at=next_at))
            else:
                if status == 429:
                    self._event(db,export_id,'rate_limited',dict(status='uncertain' if record['status'] in ('uncertain','attempted') else 'authorized', next_attempt_at=_retry_at(headers,self.now()).isoformat()))
                elif status >= 500:
                    self._event(db,export_id,'uncertain',dict(reason='server outcome unknown; same-request replay only',next_attempt_at=next_at))
                elif status != 200:
                    self._event(db,export_id,'exception',dict(reason='definitive simulator rejection',http_status=status))
                else:
                    try:
                        decoded = _decode(body)
                        remote_id = decoded['JournalEntry']['Id']
                        if headers.get('realm_id') != record['connector']['realm_id'] or type(remote_id) is not str or not remote_id.isdigit() or len(remote_id)>80:
                            raise ValueError('invalid receipt identity')
                    except (ValueError, TypeError, KeyError):
                        self._event(db,export_id,'exception',dict(reason='malformed simulator receipt; outcome requires reconciliation',observation=body[:4096].decode('utf-8',errors='replace')))
                    else:
                        self._event(db,export_id,'receipt',dict(remote_id=remote_id,body=body.decode('utf-8')))
                        self._readback(db,self._load(db,export_id))
            db.commit()
            return self._load(db,export_id)

    def check(self, export_id):
        with self.workspace.storage() as (_,ledger,_,_,_), ledger._transaction(write=True), database(self.path,self.entity) as db:
            db.execute('BEGIN IMMEDIATE')
            record = self._load(db,export_id)
            try: self._current(ledger,record)
            except ValueError as error:
                self._event(db,export_id,'exception',dict(reason='local divergence: '+str(error)))
            else:
                if not record['remote_id']: raise ValueError('no remote identity; uncertainty requires same-request recovery')
                self._readback(db,record)
            db.commit()
            return self._load(db,export_id)

    def history(self):
        if not self.path.exists(): return dict(label=LABEL,exports=[])
        with database(self.path,self.entity) as db:
            db.execute('BEGIN')
            return dict(label=LABEL,exports=[self._load(db,row[0]) for row in db.execute('SELECT export_id FROM exports ORDER BY created_at,export_id')])


def demo_sandbox_export():
    from tempfile import TemporaryDirectory
    from accounting_harness.access import AccessStore, provision_synthetic_workspace
    from accounting_harness.authenticated import AuthenticatedWorkspace
    with TemporaryDirectory(prefix='accounting-export-') as directory:
        root=Path(directory); access=AccessStore(root/'access.sqlite3')
        provision_synthetic_workspace(root/'alpha','alpha')
        access.register_entity('alpha',root/'alpha',reason='Synthetic demonstration')
        user=access.create_user('owner','Temporary synthetic export passphrase',reason='Synthetic demonstration')
        access.bootstrap_grant(user,'alpha','owner',reason='Synthetic demonstration',retry_key='grant')
        token=access.login('owner','Temporary synthetic export passphrase')
        app=AuthenticatedWorkspace(access)
        def call(action,data): return app.call(token,'alpha','action',action,data)
        common=dict(schema_version=2,synthetic=True,entity_id='alpha',currency='USD',document_date='2026-01-05',
            amount='125.00',event_id='export-rent',counterparty='Fictional landlord',counterparty_id='landlord',description='Synthetic rent')
        documents=[dict(common,document_id='export-cash',kind='cash_movement',direction='out',purpose='incurred_expense'),
                   dict(common,document_id='export-fact',kind='incurred_expense',incurred_date='2026-01-05',expense_account='5000')]
        for document in documents: call('operation-sources',dict(document=document))
        draft=call('cash-proposals',dict(operation='cash_expense',cash_source_id='export-cash',recognition_source_id='export-fact'))
        call('approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        state=app.call(token,'alpha','state'); journal=state['drafts'][0]['audit']['journal_id']
        preview=call('qbo-export-preview',dict(journal_id=journal))
        assert preview['status']=='prepared'
        call('qbo-export-authorize',dict(export_id=preview['export_id'],confirmed_digest=preview['preview_digest'],confirmed=True))
        result=call('qbo-export-send',dict(export_id=preview['export_id']))
        assert result['status']=='confirmed' and result['total_debits']==result['total_credits']=='125.00'
        assert call('qbo-export-send',dict(export_id=preview['export_id']))['remote_id']==result['remote_id']
        assert app.call(token,'alpha','state')==state
        with database(root/'alpha'/SIMULATOR_FILE,'alpha',simulator=True) as db:
            assert db.execute('SELECT count(*) FROM receipts').fetchone()[0]==1
        print('Offline contract simulation: one simulated remote journal; readback 125.00 USD debit / 125.00 USD credit.')
        print('Separate human export authorization, stable request replay, unchanged local ledger. Live sandbox export remains deferred.')
