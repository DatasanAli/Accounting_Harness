"""Reviewed customer service revenue recognition and immutable AR control reconciliation."""

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

REPORT_POLICY = 'receivables-zero-opening-v1'


def invoice_operation(records):
    """Derive the only supported intent and journal from two independent facts."""
    if len(records) != 2 or len({r.document_id for r in records}) != 2:
        raise ValueError('invoice recognition requires distinct invoice and service-completion evidence')
    documents = []
    for record in records:
        document = dict(json.loads(record.canonical_content), entity_id=record.entity_id,
                        document_id=record.document_id)
        _content(document, record.entity_id)
        documents.append(document)
    invoice = next((d for d in documents if d['kind'] == 'customer_invoice'), None)
    completion = next((d for d in documents if d['kind'] == 'service_completion'), None)
    if invoice is None or completion is None:
        raise ValueError('a customer invoice alone cannot establish service completion')
    for field in ('entity_id', 'event_id', 'counterparty_id', 'currency', 'amount', 'document_date'):
        if invoice[field] != completion[field]:
            raise ValueError('invoice and completion evidence differ in ' + field)
    if invoice['document_date'] != completion['completion_date']:
        raise ValueError('invoice issue and service completion dates must match')
    cents = Money.parse(invoice['amount']).cents
    if not 1 <= cents <= MAX_CENTS:
        raise ValueError('invoice principal exceeds storage bounds')
    invoice_id = 'invoice:' + digest([invoice['entity_id'], invoice['counterparty_id'], invoice['invoice_number']])
    draft_id = 'draft:' + invoice_id
    intent = dict(schema_version=1, kind='customer_invoice', invoice_id=invoice_id,
        customer_id=invoice['counterparty_id'], invoice_number=invoice['invoice_number'],
        recognition_event_id=invoice['event_id'], currency='USD', principal_cents=cents,
        revenue_account='4000', effective_date=completion['completion_date'],
        due_date=invoice['due_date'], evidence_roles=dict(invoice=invoice['document_id'], completion=completion['document_id']))
    proposal = dict(id='journal:' + digest([invoice['entity_id'], draft_id]), entity_id=invoice['entity_id'],
        currency='USD', effective_date=completion['completion_date'],
        description='Synthetic customer invoice: ' + invoice['invoice_number'],
        source_ids=[invoice['document_id'], completion['document_id']],
        lines=[dict(account='1100', side='debit', amount=invoice['amount']),
               dict(account='4000', side='credit', amount=invoice['amount'])])
    return draft_id, intent, proposal


def validate_invoice(store, proposal, records, intent, draft_id):
    try:
        expected_id, expected_intent, expected_proposal = invoice_operation(records)
        if not isinstance(intent, dict) or type(intent.get('schema_version')) is not int:
            raise ValueError('invoice policy requires an exact operation intent')
        if type(intent.get('principal_cents')) is not int or not 1 <= intent['principal_cents'] <= MAX_CENTS:
            raise ValueError('principal cents must be a positive bounded integer')
        if intent != expected_intent:
            raise ValueError('operation intent differs from evidenced invoice recognition')
        if draft_id != expected_id or proposal != expected_proposal:
            raise ValueError('invoice draft identity or journal differs from evidenced recognition')
        claim = store.db.execute('''SELECT draft_id FROM operation_claims
            WHERE entity_id=? AND event_id=? AND role='service_revenue_recognition' ''',
            (store.registry._entity_id, intent['recognition_event_id'])).fetchone()
        if claim and claim[0] != draft_id:
            raise ValueError('duplicate economic event and role')
        if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='receivables_context'").fetchone():
            raise ValueError('receivables must be enabled before invoice review')
        if not store.db.execute('SELECT 1 FROM receivables_context').fetchone():
            raise ValueError('receivables must be enabled before invoice review')
        prior = store.db.execute('SELECT journal_id FROM customer_invoices WHERE invoice_id=?', (intent['invoice_id'],)).fetchone()
        if prior:
            own = store.db.execute('SELECT journal_id FROM review_postings WHERE draft_id=?', (draft_id,)).fetchone()
            if own != prior:
                raise ValueError('invoice identity already posted')
        else:
            _require_reconciled(store.ledger, store.registry)
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_invoice', 'operation_intent', str(error)),)
    return ()


