"""Pure captured bank-to-book reports and immutable local human confirmations."""
import json
from dataclasses import asdict
from datetime import datetime, timezone

from accounting_harness.bank import BankStatementService, identifier, signed_amount, signed_cents
from accounting_harness.persistence import _canonical as canonical
from accounting_harness.review import digest, protect_table

POLICY = 'bank-reconciliation-zero-opening-v1'


def reconciliation_report(capture_json):
    """No reads: all labels, money, evidence and history come from the capture."""
    capture = json.loads(capture_json)
    if capture['policy'] != POLICY:
        raise ValueError('unsupported captured reconciliation policy')
    statement = capture['statement']['statement']
    cutoff = statement['period_end']
    account = statement['ledger_account']
    members = {row['transaction_id'] for row in capture['statement']['rows']}
    cash, unsupported = {}, []
    for entry in capture['ledger']['entries']:
        if entry['effective_date'] > cutoff:
            continue
        lines = [line for line in entry['lines'] if line['account'] == account]
        if not lines:
            continue
        cents = sum(int(line['cents']) * (1 if line['side'] == 'debit' else -1) for line in lines)
        item = dict(journal_id=entry['id'], effective_date=entry['effective_date'], source_ids=entry['source_ids'],
                    journal_digest=digest(entry), amount=signed_amount(cents), amount_cents=str(cents))
        cash[entry['id']] = item
        if len(lines) != 1:
            unsupported.append(dict(item, reason='multiple Cash lines require separate resolution'))
    bank_exceptions, matches, cleared = [], [], set()
    for row in capture['matching']['rows']:
        if row['booking_date'] > cutoff:
            continue
        event = row['active_match']
        book = cash.get(event['journal_id']) if event else None
        reason = None
        if statement['period_start'] <= row['booking_date'] and row['transaction_id'] not in members:
            reason = 'imported bank row is absent from the selected statement'
        elif not event:
            reason = row['status'] + ' bank row'
        elif not book or book['amount_cents'] != row['amount_cents'] or book['journal_id'] in cleared:
            reason = 'match is not one-to-one with an eligible book movement at cutoff'
        if reason:
            bank_exceptions.append(dict(transaction_id=row['transaction_id'], amount=row['amount'], reason=reason,
                                        bank_digest=row['bank_digest'], active_match=event))
        else:
            cleared.add(book['journal_id'])
            matches.append(dict(transaction_id=row['transaction_id'], booking_date=row['booking_date'],
                                bank_digest=row['bank_digest'], match=event, book=book))
    active_timing = {}
    for event in capture['timing_history']:
        if event['role'] == 'withdraw':
            active_timing.pop(event['journal_id'], None)
        else:
            active_timing[event['journal_id']] = event
    timing, timing_exceptions = [], []
    unsupported_ids = {item['journal_id'] for item in unsupported}
    for journal_id, event in active_timing.items():
        book = cash.get(journal_id)
        expected = ('deposit_in_transit' if int(book['amount_cents']) > 0 else 'outstanding_payment') if book else None
        if not book or journal_id in cleared or journal_id in unsupported_ids or event['role'] != expected:
            timing_exceptions.append(dict(event=event, reason='reviewed timing is no longer eligible at cutoff'))
        else:
            timing.append(dict(book, role=event['role'], review=event))
    classified = {item['journal_id'] for item in timing}
    unclassified = [item for key, item in cash.items() if key not in cleared | classified | unsupported_ids]
    eligible = [dict(item, role='deposit_in_transit' if int(item['amount_cents']) > 0 else 'outstanding_payment')
                for item in unclassified]
    effects = [effect for effect in capture['fee_effects'] if effect['journal_id'] in cash]
    adjustments = [dict(effect, amount=signed_amount(-int(effect['fee_cents'])),
                        book=cash[effect['journal_id']]) for effect in effects]
    book_balance = sum(int(item['amount_cents']) for item in cash.values())
    adjustment_total = -sum(int(effect['fee_cents']) for effect in effects)
    deposits = sum(int(item['amount_cents']) for item in timing if item['role'] == 'deposit_in_transit')
    payments = -sum(int(item['amount_cents']) for item in timing if item['role'] == 'outstanding_payment')
    closing = signed_cents(statement['closing_balance'])
    adjusted = closing + deposits - payments
    residual = book_balance - adjusted
    report = dict(policy=POLICY, entity_id=statement['entity_id'], currency=statement['currency'],
        bank_account_id=statement['bank_account_id'], statement_id=statement['statement_id'],
        period_start=statement['period_start'], cutoff=cutoff, ledger_account=account,
        ledger_account_name=next(a['name'] for a in capture['ledger']['catalog'] if a['code']==account),
        ledger_snapshot_digest=digest(capture['ledger']), capture_digest=digest(capture),
        original_book_balance=signed_amount(book_balance-adjustment_total),
        original_book_label='Captured book balance before linked reviewed fee adjustments (derived bridge)',
        book_adjustments_total=signed_amount(adjustment_total), book_adjustments=adjustments,
        book_balance=signed_amount(book_balance), bank_closing=signed_amount(closing),
        deposits_in_transit=signed_amount(deposits), outstanding_payments=signed_amount(payments),
        adjusted_bank_balance=signed_amount(adjusted), unexplained_difference=signed_amount(residual),
        difference_sign='book minus adjusted bank', matches=matches, timing_items=timing,
        eligible_timing=eligible, bank_exceptions=bank_exceptions, book_exceptions=unclassified+unsupported,
        timing_exceptions=timing_exceptions,
        can_complete=not (residual or bank_exceptions or unclassified or unsupported or timing_exceptions))
    report['digest'] = digest(report)
    return report


