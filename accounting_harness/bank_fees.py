"""Whole imported negative bank rows, explicitly classified and human reviewed."""
import json

from accounting_harness.approval import ReviewApplication
from accounting_harness.bank import BankStatementService, identifier
from accounting_harness.domain.accounts import _validate_text
from accounting_harness.domain.journal import Finding
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS
from accounting_harness.review import SQLiteReviewStore, digest, protect_table


def bank_evidence(ledger, bank_account_id, transaction_id):
    identifier(bank_account_id, 'bank_account_id')
    identifier(transaction_id, 'transaction_id')
    db = ledger._connection
    entity = ledger._empty.catalog.entity_id
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_transactions'").fetchone():
        raise ValueError('fee requires an imported bank transaction')
    stored = db.execute('''SELECT t.row_json,t.amount_cents FROM bank_transactions t JOIN bank_accounts a
        USING(entity_id,bank_account_id) WHERE t.entity_id=? AND t.bank_account_id=? AND t.transaction_id=?
        AND a.ledger_account='1000' AND a.currency='USD' ''', (entity,bank_account_id,transaction_id)).fetchone()
    if stored is None:
        raise ValueError('fee requires an imported transaction on the mapped Cash bank account')
    row = json.loads(stored[0])
    cents = -stored[1]
    if not 1 <= cents <= MAX_CENTS or row['currency'] != 'USD' or row['amount_cents'] != -cents:
        raise ValueError('fee requires the whole negative USD bank transaction')
    identity = digest([entity, bank_account_id, transaction_id])
    return dict(schema_version=2, synthetic=True, entity_id=entity, document_id='bank-fee-source:' + identity,
        kind='bank_fee', document_date=row['booking_date'], currency='USD', amount=str(Money(cents)),
        counterparty='Imported bank account ' + bank_account_id, description='Immutable imported bank transaction',
        event_id='bank-cash:' + identity, bank_account_id=bank_account_id, transaction_id=transaction_id,
        bank_content_digest=digest(row), bank_reference=row['reference'], bank_description=row['description'],
        signed_amount=row['amount'])


def fee_operation(document, classification, reason):
    if classification != 'bank_fee':
        raise ValueError('operator must explicitly classify this transaction as bank_fee')
    _validate_text(reason, 'operator fee reason')
    if len(reason) > 1000:
        raise ValueError('operator fee reason must be at most 1000 characters')
    draft_id = 'draft:' + document['document_id']
    intent = dict(schema_version=1, kind='bank_fee', classification=classification, operator_reason=reason,
        bank_account_id=document['bank_account_id'], transaction_id=document['transaction_id'],
        bank_content_digest=document['bank_content_digest'], cash_event_id=document['event_id'],
        fee_cents=Money.parse(document['amount']).cents, currency='USD', effective_date=document['document_date'],
        evidence_roles=dict(bank_transaction=document['document_id']))
    proposal = dict(id='journal:' + digest([document['entity_id'], draft_id]), entity_id=document['entity_id'],
        currency='USD', effective_date=document['document_date'], description='Reviewed bank fee: ' + reason,
        source_ids=[document['document_id']], lines=[dict(account='5300',side='debit',amount=document['amount']),
            dict(account='1000',side='credit',amount=document['amount'])])
    return draft_id, intent, proposal


def available_sql(effect):
    # All eligible amount/date Cash candidates block a new fee, including reference ambiguity.
    return f'''NOT EXISTS (SELECT 1 FROM bank_match_events m WHERE m.entity_id={effect}.entity_id
        AND m.bank_account_id={effect}.bank_account_id AND m.transaction_id={effect}.transaction_id
        AND m.operation='match' AND NOT EXISTS (SELECT 1 FROM bank_match_events u WHERE u.target_match=m.event_id))
        AND NOT EXISTS (SELECT 1 FROM journals j JOIN posting_events p ON p.journal_id=j.id
            JOIN lines l ON l.journal_id=j.id AND l.account='1000'
            WHERE j.entity_id={effect}.entity_id AND j.currency='USD' AND l.side='credit'
              AND l.cents={effect}.fee_cents AND abs(julianday(j.effective_date)-julianday({effect}.effective_date))<=3
              AND (SELECT count(*) FROM lines x WHERE x.journal_id=j.id AND x.account='1000')=1
              AND NOT EXISTS (SELECT 1 FROM bank_match_events m WHERE m.journal_id=j.id AND m.operation='match'
                  AND NOT EXISTS (SELECT 1 FROM bank_match_events u WHERE u.target_match=m.event_id)))'''