def collection_operation(db, records, invoice_id):
    _validate_text(invoice_id, 'invoice ID')
    invoice = db.execute('SELECT b.* FROM customer_invoices b JOIN posting_events p ON p.journal_id=b.journal_id WHERE invoice_id=?', (invoice_id,)).fetchone()
    if invoice is None:
        raise ValueError('collection requires a posted customer invoice')
    if len(records) != 2 or len({r.document_id for r in records}) != 2:
        raise ValueError('collection requires distinct invoice and cash evidence')
    documents = []
    for record in records:
        document = dict(json.loads(record.canonical_content), entity_id=record.entity_id,
                        document_id=record.document_id)
        _content(document, record.entity_id)
        documents.append(document)
    cash = next((d for d in documents if d['kind'] == 'cash_movement'), None)
    source = next((d for d in documents if d['kind'] == 'customer_invoice'), None)
    if source is None or source['document_id'] != invoice[4] or cash is None:
        raise ValueError('collection evidence must include the target invoice and cash movement')
    if (cash['direction'], cash['purpose']) != ('in', 'settlement'):
        raise ValueError('collection requires an incoming settlement movement')
    if cash['event_id'] == invoice[3]:
        raise ValueError('collection requires a distinct cash event from invoice recognition')
    if cash['currency'] != source['currency']:
        raise ValueError('collection currency must match the invoice')
    if cash['counterparty_id'] != invoice[1] or cash['entity_id'] != source['entity_id']:
        raise ValueError('collection customer/entity must match the invoice')
    if cash['document_date'] < invoice[8]:
        raise ValueError('collection cannot precede invoice recognition')
    cents = Money.parse(cash['amount']).cents
    if not 1 <= cents <= MAX_CENTS:
        raise ValueError('collection amount must be a positive bounded integer')
    draft_id = 'draft:collection:' + digest([cash['entity_id'], cash['event_id']])
    intent = dict(schema_version=1, kind='customer_invoice_collection', invoice_id=invoice_id,
        customer_id=invoice[1], receipt_event_id=cash['event_id'], currency='USD', allocated_cents=cents,
        effective_date=cash['document_date'], evidence_roles=dict(invoice=invoice[4], cash=cash['document_id']))
    proposal = dict(id='journal:' + digest([cash['entity_id'], draft_id]), entity_id=cash['entity_id'],
        currency='USD', effective_date=cash['document_date'], description='Synthetic customer collection: ' + cash['event_id'],
        source_ids=[invoice[4], cash['document_id']],
        lines=[dict(account='1000', side='debit', amount=cash['amount']),
               dict(account='1100', side='credit', amount=cash['amount'])])
    return draft_id, intent, proposal


def validate_collection(store, proposal, records, intent, draft_id):
    try:
        if (not isinstance(intent, dict) or type(intent.get('schema_version')) is not int
                or type(intent.get('allocated_cents')) is not int):
            raise ValueError('collection requires an exact integer-cent operation intent')
        expected_id, expected_intent, expected_proposal = collection_operation(store.db, records, intent.get('invoice_id'))
        if intent != expected_intent or draft_id != expected_id or proposal != expected_proposal:
            raise ValueError('collection intent, identity or journal differs from evidenced settlement')
        if not store.db.execute('SELECT 1 FROM receivables_context').fetchone():
            raise ValueError('receivables must be enabled')
        claim = store.db.execute("""SELECT draft_id FROM operation_claims
            WHERE entity_id=? AND event_id=? AND role='cash_movement' """,
            (store.registry._entity_id, intent['receipt_event_id'])).fetchone()
        if claim and claim != (draft_id,):
            raise ValueError('duplicate economic event and role')
        prior = store.db.execute('SELECT * FROM customer_invoice_collections WHERE receipt_event_id=? OR cash_source_id=?',
            (intent['receipt_event_id'], intent['evidence_roles']['cash'])).fetchall()
        if prior:
            own = store.db.execute('SELECT journal_id FROM review_postings WHERE draft_id=?', (draft_id,)).fetchone()
            expected = (intent['receipt_event_id'], intent['invoice_id'], intent['evidence_roles']['cash'],
                        intent['allocated_cents'], intent['effective_date'])
            if len(prior) != 1 or prior[0][:5] != expected or own != (prior[0][6],) or prior[0][6] != proposal['id']:
                raise ValueError('cash movement already allocated')
        else:
            principal = store.db.execute('SELECT principal_cents FROM customer_invoices WHERE invoice_id=?',
                                         (intent['invoice_id'],)).fetchone()[0]
            paid = sum(r[0] for r in store.db.execute('SELECT allocated_cents FROM customer_invoice_collections WHERE invoice_id=?',
                                                    (intent['invoice_id'],)))
            if intent['allocated_cents'] > principal - paid:
                raise ValueError('collection exceeds remaining invoice outstanding')
            _require_reconciled(store.ledger, store.registry)
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_invoice_collection', 'operation_intent', str(error)),)
    return ()


