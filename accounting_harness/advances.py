"""Reviewed customer prepayments and immutable unearned-revenue control detail."""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from accounting_harness.approval import ReviewApplication, approved_source_content
from accounting_harness.domain.accounts import _validate_text
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import Finding
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS, SQLiteLedger, _canonical
from accounting_harness.review import SQLiteReviewStore, digest, protect_table
from accounting_harness.sources import _content

REPORT_POLICY = 'advances-zero-opening-v1'


def advance_operation(records):
    if len(records) != 2 or len({r.document_id for r in records}) != 2:
        raise ValueError('advance requires distinct prepayment and cash evidence')
    documents = []
    for record in records:
        document = dict(json.loads(record.canonical_content), entity_id=record.entity_id,
                        document_id=record.document_id)
        _content(document, record.entity_id)
        documents.append(document)
    prepayment = next((d for d in documents if d['kind'] == 'customer_prepayment'), None)
    cash = next((d for d in documents if d['kind'] == 'cash_movement'), None)
    if prepayment is None or cash is None:
        raise ValueError('advance requires paired prepayment and cash evidence')
    if (cash['direction'], cash['purpose']) != ('in', 'customer_advance'):
        raise ValueError('advance requires incoming customer_advance cash')
    for field in ('entity_id', 'event_id', 'counterparty_id', 'currency', 'amount', 'document_date'):
        if prepayment[field] != cash[field]:
            raise ValueError('prepayment and cash evidence differ in ' + field)
    cents = Money.parse(prepayment['amount']).cents
    if not 1 <= cents <= MAX_CENTS:
        raise ValueError('advance principal exceeds storage bounds')
    advance_id = 'advance:' + digest([prepayment['entity_id'], prepayment['counterparty_id'], prepayment['contract_id']])
    draft_id = 'draft:' + advance_id
    intent = dict(schema_version=1, kind='customer_advance', advance_id=advance_id,
        customer_id=prepayment['counterparty_id'], contract_id=prepayment['contract_id'],
        cash_event_id=cash['event_id'], currency='USD', principal_cents=cents,
        effective_date=prepayment['document_date'],
        evidence_roles=dict(prepayment=prepayment['document_id'], cash=cash['document_id']))
    proposal = dict(id='journal:' + digest([prepayment['entity_id'], draft_id]), entity_id=prepayment['entity_id'],
        currency='USD', effective_date=prepayment['document_date'],
        description='Synthetic customer advance: ' + prepayment['contract_id'],
        source_ids=[prepayment['document_id'], cash['document_id']],
        lines=[dict(account='1000', side='debit', amount=prepayment['amount']),
               dict(account='2100', side='credit', amount=prepayment['amount'])])
    return draft_id, intent, proposal


def validate_advance(store, proposal, records, intent, draft_id):
    try:
        expected_id, expected_intent, expected_proposal = advance_operation(records)
        if (not isinstance(intent, dict) or type(intent.get('schema_version')) is not int
                or type(intent.get('principal_cents')) is not int):
            raise ValueError('advance requires an exact integer-cent operation intent')
        if intent != expected_intent or draft_id != expected_id or proposal != expected_proposal:
            raise ValueError('advance intent, identity or journal differs from paired evidence')
        claim = store.db.execute("""SELECT draft_id FROM operation_claims
            WHERE entity_id=? AND event_id=? AND role='cash_movement' """,
            (store.registry._entity_id, intent['cash_event_id'])).fetchone()
        if claim and claim != (draft_id,):
            raise ValueError('duplicate economic event and role')
        if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='advances_context'").fetchone():
            raise ValueError('advances must be enabled before review')
        if not store.db.execute('SELECT 1 FROM advances_context').fetchone():
            raise ValueError('advances must be enabled before review')
        prior = store.db.execute('SELECT * FROM customer_advances WHERE advance_id=?', (intent['advance_id'],)).fetchone()
        if prior:
            own = store.db.execute('SELECT journal_id FROM review_postings WHERE draft_id=?', (draft_id,)).fetchone()
            expected = (intent['advance_id'], intent['customer_id'], intent['contract_id'], intent['cash_event_id'],
                        intent['evidence_roles']['prepayment'], intent['evidence_roles']['cash'],
                        intent['principal_cents'], intent['effective_date'])
            if prior[:8] != expected or own != (prior[9],) or prior[9] != proposal['id']:
                raise ValueError('advance contract already posted')
        else:
            _require_reconciled(store.ledger, store.registry)
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_advance', 'operation_intent', str(error)),)
    return ()