def require_available(ledger, document):
    db = ledger._connection
    query = '''SELECT 1 FROM (SELECT ? AS entity_id, ? AS bank_account_id, ? AS transaction_id,
        ? AS fee_cents, ? AS effective_date) b WHERE ''' + available_sql('b')
    if not db.execute(query, (document['entity_id'],document['bank_account_id'],document['transaction_id'],
                            Money.parse(document['amount']).cents,document['document_date'])).fetchone():
        raise ValueError('bank row is matched or has an existing Cash candidate; resolve the exception explicitly')


def validate_fee(store, proposal, records, intent, draft_id):
    try:
        if (type(intent) is not dict or type(intent.get('schema_version')) is not int
                or type(intent.get('fee_cents')) is not int):
            raise ValueError('bank fee requires a strict integer-cent intent')
        document = bank_evidence(store.ledger, intent.get('bank_account_id'), intent.get('transaction_id'))
        expected_id, expected_intent, expected_proposal = fee_operation(document, intent.get('classification'), intent.get('operator_reason'))
        if intent != expected_intent or draft_id != expected_id or proposal != expected_proposal:
            raise ValueError('fee intent, identity or journal differs from imported bank evidence and classification')
        if len(records) != 1 or dict(json.loads(records[0].canonical_content),
                entity_id=records[0].entity_id, document_id=records[0].document_id) != document:
            raise ValueError('fee evidence must be reconstructed exactly from the imported bank row')
        if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_fee_effects'").fetchone():
            raise ValueError('bank fee service must be enabled')
        if not store.db.execute("SELECT 1 FROM account_extensions WHERE account_code='5300'").fetchone():
            raise ValueError('activate the audited Bank Fees Expense account first')
        claim = store.db.execute("SELECT draft_id FROM operation_claims WHERE entity_id=? AND event_id=? AND role='cash_movement'",
            (document['entity_id'], document['event_id'])).fetchone()
        if claim and claim != (draft_id,):
            raise ValueError('duplicate economic cash event')
        prior = store.db.execute('SELECT journal_id FROM bank_fee_effects WHERE entity_id=? AND bank_account_id=? AND transaction_id=?',
            (document['entity_id'], document['bank_account_id'], document['transaction_id'])).fetchone()
        if prior:
            own = store.db.execute('SELECT journal_id FROM review_postings WHERE draft_id=?', (draft_id,)).fetchone()
            if prior != (proposal['id'],) or own != prior:
                raise ValueError('bank transaction already consumed')
        else:
            require_available(store.ledger, document)
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_bank_fee', 'operation_intent', str(error)),)
    return ()