@dataclass(frozen=True, slots=True)
class CustomerInvoiceCollection:
    receipt_event_id: str
    invoice_id: str
    cash_source_id: str
    allocated_cents: int
    effective_date: str
    approval_id: str
    journal_id: str


@dataclass(frozen=True, slots=True)
class CustomerInvoice:
    invoice_id: str
    customer_id: str
    invoice_number: str
    recognition_event_id: str
    invoice_source_id: str
    completion_source_id: str
    principal_cents: int
    revenue_account: str
    effective_date: str
    due_date: str
    approval_id: str
    journal_id: str
    customer_name: str


@dataclass(frozen=True, slots=True)
class ReceivablesSnapshot:
    ledger: object
    invoices: tuple[CustomerInvoice, ...]
    activation_json: str | None
    ledger_context: str
    collections: tuple[CustomerInvoiceCollection, ...] = ()


def _snapshot(ledger, registry):
    db = ledger._connection
    rows = db.execute('SELECT * FROM customer_invoices ORDER BY invoice_id').fetchall()
    invoices = []
    for row in rows:
        content = approved_source_content(db, registry, row[4], row[10])
        invoices.append(CustomerInvoice(*row, json.loads(content)['counterparty']))
    activation = db.execute('SELECT * FROM receivables_context').fetchone()
    return ReceivablesSnapshot(ledger._snapshot(), tuple(invoices), _canonical(activation) if activation else None, ledger._context,
        tuple(CustomerInvoiceCollection(*r) for r in db.execute('SELECT * FROM customer_invoice_collections ORDER BY receipt_event_id')))


def receivables_report(snapshot, *, as_of):
    cutoff = accounting_date(as_of)
    if not snapshot.ledger.period_start <= cutoff <= snapshot.ledger.period_end:
        raise ValueError('report cutoff is outside the ledger period')
    entries = tuple(e for e in snapshot.ledger.entries if e.effective_date <= cutoff)
    ids = tuple(e.id for e in entries)
    invoices = [dict(asdict(b), paid_cents=0, outstanding_cents=b.principal_cents)
             for b in snapshot.invoices if b.journal_id in ids and accounting_date(b.effective_date) <= cutoff]
    collections = [asdict(p) for p in snapshot.collections
                   if p.journal_id in ids and accounting_date(p.effective_date) <= cutoff]
    for invoice in invoices:
        invoice['paid_cents'] = sum(p['allocated_cents'] for p in collections if p['invoice_id'] == invoice['invoice_id'])
        invoice['outstanding_cents'] -= invoice['paid_cents']
        days = max(0, (cutoff - accounting_date(invoice['due_date'])).days)
        invoice['days_past_due'] = days
        invoice['aging_bucket'] = ('current' if days == 0 else 'days_1_30' if days <= 30 else
                                  'days_31_60' if days <= 60 else 'days_61_90' if days <= 90 else 'days_91_plus')
    control = sum(l.amount.cents if l.side == 'debit' else -l.amount.cents
                  for e in entries for l in e.lines if l.account == '1100')
    subledger = sum(b['outstanding_cents'] for b in invoices)
    customers = []
    for customer_id in sorted({b['customer_id'] for b in invoices}):
        selected = [b for b in invoices if b['customer_id'] == customer_id]
        customers.append(dict(customer_id=customer_id, names=sorted({b['customer_name'] for b in selected}),
                            outstanding_cents=sum(b['outstanding_cents'] for b in selected), aging_cents=_aging(selected)))
    snapshot_digest = digest([snapshot.ledger_context,
        [SQLiteLedger._entry_payload(e) for e in snapshot.ledger.entries],
        [asdict(b) for b in snapshot.invoices], snapshot.activation_json, [asdict(p) for p in snapshot.collections]])
    report = dict(policy=REPORT_POLICY, as_of=cutoff.isoformat(), snapshot_digest=snapshot_digest,
        included_journal_ids=list(ids), enabled=snapshot.activation_json is not None,
        activation=json.loads(snapshot.activation_json) if snapshot.activation_json else None,
        invoices=invoices, collections=collections, customers=customers, aging_cents=_aging(invoices),
        ar_control_cents=control, subledger_cents=subledger,
        unassigned_control_cents=control-subledger, reconciled=control == subledger)
    catalog = asdict(snapshot.ledger.catalog)
    if _canonical(catalog) != _canonical(json.loads(snapshot.ledger_context)['catalog']):
        # Preserve historical report bytes; new captures bind their effective catalog.
        report.update(catalog=catalog, snapshot_digest=digest([snapshot_digest, catalog]))
    return dict(report, report_digest=digest(report))