@dataclass(frozen=True, slots=True)
class CustomerAdvance:
    advance_id: str
    customer_id: str
    contract_id: str
    cash_event_id: str
    prepayment_source_id: str
    cash_source_id: str
    principal_cents: int
    effective_date: str
    approval_id: str
    journal_id: str
    customer_name: str


@dataclass(frozen=True, slots=True)
class AdvancesSnapshot:
    ledger: object
    advances: tuple[CustomerAdvance, ...]
    activation_json: str | None
    ledger_context: str


def _snapshot(ledger, registry):
    db = ledger._connection
    advances = []
    for row in db.execute('SELECT * FROM customer_advances ORDER BY advance_id'):
        content = approved_source_content(db, registry, row[4], row[8])
        advances.append(CustomerAdvance(*row, json.loads(content)['counterparty']))
    activation = db.execute('SELECT * FROM advances_context').fetchone()
    return AdvancesSnapshot(ledger._snapshot(), tuple(advances), _canonical(activation) if activation else None, ledger._context)


def advances_report(snapshot, *, as_of):
    cutoff = accounting_date(as_of)
    if not snapshot.ledger.period_start <= cutoff <= snapshot.ledger.period_end:
        raise ValueError('report cutoff is outside the ledger period')
    entries = tuple(e for e in snapshot.ledger.entries if e.effective_date <= cutoff)
    ids = tuple(e.id for e in entries)
    advances = [dict(asdict(a), earned_cents=0, remaining_cents=a.principal_cents)
                for a in snapshot.advances if a.journal_id in ids and accounting_date(a.effective_date) <= cutoff]
    control = sum(l.amount.cents if l.side == 'credit' else -l.amount.cents
                  for e in entries for l in e.lines if l.account == '2100')
    principal = sum(a['principal_cents'] for a in advances)
    customers = []
    for customer_id in sorted({a['customer_id'] for a in advances}):
        selected = [a for a in advances if a['customer_id'] == customer_id]
        total = sum(a['principal_cents'] for a in selected)
        customers.append(dict(customer_id=customer_id, names=sorted({a['customer_name'] for a in selected}),
                              principal_cents=total, earned_cents=0, remaining_cents=total))
    snapshot_digest = digest([snapshot.ledger_context,
        [SQLiteLedger._entry_payload(e) for e in snapshot.ledger.entries],
        [asdict(a) for a in snapshot.advances], snapshot.activation_json])
    report = dict(schema_version=1, policy=REPORT_POLICY, as_of=cutoff.isoformat(), snapshot_digest=snapshot_digest,
        included_journal_ids=list(ids), enabled=snapshot.activation_json is not None,
        activation=json.loads(snapshot.activation_json) if snapshot.activation_json else None,
        advances=advances, customers=customers, principal_cents=principal, earned_cents=0,
        remaining_cents=principal, unearned_control_cents=control, subledger_cents=principal,
        unassigned_control_cents=control-principal, reconciled=control == principal)
    return dict(report, report_digest=digest(report))


def _require_reconciled(ledger, registry):
    report = advances_report(_snapshot(ledger, registry), as_of=ledger._empty.period_end)
    if not report['reconciled']:
        raise ValueError(f"unassigned advance residual {report['unassigned_control_cents']} cents; correction workflow required")


