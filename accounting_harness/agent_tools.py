"""Strict JSON capabilities for proposing work; no approval or posting tool."""

import hashlib
import json
import re
from dataclasses import asdict

from accounting_harness.domain.accounts import _validate_text


class ToolError(ValueError):
    """A denied/malformed tool call; safe to route back to human review."""


def _object(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


_TEXT = dict(type='string', minLength=1, pattern=r'\S(?:[\s\S]*\S)?')
_ENTITY = {'entity_id': _TEXT}
_MONEY = dict(type='string', pattern=r'^[0-9]+\.[0-9]{2}$')
_EVIDENCE = dict(type='object', additionalProperties=dict(type='string', pattern=r'^[0-9a-f]{64}$'))
_PROPOSAL = _object(dict(
    id=_TEXT, entity_id=_TEXT, currency=dict(type='string', enum=['USD']),
    effective_date=_TEXT, description=_TEXT,
    source_ids=dict(type='array', minItems=1, items=_TEXT),
    lines=dict(type='array', minItems=2, items=_object(dict(
        account=_TEXT, side=dict(type='string', enum=['debit', 'credit']), amount=_MONEY))),
))
_SCHEMAS = {
    'read_accounts': _object(_ENTITY),
    'get_evidence': _object(dict(_ENTITY, source_id=_TEXT)),
    'validate_proposal': _object(dict(_ENTITY, proposal=_PROPOSAL, evidence=_EVIDENCE)),
    'save_draft': _object(dict(_ENTITY, draft_id=_TEXT, proposal=_PROPOSAL, evidence=_EVIDENCE,
                              expected_revision=dict(type='integer', minimum=0),
                              idempotency_key=_TEXT, reason=_TEXT)),
    'request_review': _object(dict(_ENTITY, draft_id=_TEXT, revision=dict(type='integer', minimum=1))),
}


def _check(schema, value, path='$'):
    """Validate the small JSON-schema subset used above; no external schemas."""
    expected = {'object': dict, 'array': list, 'string': str, 'integer': int}[schema['type']]
    if type(value) is not expected:
        raise ToolError(f'{path}: expected {schema["type"]}')
    if 'enum' in schema and value not in schema['enum']:
        raise ToolError(f'{path}: unsupported value')
    if expected is dict:
        properties = schema.get('properties', {})
        if any(key not in value for key in schema.get('required', [])):
            raise ToolError(f'{path}: missing required fields')
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or key != key.strip():
                raise ToolError(f'{path}: invalid object key')
            field = properties.get(key, schema.get('additionalProperties', False))
            if field is False:
                raise ToolError(f'{path}.{key}: unsupported field')
            _check(field, item, f'{path}.{key}')
    elif expected is list:
        if len(value) < schema.get('minItems', 0):
            raise ToolError(f'{path}: too few items')
        for index, item in enumerate(value):
            _check(schema['items'], item, f'{path}[{index}]')
    elif expected is str:
        if len(value) < schema.get('minLength', 0) or not value.strip() or value != value.strip():
            raise ToolError(f'{path}: requires nonblank unpadded text')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
            raise ToolError(f'{path}: invalid format')
    elif value < schema.get('minimum', 0):
        raise ToolError(f'{path}: value below minimum')


class AgentTools:
    """Constructed by trusted runtime code; callers supply only names and JSON.

    This is not a sandbox for executing untrusted Python. Keep the application,
    ledger connection and this Python object out of model-executable code.
    """
    def __init__(self, store, *, actor_id):
        _validate_text(actor_id, 'agent actor ID')
        self._store = store
        self._actor_id = actor_id
        self._entity_id = store.ledger._empty.catalog.entity_id

    @staticmethod
    def schemas():
        return json.loads(json.dumps(_SCHEMAS))

    def _bound_evidence(self, proposal, evidence):
        if proposal['entity_id'] != self._entity_id:
            raise ToolError('proposal entity is outside runtime scope')
        if set(proposal['source_ids']) != set(evidence):
            raise ToolError('every source must have an exact registered digest')
        for source_id, expected in evidence.items():
            record = self._store.registry.get(source_id)
            actual = hashlib.sha256(record.canonical_content.encode()).hexdigest()
            if record.content_digest != expected or actual != expected:
                raise ToolError('evidence digest conflicts with registered content')

    @staticmethod
    def _revision(record):
        # The stored findings remain available in revision history; current
        # findings control whether this pending item can be reviewed now.
        findings = tuple(dict.fromkeys(record.findings + record.current_findings))
        return dict(draft_id=record.draft_id, revision=record.revision, state=record.state,
                    content_digest=record.content_digest, valid=record.reviewable,
                    findings=[asdict(f) for f in findings], human_review_required=True)

    def call(self, name, arguments):
        if not isinstance(name, str) or name not in _SCHEMAS:
            raise ToolError('tool is not allowed')
        _check(_SCHEMAS[name], arguments)
        # Freeze the validated JSON before touching storage.
        args = json.loads(json.dumps(arguments, allow_nan=False))
        if args.pop('entity_id') != self._entity_id:
            raise ToolError('entity is outside runtime scope')
        try:
            if name == 'read_accounts':
                return dict(entity_id=self._entity_id,
                            accounts=[asdict(a) for a in self._store.ledger._empty.catalog.list_accounts()])
            if name == 'get_evidence':
                record = self._store.registry.get(args['source_id'])
                return dict(entity_id=record.entity_id, source_id=record.document_id,
                            content_digest=record.content_digest, document=json.loads(record.canonical_content))
            if name in ('validate_proposal', 'save_draft'):
                self._bound_evidence(args['proposal'], args['evidence'])
                if name == 'validate_proposal':
                    findings = self._store.validate(args['proposal'], args['evidence'])
                    return dict(valid=not findings, findings=[asdict(f) for f in findings],
                                human_review_required=True)
                return self._revision(self._store.save(**args, actor_id=self._actor_id))
            # request_review acknowledges the pending queue item already
            # committed with save_draft; it cannot grant approval or post.
            with self._store.ledger._transaction():
                record = self._store._get(args['draft_id'])
                if (record.revision != args['revision'] or record.state != 'pending'
                        or self._store._is_posted(record.draft_id)):
                    raise ToolError('review request requires the current pending unposted revision')
                return self._revision(record)
        except (ValueError, TypeError, KeyError) as error:
            if isinstance(error, ToolError):
                raise
            raise ToolError(str(error)) from error