def _aging(invoices):
    return {bucket: sum(b['outstanding_cents'] for b in invoices if b['aging_bucket'] == bucket)
            for bucket in ('current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_91_plus')}


def _require_reconciled(ledger, registry):
    report = receivables_report(_snapshot(ledger, registry), as_of=ledger._empty.period_end)
    if not report['reconciled']:
        raise ValueError(f"unassigned AR residual {report['unassigned_control_cents']} cents; correction workflow required")


class ReceivablesService:
    def __init__(self, ledger, registry):
        self.ledger, self.registry, self.db = ledger, registry, ledger._connection
        self.store = SQLiteReviewStore(ledger, registry, policy_version='invoice-v1')
        self.app = ReviewApplication(self.store)
        with ledger._transaction(write=True):
            self._initialize()
            self._initialize_collections()

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='receivables_schema'").fetchone():
            if self.db.execute('SELECT version FROM receivables_schema').fetchall() not in ([(1,)], [(2,)]):
                raise ValueError('unsupported receivables schema version')
            return
        self.db.execute('CREATE TABLE receivables_schema (version INTEGER PRIMARY KEY) STRICT')
        self.db.execute('INSERT INTO receivables_schema VALUES (1)')
        self.db.execute('''CREATE TABLE receivables_context (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), entity_id TEXT NOT NULL,
            actor_id TEXT NOT NULL CHECK(length(trim(actor_id))>0 AND actor_id=trim(actor_id)),
            recorded_at TEXT NOT NULL, snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=64),
            journal_ids_json TEXT NOT NULL, policy TEXT NOT NULL CHECK(policy='receivables-zero-opening-v1')
        ) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE customer_invoices (
            invoice_id TEXT PRIMARY KEY CHECK(length(trim(invoice_id))>0 AND invoice_id=trim(invoice_id)),
            customer_id TEXT NOT NULL CHECK(length(trim(customer_id))>0 AND customer_id=trim(customer_id)),
            invoice_number TEXT NOT NULL CHECK(length(trim(invoice_number))>0 AND invoice_number=trim(invoice_number)),
            recognition_event_id TEXT NOT NULL UNIQUE CHECK(length(trim(recognition_event_id))>0),
            invoice_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            completion_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            principal_cents INTEGER NOT NULL CHECK(principal_cents>0),
            revenue_account TEXT NOT NULL REFERENCES accounts(code) CHECK(revenue_account='4000'),
            effective_date TEXT NOT NULL CHECK(effective_date BETWEEN '2026-01-01' AND '2026-01-31'),
            due_date TEXT NOT NULL CHECK(length(due_date)=10 AND date(due_date) IS NOT NULL AND date(due_date)=due_date AND due_date>=effective_date),
            approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
            UNIQUE(customer_id,invoice_number), CHECK(invoice_source_id!=completion_source_id)
        ) STRICT, WITHOUT ROWID''')
        for table, conflict in [('receivables_schema','1'), ('receivables_context','1'),
                ('customer_invoices','invoice_id=NEW.invoice_id OR (customer_id=NEW.customer_id AND invoice_number=NEW.invoice_number)')]:
            protect_table(self.db, table, conflict)
        self.db.execute('''CREATE TRIGGER invoice_before_post BEFORE INSERT ON customer_invoices
            WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
                 OR NOT EXISTS (SELECT 1 FROM receivables_context)
            BEGIN SELECT RAISE(ABORT,'invoice effect requires an enabled, unsealed journal'); END''')
        # SQL seals the exact approved operation shape; raw DB owners can still drop guards.
        self.db.execute('''CREATE TRIGGER invoice_approved_operation BEFORE INSERT ON customer_invoices
            WHEN NOT EXISTS (
                SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
                JOIN draft_operation_intents i USING(draft_id,revision)
                WHERE a.approval_id=NEW.approval_id AND r.policy_version='invoice-v1'
                  AND r.state='pending'
                  AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
                  AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
                  AND json_extract(r.proposal_json,'$.id')=NEW.journal_id
                  AND json_extract(i.intent_json,'$.kind')='customer_invoice'
                  AND json_extract(i.intent_json,'$.invoice_id')=NEW.invoice_id
                  AND json_extract(i.intent_json,'$.customer_id')=NEW.customer_id
                  AND json_extract(i.intent_json,'$.invoice_number')=NEW.invoice_number
                  AND json_extract(i.intent_json,'$.recognition_event_id')=NEW.recognition_event_id
                  AND json_extract(i.intent_json,'$.principal_cents')=NEW.principal_cents
                  AND json_extract(i.intent_json,'$.revenue_account')=NEW.revenue_account
                  AND json_extract(i.intent_json,'$.effective_date')=NEW.effective_date
                  AND json_extract(i.intent_json,'$.due_date')=NEW.due_date
                  AND json_extract(i.intent_json,'$.evidence_roles.invoice')=NEW.invoice_source_id
                  AND json_extract(i.intent_json,'$.evidence_roles.completion')=NEW.completion_source_id)
            BEGIN SELECT RAISE(ABORT,'invoice effect must match approved operation'); END''')
        self._create_post_guard()

    def _create_post_guard(self, *, collections=False):
        collection_when = ('OR EXISTS (SELECT 1 FROM customer_invoice_collections WHERE journal_id=NEW.journal_id)'
                           if collections else '')
        collection_match = (f""" AND NOT EXISTS (
            SELECT 1 FROM customer_invoice_collections c JOIN customer_invoices b USING(invoice_id)
            JOIN journals j ON j.id=c.journal_id
            WHERE c.journal_id=NEW.journal_id AND j.effective_date=c.effective_date
            AND {self._collection_approval_match('c')}
            AND NOT EXISTS (SELECT 1 FROM customer_invoices WHERE journal_id=NEW.journal_id)
            AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
            AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                AND account='1000' AND side='debit' AND cents=c.allocated_cents)
            AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                AND account='1100' AND side='credit' AND cents=c.allocated_cents)
            AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=2
            AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.invoice_source_id)
            AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=c.cash_source_id)
        )""" if collections else '')
        self.db.execute(f'''CREATE TRIGGER receivables_post_guard BEFORE INSERT ON posting_events
            WHEN (EXISTS (SELECT 1 FROM receivables_context)
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='1100'))
                 OR EXISTS (SELECT 1 FROM customer_invoices WHERE journal_id=NEW.journal_id)
                 {collection_when}
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM customer_invoices b JOIN journals j ON j.id=b.journal_id
                    JOIN approvals a ON a.approval_id=b.approval_id
                    JOIN draft_revisions r USING(draft_id,revision)
                    JOIN draft_operation_intents i USING(draft_id,revision)
                    WHERE b.journal_id=NEW.journal_id AND j.effective_date=b.effective_date
                    AND r.policy_version='invoice-v1' AND r.state='pending'
                    AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
                    AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
                    AND json_extract(r.proposal_json,'$.id')=b.journal_id
                    AND json_extract(i.intent_json,'$.kind')='customer_invoice'
                    AND json_extract(i.intent_json,'$.invoice_id')=b.invoice_id
                    AND json_extract(i.intent_json,'$.customer_id')=b.customer_id
                    AND json_extract(i.intent_json,'$.invoice_number')=b.invoice_number
                    AND json_extract(i.intent_json,'$.recognition_event_id')=b.recognition_event_id
                    AND json_extract(i.intent_json,'$.principal_cents')=b.principal_cents
                    AND json_extract(i.intent_json,'$.revenue_account')=b.revenue_account
                    AND json_extract(i.intent_json,'$.effective_date')=b.effective_date
                    AND json_extract(i.intent_json,'$.due_date')=b.due_date
                    AND json_extract(i.intent_json,'$.evidence_roles.invoice')=b.invoice_source_id
                    AND json_extract(i.intent_json,'$.evidence_roles.completion')=b.completion_source_id
                    AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='1100' AND side='debit' AND cents=b.principal_cents)
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account=b.revenue_account AND side='credit' AND cents=b.principal_cents)
                    AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.invoice_source_id)
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.completion_source_id)
                ){collection_match} THEN RAISE(ABORT,'AR posting requires matching approved receivable effect; correction workflow required') END;
            END''')

    @staticmethod
    def _collection_approval_match(effect):
        return f"""EXISTS (
            SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
            JOIN draft_operation_intents i USING(draft_id,revision)
            JOIN customer_invoices target ON target.invoice_id={effect}.invoice_id
            JOIN posting_events target_post ON target_post.journal_id=target.journal_id
            WHERE a.approval_id={effect}.approval_id AND r.policy_version='invoice-collection-v1'
              AND r.state='pending'
              AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
              AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
              AND json_extract(r.proposal_json,'$.id')={effect}.journal_id
              AND json_extract(i.intent_json,'$.kind')='customer_invoice_collection'
              AND json_extract(i.intent_json,'$.invoice_id')={effect}.invoice_id
              AND json_extract(i.intent_json,'$.customer_id')=target.customer_id
              AND json_extract(i.intent_json,'$.receipt_event_id')={effect}.receipt_event_id
              AND json_extract(i.intent_json,'$.allocated_cents')={effect}.allocated_cents
              AND json_extract(i.intent_json,'$.effective_date')={effect}.effective_date
              AND {effect}.effective_date>=target.effective_date
              AND json_extract(i.intent_json,'$.evidence_roles.invoice')=target.invoice_source_id
              AND json_extract(i.intent_json,'$.evidence_roles.cash')={effect}.cash_source_id)"""

    def _initialize_collections(self):
        if self.db.execute('SELECT version FROM receivables_schema').fetchall() == [(2,)]:
            return
        self.db.execute("""CREATE TABLE customer_invoice_collections (
            receipt_event_id TEXT PRIMARY KEY CHECK(length(trim(receipt_event_id))>0 AND receipt_event_id=trim(receipt_event_id)),
            invoice_id TEXT NOT NULL REFERENCES customer_invoices(invoice_id),
            cash_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            allocated_cents INTEGER NOT NULL CHECK(allocated_cents>0),
            effective_date TEXT NOT NULL CHECK(length(effective_date)=10 AND date(effective_date)=effective_date
                AND effective_date BETWEEN '2026-01-01' AND '2026-01-31'),
            approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED
        ) STRICT, WITHOUT ROWID""")
        protect_table(self.db, 'customer_invoice_collections', 'receipt_event_id=NEW.receipt_event_id OR cash_source_id=NEW.cash_source_id')
        self.db.execute("""CREATE TRIGGER collection_before_post BEFORE INSERT ON customer_invoice_collections
            WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
                 OR NOT EXISTS (SELECT 1 FROM receivables_context)
            BEGIN SELECT RAISE(ABORT,'collection effect requires an enabled, unsealed journal'); END""")
        self.db.execute(f"""CREATE TRIGGER collection_approved_operation BEFORE INSERT ON customer_invoice_collections
            WHEN NOT {self._collection_approval_match('NEW')}
              OR NEW.allocated_cents > (SELECT principal_cents FROM customer_invoices WHERE invoice_id=NEW.invoice_id)
                 - COALESCE((SELECT sum(allocated_cents) FROM customer_invoice_collections WHERE invoice_id=NEW.invoice_id),0)
            BEGIN SELECT RAISE(ABORT,'collection effect must match approved operation and remaining balance'); END""")
        self.db.execute('DROP TRIGGER receivables_post_guard')
        self._create_post_guard(collections=True)
        self.db.execute('DROP TRIGGER receivables_schema_no_update')
        self.db.execute('UPDATE receivables_schema SET version=2')
        self.db.execute("""CREATE TRIGGER receivables_schema_no_update BEFORE UPDATE ON receivables_schema
            BEGIN SELECT RAISE(ABORT,'receivables schema is immutable'); END""")

    def ensure_enabled(self, *, actor_id):
        _validate_text(actor_id, 'actor ID')
        with self.ledger._transaction(write=True):
            prior = self.db.execute('SELECT * FROM receivables_context').fetchone()
            if prior:
                return prior
            _require_reconciled(self.ledger, self.registry)
            snapshot = self.ledger._snapshot()
            self.db.execute('INSERT INTO receivables_context VALUES (1,?,?,?,?,?,?)',
                (snapshot.catalog.entity_id, actor_id, datetime.now(timezone.utc).isoformat(),
                 digest([self.ledger._context, [self.ledger._entry_payload(e) for e in snapshot.entries]]),
                 _canonical([e.id for e in snapshot.entries]), REPORT_POLICY))
            return self.db.execute('SELECT * FROM receivables_context').fetchone()

    def propose_invoice(self, *, invoice_source_id, completion_source_id, expected_revision, actor_id, idempotency_key):
        records = (self.registry.get(invoice_source_id), self.registry.get(completion_source_id))
        draft_id, intent, proposal = invoice_operation(records)
        if intent['evidence_roles'] != dict(invoice=invoice_source_id, completion=completion_source_id):
            raise ValueError('sources must match invoice and completion roles')
        self.ensure_enabled(actor_id=actor_id)
        return self.store.save(draft_id, proposal, evidence={r.document_id:r.content_digest for r in records},
            operation_intent=intent, expected_revision=expected_revision, actor_id=actor_id,
            idempotency_key=idempotency_key, reason='Synthetic customer invoice; separate human review required')

    def propose_collection(self, *, invoice_id, cash_source_id, expected_revision, actor_id, idempotency_key):
        row = self.db.execute('SELECT invoice_source_id FROM customer_invoices WHERE invoice_id=?', (invoice_id,)).fetchone()
        if row is None:
            raise ValueError('collection requires a posted customer invoice')
        records = (self.registry.get(row[0]), self.registry.get(cash_source_id))
        draft_id, intent, proposal = collection_operation(self.db, records, invoice_id)
        store = SQLiteReviewStore(self.ledger, self.registry, policy_version='invoice-collection-v1')
        return store.save(draft_id, proposal, evidence={r.document_id:r.content_digest for r in records},
            operation_intent=intent, expected_revision=expected_revision, actor_id=actor_id,
            idempotency_key=idempotency_key, reason='Synthetic recorded customer collection; separate human review required')

    def snapshot(self):
        with self.ledger._transaction():
            return _snapshot(self.ledger, self.registry)