class BankFeeService:
    def __init__(self, ledger, registry):
        self.ledger, self.registry, self.db = ledger, registry, ledger._connection
        BankStatementService(ledger)
        with ledger._transaction(write=True):
            self.store = SQLiteReviewStore(ledger, registry, policy_version='bank-fee-v1')
            self.app = ReviewApplication(self.store)
            self._initialize()

    @staticmethod
    def approval_match(effect):
        fields = ('bank_account_id','transaction_id','bank_content_digest','cash_event_id','fee_cents','effective_date')
        equalities = ' AND '.join(f"json_extract(i.intent_json,'$.{field}')={effect}.{field}" for field in fields)
        return f'''EXISTS (SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
            JOIN draft_operation_intents i USING(draft_id,revision)
            JOIN bank_transactions t ON t.entity_id={effect}.entity_id AND t.bank_account_id={effect}.bank_account_id
                AND t.transaction_id={effect}.transaction_id
            JOIN source_enrollments s ON s.source_id={effect}.source_id
            JOIN operation_claims c ON c.entity_id={effect}.entity_id AND c.event_id={effect}.cash_event_id
                AND c.role='cash_movement' AND c.draft_id=r.draft_id
            WHERE a.approval_id={effect}.approval_id AND r.policy_version='bank-fee-v1' AND r.state='pending'
              AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
              AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
              AND json_extract(a.binding_json,'$.policy_version')='bank-fee-v1'
              AND json_extract(a.binding_json,'$.entity_id')={effect}.entity_id
              AND json_extract(a.binding_json,'$.action')='post'
              AND json_extract(r.proposal_json,'$.id')={effect}.journal_id
              AND (SELECT count(*) FROM json_each(i.intent_json))=12
              AND (SELECT count(*) FROM json_each(i.intent_json,'$.evidence_roles'))=1
              AND (SELECT count(*) FROM json_each(a.binding_json,'$.evidence'))=1
              AND json_type(i.intent_json,'$.schema_version')='integer'
              AND json_type(i.intent_json,'$.fee_cents')='integer'
              AND json_extract(i.intent_json,'$.schema_version')=1
              AND json_extract(i.intent_json,'$.kind')='bank_fee'
              AND json_extract(i.intent_json,'$.classification')='bank_fee'
              AND length(trim(json_extract(i.intent_json,'$.operator_reason')))>0
              AND json_extract(i.intent_json,'$.currency')='USD' AND {equalities}
              AND json_extract(i.intent_json,'$.evidence_roles.bank_transaction')={effect}.source_id
              AND t.amount_cents=-{effect}.fee_cents
              AND json_extract(t.row_json,'$.booking_date')={effect}.effective_date
              AND json_extract(s.canonical_content,'$.kind')='bank_fee'
              AND json_extract(s.canonical_content,'$.bank_content_digest')={effect}.bank_content_digest
              AND EXISTS (SELECT 1 FROM json_each(a.binding_json,'$.evidence') e
                  WHERE e.key=s.source_id AND e.value=s.content_digest))'''

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_fee_schema'").fetchone():
            if self.db.execute('SELECT version FROM bank_fee_schema').fetchall() != [(1,)]:
                raise ValueError('unsupported bank fee schema')
            return
        self.db.execute('CREATE TABLE bank_fee_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
        self.db.execute('INSERT INTO bank_fee_schema VALUES(1)')
        self.db.execute('''CREATE TABLE bank_fee_effects (
            entity_id TEXT NOT NULL, bank_account_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
            source_id TEXT NOT NULL UNIQUE REFERENCES sources(id), bank_content_digest TEXT NOT NULL,
            cash_event_id TEXT NOT NULL UNIQUE, fee_cents INTEGER NOT NULL CHECK(fee_cents>0),
            effective_date TEXT NOT NULL, approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
            PRIMARY KEY(entity_id,bank_account_id,transaction_id),
            FOREIGN KEY(entity_id,bank_account_id,transaction_id) REFERENCES bank_transactions(entity_id,bank_account_id,transaction_id)
        ) STRICT, WITHOUT ROWID''')
        protect_table(self.db, 'bank_fee_schema', '1')
        protect_table(self.db, 'bank_fee_effects', 'journal_id=NEW.journal_id OR source_id=NEW.source_id OR approval_id=NEW.approval_id OR (entity_id=NEW.entity_id AND bank_account_id=NEW.bank_account_id AND transaction_id=NEW.transaction_id)')
        self.db.execute(f'''CREATE TRIGGER bank_fee_approved_effect BEFORE INSERT ON bank_fee_effects
            WHEN NOT {self.approval_match('NEW')} OR NOT ({available_sql('NEW')})
              OR EXISTS (SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
            BEGIN SELECT RAISE(ABORT,'bank fee requires current approved operation and unused bank row'); END''')
        self.db.execute(f'''CREATE TRIGGER bank_fee_post_guard BEFORE INSERT ON posting_events
            WHEN EXISTS (SELECT 1 FROM bank_fee_effects WHERE journal_id=NEW.journal_id)
              OR EXISTS (SELECT 1 FROM journal_sources js JOIN source_enrollments s ON js.source_id=s.source_id
                WHERE js.journal_id=NEW.journal_id AND json_extract(s.canonical_content,'$.kind')='bank_fee')
            BEGIN SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM bank_fee_effects f JOIN journals j ON j.id=f.journal_id
                WHERE f.journal_id=NEW.journal_id AND j.entity_id=f.entity_id AND j.currency='USD'
                  AND j.effective_date=f.effective_date AND {self.approval_match('f')} AND ({available_sql('f')})
                  AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='5300' AND side='debit' AND cents=f.fee_cents)
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='1000' AND side='credit' AND cents=f.fee_cents)
                  AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=1
                  AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=f.source_id)
            ) THEN RAISE(ABORT,'bank fee posting requires an exact current approved fee effect') END; END''')

    def propose(self, document, *, classification, reason, expected_revision, actor_id, idempotency_key):
        draft_id, intent, proposal = fee_operation(document, classification, reason)
        record = self.registry.get(document['document_id'])
        return self.store.save(draft_id, proposal, evidence={record.document_id:record.content_digest},
            operation_intent=intent, expected_revision=expected_revision, actor_id=actor_id,
            idempotency_key=idempotency_key, reason='Operator fee classification: ' + reason)


def prepare_fee_post(store, approval, revision, entry):
    intent = json.loads(revision.operation_intent_json)
    findings = store.validate(json.loads(revision.proposal_json), json.loads(revision.evidence_json),
                              operation_intent=intent, draft_id=revision.draft_id)
    if findings:
        raise ValueError('fee operation no longer valid: ' + findings[0].message)
    store.db.execute('INSERT INTO bank_fee_effects VALUES(?,?,?,?,?,?,?,?,?,?)',
        (entry.entity_id,intent['bank_account_id'],intent['transaction_id'],intent['evidence_roles']['bank_transaction'],
         intent['bank_content_digest'],intent['cash_event_id'],intent['fee_cents'],intent['effective_date'],approval.approval_id,entry.id))


def demo_bank_fee():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='accounting-bank-fee-') as directory:
        workspace = Workspace(directory)
        workspace.action('bank-fee-account', {})
        workspace.import_bank_statement(dict(statement_id='fee-demo',bank_account_id='fictional-bank',
            period_start='2026-01-01',period_end='2026-01-31',opening_balance='1000.00',closing_balance='990.00',currency='USD',
            csv_content='bank_account_id,transaction_id,booking_date,amount,currency,reference,description\nfictional-bank,monthly-fee,2026-01-05,-10.00,USD,,Synthetic monthly account fee\n'))
        with workspace.storage() as (_,ledger,_,_,_):
            ledger.admit(dict(id='fixture-capital',entity_id=workspace.catalog.entity_id,currency='USD',
                effective_date='2026-01-01',description='Fictional starting capital',source_ids=['synthetic-receipt-002'],
                lines=[dict(account='1000',side='debit',amount='1000.00'),dict(account='3000',side='credit',amount='1000.00')]),
                actor_id='fixture-operator',idempotency_key='capital')
        request = dict(bank_account_id='fictional-bank',transaction_id='monthly-fee',classification='bank_fee',
                       reason='Monthly account maintenance fee',expected_revision=0)
        draft = workspace.action('bank-fee-proposals',request)
        assert workspace.state()['journal_count'] == 1
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        receipt=workspace.action('approve-post',confirmation)
        state=workspace.state()
        balances={r['account']:r['debit'] for r in state['trial_balance']['rows']}
        assert balances['1000']=='990.00' and balances['5300']=='10.00' and state['journal_count']==2
        row=workspace.bank_matches('fictional-bank')['rows'][0]
        assert row['status']=='unmatched' and row['confirmable']
        workspace.action('bank-match',dict(bank_account_id='fictional-bank',transaction_id='monthly-fee',
            journal_id=receipt['journal_id'],binding=row['binding'],idempotency_key='explicit-match'))
        workspace=Workspace(directory)
        assert workspace.action('bank-fee-proposals',request)==draft
        assert workspace.action('approve-post',confirmation)==receipt
        assert workspace.state()['journal_count']==2
        print('Cash 1000.00 -> 990.00 USD; debit 5300 Bank Fees Expense 10.00 / credit 1000 Cash 10.00.')
        print('Before human confirmation: one fixture journal. After: exactly one additional bank-fee journal.')
        print('Imported bank evidence and operator reason retained; bank-fee-v1 exact approval recorded.')
        print('Posting and explicit matching are separate; restart and retries retain one fee.')
        print('No timing-difference entries or reconciliation completion; zero model calls.')
