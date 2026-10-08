"""Reviewed vendor expense recognition and immutable AP control reconciliation."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.accounts import _validate_text
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import Finding
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS, SQLiteLedger, _canonical
from accounting_harness.review import SQLiteReviewStore, digest, protect_table
from accounting_harness.sources import _content

REPORT_POLICY = 'payables-zero-opening-v1'


def bill_operation(records):
    """Derive the only supported intent and journal from two independent facts."""
    if len(records) != 2 or len({r.document_id for r in records}) != 2:
        raise ValueError('bill recognition requires distinct bill and incurred-expense evidence')
    documents = []
    for record in records:
        document = dict(json.loads(record.canonical_content), entity_id=record.entity_id,
                        document_id=record.document_id)
        _content(document, record.entity_id)
        documents.append(document)
    bill = next((d for d in documents if d['kind'] == 'vendor_bill'), None)
    incurred = next((d for d in documents if d['kind'] == 'incurred_expense'), None)
    if bill is None or incurred is None:
        raise ValueError('a vendor bill alone cannot establish expense incurrence')
    for field in ('entity_id', 'event_id', 'counterparty_id', 'currency', 'amount', 'document_date'):
        if bill[field] != incurred[field]:
            raise ValueError('bill and incurrence evidence differ in ' + field)
    if bill['document_date'] != incurred['incurred_date']:
        raise ValueError('bill issue and expense incurrence dates must match')
    cents = Money.parse(bill['amount']).cents
    if not 1 <= cents <= MAX_CENTS:
        raise ValueError('bill principal exceeds storage bounds')
    bill_id = 'bill:' + digest([bill['entity_id'], bill['counterparty_id'], bill['bill_number']])
    draft_id = 'draft:' + bill_id
    intent = dict(schema_version=1, kind='vendor_bill', bill_id=bill_id,
        vendor_id=bill['counterparty_id'], bill_number=bill['bill_number'],
        recognition_event_id=bill['event_id'], currency='USD', principal_cents=cents,
        expense_account=incurred['expense_account'], effective_date=incurred['incurred_date'],
        due_date=bill['due_date'], evidence_roles=dict(bill=bill['document_id'], incurrence=incurred['document_id']))
    proposal = dict(id='journal:' + digest([bill['entity_id'], draft_id]), entity_id=bill['entity_id'],
        currency='USD', effective_date=incurred['incurred_date'],
        description='Synthetic vendor bill: ' + bill['bill_number'],
        source_ids=[bill['document_id'], incurred['document_id']],
        lines=[dict(account=incurred['expense_account'], side='debit', amount=bill['amount']),
               dict(account='2000', side='credit', amount=bill['amount'])])
    return draft_id, intent, proposal


def validate_bill(store, proposal, records, intent, draft_id):
    try:
        expected_id, expected_intent, expected_proposal = bill_operation(records)
        if not isinstance(intent, dict) or type(intent.get('schema_version')) is not int:
            raise ValueError('bill policy requires an exact operation intent')
        if type(intent.get('principal_cents')) is not int or not 1 <= intent['principal_cents'] <= MAX_CENTS:
            raise ValueError('principal cents must be a positive bounded integer')
        if intent != expected_intent:
            raise ValueError('operation intent differs from evidenced bill recognition')
        if draft_id != expected_id or proposal != expected_proposal:
            raise ValueError('bill draft identity or journal differs from evidenced recognition')
        claim = store.db.execute('''SELECT draft_id FROM operation_claims
            WHERE entity_id=? AND event_id=? AND role='expense_recognition' ''',
            (store.registry._entity_id, intent['recognition_event_id'])).fetchone()
        if claim and claim[0] != draft_id:
            raise ValueError('duplicate economic event and role')
        if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='payables_context'").fetchone():
            raise ValueError('payables must be enabled before bill review')
        if not store.db.execute('SELECT 1 FROM payables_context').fetchone():
            raise ValueError('payables must be enabled before bill review')
        prior = store.db.execute('SELECT journal_id FROM vendor_bills WHERE bill_id=?', (intent['bill_id'],)).fetchone()
        if prior:
            own = store.db.execute('SELECT journal_id FROM review_postings WHERE draft_id=?', (draft_id,)).fetchone()
            if own != prior:
                raise ValueError('bill identity already posted')
        else:
            _require_reconciled(store.ledger, store.registry)
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_bill', 'operation_intent', str(error)),)
    return ()


@dataclass(frozen=True, slots=True)
class VendorBill:
    bill_id: str
    vendor_id: str
    bill_number: str
    recognition_event_id: str
    bill_source_id: str
    incurrence_source_id: str
    principal_cents: int
    expense_account: str
    effective_date: str
    due_date: str
    approval_id: str
    journal_id: str
    vendor_name: str


@dataclass(frozen=True, slots=True)
class PayablesSnapshot:
    ledger: object
    bills: tuple[VendorBill, ...]
    activation_json: str | None
    ledger_context: str


def _snapshot(ledger, registry):
    db = ledger._connection
    rows = db.execute('''SELECT b.*, e.canonical_content FROM vendor_bills b
        LEFT JOIN source_enrollments e ON e.source_id=b.bill_source_id ORDER BY b.bill_id''').fetchall()
    bills = []
    for row in rows:
        content = row[-1]
        if content is None:
            # Initial-context sources lack enrollment anchors; capture their approved immutable content now.
            source = registry.get(row[4])
            binding = json.loads(db.execute('SELECT binding_json FROM approvals WHERE approval_id=?',
                                            (row[10],)).fetchone()[0])
            expected = binding['evidence'][row[4]]
            if (source.content_digest != expected
                    or hashlib.sha256(source.canonical_content.encode()).hexdigest() != expected):
                raise ValueError('bill source differs from approved evidence')
            content = source.canonical_content
        bills.append(VendorBill(*row[:-1], json.loads(content)['counterparty']))
    activation = db.execute('SELECT * FROM payables_context').fetchone()
    return PayablesSnapshot(ledger._snapshot(), tuple(bills), _canonical(activation) if activation else None, ledger._context)


def payables_report(snapshot, *, as_of):
    cutoff = accounting_date(as_of)
    if not snapshot.ledger.period_start <= cutoff <= snapshot.ledger.period_end:
        raise ValueError('report cutoff is outside the ledger period')
    entries = tuple(e for e in snapshot.ledger.entries if e.effective_date <= cutoff)
    ids = tuple(e.id for e in entries)
    bills = [dict(asdict(b), paid_cents=0, outstanding_cents=b.principal_cents)
             for b in snapshot.bills if b.journal_id in ids and accounting_date(b.effective_date) <= cutoff]
    control = sum(l.amount.cents if l.side == 'credit' else -l.amount.cents
                  for e in entries for l in e.lines if l.account == '2000')
    subledger = sum(b['outstanding_cents'] for b in bills)
    vendors = []
    for vendor_id in sorted({b['vendor_id'] for b in bills}):
        selected = [b for b in bills if b['vendor_id'] == vendor_id]
        vendors.append(dict(vendor_id=vendor_id, names=sorted({b['vendor_name'] for b in selected}),
                            outstanding_cents=sum(b['outstanding_cents'] for b in selected)))
    snapshot_digest = digest([snapshot.ledger_context,
        [SQLiteLedger._entry_payload(e) for e in snapshot.ledger.entries],
        [asdict(b) for b in snapshot.bills], snapshot.activation_json])
    report = dict(policy=REPORT_POLICY, as_of=cutoff.isoformat(), snapshot_digest=snapshot_digest,
        included_journal_ids=list(ids), enabled=snapshot.activation_json is not None,
        activation=json.loads(snapshot.activation_json) if snapshot.activation_json else None,
        bills=bills, vendors=vendors, ap_control_cents=control, subledger_cents=subledger,
        unassigned_control_cents=control-subledger, reconciled=control == subledger)
    return dict(report, report_digest=digest(report))


def _require_reconciled(ledger, registry):
    report = payables_report(_snapshot(ledger, registry), as_of=ledger._empty.period_end)
    if not report['reconciled']:
        raise ValueError(f"unassigned AP residual {report['unassigned_control_cents']} cents; correction workflow required")


class PayablesService:
    def __init__(self, ledger, registry):
        self.ledger, self.registry, self.db = ledger, registry, ledger._connection
        self.store = SQLiteReviewStore(ledger, registry, policy_version='bill-v1')
        self.app = ReviewApplication(self.store)
        with ledger._transaction(write=True):
            self._initialize()

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='payables_schema'").fetchone():
            if self.db.execute('SELECT version FROM payables_schema').fetchall() != [(1,)]:
                raise ValueError('unsupported payables schema version')
            return
        self.db.execute('CREATE TABLE payables_schema (version INTEGER PRIMARY KEY) STRICT')
        self.db.execute('INSERT INTO payables_schema VALUES (1)')
        self.db.execute('''CREATE TABLE payables_context (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), entity_id TEXT NOT NULL,
            actor_id TEXT NOT NULL CHECK(length(trim(actor_id))>0 AND actor_id=trim(actor_id)),
            recorded_at TEXT NOT NULL, snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=64),
            journal_ids_json TEXT NOT NULL, policy TEXT NOT NULL CHECK(policy='payables-zero-opening-v1')
        ) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE vendor_bills (
            bill_id TEXT PRIMARY KEY CHECK(length(trim(bill_id))>0 AND bill_id=trim(bill_id)),
            vendor_id TEXT NOT NULL CHECK(length(trim(vendor_id))>0 AND vendor_id=trim(vendor_id)),
            bill_number TEXT NOT NULL CHECK(length(trim(bill_number))>0 AND bill_number=trim(bill_number)),
            recognition_event_id TEXT NOT NULL UNIQUE CHECK(length(trim(recognition_event_id))>0),
            bill_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            incurrence_source_id TEXT NOT NULL UNIQUE REFERENCES sources(id),
            principal_cents INTEGER NOT NULL CHECK(principal_cents>0),
            expense_account TEXT NOT NULL REFERENCES accounts(code) CHECK(expense_account IN ('5000','5100')),
            effective_date TEXT NOT NULL CHECK(effective_date BETWEEN '2026-01-01' AND '2026-01-31'),
            due_date TEXT NOT NULL CHECK(length(due_date)=10 AND date(due_date) IS NOT NULL AND date(due_date)=due_date AND due_date>=effective_date),
            approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
            UNIQUE(vendor_id,bill_number), CHECK(bill_source_id!=incurrence_source_id)
        ) STRICT, WITHOUT ROWID''')
        for table, conflict in [('payables_schema','1'), ('payables_context','1'),
                ('vendor_bills','bill_id=NEW.bill_id OR (vendor_id=NEW.vendor_id AND bill_number=NEW.bill_number)')]:
            protect_table(self.db, table, conflict)
        self.db.execute('''CREATE TRIGGER bill_before_post BEFORE INSERT ON vendor_bills
            WHEN EXISTS (SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
                 OR NOT EXISTS (SELECT 1 FROM payables_context)
            BEGIN SELECT RAISE(ABORT,'bill effect requires an enabled, unsealed journal'); END''')
        # SQL seals the exact approved operation shape; raw DB owners can still drop guards.
        self.db.execute('''CREATE TRIGGER bill_approved_operation BEFORE INSERT ON vendor_bills
            WHEN NOT EXISTS (
                SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
                JOIN draft_operation_intents i USING(draft_id,revision)
                WHERE a.approval_id=NEW.approval_id AND r.policy_version='bill-v1'
                  AND r.state='pending'
                  AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
                  AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
                  AND json_extract(r.proposal_json,'$.id')=NEW.journal_id
                  AND json_extract(i.intent_json,'$.kind')='vendor_bill'
                  AND json_extract(i.intent_json,'$.bill_id')=NEW.bill_id
                  AND json_extract(i.intent_json,'$.vendor_id')=NEW.vendor_id
                  AND json_extract(i.intent_json,'$.bill_number')=NEW.bill_number
                  AND json_extract(i.intent_json,'$.recognition_event_id')=NEW.recognition_event_id
                  AND json_extract(i.intent_json,'$.principal_cents')=NEW.principal_cents
                  AND json_extract(i.intent_json,'$.expense_account')=NEW.expense_account
                  AND json_extract(i.intent_json,'$.effective_date')=NEW.effective_date
                  AND json_extract(i.intent_json,'$.due_date')=NEW.due_date
                  AND json_extract(i.intent_json,'$.evidence_roles.bill')=NEW.bill_source_id
                  AND json_extract(i.intent_json,'$.evidence_roles.incurrence')=NEW.incurrence_source_id)
            BEGIN SELECT RAISE(ABORT,'bill effect must match approved operation'); END''')
        self.db.execute('''CREATE TRIGGER payables_post_guard BEFORE INSERT ON posting_events
            WHEN (EXISTS (SELECT 1 FROM payables_context)
                  AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='2000'))
                 OR EXISTS (SELECT 1 FROM vendor_bills WHERE journal_id=NEW.journal_id)
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM vendor_bills b JOIN journals j ON j.id=b.journal_id
                    WHERE b.journal_id=NEW.journal_id AND j.effective_date=b.effective_date
                    AND (SELECT count(*) FROM lines WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account='2000' AND side='credit' AND cents=b.principal_cents)
                    AND EXISTS (SELECT 1 FROM lines WHERE journal_id=NEW.journal_id
                        AND account=b.expense_account AND side='debit' AND cents=b.principal_cents)
                    AND (SELECT count(*) FROM journal_sources WHERE journal_id=NEW.journal_id)=2
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.bill_source_id)
                    AND EXISTS (SELECT 1 FROM journal_sources WHERE journal_id=NEW.journal_id AND source_id=b.incurrence_source_id)
                ) THEN RAISE(ABORT,'AP posting requires matching approved payable effect; correction workflow required') END;
            END''')

    def ensure_enabled(self, *, actor_id):
        _validate_text(actor_id, 'actor ID')
        with self.ledger._transaction(write=True):
            prior = self.db.execute('SELECT * FROM payables_context').fetchone()
            if prior:
                return prior
            _require_reconciled(self.ledger, self.registry)
            snapshot = self.ledger._snapshot()
            self.db.execute('INSERT INTO payables_context VALUES (1,?,?,?,?,?,?)',
                (snapshot.catalog.entity_id, actor_id, datetime.now(timezone.utc).isoformat(),
                 digest([self.ledger._context, [self.ledger._entry_payload(e) for e in snapshot.entries]]),
                 _canonical([e.id for e in snapshot.entries]), REPORT_POLICY))
            return self.db.execute('SELECT * FROM payables_context').fetchone()

    def propose_bill(self, *, bill_source_id, incurrence_source_id, expected_revision, actor_id, idempotency_key):
        records = (self.registry.get(bill_source_id), self.registry.get(incurrence_source_id))
        draft_id, intent, proposal = bill_operation(records)
        if intent['evidence_roles'] != dict(bill=bill_source_id, incurrence=incurrence_source_id):
            raise ValueError('sources must match bill and incurrence roles')
        self.ensure_enabled(actor_id=actor_id)
        return self.store.save(draft_id, proposal, evidence={r.document_id:r.content_digest for r in records},
            operation_intent=intent, expected_revision=expected_revision, actor_id=actor_id,
            idempotency_key=idempotency_key, reason='Synthetic vendor bill; separate human review required')

    def snapshot(self):
        with self.ledger._transaction():
            return _snapshot(self.ledger, self.registry)


def prepare_payable_post(store, approval, revision, entry):
    """Mandatory transaction-internal effect; caller cannot omit it on approved posts."""
    if not store.db.in_transaction:
        raise ValueError('payable posting requires the ledger write transaction')
    intent = json.loads(revision.operation_intent_json)
    if revision.policy_version != 'bill-v1' or intent['kind'] != 'vendor_bill':
        raise ValueError('unsupported payable operation')
    findings = store.validate(json.loads(revision.proposal_json), json.loads(revision.evidence_json),
                              operation_intent=intent, draft_id=revision.draft_id)
    if findings:
        raise ValueError('payable operation is no longer valid: ' + findings[0].message)
    if entry.id != json.loads(revision.proposal_json)['id']:
        raise ValueError('effect journal must match approved operation')
    claim = store.db.execute('''SELECT draft_id FROM operation_claims
        WHERE entity_id=? AND event_id=? AND role='expense_recognition' ''',
        (entry.entity_id,intent['recognition_event_id'])).fetchone()
    if claim != (revision.draft_id,):
        raise ValueError('expense recognition claim is not owned by this draft')
    _require_reconciled(store.ledger, store.registry)
    store.db.execute('INSERT INTO vendor_bills VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (intent['bill_id'],intent['vendor_id'],intent['bill_number'],intent['recognition_event_id'],
         intent['evidence_roles']['bill'],intent['evidence_roles']['incurrence'],intent['principal_cents'],
         intent['expense_account'],intent['effective_date'],intent['due_date'],approval.approval_id,entry.id))