def prepare_receivable_post(store, approval, revision, entry):
    """Mandatory transaction-internal effect; caller cannot omit it on approved posts."""
    if not store.db.in_transaction:
        raise ValueError('receivable posting requires the ledger write transaction')
    intent = json.loads(revision.operation_intent_json)
    if (revision.policy_version, intent['kind']) not in (('invoice-v1', 'customer_invoice'),
            ('invoice-collection-v1', 'customer_invoice_collection')):
        raise ValueError('unsupported receivable operation')
    findings = store.validate(json.loads(revision.proposal_json), json.loads(revision.evidence_json),
                              operation_intent=intent, draft_id=revision.draft_id)
    if findings:
        raise ValueError('receivable operation is no longer valid: ' + findings[0].message)
    if entry.id != json.loads(revision.proposal_json)['id']:
        raise ValueError('effect journal must match approved operation')
    collection = intent['kind'] == 'customer_invoice_collection'
    claim = store.db.execute('''SELECT draft_id FROM operation_claims
        WHERE entity_id=? AND event_id=? AND role=?''',
        (entry.entity_id, intent['receipt_event_id' if collection else 'recognition_event_id'],
         'cash_movement' if collection else 'service_revenue_recognition')).fetchone()
    if claim != (revision.draft_id,):
        raise ValueError('service recognition claim is not owned by this draft')
    _require_reconciled(store.ledger, store.registry)
    if collection:
        store.db.execute('INSERT INTO customer_invoice_collections VALUES (?,?,?,?,?,?,?)',
            (intent['receipt_event_id'],intent['invoice_id'],intent['evidence_roles']['cash'],
             intent['allocated_cents'],intent['effective_date'],approval.approval_id,entry.id))
        return
    store.db.execute('INSERT INTO customer_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (intent['invoice_id'],intent['customer_id'],intent['invoice_number'],intent['recognition_event_id'],
         intent['evidence_roles']['invoice'],intent['evidence_roles']['completion'],intent['principal_cents'],
         intent['revenue_account'],intent['effective_date'],intent['due_date'],approval.approval_id,entry.id))
