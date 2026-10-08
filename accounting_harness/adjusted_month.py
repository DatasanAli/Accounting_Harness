"""Synthetic fixture assembly, never an authenticated input or posting interface.

The original reference remains unchanged. This separately identified operational
variant purchases insurance on January 1 to meet the delivered coverage policy.
Only owner capital, drawings and the purchase use the trusted core fixture
primitive; all supported operations use separate simulated approval/post calls.
"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.advances import AdvancesService
from accounting_harness.approval import ReviewApplication
from accounting_harness.operations import cash_expense_proposal
from accounting_harness.payables import PayablesService
from accounting_harness.prepaid import PrepaidService
from accounting_harness.receivables import ReceivablesService
from accounting_harness.review import SQLiteReviewStore, digest
from accounting_harness.sources import _content

FIXTURE_ID = 'adjusted-month-insurance-jan1-v1'
REFERENCE = Path(__file__).resolve().parents[1] / 'data/fixtures/service-business-month.json'
DATE_VARIANT = ('New synthetic insurance purchase on 2026-01-01; original T03 remains 2026-01-03. '
                'January 31 totals agree; January 1–2 cutoffs intentionally differ.')
CORE_ACTOR = 'synthetic-adjusted-month-core'
PROPOSER = 'synthetic-adjusted-month-template'
REVIEWER = 'synthetic-adjusted-month-reviewer'
POSTER = 'synthetic-adjusted-month-poster'
TRUSTED = ('T01', 'T03', 'T09')
REVIEWED = ('T02', 'T04', 'T05', 'T06', 'T07', 'T08', 'A01', 'A02')


def fixture_inputs():
    """Fixed facts, with scoped identities distinct from the original reference."""
    raw = REFERENCE.read_bytes()
    reference = json.loads(raw)
    entity = reference['entity']['id']
    transactions = {t['id']: t for t in reference['transactions']}
    documents, trusted = {}, {}

    def fact(alias, transaction, kind, party, **extra):
        t = transactions[transaction]
        date = '2026-01-01' if transaction == 'T03' else t['date']
        document = dict(schema_version=1 if kind == 'receipt' else 2, synthetic=True,
            entity_id=entity, document_id=FIXTURE_ID + ':' + alias, kind=kind,
            document_date=date, currency='USD', amount=t['lines'][0]['amount'],
            counterparty='Fictional ' + party, description=t['description'])
        if kind not in ('receipt', 'prepaid_coverage'):
            document.update(event_id=FIXTURE_ID + ':' + transaction,
                            counterparty_id=FIXTURE_ID + ':' + party)
        document.update(extra)
        documents[alias] = document
        return document

    for name, party in [('T01', 'owner'), ('T03', 'insurer'), ('T09', 'owner')]:
        doc = fact(name, name, 'receipt', party)
        t = transactions[name]
        trusted[name] = dict(id=FIXTURE_ID + ':' + name, entity_id=entity, currency='USD',
            effective_date=doc['document_date'], description='Trusted core synthetic fixture: ' + t['description'],
            source_ids=[doc['document_id']], lines=t['lines'])
    fact('T02-cash', 'T02', 'cash_movement', 'landlord', direction='out', purpose='incurred_expense')
    fact('T02-incurrence', 'T02', 'incurred_expense', 'landlord', expense_account='5000', incurred_date='2026-01-02')
    fact('T04-invoice', 'T04', 'customer_invoice', 'customer', invoice_number=FIXTURE_ID + ':invoice', due_date='2026-01-31')
    fact('T04-completion', 'T04', 'service_completion', 'customer', completion_date='2026-01-10')
    fact('T05-cash', 'T05', 'cash_movement', 'customer', direction='in', purpose='settlement')
    fact('T06-bill', 'T06', 'vendor_bill', 'software-vendor', bill_number=FIXTURE_ID + ':bill', due_date='2026-01-31')
    fact('T06-incurrence', 'T06', 'incurred_expense', 'software-vendor', expense_account='5100', incurred_date='2026-01-18')
    fact('T07-cash', 'T07', 'cash_movement', 'software-vendor', direction='out', purpose='settlement')
    fact('T08-prepayment', 'T08', 'customer_prepayment', 'advance-customer', contract_id=FIXTURE_ID + ':contract')
    fact('T08-cash', 'T08', 'cash_movement', 'advance-customer', direction='in', purpose='customer_advance')
    fact('A01-coverage', 'T03', 'prepaid_coverage', 'insurer', original_journal_id=trusted['T03']['id'],
         original_source_id=documents['T03']['document_id'], coverage_start='2026-01-01', coverage_end='2026-12-31',
         allocation_policy='equal-months-cents-v1', description='Explicit synthetic annual coverage; January 1 purchase variant.')
    fact('A02-completion', 'A02', 'advance_completion', 'advance-customer', contract_id=FIXTURE_ID + ':contract',
         completion_date='2026-01-31')
    return dict(fixture_id=FIXTURE_ID, reference_sha256=hashlib.sha256(raw).hexdigest(),
                date_variant=DATE_VARIANT, documents=documents, trusted=trusted)


def _preflight(workspace, registry, ledger, store, inputs):
    """Refuse mixed actuals or changed inputs before making fixture mutations."""
    documents = {d['document_id']: d for d in inputs['documents'].values()}
    existing = {r.document_id: r for r in registry.list_documents()}
    anchor = inputs['documents']['T01']['document_id']
    if anchor not in existing and (ledger.snapshot.entries or set(existing) - set(workspace.sources)):
        raise ValueError('adjusted fixture requires an isolated workspace without unrelated journals or fixture identity')
    for source_id, record in existing.items():
        if source_id in workspace.sources:
            continue
        if source_id not in documents or record.canonical_content != _content(documents[source_id], record.entity_id)[1]:
            raise ValueError('adjusted fixture identity or payload differs from registered evidence')
    allowed = {p['id'] for p in inputs['trusted'].values()}
    for name in REVIEWED:
        row = store.db.execute('''SELECT p.journal_id FROM review_postings p
            JOIN review_requests r ON r.draft_id=p.draft_id AND r.operation='save'
            JOIN approval_requests a ON a.approval_id=p.approval_id
            JOIN approved_post_requests q ON q.draft_id=p.draft_id
            WHERE r.key=? AND a.key=? AND q.key=?''',
            (FIXTURE_ID + ':' + name + ':prepare', FIXTURE_ID + ':' + name + ':approve',
             FIXTURE_ID + ':' + name + ':post')).fetchone()
        if row:
            allowed.add(row[0])
    if any(e.id not in allowed for e in ledger.snapshot.entries):
        raise ValueError('adjusted fixture refuses unrelated journals in a populated workspace')
    for name, proposal in inputs['trusted'].items():
        if any(e.id == proposal['id'] for e in ledger.snapshot.entries):
            receipt = ledger.receipt(proposal['id'])
            if receipt.entry != ledger._validate_entry(proposal) or receipt.actor_id != CORE_ACTOR:
                raise ValueError('trusted fixture journal differs from expected payload')


def build_adjusted_month(workspace):
    """Populate a fresh Workspace, or resume this exact fixed fixture there.

    Returns a JSON-safe reference map keyed by the published T/A labels. Those
    labels are not journal IDs. Reopening uses immutable source/draft/approval/
    posting receipts; no fixture progress file or fabricated subsidiary effects.
    """
    inputs = fixture_inputs()
    # Bind all planned input facts (including not-yet-registered ones) in the
    # first immutable source. A changed sequence cannot silently resume a prefix.
    payload_digest = digest(inputs)
    inputs['documents']['T01']['description'] += ' Fixture payload SHA-256: ' + payload_digest
    documents = inputs['documents']
    traces = {}
    with workspace.storage() as (registry, ledger, store, _, _):
        _preflight(workspace, registry, ledger, store, inputs)

        def enroll(*aliases):
            for alias in aliases:
                document = documents[alias]
                registry.register(document, actor_id=PROPOSER)
                ledger.enroll_source(registry, document['document_id'], actor_id=PROPOSER)

        def source(alias):
            return documents[alias]['document_id']

        def core(name):
            enroll(name)
            receipt = ledger.admit(inputs['trusted'][name], actor_id=CORE_ACTOR,
                                   idempotency_key=FIXTURE_ID + ':' + name + ':core')
            traces[name] = dict(boundary='trusted_core_fixture', journal_id=receipt.entry.id,
                sources={s: registry.get(s).content_digest for s in receipt.entry.source_ids},
                draft_id=None, revision=None, draft_digest=None, approval_id=None, subsidiary_id=None)

        def reviewed(name, draft):
            selected = SQLiteReviewStore(ledger, registry, policy_version=draft.policy_version)
            app = ReviewApplication(selected)
            # Explicitly separate simulated human approval from application posting.
            approval = app.approve(draft.draft_id, revision=draft.revision,
                confirmed_digest=draft.content_digest, actor_id=REVIEWER,
                idempotency_key=FIXTURE_ID + ':' + name + ':approve')
            receipt = app.post(approval.approval_id, actor_id=POSTER,
                              idempotency_key=FIXTURE_ID + ':' + name + ':post')
            intent = json.loads(draft.operation_intent_json) if draft.operation_intent_json else {}
            traces[name] = dict(boundary='simulated_human_approval', journal_id=receipt.entry.id,
                sources=json.loads(draft.evidence_json), draft_id=draft.draft_id, revision=draft.revision,
                draft_digest=draft.content_digest, approval_id=approval.approval_id,
                subsidiary_id=intent.get('invoice_id', intent.get('bill_id', intent.get('advance_id'))))

        def request(name):
            return dict(expected_revision=0, actor_id=PROPOSER, idempotency_key=FIXTURE_ID + ':' + name + ':prepare')

        core('T01')
        enroll('T02-cash', 'T02-incurrence')
        cash = SQLiteReviewStore(ledger, registry, policy_version='cash-v1')
        proposal, evidence = cash_expense_proposal(registry, entry_id=FIXTURE_ID + ':T02',
            cash_source_id=source('T02-cash'), recognition_source_id=source('T02-incurrence'))
        reviewed('T02', cash.save(FIXTURE_ID + ':T02-draft', proposal, evidence=evidence, **request('T02'),
            reason='Synthetic reference rent; separate simulated human review', require_unused_evidence=True))
        core('T03')
        enroll('T04-invoice', 'T04-completion')
        receivables = ReceivablesService(ledger, registry)
        reviewed('T04', receivables.propose_invoice(invoice_source_id=source('T04-invoice'),
            completion_source_id=source('T04-completion'), **request('T04')))
        enroll('T05-cash')
        reviewed('T05', receivables.propose_collection(invoice_id=traces['T04']['subsidiary_id'],
            cash_source_id=source('T05-cash'), **request('T05')))
        enroll('T06-bill', 'T06-incurrence')
        payables = PayablesService(ledger, registry)
        reviewed('T06', payables.propose_bill(bill_source_id=source('T06-bill'),
            incurrence_source_id=source('T06-incurrence'), **request('T06')))
        enroll('T07-cash')
        reviewed('T07', payables.propose_payment(bill_id=traces['T06']['subsidiary_id'],
            cash_source_id=source('T07-cash'), **request('T07')))
        enroll('T08-prepayment', 'T08-cash')
        advances = AdvancesService(ledger, registry)
        reviewed('T08', advances.propose_advance(prepayment_source_id=source('T08-prepayment'),
            cash_source_id=source('T08-cash'), **request('T08')))
        core('T09')
        enroll('A01-coverage')
        reviewed('A01', PrepaidService(ledger, registry).propose(coverage_source_id=source('A01-coverage'),
            allocation_month='2026-01', **request('A01')))
        enroll('A02-completion')
        reviewed('A02', advances.propose_earning(advance_id=traces['T08']['subsidiary_id'],
            completion_source_id=source('A02-completion'), **request('A02')))
    return dict(fixture_id=FIXTURE_ID, reference_sha256=inputs['reference_sha256'],
                payload_digest=payload_digest, date_variant=DATE_VARIANT, transactions=traces)


def demo_adjusted_month():
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='accounting-adjusted-month-') as directory:
        workspace = Workspace(directory)
        result = build_adjusted_month(workspace)
        state = workspace.state()
        expected = json.loads(REFERENCE.read_text())['expected']['adjusted_trial_balance']
        actual = state['trial_balance']
        assert [{k: row[k] for k in ('account', 'debit', 'credit')} for row in actual['rows']] == expected['rows']
        assert actual['total_debits'] == actual['total_credits'] == '13300.00'
        assert state['journal_count'] == 11
        assert all(state[k]['unassigned_control_cents'] == 0 for k in ('payables', 'receivables', 'advances', 'prepaid'))
        assert build_adjusted_month(Workspace(directory)) == result
        assert workspace.state()['journal_count'] == 11
        print(FIXTURE_ID + ': ' + DATE_VARIANT)
        print('11 journals; total debits 13300.00 / credits 13300.00 USD; subsidiary residuals: 0')
        for row in actual['rows']:
            print(row['account'], row['name'], 'debit', row['debit'], 'credit', row['credit'])
        for name, trace in result['transactions'].items():
            print(name, trace['boundary'], 'sources', ', '.join(trace['sources']),
                  'draft', trace['draft_id'], 'approval', trace['approval_id'], 'journal', trace['journal_id'])
        print('trusted_core_fixture: owner contribution, drawings and purchase are synthetic setup, not authenticated input.')
        print('Eight separate simulated reviewer approvals; exact reopen/retry preserves all records. No close or model calls.')