class ReconciliationService:
    def __init__(self, ledger):
        self.ledger, self.db = ledger, ledger._connection
        self.bank = BankStatementService(ledger)
        self.entity_id = self.bank.entity_id
        with ledger._transaction(write=True):
            exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='reconciliation_schema'").fetchone()
            if exists:
                if self.db.execute('SELECT version FROM reconciliation_schema').fetchall() != [(1,)]:
                    raise ValueError('unsupported reconciliation schema')
                return
            self.db.execute('CREATE TABLE reconciliation_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
            self.db.execute('INSERT INTO reconciliation_schema VALUES(1)')
            self.db.execute('''CREATE TABLE reconciliation_timing(
                sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, statement_id TEXT NOT NULL,
                journal_id TEXT NOT NULL REFERENCES journals(id), role TEXT NOT NULL
                    CHECK(role IN ('deposit_in_transit','outstanding_payment','withdraw')),
                key TEXT NOT NULL, event_json TEXT NOT NULL,
                FOREIGN KEY(entity_id,bank_account_id,statement_id) REFERENCES bank_statements(entity_id,bank_account_id,statement_id),
                FOREIGN KEY(entity_id,bank_account_id,statement_id,key) REFERENCES reconciliation_receipts(entity_id,bank_account_id,statement_id,key)
                    DEFERRABLE INITIALLY DEFERRED) STRICT''')
            self.db.execute('''CREATE TABLE reconciliation_completions(
                completion_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL,
                statement_id TEXT NOT NULL, key TEXT NOT NULL, completion_json TEXT NOT NULL,
                FOREIGN KEY(entity_id,bank_account_id,statement_id) REFERENCES bank_statements(entity_id,bank_account_id,statement_id),
                FOREIGN KEY(entity_id,bank_account_id,statement_id,key) REFERENCES reconciliation_receipts(entity_id,bank_account_id,statement_id,key)
                    DEFERRABLE INITIALLY DEFERRED) STRICT, WITHOUT ROWID''')
            self.db.execute('''CREATE TABLE reconciliation_receipts(
                entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, statement_id TEXT NOT NULL,
                key TEXT NOT NULL, payload_digest TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(entity_id,bank_account_id,statement_id,key)) STRICT, WITHOUT ROWID''')
            for table, conflict in [('reconciliation_schema','1'),
                ('reconciliation_timing','sequence=NEW.sequence OR event_id=NEW.event_id'),
                ('reconciliation_completions','completion_id=NEW.completion_id'),
                ('reconciliation_receipts','entity_id=NEW.entity_id AND bank_account_id=NEW.bank_account_id AND statement_id=NEW.statement_id AND key=NEW.key')]:
                protect_table(self.db,table,conflict)

    def _capture(self, bank_account_id, statement_id):
        identity = self.entity_id, bank_account_id, statement_id
        statement = self.bank._detail(identity)
        snapshot = self.ledger._snapshot()
        entries = [self.ledger._entry_payload(entry) for entry in snapshot.entries]
        for entry in entries:
            for line in entry['lines']:
                line['cents'] = str(line['cents'])
        fees = []
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_fee_effects'").fetchone():
            cursor = self.db.execute('SELECT * FROM bank_fee_effects WHERE entity_id=? AND bank_account_id=? ORDER BY transaction_id', identity[:2])
            names = [col[0] for col in cursor.description]
            for values in cursor:
                item = dict(zip(names,values)); item['fee_cents'] = str(item['fee_cents']); fees.append(item)
        history = [json.loads(row[0]) for row in self.db.execute('''SELECT event_json FROM reconciliation_timing
            WHERE entity_id=? AND bank_account_id=? AND statement_id=? ORDER BY sequence''',identity)]
        return canonical(dict(policy=POLICY, statement=statement,
            ledger=dict(period_start=snapshot.period_start.isoformat(),period_end=snapshot.period_end.isoformat(),
                        catalog=[asdict(account) for account in snapshot.catalog.list_accounts()],entries=entries),
            matching=self.bank._matching(bank_account_id),fee_effects=fees,timing_history=history))

    def capture(self, bank_account_id, statement_id):
        identifier(bank_account_id,'bank_account_id'); identifier(statement_id,'statement_id')
        with self.ledger._transaction():
            return self._capture(bank_account_id, statement_id)

    def view(self, bank_account_id, statement_id):
        identifier(bank_account_id,'bank_account_id'); identifier(statement_id,'statement_id')
        with self.ledger._transaction():
            capture = self._capture(bank_account_id,statement_id)
            report = reconciliation_report(capture)
            completions = [json.loads(row[0]) for row in self.db.execute('''SELECT completion_json FROM reconciliation_completions
                WHERE entity_id=? AND bank_account_id=? AND statement_id=? ORDER BY completion_id''',
                (self.entity_id,bank_account_id,statement_id))]
        return dict(report=report,capture_json=capture,completions=[dict(completion=item,
            current_state_drift=item['report']['digest'] != report['digest']) for item in completions])

    def action(self, operation, data, *, actor_id):
        expected = {'bank_account_id','statement_id','binding','idempotency_key'}
        if operation == 'timing':
            expected |= {'journal_id','role','reason'}
        if operation not in ('timing','reconcile') or type(data) is not dict or set(data) != expected:
            raise ValueError('reconciliation request requires exactly: '+', '.join(sorted(expected)))
        for key,value in data.items():
            if key == 'reason':
                if type(value) is not str or not value.strip() or len(value)>1000 or '\x00' in value:
                    raise ValueError('timing review requires a nonempty reason of at most 1000 characters')
            else:
                identifier(value,key)
        identifier(actor_id,'actor_id')
        scope = self.entity_id,data['bank_account_id'],data['statement_id'],data['idempotency_key']
        payload_digest = digest(dict(operation=operation,data=data,actor_id=actor_id,entity_id=self.entity_id))
        with self.ledger._transaction(write=True):
            prior = self.db.execute('''SELECT payload_digest,result_json FROM reconciliation_receipts
                WHERE entity_id=? AND bank_account_id=? AND statement_id=? AND key=?''',scope).fetchone()
            if prior:
                if prior[0] != payload_digest:
                    raise ValueError('idempotency key conflicts with original payload or actor')
                return json.loads(prior[1])
            capture = self._capture(*scope[1:3])
            report = reconciliation_report(capture)
            if data['binding'] != report['digest']:
                raise ValueError('reconciliation state is stale; refresh and review again')
            result = dict(entity_id=self.entity_id,bank_account_id=scope[1],statement_id=scope[2],
                policy=POLICY,actor_id=actor_id,recorded_at=datetime.now(timezone.utc).isoformat(),binding=data['binding'])
            identity = digest([scope,payload_digest])
            if operation == 'timing':
                role, journal = data['role'],data['journal_id']
                if role == 'withdraw':
                    active = {item['journal_id'] for item in report['timing_items']} | {
                        item['event']['journal_id'] for item in report['timing_exceptions']}
                    if journal not in active:
                        raise ValueError('no active timing review to withdraw')
                elif not any(item['journal_id']==journal and item['role']==role for item in report['eligible_timing']):
                    raise ValueError('timing journal is duplicate, cleared, future, unsupported or has wrong sign/account')
                result.update(event_id='rt-'+identity,journal_id=journal,role=role,reason=data['reason'])
                self.db.execute('''INSERT INTO reconciliation_timing(event_id,entity_id,bank_account_id,statement_id,
                    journal_id,role,key,event_json) VALUES(?,?,?,?,?,?,?,?)''',
                    (result['event_id'],*scope[:3],journal,role,scope[3],canonical(result)))
            else:
                if not report['can_complete']:
                    raise ValueError('unexplained difference or unresolved bank/book/timing exceptions block completion')
                result.update(completion_id='rc-'+identity,report=report,capture_json=capture)
                self.db.execute('INSERT INTO reconciliation_completions VALUES(?,?,?,?,?,?)',
                    (result['completion_id'],*scope,canonical(result)))
            self.db.execute('INSERT INTO reconciliation_receipts VALUES(?,?,?,?,?,?)',(*scope,payload_digest,canonical(result)))
            return result


def demo_reconciliation():
    """Full January synthetic funding, owner movements and reviewed bank fee."""
    import tempfile
    from accounting_harness.workspace import Workspace
    from accounting_harness.bank import CSV_HEADERS
    with tempfile.TemporaryDirectory() as directory:
        workspace = Workspace(directory)
        for journal, amount, side, day in [('funding','950.00','debit','01'),
                ('deposit','200.00','debit','20'),('payment','150.00','credit','21')]:
            source = dict(schema_version=2,synthetic=True,entity_id=workspace.catalog.entity_id,
                document_id='evidence-'+journal,kind='cash_movement',currency='USD',amount=amount,
                document_date='2026-01-'+day,counterparty='Fictional owner',counterparty_id='owner',
                description='Synthetic owner funding' if side=='debit' else 'Synthetic owner drawing',
                event_id='event-'+journal,direction='in' if side=='debit' else 'out',
                purpose='owner_contribution' if side=='debit' else 'owner_draw')
            with workspace.storage() as (registry,ledger,_,_,_):
                registry.register(source,actor_id='fixture-human')
                ledger.enroll_source(registry,source['document_id'],actor_id='fixture-human')
                ledger.admit(dict(id=journal,entity_id=workspace.catalog.entity_id,currency='USD',
                    effective_date=source['document_date'],description=source['description'],source_ids=[source['document_id']],
                    lines=[dict(account='1000',side=side,amount=amount),dict(account='3000' if side=='debit' else '3100',
                        side='credit' if side=='debit' else 'debit',amount=amount)]),actor_id='fixture-human',idempotency_key=journal)
        workspace.import_bank_statement(dict(bank_account_id='fictional-bank',statement_id='january',
            period_start='2026-01-01',period_end='2026-01-31',currency='USD',opening_balance='0.00',closing_balance='940.00',
            csv_content=','.join(CSV_HEADERS)+'\nfictional-bank,funding,2026-01-01,950.00,USD,funding,Fictional funding\n'
                'fictional-bank,fee,2026-01-05,-10.00,USD,,Fictional maintenance fee\n'))
        original_count = workspace.state()['journal_count']
        workspace.action('bank-fee-account',{})
        draft = workspace.action('bank-fee-proposals',dict(bank_account_id='fictional-bank',transaction_id='fee',
            classification='bank_fee',reason='Human reviewed monthly fee',expected_revision=0))
        workspace.action('approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        for transaction in ['funding','fee']:
            row = next(row for row in workspace.bank_matches('fictional-bank')['rows'] if row['transaction_id']==transaction)
            workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id=transaction,
                journal_id=row['candidates'][0]['journal_id'],binding=row['binding'],idempotency_key=transaction))
        for journal, role in [('deposit','deposit_in_transit'),('payment','outstanding_payment')]:
            report = workspace.bank_reconciliation('fictional-bank','january')['report']
            workspace.action('bank-timing',dict(bank_account_id='fictional-bank',statement_id='january',journal_id=journal,
                role=role,reason='Reviewed existing owner cash movement outstanding at cutoff',binding=report['digest'],idempotency_key=journal))
        report = workspace.bank_reconciliation('fictional-bank','january')['report']
        receipt = workspace.action('bank-reconcile',dict(bank_account_id='fictional-bank',statement_id='january',
            binding=report['digest'],idempotency_key='complete'))
        assert report['book_balance'] == report['adjusted_bank_balance'] == '990.00'
        assert workspace.state()['journal_count'] == original_count + 1
        assert report['unexplained_difference'] == '0.00'
        print('Full January statement: opening 0.00 + funding 950.00 - fee 10.00 = bank 940.00.')
        print('Book 1000.00 - reviewed fee 10.00 = 990.00; bank 940.00 + deposit 200.00 - outstanding 150.00 = 990.00.')
        print('Only the 10.00 fee added a journal; timing review and explicit completion posted nothing; zero model calls.')
        print('Report digest:',report['digest'])
        print('Immutable human completion:',receipt['completion_id'])