class AdvancesService:
    def __init__(self, ledger, registry):
        self.ledger, self.registry, self.db = ledger, registry, ledger._connection
        with ledger._transaction(write=True):
            self.store = SQLiteReviewStore(ledger, registry, policy_version='advance-v1')
            self.app = ReviewApplication(self.store)
            self._initialize()

    @staticmethod
    def _approval_match(effect):
        # Reused at effect insertion AND final journal seal: later revisions revoke authority.
        return f"""EXISTS (
            SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
            JOIN draft_operation_intents i USING(draft_id,revision)
            WHERE a.approval_id={effect}.approval_id AND r.policy_version='advance-v1'
              AND r.state='pending'
              AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
              AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
              AND json_extract(a.binding_json,'$.policy_version')='advance-v1'
              AND json_extract(a.binding_json,'$.action')='post'
              AND json_extract(r.proposal_json,'$.id')={effect}.journal_id
              AND json_extract(i.intent_json,'$.schema_version')=1
              AND json_extract(i.intent_json,'$.currency')='USD'
              AND json_extract(i.intent_json,'$.kind')='customer_advance'
              AND json_extract(i.intent_json,'$.advance_id')={effect}.advance_id
              AND json_extract(i.intent_json,'$.customer_id')={effect}.customer_id
              AND json_extract(i.intent_json,'$.contract_id')={effect}.contract_id
              AND json_extract(i.intent_json,'$.cash_event_id')={effect}.cash_event_id
              AND json_extract(i.intent_json,'$.principal_cents')={effect}.principal_cents
              AND json_extract(i.intent_json,'$.effective_date')={effect}.effective_date
              AND json_extract(i.intent_json,'$.evidence_roles.prepayment')={effect}.prepayment_source_id
              AND json_extract(i.intent_json,'$.evidence_roles.cash')={effect}.cash_source_id)"""

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='advances_schema'").fetchone():
            if self.db.execute('SELECT version FROM advances_schema').fetchall() != [(1,)]:
                raise ValueError('unsupported advances schema version')
            return
        self.db.execute('CREATE TABLE advances_schema (version INTEGER PRIMARY KEY) STRICT')
        self.db.execute('INSERT INTO advances_schema VALUES (1)')
        self.db.execute('''CREATE TABLE advances_context (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), entity_id TEXT NOT NULL,
            actor_id TEXT NOT NULL CHECK(length(trim(actor_id))>0 AND actor_id=trim(actor_id)),
            recorded_at TEXT NOT NULL, snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=64),
            journal_ids_json TEXT NOT NULL, policy TEXT NOT NULL CHECK(policy='advances-zero-opening-v1')
        ) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE customer_advances (
            advance_id TEXT PRIMARY KEY CHECK(length(trim(advance_id))>0 AND advance_id=trim(advance_id)),
            customer_id TEXT NOT NULL CHECK(length(trim(customer_id))>0 AND customer_id=trim(customer_id)),
            contract_id TEXT NOT NULL CHECK(length(trim(contract_id))>0 AND contract_id=trim(contract_id)),
            cash_event_id TEXT NOT NULL UNIQUE CHECK(length(trim(cash_event_id))>0 AND cash_event_id=trim(cash_event_id)),
            prepayment_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            cash_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            principal_cents INTEGER NOT NULL CHECK(principal_cents>0),
            effective_date TEXT NOT NULL CHECK(length(effective_date)=10 AND date(effective_date)=effective_date
                AND effective_date BETWEEN '2026-01-01' AND '2026-01-31'),
            approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
            UNIQUE(customer_id,contract_id), CHECK(prepayment_source_id!=cash_source_id)
        ) STRICT, WITHOUT ROWID''')
        for table, conflict in [('advances_schema','1'), ('advances_context','1'),
                ('customer_advances','advance_id=NEW.advance_id OR (customer_id=NEW.customer_id AND contract_id=NEW.contract_id)')]:
            protect_table(self.db, table, conflict)
        self.db.execute('''CREATE TRIGGER advance_before_post BEFORE INSERT ON customer_advances
            WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
                 OR NOT EXISTS (SELECT 1 FROM advances_context)
            BEGIN SELECT RAISE(ABORT,'advance effect requires an enabled, unsealed journal'); END''')
        self.db.execute(f'''CREATE TRIGGER advance_approved_operation BEFORE INSERT ON customer_advances
            WHEN NOT {self._approval_match('NEW')}
            BEGIN SELECT RAISE(ABORT,'advance effect must match approved operation'); END''')
        self.db.execute(f'''CREATE TRIGGER advances_post_guard BEFORE INSERT ON posting_events
            WHEN (EXISTS (SELECT 1 FROM advances_context)
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='2100'))
                 OR EXISTS (SELECT 1 FROM customer_advances WHERE journal_id=NEW.journal_id)
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM customer_advances b JOIN journals j ON j.id=b.journal_id
                    WHERE b.journal_id=NEW.journal_id AND j.effective_date=b.effective_date
                    AND {self._approval_match('b')}
                    AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='1000' AND side='debit' AND cents=b.principal_cents)
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='2100' AND side='credit' AND cents=b.principal_cents)
                    AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.prepayment_source_id)
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.cash_source_id)
                ) THEN RAISE(ABORT,'2100 posting requires matching approved advance effect; correction workflow required') END;
            END''')

    def ensure_enabled(self, *, actor_id):
        _validate_text(actor_id, 'actor ID')
        with self.ledger._transaction(write=True):
            prior = self.db.execute('SELECT * FROM advances_context').fetchone()
            if prior:
                return prior
            _require_reconciled(self.ledger, self.registry)
            snapshot = self.ledger._snapshot()
            self.db.execute('INSERT INTO advances_context VALUES (1,?,?,?,?,?,?)',
                (snapshot.catalog.entity_id, actor_id, datetime.now(timezone.utc).isoformat(),
                 digest([self.ledger._context, [self.ledger._entry_payload(e) for e in snapshot.entries]]),
                 _canonical([e.id for e in snapshot.entries]), REPORT_POLICY))
            return self.db.execute('SELECT * FROM advances_context').fetchone()

    def propose_advance(self, *, prepayment_source_id, cash_source_id, expected_revision, actor_id, idempotency_key):
        records = (self.registry.get(prepayment_source_id), self.registry.get(cash_source_id))
        draft_id, intent, proposal = advance_operation(records)
        if intent['evidence_roles'] != dict(prepayment=prepayment_source_id, cash=cash_source_id):
            raise ValueError('sources must match prepayment and cash roles')
        self.ensure_enabled(actor_id=actor_id)
        return self.store.save(draft_id, proposal, evidence={r.document_id:r.content_digest for r in records},
            operation_intent=intent, expected_revision=expected_revision, actor_id=actor_id,
            idempotency_key=idempotency_key, reason='Synthetic customer advance; separate human review required')

    def snapshot(self):
        with self.ledger._transaction():
            return _snapshot(self.ledger, self.registry)


