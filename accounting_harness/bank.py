"""One fictional CSV format; immutable bank records, never ledger postings."""
import csv
import hashlib
import io
import json
from datetime import datetime, timezone

from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.money import Money
from accounting_harness.persistence import _canonical as canonical
from accounting_harness.review import digest, protect_table

CSV_HEADERS = ('bank_account_id', 'transaction_id', 'booking_date', 'amount', 'currency', 'reference', 'description')
MAX_CSV_BYTES = 8192
MAX_ROWS = 100
MAX_FIELD_CHARS = 512
MAX_ID_CHARS = 80
MAX_CENTS = 2**63 - 1
REQUEST_FIELDS = {'statement_id', 'bank_account_id', 'period_start', 'period_end',
                  'opening_balance', 'closing_balance', 'currency', 'csv_content'}


def signed_amount(cents):
    return ('-' if cents < 0 else '') + str(Money(abs(cents)))


def signed_cents(value, *, movement=False):
    if type(value) is not str or len(value) > 22:
        raise ValueError('amount must be a decimal string of at most 22 characters')
    negative = value.startswith('-')
    cents = Money.parse(value[1:] if negative else value).cents
    if cents > MAX_CENTS or (negative and cents == 0) or (movement and cents == 0):
        raise ValueError('amount exceeds signed 64-bit cents, is negative zero, or is a zero movement')
    return -cents if negative else cents


