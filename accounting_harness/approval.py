"""Trusted local application approval/posting; never exposed as agent tools."""

import hashlib
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone

from accounting_harness.domain.accounts import _validate_text
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest, protect_table


def approved_source_content(db, registry, source_id, approval_id):
    """Capture the original evidenced content, including initial-context sources."""
    row = db.execute('SELECT content_digest, canonical_content FROM source_enrollments WHERE source_id=?',
                     (source_id,)).fetchone()
    if row is None:
        source = registry.get(source_id)
        row = (source.content_digest, source.canonical_content)
    binding = json.loads(db.execute('SELECT binding_json FROM approvals WHERE approval_id=?',
                                    (approval_id,)).fetchone()[0])
    expected = binding['evidence'][source_id]
    if row[0] != expected or hashlib.sha256(row[1].encode()).hexdigest() != expected:
        raise ValueError('source differs from approved evidence')
    return row[1]


@dataclass(frozen=True, slots=True)
class Approval:
    approval_id: str
    draft_id: str
    revision: int
    binding_json: str
    actor_id: str
    recorded_at: str


class ReviewApplication:
    def __init__(self, store):
        self.store = store
        self.ledger = store.ledger
        self.db = store.db
        # Initialization may join a service-owned write transaction so schema setup rolls back together.
        with (nullcontext() if self.db.in_transaction else self.ledger._transaction(write=True)):
            self._initialize()

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='approval_schema'").fetchone():
            if self.db.execute('SELECT version FROM approval_schema').fetchall() != [(1,)]:
                raise ValueError('unsupported approval schema version')
            return
        self.db.execute('CREATE TABLE approval_schema (version INTEGER PRIMARY KEY) STRICT')
        self.db.execute('INSERT INTO approval_schema VALUES (1)')
        self.db.execute("""CREATE TABLE approvals (
            approval_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
            binding_json TEXT NOT NULL, actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
            UNIQUE(draft_id, revision),
            FOREIGN KEY(draft_id, revision) REFERENCES draft_revisions(draft_id, revision)
        ) STRICT, WITHOUT ROWID""")
        self.db.execute("""CREATE TABLE approval_requests (
            key TEXT PRIMARY KEY, digest TEXT NOT NULL,
            approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id)
        ) STRICT, WITHOUT ROWID""")
        self.db.execute("""CREATE TABLE review_postings (
            draft_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id)
        ) STRICT, WITHOUT ROWID""")
        self.db.execute("""CREATE TABLE approved_post_requests (
            key TEXT PRIMARY KEY, digest TEXT NOT NULL,
            draft_id TEXT NOT NULL UNIQUE REFERENCES review_postings(draft_id)
        ) STRICT, WITHOUT ROWID""")
        for table, conflict in (
            ('approval_schema', '1'),
            ('approvals', 'approval_id=NEW.approval_id OR (draft_id=NEW.draft_id AND revision=NEW.revision)'),
            ('approval_requests', 'key=NEW.key OR approval_id=NEW.approval_id'),
            ('review_postings', 'draft_id=NEW.draft_id OR approval_id=NEW.approval_id OR journal_id=NEW.journal_id'),
            ('approved_post_requests', 'key=NEW.key OR draft_id=NEW.draft_id'),
        ):
            protect_table(self.db, table, conflict)
        # Protect posted drafts even through old Step 08 service code.
        self.db.execute("""CREATE TRIGGER posted_draft_sealed BEFORE INSERT ON draft_revisions
            WHEN EXISTS (SELECT 1 FROM review_postings WHERE draft_id=NEW.draft_id)
            BEGIN SELECT RAISE(ABORT, 'posted draft is sealed'); END""")

    def _binding(self, revision):
        return _canonical(dict(entity_id=self.ledger._empty.catalog.entity_id,
                               draft_id=revision.draft_id, revision=revision.revision,
                               revision_digest=revision.content_digest,
                               evidence=json.loads(revision.evidence_json),
                               policy_version=revision.policy_version, action='post',
                               ledger_context=self.ledger._context))

    def _approval(self, approval_id):
        row = self.db.execute('SELECT * FROM approvals WHERE approval_id=?', (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return Approval(*row)

    def approve(self, draft_id, *, revision, confirmed_digest, actor_id, idempotency_key):
        self.store._inputs(draft_id, revision, actor_id, idempotency_key, 'approve')
        _validate_text(confirmed_digest, 'confirmed digest')
        request_digest = digest([draft_id, revision, confirmed_digest, actor_id, self.store.policy_version, 'post'])
        with self.ledger._transaction(write=True):
            prior = self.db.execute('SELECT digest, approval_id FROM approval_requests WHERE key=?',
                                    (idempotency_key,)).fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise ValueError('approval retry key binds a different request')
                return self._approval(prior[1])
            current = self.store._get(draft_id)
            if current.revision != revision or current.content_digest != confirmed_digest:
                raise ValueError('human confirmation does not match current revision')
            if not current.reviewable or self.store._is_posted(draft_id):
                raise ValueError('only a valid pending revision may be approved')
            if self.db.execute('SELECT 1 FROM approvals WHERE draft_id=? AND revision=?',
                               (draft_id, revision)).fetchone():
                raise ValueError('revision already approved; use original retry key')
            binding = self._binding(current)
            approval_id = digest([binding, actor_id])
            self.db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?)',
                            (approval_id, draft_id, revision, binding, actor_id,
                             datetime.now(timezone.utc).isoformat()))
            self.db.execute('INSERT INTO approval_requests VALUES (?,?,?)',
                            (idempotency_key, request_digest, approval_id))
            return self._approval(approval_id)

    def post(self, approval_id, *, actor_id, idempotency_key):
        for value, label in ((approval_id, 'approval ID'), (actor_id, 'actor ID'), (idempotency_key, 'retry key')):
            _validate_text(value, label)
        request_digest = digest([approval_id, actor_id, self.store.policy_version, 'post-approved-v1'])
        with self.ledger._transaction(write=True):
            prior = self.db.execute('''SELECT r.digest, p.journal_id FROM approved_post_requests r
                JOIN review_postings p USING(draft_id) WHERE r.key=?''', (idempotency_key,)).fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise ValueError('posting retry key binds a different request')
                return self.ledger._receipt(prior[1])
            approval = self._approval(approval_id)
            current = self.store._get(approval.draft_id)
            if self.store._is_posted(current.draft_id):
                raise ValueError('draft is already posted')
            if (not current.reviewable or current.revision != approval.revision
                    or self._binding(current) != approval.binding_json):
                raise ValueError('approval is stale or evidence/policy/validation changed')
            # The existing ledger primitive rechecks period, accounts, sources,
            # balance and integer storage limits inside this same transaction.
            entry = self.ledger._validate_entry(json.loads(current.proposal_json))
            if current.policy_version in ('bill-v1', 'bill-payment-v1'):
                from accounting_harness.payables import prepare_payable_post
                prepare_payable_post(self.store, approval, current, entry)
            if current.policy_version in ('invoice-v1', 'invoice-collection-v1'):
                from accounting_harness.receivables import prepare_receivable_post
                prepare_receivable_post(self.store, approval, current, entry)
            if current.policy_version in ('advance-v1', 'advance-earning-v1'):
                from accounting_harness.advances import prepare_advance_post
                prepare_advance_post(self.store, approval, current, entry)
            receipt = self.ledger._store_entry(entry, actor_id)
            self.db.execute('INSERT INTO review_postings VALUES (?,?,?)',
                            (current.draft_id, approval_id, entry.id))
            self.db.execute('INSERT INTO approved_post_requests VALUES (?,?,?)',
                            (idempotency_key, request_digest, current.draft_id))
            return receipt

    def status(self, draft_id):
        with self.ledger._transaction():
            revision = self.store._get(draft_id)
            if self.store._is_posted(draft_id):
                return 'posted'
            if revision.state == 'rejected':
                return 'rejected'
            if not revision.reviewable:
                return 'pending'
            if self.db.execute('SELECT 1 FROM approvals WHERE draft_id=? AND revision=?',
                               (draft_id, revision.revision)).fetchone():
                return 'approved'
            return 'awaiting_approval'

    def trace(self, draft_id):
        with self.ledger._transaction():
            row = self.db.execute('SELECT approval_id, journal_id FROM review_postings WHERE draft_id=?',
                                  (draft_id,)).fetchone()
            if row is None:
                raise KeyError(draft_id)
            approval = self._approval(row[0])
            revisions = self.db.execute('SELECT revision FROM draft_revisions WHERE draft_id=? ORDER BY revision',
                                        (draft_id,)).fetchall()
            return dict(revisions=tuple(self.store._get(draft_id, r[0]) for r in revisions),
                        approvals=tuple(Approval(*r) for r in self.db.execute(
                            'SELECT * FROM approvals WHERE draft_id=? ORDER BY revision', (draft_id,)).fetchall()),
                        approval=approval, receipt=self.ledger._receipt(row[1]),
                        evidence=tuple(self.store.registry.get(source_id)
                                       for source_id in json.loads(approval.binding_json)['evidence']))
