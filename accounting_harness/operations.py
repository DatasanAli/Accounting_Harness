"""Two immediate-cash templates. Facts propose recognition; humans authorize posting."""

import json

from accounting_harness.domain.accounts import _validate_text
from accounting_harness.domain.journal import Finding
from accounting_harness.sources import _content


def _cash_facts(records):
    if len(records) != 2 or len({r.document_id for r in records}) != 2:
        raise ValueError('cash policy requires two distinct cash and recognition documents')
    documents = []
    for record in records:
        document = dict(json.loads(record.canonical_content), entity_id=record.entity_id,
                        document_id=record.document_id)
        _content(document, record.entity_id)
        if document['schema_version'] != 2:
            raise ValueError('cash policy requires typed schema v2 facts; raw receipts are insufficient')
        documents.append(document)
    cash = next((d for d in documents if d['kind'] == 'cash_movement'), None)
    recognition = next((d for d in documents if d['kind'] in ('incurred_expense', 'service_completion')), None)
    if cash is None or recognition is None:
        raise ValueError('cash movement and separate completion/incurrence evidence are required')
    for field in ('entity_id', 'event_id', 'counterparty_id', 'currency', 'amount', 'document_date'):
        if cash[field] != recognition[field]:
            raise ValueError(f'cash and recognition evidence differ in {field}')
    expense = recognition['kind'] == 'incurred_expense'
    if (cash['direction'], cash['purpose']) != (('out', 'incurred_expense') if expense else ('in', 'earned_service')):
        raise ValueError('cash direction/purpose does not support this recognition')
    recognition_date = recognition['incurred_date' if expense else 'completion_date']
    if cash['document_date'] != recognition_date:
        raise ValueError('cash and recognition dates must match for immediate-cash policy')
    debit, credit = (recognition['expense_account'], '1000') if expense else ('1000', '4000')
    lines = [dict(account=debit, side='debit', amount=cash['amount']),
             dict(account=credit, side='credit', amount=cash['amount'])]
    return cash, recognition, lines


def validate_cash_evidence(proposal, records):
    """Reconstruct allowed accounting directly from facts, including forged drafts."""
    try:
        cash, recognition, lines = _cash_facts(records)
    except (ValueError, TypeError, KeyError) as error:
        return (Finding('unsupported_cash_evidence', 'source_ids', str(error)),)
    findings = []
    expected = dict(entity_id=cash['entity_id'], currency=cash['currency'],
                    effective_date=cash['document_date'], lines=lines)
    for field, value in expected.items():
        if proposal.get(field) != value:
            findings.append(Finding('cash_mapping', field, 'proposal differs from the evidenced cash recognition'))
    sources = proposal.get('source_ids')
    if (not isinstance(sources, list) or len(sources) != 2
            or any(not isinstance(s, str) for s in sources)
            or set(sources) != {cash['document_id'], recognition['document_id']}):
        findings.append(Finding('cash_evidence_binding', 'source_ids', 'bind exactly the cash and recognition facts'))
    return tuple(findings)


def _proposal(registry, entry_id, cash_source_id, recognition_source_id, kind):
    _validate_text(entry_id, 'entry ID')
    records = (registry.get(cash_source_id), registry.get(recognition_source_id))
    cash, recognition, lines = _cash_facts(records)
    if (cash['document_id'] != cash_source_id or recognition['document_id'] != recognition_source_id
            or recognition['kind'] != kind):
        raise ValueError('sources do not match the selected operation and evidence roles')
    return (dict(id=entry_id, entity_id=cash['entity_id'], currency=cash['currency'],
                 effective_date=cash['document_date'], description='Synthetic immediate cash: ' + cash['event_id'],
                 source_ids=[cash_source_id, recognition_source_id], lines=lines),
            {r.document_id: r.content_digest for r in records})


def cash_expense_proposal(registry, *, entry_id, cash_source_id, recognition_source_id):
    return _proposal(registry, entry_id, cash_source_id, recognition_source_id, 'incurred_expense')


def earned_cash_proposal(registry, *, entry_id, cash_source_id, recognition_source_id):
    return _proposal(registry, entry_id, cash_source_id, recognition_source_id, 'service_completion')


def economic_claims(records):
    """Event/role identity is shared across accounting policies, not template names.

    Claims conservatively retain evidence use even after rejection. A new source
    identity cannot recognize the same expense or service event a second time.
    """
    roles = {'cash_movement': 'cash_movement', 'incurred_expense': 'expense_recognition',
             'service_completion': 'service_revenue_recognition'}
    claims = []
    for record in records:
        document = json.loads(record.canonical_content)
        if document.get('schema_version') == 2 and document.get('kind') in roles:
            claims.append((record.entity_id, document['event_id'], roles[document['kind']]))
    return tuple(claims)
