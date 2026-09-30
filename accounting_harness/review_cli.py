"""Explicit local operator confirmation; authenticated roles come in Step 29."""

import json
import sqlite3
from pathlib import Path

from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.accounts import Account, AccountCatalog
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.sources import SQLiteSourceRegistry


def review_post(args):
    # Read-only open prevents misspelled paths from silently creating databases.
    with sqlite3.connect(Path(args.ledger).resolve().as_uri() + '?mode=ro', uri=True) as db:
        context = json.loads(db.execute('SELECT canonical FROM ledger_context WHERE singleton=1').fetchone()[0])
    if not Path(args.registry).is_file():
        raise ValueError('source registry must already exist')
    catalog = AccountCatalog(**dict(context['catalog'], accounts=[Account(**a) for a in context['catalog']['accounts']]))
    with SQLiteLedger(args.ledger, catalog, context['period_start'], context['period_end'],
                      known_source_ids=set(context['known_source_ids'])) as ledger:
        with SQLiteSourceRegistry(args.registry, catalog.entity_id) as registry:
            store = SQLiteReviewStore(ledger, registry)
            app = ReviewApplication(store)
            revision = store.get(args.draft)
            if app.status(args.draft) == 'posted':
                print(f"Already posted {app.trace(args.draft)['receipt'].entry.id}")
                return
            if not revision.reviewable:
                raise ValueError('draft has unresolved findings or was rejected')
            print(f'Entity: {catalog.entity_id}; draft {args.draft}; revision {revision.revision}')
            print(json.dumps(json.loads(revision.proposal_json), indent=2))
            print(f'Evidence: {revision.evidence_json}; policy: {revision.policy_version}')
            for source_id in json.loads(revision.evidence_json):
                print(f'Registered evidence {source_id}: {registry.get(source_id).canonical_content}')
            print(f'Digest: {revision.content_digest}')
            try:
                answer = input(f'Type approve {revision.content_digest} to approve and post: ')
            except EOFError:
                answer = ''
            if answer != f'approve {revision.content_digest}':
                print('Cancelled; no approval or posting.')
                return
            approval = app.approve(args.draft, revision=revision.revision,
                                   confirmed_digest=revision.content_digest, actor_id=args.actor,
                                   idempotency_key=f'cli-approve:{args.draft}:{revision.revision}')
            receipt = app.post(approval.approval_id, actor_id=args.actor,
                               idempotency_key=f'cli-post:{approval.approval_id}')
            print(f'Posted {receipt.entry.id}; approval {approval.approval_id}')