def prepare_advance_post(store, approval, revision, entry):
    if not store.db.in_transaction:
        raise ValueError('advance posting requires the ledger write transaction')
    intent = json.loads(revision.operation_intent_json)
    if (revision.policy_version, intent['kind']) != ('advance-v1', 'customer_advance'):
        raise ValueError('unsupported advance operation')
    findings = store.validate(json.loads(revision.proposal_json), json.loads(revision.evidence_json),
                              operation_intent=intent, draft_id=revision.draft_id)
    if findings:
        raise ValueError('advance operation is no longer valid: ' + findings[0].message)
    if entry.id != json.loads(revision.proposal_json)['id']:
        raise ValueError('effect journal must match approved operation')
    claim = store.db.execute("""SELECT draft_id FROM operation_claims
        WHERE entity_id=? AND event_id=? AND role='cash_movement' """,
        (entry.entity_id, intent['cash_event_id'])).fetchone()
    if claim != (revision.draft_id,):
        raise ValueError('cash movement claim is not owned by this draft')
    _require_reconciled(store.ledger, store.registry)
    store.db.execute('INSERT INTO customer_advances VALUES (?,?,?,?,?,?,?,?,?,?)',
        (intent['advance_id'],intent['customer_id'],intent['contract_id'],intent['cash_event_id'],
         intent['evidence_roles']['prepayment'],intent['evidence_roles']['cash'],intent['principal_cents'],
         intent['effective_date'],approval.approval_id,entry.id))
