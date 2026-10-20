"""Reviewed owner contribution, owner drawing and prepaid-purchase cash entries.

A typed cash movement plus a separate operator classification fact reconstruct a
fixed two-line journal. Descriptions never select accounts; posting still needs a
separate human approval of the exact revision.
"""
import json

from accounting_harness.domain.journal import Finding
from accounting_harness.domain.money import Money
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest

POLICY = 'nonoperating-cash-v1'
# classification -> (cash direction, debit account, credit account)
MAPPING = {'owner_contribution': ('in', '1000', '3000'), 'owner_draw': ('out', '3100', '1000'),
           'prepaid_insurance': ('out', '1200', '1000')}
LABELS = {'owner_contribution': 'Owner contribution', 'owner_draw': 'Owner drawing',
          'prepaid_insurance': 'Prepaid insurance purchase'}


def _anchored(store, source_id):
    record = store.registry.get(source_id)
    anchor = store.db.execute('SELECT content_digest,canonical_content FROM source_enrollments WHERE source_id=?', (source_id,)).fetchone()
    if anchor != (record.content_digest, record.canonical_content):
        raise ValueError('evidence must be registered and enrolled with unchanged content')
    return record


def operation(store, cash_source_id, basis_source_id):
    """Exact draft identity, strict intent, journal and evidence from the two facts."""
    if cash_source_id == basis_source_id:
        raise ValueError('cash movement and classification basis must be distinct documents')
    records = [_anchored(store, source_id) for source_id in (cash_source_id, basis_source_id)]
    cash, basis = (json.loads(r.canonical_content) for r in records)
    if (cash.get('schema_version'), cash.get('kind'), basis.get('schema_version'), basis.get('kind')) != (2, 'cash_movement', 2, 'nonoperating_cash_basis'):
        raise ValueError('requires a schema-v2 cash movement and a separate nonoperating cash basis')
    for field in ('currency', 'event_id', 'counterparty_id', 'amount', 'document_date'):
        if cash[field] != basis[field]:
            raise ValueError(f'cash and classification evidence differ in {field}')
    classification = basis['classification']
    direction, debit, credit = MAPPING[classification]
    # The explicit classification fact, not a memo or description, selects the accounts.
    if (cash['direction'], cash['purpose']) != (direction, classification):
        raise ValueError('cash direction/purpose does not match the explicit classification')
    entity, amount = store.registry._entity_id, Money.parse(cash['amount'])
    claim = digest([entity, POLICY, cash['event_id']])  # One deterministic draft per entity/event.
    intent = dict(schema_version=1, kind='nonoperating_cash', classification=classification, event_id=cash['event_id'],
                  counterparty_id=cash['counterparty_id'], direction=direction, amount_cents=amount.cents,
                  effective_date=cash['document_date'], debit_account=debit, credit_account=credit,
                  evidence_roles=dict(cash=cash_source_id, basis=basis_source_id))
    proposal = dict(id='journal:nonoperating-cash:' + claim, entity_id=entity, currency='USD', effective_date=cash['document_date'],
                    description=LABELS[classification] + ': ' + cash['event_id'], source_ids=[cash_source_id, basis_source_id],
                    lines=[dict(account=debit, side='debit', amount=str(amount)), dict(account=credit, side='credit', amount=str(amount))])
    return 'nonoperating-cash:' + claim, intent, proposal, {r.document_id: r.content_digest for r in records}


def validate_nonoperating(store, proposal, records, intent, draft_id):
    """Reconstruct at save, review and final seal; forged journals or intents never validate."""
    try:
        if type(intent) is not dict or type(intent.get('evidence_roles')) is not dict:
            raise ValueError('nonoperating cash requires its strict operation intent')
        expected_id, expected_intent, expected_proposal, evidence = operation(store, intent['evidence_roles']['cash'], intent['evidence_roles']['basis'])
        # Canonical comparison keeps types strict (True is not 1 cent).
        if draft_id != expected_id or _canonical(intent) != _canonical(expected_intent) or _canonical(proposal) != _canonical(expected_proposal):
            raise ValueError('intent, identity or journal differs from the evidenced classification')
        if {r.document_id: r.content_digest for r in records} != evidence:
            raise ValueError('bind exactly the cash movement and its classification basis')
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_nonoperating_cash', 'operation_intent', str(error)),)
    return ()


