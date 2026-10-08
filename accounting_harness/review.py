"""Append-only proposal revisions; validation is never posting authority."""

import hashlib
import json
import re
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from accounting_harness.domain.accounts import _validate_text
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import Finding, validate_journal
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS, _canonical


def digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def protect_table(db, table, conflict):
    for action in ('UPDATE', 'DELETE'):
        db.execute(f"""CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}
            BEGIN SELECT RAISE(ABORT, 'review records are append-only'); END""")
    db.execute(f"""CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
        WHEN EXISTS (SELECT 1 FROM {table} WHERE {conflict})
        BEGIN SELECT RAISE(ABORT, 'review records cannot be replaced'); END""")


@dataclass(frozen=True, slots=True)
class DraftRevision:
    draft_id: str
    revision: int
    proposal_json: str
    evidence_json: str
    policy_version: str
    content_digest: str
    state: str
    reason: str
    actor_id: str
    recorded_at: str
    findings: tuple[Finding, ...]
    current_findings: tuple[Finding, ...]

    operation_intent_json: str | None = None

    @property
    def reviewable(self):
        return self.state == 'pending' and not self.findings and not self.current_findings


class SQLiteReviewStore:
    def __init__(self, ledger, registry, *, policy_version='review-v1'):
        _validate_text(policy_version, 'policy version')
        if ledger._empty.catalog.entity_id != registry._entity_id:
            raise ValueError('registry entity must match ledger entity')
        self.ledger = ledger
        self.registry = registry
        self.policy_version = policy_version
        self.db = ledger._connection
        # Initialization may join a service-owned write transaction so schema setup rolls back together.
        with (nullcontext() if self.db.in_transaction else self.ledger._transaction(write=True)):
            self._initialize()
            self._initialize_intents()
            self._initialize_payment_intents()
            self._initialize_invoice_intents()
            self._initialize_collection_intents()
            self._initialize_advance_intents()
            self._initialize_earning_intents()
            self._initialize_fee_intents()
            self._initialize_claims()

    def _initialize_claims(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='operation_claims'").fetchone():
            return
        self.db.execute('''CREATE TABLE operation_claims (
            entity_id TEXT NOT NULL, event_id TEXT NOT NULL, role TEXT NOT NULL,
            draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY(entity_id, event_id, role),
            FOREIGN KEY(draft_id, revision) REFERENCES draft_revisions(draft_id, revision)
        ) STRICT, WITHOUT ROWID''')
        protect_table(self.db, 'operation_claims',
                      'entity_id=NEW.entity_id AND event_id=NEW.event_id AND role=NEW.role')

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='review_schema'").fetchone():
            if self.db.execute('SELECT version FROM review_schema').fetchall() not in ([(1,)], [(2,)], [(3,)], [(4,)], [(5,)], [(6,)], [(7,)], [(8,)]):
                raise ValueError('unsupported review schema version')
            return
        self.db.execute('CREATE TABLE review_schema (version INTEGER PRIMARY KEY) STRICT')
        self.db.execute('INSERT INTO review_schema VALUES (1)')
        self.db.execute("""CREATE TABLE draft_revisions (
            draft_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
            proposal_json TEXT NOT NULL, evidence_json TEXT NOT NULL, policy_version TEXT NOT NULL,
            content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
            state TEXT NOT NULL CHECK(state IN ('pending','rejected')),
            reason TEXT NOT NULL CHECK(length(trim(reason))>0), actor_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL, findings_json TEXT NOT NULL,
            PRIMARY KEY(draft_id, revision)
        ) STRICT, WITHOUT ROWID""")
        self.db.execute("""CREATE TABLE review_events (
            draft_id TEXT NOT NULL, revision INTEGER NOT NULL, operation TEXT NOT NULL,
            PRIMARY KEY(draft_id, revision),
            FOREIGN KEY(draft_id, revision) REFERENCES draft_revisions(draft_id, revision)
        ) STRICT, WITHOUT ROWID""")
        self.db.execute("""CREATE TABLE review_requests (
            operation TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
            draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY(operation, key),
            FOREIGN KEY(draft_id, revision) REFERENCES review_events(draft_id, revision)
        ) STRICT, WITHOUT ROWID""")
        for table, conflict in (
            ('review_schema', '1'),
            ('draft_revisions', 'draft_id=NEW.draft_id AND revision=NEW.revision'),
            ('review_events', 'draft_id=NEW.draft_id AND revision=NEW.revision'),
            ('review_requests', 'operation=NEW.operation AND key=NEW.key'),
        ):
            protect_table(self.db, table, conflict)

    def _initialize_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() in ([(2,)], [(3,)], [(4,)], [(5,)], [(6,)], [(7,)], [(8,)]):
            return
        self.db.execute("""CREATE TABLE draft_operation_intents (
            draft_id TEXT NOT NULL, revision INTEGER NOT NULL, intent_json TEXT NOT NULL,
            PRIMARY KEY(draft_id, revision),
            FOREIGN KEY(draft_id, revision) REFERENCES draft_revisions(draft_id, revision)
        ) STRICT, WITHOUT ROWID""")
        protect_table(self.db, 'draft_operation_intents', 'draft_id=NEW.draft_id AND revision=NEW.revision')
        self.db.execute("""CREATE TRIGGER intent_before_seal BEFORE INSERT ON draft_operation_intents
            WHEN EXISTS (SELECT 1 FROM review_events WHERE draft_id=NEW.draft_id AND revision=NEW.revision)
            BEGIN SELECT RAISE(ABORT, 'revision intent is sealed'); END""")
        self.db.execute("""CREATE TRIGGER intent_required_at_seal BEFORE INSERT ON review_events
            WHEN (SELECT policy_version FROM draft_revisions
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision) = 'bill-v1'
                 AND NOT EXISTS (SELECT 1 FROM draft_operation_intents
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision)
              OR (SELECT policy_version FROM draft_revisions
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision) != 'bill-v1'
                 AND EXISTS (SELECT 1 FROM draft_operation_intents
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision)
            BEGIN SELECT RAISE(ABORT, 'missing or unexpected operation intent'); END""")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=2')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT, 'review records are append-only'); END""")

    def _initialize_payment_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() in ([(3,)], [(4,)], [(5,)], [(6,)], [(7,)], [(8,)]):
            return
        self._replace_intent_seal("'bill-v1','bill-payment-v1'")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=3')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT, 'review records are append-only'); END""")

    def _initialize_invoice_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() in ([(4,)], [(5,)], [(6,)], [(7,)], [(8,)]):
            return
        self._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1'")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=4')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT, 'review records are append-only'); END""")

    def _initialize_collection_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() in ([(5,)], [(6,)], [(7,)], [(8,)]):
            return
        self._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1'")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=5')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT, 'review records are append-only'); END""")

    def _initialize_advance_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() in ([(6,)], [(7,)], [(8,)]):
            return
        self._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1'")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=6')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT, 'review records are append-only'); END""")

    def _initialize_earning_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() in ([(7,)], [(8,)]):
            return
        self._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1'")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=7')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT,'review schema is immutable'); END""")

    def _initialize_fee_intents(self):
        if self.db.execute('SELECT version FROM review_schema').fetchall() == [(8,)]:
            return
        self._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1','advance-v1','advance-earning-v1','bank-fee-v1'")
        self.db.execute('DROP TRIGGER review_schema_no_update')
        self.db.execute('UPDATE review_schema SET version=8')
        self.db.execute("""CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema
            BEGIN SELECT RAISE(ABORT,'review schema is immutable'); END""")

    def _replace_intent_seal(self, policies):
        # Only versioned migration literals call this concrete seal; never rewrite stored SQL fragments.
        self.db.execute('DROP TRIGGER intent_required_at_seal')
        self.db.execute(f"""CREATE TRIGGER intent_required_at_seal BEFORE INSERT ON review_events
            WHEN (SELECT policy_version FROM draft_revisions
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision) IN ({policies})
                 AND NOT EXISTS (SELECT 1 FROM draft_operation_intents
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision)
              OR (SELECT policy_version FROM draft_revisions
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision) NOT IN ({policies})
                 AND EXISTS (SELECT 1 FROM draft_operation_intents
                  WHERE draft_id=NEW.draft_id AND revision=NEW.revision)
            BEGIN SELECT RAISE(ABORT, 'missing or unexpected operation intent'); END""")

    def validate(self, proposal, evidence, *, operation_intent=None, draft_id=None):
        """Read-only validation against registered evidence and the current ledger catalog."""
        catalog = self.ledger.current_catalog()
        result = validate_journal(proposal, catalog, known_source_ids=self.ledger.known_source_ids())
        findings = list(result.findings)
        if not isinstance(proposal, dict):
            return tuple(findings)
        sources = proposal.get('source_ids')
        valid_sources = isinstance(sources, list) and all(isinstance(s, str) for s in sources)
        if not valid_sources or set(sources) != set(evidence):
            findings.append(Finding('evidence_binding', 'source_ids', 'bind every source identity exactly'))
        records = []
        for source_id, expected in evidence.items():
            try:
                source = self.registry.get(source_id)
            except KeyError:
                findings.append(Finding('missing_evidence', source_id, 'registered evidence is missing'))
                continue
            if (source.content_digest != expected
                    or hashlib.sha256(source.canonical_content.encode()).hexdigest() != expected):
                findings.append(Finding('conflicting_evidence', source_id, 'registered digest differs'))
            anchor = self.db.execute(
                'SELECT content_digest, canonical_content FROM source_enrollments WHERE source_id=?',
                (source_id,)).fetchone()
            if anchor is not None and anchor != (source.content_digest, source.canonical_content):
                findings.append(Finding('conflicting_evidence', source_id, 'evidence differs from enrollment anchor'))
            records.append(source)
        if self.policy_version == 'review-v1':
            extension_codes = {a.code for a in catalog.accounts} - {a.code for a in self.ledger._empty.catalog.accounts}
            for line in proposal.get('lines', []) if isinstance(proposal.get('lines'), list) else []:
                if isinstance(line, dict) and isinstance(line.get('account'), str) and line['account'] in extension_codes:
                    findings.append(Finding('unsupported_account', 'lines',
                                            'receipt policy requires an original baseline account'))
            if valid_sources and len(sources) != 1:
                findings.append(Finding('unsupported_evidence', 'source_ids', 'receipt policy requires one source'))
            for record in records:
                document = json.loads(record.canonical_content)
                if document.get('schema_version') != 1 or document.get('kind') != 'receipt':
                    findings.append(Finding('unsupported_evidence', record.document_id,
                                            'receipt policy requires a schema v1 receipt'))
        elif self.policy_version == 'bank-fee-v1':
            from accounting_harness.bank_fees import validate_fee
            findings.extend(validate_fee(self, proposal, records, operation_intent, draft_id))
        elif self.policy_version == 'cash-v1':
            from accounting_harness.operations import validate_cash_evidence
            findings.extend(validate_cash_evidence(proposal, records))
        elif self.policy_version == 'bill-v1':
            from accounting_harness.payables import validate_bill
            findings.extend(validate_bill(self, proposal, records, operation_intent, draft_id))
        elif self.policy_version == 'advance-earning-v1':
            from accounting_harness.advances import validate_earning
            findings.extend(validate_earning(self, proposal, records, operation_intent, draft_id))
        elif self.policy_version == 'advance-v1':
            from accounting_harness.advances import validate_advance
            findings.extend(validate_advance(self, proposal, records, operation_intent, draft_id))
        elif self.policy_version == 'invoice-v1':
            from accounting_harness.receivables import validate_invoice
            findings.extend(validate_invoice(self, proposal, records, operation_intent, draft_id))
        elif self.policy_version == 'invoice-collection-v1':
            from accounting_harness.receivables import validate_collection
            findings.extend(validate_collection(self, proposal, records, operation_intent, draft_id))
        elif self.policy_version == 'bill-payment-v1':
            from accounting_harness.payables import validate_payment
            findings.extend(validate_payment(self, proposal, records, operation_intent, draft_id))
        else:
            findings.append(Finding('unsupported_policy', 'policy_version', 'unknown review policy'))
        if operation_intent is not None and self.policy_version not in ('bill-v1', 'bill-payment-v1', 'invoice-v1', 'invoice-collection-v1', 'advance-v1', 'advance-earning-v1', 'bank-fee-v1'):
            findings.append(Finding('unexpected_intent', 'operation_intent', 'policy does not accept an intent'))
        try:
            effective = accounting_date(proposal.get('effective_date'))
            if not self.ledger._empty.period_start <= effective <= self.ledger._empty.period_end:
                findings.append(Finding('outside_period', 'effective_date', 'date is outside the ledger period'))
        except ValueError:
            pass  # The journal validator supplies the date finding.
        if self.policy_version == 'review-v1' and len(records) == 1 and result.total_debits is not None:
            if result.total_debits != Money.parse(json.loads(records[0].canonical_content)['amount']):
                findings.append(Finding('evidence_amount', 'lines', 'debit total differs from receipt amount'))
        lines = proposal.get('lines')
        for i, line in enumerate(lines if isinstance(lines, list) else []):
            if isinstance(line, dict):
                try:
                    if Money.parse(line.get('amount')).cents > MAX_CENTS:
                        findings.append(Finding('storage_overflow', f'lines[{i}].amount', 'exceeds SQLite cents limit'))
                except (ValueError, TypeError):
                    pass
        return tuple(findings)

    @staticmethod
    def _inputs(draft_id, expected_revision, actor_id, idempotency_key, reason):
        for value, label in ((draft_id, 'draft ID'), (actor_id, 'actor ID'),
                             (idempotency_key, 'retry key'), (reason, 'reason')):
            _validate_text(value, label)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('expected revision must be a nonnegative integer')

    def save(self, draft_id, proposal, *, evidence, expected_revision, actor_id, idempotency_key, reason,
             require_unused_evidence=False, operation_intent=None):
        # Snapshot JSON inputs; do not accept Python objects or nonfinite numbers.
        proposal = json.loads(json.dumps(proposal, allow_nan=False))
        if operation_intent is not None:
            operation_intent = json.loads(json.dumps(operation_intent, allow_nan=False))
        if not isinstance(evidence, dict):
            raise TypeError('evidence must map source identities to digests')
        for source_id, value in evidence.items():
            _validate_text(source_id, 'source ID')
            if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('evidence requires a SHA-256 digest')
        evidence = dict(evidence)
        return self._mutate('save', draft_id, expected_revision, actor_id, idempotency_key,
                            reason, proposal, evidence, require_unused_evidence=require_unused_evidence,
                            operation_intent=operation_intent)

    def reject(self, draft_id, *, expected_revision, actor_id, idempotency_key, reason):
        return self._mutate('reject', draft_id, expected_revision, actor_id, idempotency_key, reason)

    def source_used(self, source_id):
        used = self.db.execute('SELECT 1 FROM journal_sources WHERE source_id=? LIMIT 1', (source_id,)).fetchone()
        # ponytail: scan local draft history; index evidence when the queue grows.
        return bool(used) or any(source_id in json.loads(row[0]) for row in
                                self.db.execute('SELECT evidence_json FROM draft_revisions'))

    def _mutate(self, operation, draft_id, expected, actor, key, reason, proposal=None, evidence=None,
                *, require_unused_evidence=False, operation_intent=None):
        self._inputs(draft_id, expected, actor, key, reason)
        request_digest = digest([operation, draft_id, expected, actor, reason,
                                 proposal, evidence, self.policy_version] + ([True] if require_unused_evidence else [])
                                 + ([{'operation_intent_v1': operation_intent}]
                                    if operation_intent is not None and operation == 'save' else []))
        with self.ledger._transaction(write=True):
            prior = self.db.execute('SELECT digest, draft_id, revision FROM review_requests WHERE operation=? AND key=?',
                                    (operation, key)).fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise ValueError('retry key binds a different request')
                return self._get(prior[1], prior[2])
            if require_unused_evidence and any(self.source_used(source_id) for source_id in evidence):
                raise ValueError('duplicate evidence')
            current = self.db.execute('SELECT max(revision) FROM draft_revisions WHERE draft_id=?',
                                      (draft_id,)).fetchone()[0] or 0
            if self._is_posted(draft_id):
                raise ValueError("posted drafts cannot be edited or rejected")
            if current != expected:
                raise ValueError('stale draft revision')
            if current and self._get(draft_id, current).policy_version != self.policy_version:
                raise ValueError('draft policy differs from configured store')
            if operation == 'reject':
                previous = self._get(draft_id, current)
                if previous.state != 'pending':
                    raise ValueError('only pending revisions may be rejected')
                proposal, evidence = json.loads(previous.proposal_json), json.loads(previous.evidence_json)
                operation_intent = (json.loads(previous.operation_intent_json)
                                    if previous.operation_intent_json is not None else None)
            findings = self.validate(proposal, evidence, operation_intent=operation_intent, draft_id=draft_id)
            revision = current + 1
            self.db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)', (
                draft_id, revision, _canonical(proposal), _canonical(evidence), self.policy_version,
                digest([proposal, evidence, self.policy_version] +
                       ([{'operation_intent_v1': operation_intent}] if operation_intent is not None else [])),
                'rejected' if operation == 'reject' else 'pending', reason, actor,
                datetime.now(timezone.utc).isoformat(), _canonical([asdict(f) for f in findings])))
            if operation_intent is not None:
                self.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                                (draft_id, revision, _canonical(operation_intent)))
            self.db.execute('INSERT INTO review_events VALUES (?,?,?)', (draft_id, revision, operation))
            self.db.execute('INSERT INTO review_requests VALUES (?,?,?,?,?)',
                            (operation, key, request_digest, draft_id, revision))
            if self.policy_version in ('cash-v1', 'bill-v1', 'bill-payment-v1', 'invoice-v1', 'invoice-collection-v1', 'advance-v1', 'advance-earning-v1', 'bank-fee-v1'):
                from accounting_harness.operations import economic_claims
                records = []
                for source_id in evidence:
                    try:
                        records.append(self.registry.get(source_id))
                    except KeyError:
                        pass  # Missing evidence already prevents approval.
                for claim in economic_claims(records):
                    prior_claim = self.db.execute('''SELECT draft_id FROM operation_claims
                        WHERE entity_id=? AND event_id=? AND role=?''', claim).fetchone()
                    if prior_claim and prior_claim[0] != draft_id:
                        raise ValueError('duplicate economic event and role')
                    if not prior_claim:
                        self.db.execute('INSERT INTO operation_claims VALUES (?,?,?,?,?)',
                                        (*claim, draft_id, revision))
            return self._get(draft_id, revision)

    def _get(self, draft_id, revision=None):
        row = self.db.execute('SELECT * FROM draft_revisions WHERE draft_id=? AND revision=' +
                              ('(SELECT max(revision) FROM draft_revisions WHERE draft_id=?)' if revision is None else '?'),
                              (draft_id, draft_id if revision is None else revision)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        intent_row = self.db.execute('SELECT intent_json FROM draft_operation_intents WHERE draft_id=? AND revision=?',
                                     (row[0], row[1])).fetchone()
        intent_json = intent_row[0] if intent_row else None
        intent = json.loads(intent_json) if intent_json is not None else None
        current = self.validate(json.loads(row[2]), json.loads(row[3]), operation_intent=intent, draft_id=row[0])
        content = [json.loads(row[2]), json.loads(row[3]), row[4]]
        if intent is not None:
            content += [{'operation_intent_v1': intent}]
        if digest(content) != row[5]:
            current += (Finding('content_digest', 'content_digest', 'stored revision content does not match digest'),)
        if row[4] != self.policy_version:
            current += (Finding('changed_policy', 'policy_version', 'revision uses a different policy'),)
        return DraftRevision(*row[:10], tuple(Finding(**f) for f in json.loads(row[10])), current, intent_json)

    def get(self, draft_id, revision=None):
        with self.ledger._transaction():
            return self._get(draft_id, revision)

    def history(self, draft_id):
        with self.ledger._transaction():
            revisions = self.db.execute('SELECT revision FROM draft_revisions WHERE draft_id=? ORDER BY revision',
                                        (draft_id,)).fetchall()
            return tuple(self._get(draft_id, r[0]) for r in revisions)

    def _is_posted(self, draft_id):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='review_postings'").fetchone():
            return False
        return self.db.execute("SELECT 1 FROM review_postings WHERE draft_id=?", (draft_id,)).fetchone() is not None

    def queue(self, state=None):
        if state not in (None, 'pending', 'rejected'):
            raise ValueError('queue state must be pending or rejected')
        with self.ledger._transaction():
            ids = self.db.execute('SELECT DISTINCT draft_id FROM draft_revisions ORDER BY draft_id').fetchall()
            records = tuple(self._get(row[0]) for row in ids if not self._is_posted(row[0]))
            return tuple(r for r in records if state is None or r.state == state)