def identifier(value, label):
    if (type(value) is not str or not value or len(value) > MAX_ID_CHARS
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(f'{label} must contain 1 through {MAX_ID_CHARS} characters without surrounding whitespace or controls')
    return value


def parse_statement(data, *, entity_id, period_start, period_end):
    if type(data) is not dict or set(data) != REQUEST_FIELDS:
        raise ValueError('statement requires exactly: ' + ', '.join(sorted(REQUEST_FIELDS)))
    for field in REQUEST_FIELDS - {'csv_content'}:
        if type(data[field]) is not str:
            raise ValueError(f'{field} must be a string')
    statement_id = identifier(data['statement_id'], 'statement_id')
    account = identifier(data['bank_account_id'], 'bank_account_id')
    start, end = accounting_date(data['period_start']), accounting_date(data['period_end'])
    if not period_start <= start <= end <= period_end:
        raise ValueError('statement dates must be ordered and inside the workspace period')
    if data['currency'] != 'USD':
        raise ValueError('only USD is supported')
    opening, closing = signed_cents(data['opening_balance']), signed_cents(data['closing_balance'])
    source = data['csv_content']
    if type(source) is bytes:
        if len(source) > MAX_CSV_BYTES:
            raise ValueError(f'CSV must be at most {MAX_CSV_BYTES} UTF-8 bytes')
        source = source.decode('utf-8', errors='strict')
    if type(source) is not str:
        raise ValueError('csv_content must be UTF-8 text or bytes')
    source_bytes = source.encode('utf-8', errors='strict')
    if len(source_bytes) > MAX_CSV_BYTES:
        raise ValueError(f'CSV must be at most {MAX_CSV_BYTES} UTF-8 bytes')
    rows, seen = [], set()
    reader = csv.reader(io.StringIO(source, newline=''), strict=True)
    try:
        if next(reader, None) != list(CSV_HEADERS):
            raise ValueError('CSV headers must be exactly: ' + ','.join(CSV_HEADERS))
        for number, cells in enumerate(reader, 1):
            try:
                if number > MAX_ROWS:
                    raise ValueError(f'CSV accepts at most {MAX_ROWS} movement rows')
                if len(cells) != len(CSV_HEADERS):
                    raise ValueError('expected exactly seven cells')
                if any(len(cell) > MAX_FIELD_CHARS or '\x00' in cell for cell in cells):
                    raise ValueError(f'fields must be at most {MAX_FIELD_CHARS} characters without NUL')
                row = dict(zip(CSV_HEADERS, cells))
                if row['bank_account_id'] != account:
                    raise ValueError('bank account does not match statement metadata')
                transaction_id = identifier(row['transaction_id'], 'transaction_id')
                if transaction_id in seen:
                    raise ValueError('duplicate transaction_id inside statement')
                if not start <= accounting_date(row['booking_date']) <= end:
                    raise ValueError('booking_date is outside statement dates')
                if row['currency'] != 'USD':
                    raise ValueError('only USD is supported')
                cents = signed_cents(row['amount'], movement=True)
                row['amount'] = signed_amount(cents)
                row['amount_cents'] = cents
                seen.add(transaction_id)
                rows.append(row)
            except (TypeError, ValueError) as error:
                raise ValueError(f'CSV row {number} (physical line {reader.line_num}): {error}') from error
    except csv.Error as error:
        raise ValueError(f'CSV physical line {reader.line_num}: {error}') from error
    movements = sum(row['amount_cents'] for row in rows)
    residual = opening + movements - closing
    if residual:
        raise ValueError('statement does not balance: opening + movements - closing residual ' + signed_amount(residual) + ' USD')
    statement = dict(entity_id=entity_id, synthetic=True, statement_id=statement_id,
        bank_account_id=account, ledger_account='1000', period_start=start.isoformat(), period_end=end.isoformat(),
        currency='USD', opening_balance=signed_amount(opening), movement_total=signed_amount(movements),
        closing_balance=signed_amount(closing), source_digest=hashlib.sha256(source_bytes).hexdigest(), row_count=len(rows))
    return statement, rows


class BankStatementService:
    """Versioned additive bank storage in the existing ledger database."""
    def __init__(self, ledger):
        self.ledger = ledger
        self.db = ledger._connection
        self.entity_id = ledger._empty.catalog.entity_id
        with ledger._transaction(write=True):
            self._initialize()

    def _initialize(self):
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_schema'").fetchone()
        if exists:
            if self.db.execute('SELECT version FROM bank_schema').fetchall() != [(1,)]:
                raise ValueError('unsupported bank schema')
            return
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'bank_*' LIMIT 1").fetchone():
            raise ValueError('refusing to adopt unversioned bank records')
        self.db.execute('CREATE TABLE bank_schema (version INTEGER PRIMARY KEY CHECK(version=1)) STRICT, WITHOUT ROWID')
        self.db.execute('INSERT INTO bank_schema VALUES (1)')
        self.db.execute('''CREATE TABLE bank_accounts (
            entity_id TEXT PRIMARY KEY, bank_account_id TEXT NOT NULL,
            ledger_account TEXT NOT NULL CHECK(ledger_account='1000') REFERENCES accounts(code),
            currency TEXT NOT NULL CHECK(currency='USD'), synthetic INTEGER NOT NULL CHECK(synthetic=1),
            actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
            UNIQUE(entity_id,bank_account_id)) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE bank_statements (
            entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, statement_id TEXT NOT NULL,
            content_digest TEXT NOT NULL, statement_json TEXT NOT NULL,
            PRIMARY KEY(entity_id,bank_account_id,statement_id),
            FOREIGN KEY(entity_id,bank_account_id) REFERENCES bank_accounts(entity_id,bank_account_id),
            FOREIGN KEY(entity_id,bank_account_id,statement_id) REFERENCES bank_receipts(entity_id,bank_account_id,statement_id)
                DEFERRABLE INITIALLY DEFERRED) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE bank_transactions (
            entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents!=0), row_json TEXT NOT NULL,
            actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
            PRIMARY KEY(entity_id,bank_account_id,transaction_id),
            FOREIGN KEY(entity_id,bank_account_id) REFERENCES bank_accounts(entity_id,bank_account_id)) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE bank_membership (
            entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, statement_id TEXT NOT NULL,
            row_number INTEGER NOT NULL CHECK(row_number BETWEEN 1 AND 100), transaction_id TEXT NOT NULL,
            PRIMARY KEY(entity_id,bank_account_id,statement_id,row_number),
            UNIQUE(entity_id,bank_account_id,statement_id,transaction_id),
            FOREIGN KEY(entity_id,bank_account_id,statement_id) REFERENCES bank_statements(entity_id,bank_account_id,statement_id),
            FOREIGN KEY(entity_id,bank_account_id,transaction_id) REFERENCES bank_transactions(entity_id,bank_account_id,transaction_id)) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE bank_receipts (
            entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, statement_id TEXT NOT NULL, audit_json TEXT NOT NULL,
            PRIMARY KEY(entity_id,bank_account_id,statement_id),
            FOREIGN KEY(entity_id,bank_account_id,statement_id) REFERENCES bank_statements(entity_id,bank_account_id,statement_id)) STRICT, WITHOUT ROWID''')
        for table, conflict in [
            ('bank_schema', '1'), ('bank_accounts', 'entity_id=NEW.entity_id'),
            ('bank_statements', 'entity_id=NEW.entity_id AND bank_account_id=NEW.bank_account_id AND statement_id=NEW.statement_id'),
            ('bank_transactions', 'entity_id=NEW.entity_id AND bank_account_id=NEW.bank_account_id AND transaction_id=NEW.transaction_id'),
            ('bank_membership', '''entity_id=NEW.entity_id AND bank_account_id=NEW.bank_account_id
                AND statement_id=NEW.statement_id AND (row_number=NEW.row_number OR transaction_id=NEW.transaction_id)'''),
            ('bank_receipts', 'entity_id=NEW.entity_id AND bank_account_id=NEW.bank_account_id AND statement_id=NEW.statement_id')]:
            protect_table(self.db, table, conflict)
        self.db.execute('''CREATE TRIGGER bank_membership_sealed BEFORE INSERT ON bank_membership
            WHEN EXISTS (SELECT 1 FROM bank_receipts WHERE entity_id=NEW.entity_id
                AND bank_account_id=NEW.bank_account_id AND statement_id=NEW.statement_id)
            BEGIN SELECT RAISE(ABORT,'statement membership is sealed'); END''')

    def import_statement(self, data, *, actor_id):
        actor_id = identifier(actor_id, 'actor_id')
        statement, rows = parse_statement(data, entity_id=self.entity_id,
            period_start=self.ledger._empty.period_start, period_end=self.ledger._empty.period_end)
        identity = (self.entity_id, statement['bank_account_id'], statement['statement_id'])
        content_digest = digest([statement, rows])
        with self.ledger._transaction(write=True):
            prior = self.db.execute('''SELECT content_digest FROM bank_statements
                WHERE entity_id=? AND bank_account_id=? AND statement_id=?''', identity).fetchone()
            if prior:
                if prior[0] != content_digest:
                    raise ValueError('statement identity conflicts with immutable content')
                return self._detail(identity)
            mapping = self.db.execute('SELECT bank_account_id FROM bank_accounts WHERE entity_id=?', (self.entity_id,)).fetchone()
            if mapping and mapping[0] != statement['bank_account_id']:
                raise ValueError('workspace bank account mapping is immutable; use the selected bank account')
            now = datetime.now(timezone.utc).isoformat()
            if not mapping:
                self.db.execute('INSERT INTO bank_accounts VALUES (?,?,?,?,?,?,?)',
                    (self.entity_id, statement['bank_account_id'], '1000', 'USD', 1, actor_id, now))
            self.db.execute('INSERT INTO bank_statements VALUES (?,?,?,?,?)', (*identity, content_digest, canonical(statement)))
            for index, row in enumerate(rows, 1):
                transaction = (*identity[:2], row['transaction_id'])
                stored = self.db.execute('''SELECT row_json FROM bank_transactions
                    WHERE entity_id=? AND bank_account_id=? AND transaction_id=?''', transaction).fetchone()
                row_json = canonical(row)
                if stored:
                    if stored[0] != row_json:
                        raise ValueError(f'CSV row {index}: transaction identity {row["transaction_id"]} conflicts with immutable content')
                else:
                    self.db.execute('INSERT INTO bank_transactions VALUES (?,?,?,?,?,?,?)',
                        (*transaction, row['amount_cents'], row_json, actor_id, now))
                self.db.execute('INSERT INTO bank_membership VALUES (?,?,?,?,?)', (*identity, index, row['transaction_id']))
            audit = dict(receipt_id='bank-import-' + digest(list(identity)), content_digest=content_digest,
                         actor_id=actor_id, recorded_at=now, source_digest=statement['source_digest'])
            self.db.execute('INSERT INTO bank_receipts VALUES (?,?,?,?)', (*identity, canonical(audit)))
            return self._detail(identity)

    def _detail(self, identity):
        found = self.db.execute('''SELECT s.statement_json,r.audit_json FROM bank_statements s JOIN bank_receipts r
            USING(entity_id,bank_account_id,statement_id) WHERE s.entity_id=? AND s.bank_account_id=? AND s.statement_id=?''', identity).fetchone()
        if not found:
            raise KeyError('bank statement not found')
        rows = []
        for row_json, actor_id, recorded_at in self.db.execute('''SELECT t.row_json,t.actor_id,t.recorded_at
            FROM bank_membership m JOIN bank_transactions t USING(entity_id,bank_account_id,transaction_id)
            WHERE m.entity_id=? AND m.bank_account_id=? AND m.statement_id=? ORDER BY m.row_number''', identity):
            row = json.loads(row_json)
            # Exact strings across the JSON/browser boundary, including cents in the audit.
            row['amount_cents'] = str(row['amount_cents'])
            rows.append(dict(row, actor_id=actor_id, recorded_at=recorded_at))
        result = dict(statement=json.loads(found[0]), rows=rows, audit=json.loads(found[1]))
        result['trace_json'] = json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True)
        return result

    def detail(self, bank_account_id, statement_id):
        identity = (self.entity_id, identifier(bank_account_id, 'bank_account_id'), identifier(statement_id, 'statement_id'))
        with self.ledger._transaction():
            return self._detail(identity)

    def list_statements(self):
        with self.ledger._transaction():
            return [json.loads(row[0]) for row in self.db.execute('''SELECT statement_json FROM bank_statements
                WHERE entity_id=? ORDER BY bank_account_id,statement_id''', (self.entity_id,))]


def demo_bank_import():
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    fixture = Path(__file__).resolve().parent.parent / 'data/fixtures/fictional-bank-january.csv'
    data = dict(statement_id='fictional-january', bank_account_id='fictional-bank',
        period_start='2026-01-01', period_end='2026-01-31', opening_balance='1000.00',
        closing_balance='1050.00', currency='USD', csv_content=fixture.read_text())
    with TemporaryDirectory(prefix='accounting-bank-') as directory:
        workspace = Workspace(directory)
        before = workspace.state()['trial_balance']
        first = workspace.import_bank_statement(data)
        reopened = Workspace(directory)
        assert reopened.import_bank_statement(data) == first
        assert len(reopened.list_bank_statements()['statements']) == 1 and len(first['rows']) == 2
        assert reopened.state()['trial_balance'] == before
        assert reopened.state()['journal_count'] == 0
        print('Fictional bank import: opening 1000.00 + 200.00 - 150.00 = closing 1050.00 USD.')
        print('Reopen/retry: two transactions, one statement and identical audit receipt.')
        print('Ledger snapshot unchanged; zero journals, evidence enrollments or provider calls.')