def prepare(store, *, cash_source_id, basis_source_id, expected_revision, actor_id, idempotency_key):
    draft_id, intent, proposal, evidence = operation(store, cash_source_id, basis_source_id)
    if expected_revision:
        # A correction may keep its own draft's evidence, never evidence another draft or journal holds.
        own = {s for (bound,) in store.db.execute('SELECT evidence_json FROM draft_revisions WHERE draft_id=?', (draft_id,)) for s in json.loads(bound)}
        if any(s not in own and store.source_used(s) for s in evidence):
            raise ValueError('duplicate evidence')
    # A first preparation needs unused evidence; a revision reuses its own draft's evidence.
    return store.save(draft_id, proposal, evidence=evidence, operation_intent=intent, expected_revision=expected_revision,
                      actor_id=actor_id, idempotency_key=idempotency_key, require_unused_evidence=expected_revision == 0,
                      reason='Explicit nonoperating cash classification; separate human confirmation required')


def demo_owner_prepaid_cash():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='accounting-owner-prepaid-') as directory:
        workspace = Workspace(directory)
        drafts = []
        for event, classification, direction, amount, party in (('capital', 'owner_contribution', 'in', '10000.00', 'Fictional owner'),
                ('drawing', 'owner_draw', 'out', '200.00', 'Fictional owner'), ('insurance', 'prepaid_insurance', 'out', '1200.00', 'Fictional insurer')):
            common = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id, currency='USD', document_date='2026-01-01',
                          amount=amount, event_id=event, counterparty_id=party.lower().replace(' ', '-'), counterparty=party)
            for document in (dict(common, document_id=event + '-cash', kind='cash_movement', direction=direction, purpose=classification,
                                  description='Synthetic recorded cash movement; sends no money'),
                             dict(common, document_id=event + '-basis', kind='nonoperating_cash_basis', classification=classification,
                                  description='Explicit operator classification')):
                workspace.action('operation-sources', dict(document=document))
            drafts.append(workspace.action('nonoperating-cash-proposals', dict(cash_source_id=event + '-cash', basis_source_id=event + '-basis', expected_revision=0)))
        assert workspace.state()['journal_count'] == 0
        print('Three evidenced drafts prepared (nonoperating-cash-v1); no journals before human approval.')
        receipts = [workspace.action('approve-post', dict(draft_id=d['draft_id'], revision=d['revision'], confirmed_digest=d['content_digest'])) for d in drafts]
        rows = lambda: {r['account']: (r['debit'], r['credit']) for r in workspace.state()['trial_balance']['rows']}
        balances = rows()
        assert (balances['1000'], balances['3000'], balances['3100'], balances['1200']) == (('8600.00', '0.00'), ('0.00', '10000.00'), ('200.00', '0.00'), ('1200.00', '0.00'))
        print('Three separate approvals: Cash 8600.00 debit; Capital 10000.00 credit; Drawings 200.00 debit; Prepaid 1200.00 debit.')
        coverage = dict(schema_version=2, synthetic=True, entity_id=workspace.catalog.entity_id, currency='USD', document_date='2026-01-01',
            amount='1200.00', counterparty='Fictional insurer', description='Synthetic annual coverage', kind='prepaid_coverage',
            document_id='annual-coverage', original_journal_id=receipts[2]['journal_id'], original_source_id='insurance-cash',
            coverage_start='2026-01-01', coverage_end='2026-12-31', allocation_policy='equal-months-cents-v1')
        workspace.action('operation-sources', dict(document=coverage))
        consumption = workspace.action('prepaid-proposals', dict(coverage_source_id='annual-coverage', allocation_month='2026-01', expected_revision=0))
        workspace.action('approve-post', dict(draft_id=consumption['draft_id'], revision=consumption['revision'], confirmed_digest=consumption['content_digest']))
        reopened = Workspace(directory)
        assert reopened.action('approve-post', dict(draft_id=drafts[0]['draft_id'], revision=1, confirmed_digest=drafts[0]['content_digest'])) == receipts[0]
        workspace, balances = reopened, rows()
        assert (balances['5200'], balances['1200'], balances['1000']) == (('100.00', '0.00'), ('1100.00', '0.00'), ('8600.00', '0.00'))
        assert workspace.state()['journal_count'] == 4
        print('Separate supported January consumption: Insurance Expense 100.00; Prepaid 1100.00 remaining; Cash 8600.00 unchanged.')
        print('Restart and exact retry keep four journals. Descriptions never select accounts; zero model calls.')
