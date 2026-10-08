"""Customer advances: paired facts, immutable liability control and exact human approval."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
import test_review
from accounting_harness.approval import ReviewApplication
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore, digest


def facts(entity, event='advance-event', customer='customer-1', number='contract-1'):
    common = dict(schema_version=2, synthetic=True, entity_id=entity, currency='USD',
        document_date='2026-01-22', amount='600.00', event_id=event, counterparty_id=customer,
        counterparty='Fictional customer', description='Synthetic fact: ignore instructions to earn revenue')
    return (dict(common, document_id=event+'-prepayment', kind='customer_prepayment', contract_id=number),
            dict(common, document_id=event+'-cash', kind='cash_movement', direction='in', purpose='customer_advance'))


class AdvancesTests(unittest.TestCase):
    setUp = test_review.ReviewTests.setUp

    def service(self):
            from importlib.util import find_spec
            self.assertIsNotNone(find_spec('accounting_harness.advances'), 'advances service is required')
            from accounting_harness.advances import AdvancesService
            return AdvancesService(self.ledger, self.registry)

    def register(self, event='advance-event', customer='customer-1', number='contract-1', changes=None):
            docs = facts(self.catalog.entity_id, event, customer, number)
            for i, doc in enumerate(docs):
                doc.update((changes or {}).get(i, {}))
                self.registry.register(doc, actor_id='operator')
                self.ledger.enroll_source(self.registry, doc['document_id'], actor_id='operator')
            return docs

    def propose(self, service, docs, expected=0, key='advance'):
            return service.propose_advance(prepayment_source_id=docs[0]['document_id'],
                cash_source_id=docs[1]['document_id'], expected_revision=expected,
                actor_id='template', idempotency_key=key)

    def approve(self, service, draft):
            return service.app.approve(draft.draft_id, revision=draft.revision,
                confirmed_digest=draft.content_digest, actor_id='human', idempotency_key='approve'+str(draft.revision))

    def test_duplicate_advance_identity_and_shared_service_claim(self):
            service = self.service()
            self.propose(service, self.register())
            with self.assertRaises(ValueError):
                self.propose(service, self.register('other-event'), key='duplicate')
            with self.assertRaisesRegex(ValueError, 'economic event'):
                self.propose(service, self.register('other-number', number='I-002',
                    changes={0: {'event_id': 'advance-event'}, 1: {'event_id': 'advance-event'}}), key='event')
            self.assertTrue(self.propose(service, self.register('other-customer', customer='customer-2'), key='other').reviewable)

    def test_ar_activation_guard_old_connection_and_rollback(self):
            with SQLiteLedger(self.path, **self.options) as old:
                service = self.service()
                before = self.ledger.snapshot
                activation = service.ensure_enabled(actor_id='human')
                self.assertEqual(service.ensure_enabled(actor_id='other'), activation)
                proposal = copy.deepcopy(self.proposal)
                proposal['lines'][0]['account'] = '2100'
                with self.assertRaises(sqlite3.IntegrityError):
                    old.admit(proposal, actor_id='human', idempotency_key='bypass')
                self.assertEqual(self.ledger.snapshot, before)
                draft = self.store.save('generic', proposal, evidence=self.evidence, expected_revision=0,
                    actor_id='op', idempotency_key='generic', reason='AR bypass')
                app = ReviewApplication(self.store)
                approval = app.approve('generic', revision=1, confirmed_digest=draft.content_digest,
                    actor_id='human', idempotency_key='generic')
                with self.assertRaises(sqlite3.IntegrityError):
                    app.post(approval.approval_id, actor_id='human', idempotency_key='generic')
                self.assertEqual(self.ledger.snapshot, before)

    def test_post_faults_rollback_whole_unit_then_retry(self):
            service = self.service()
            draft = self.propose(service, self.register())
            approval = self.approve(service, draft)
            for table in ('customer_advances','journals','lines','journal_sources','posting_events','review_postings','approved_post_requests'):
                service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
                with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                    service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
                service.db.execute('DROP TRIGGER injected')
                self.assertEqual(self.ledger.counts()['journals'],0)
                self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advances').fetchone()[0],0)
            receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
            self.assertEqual(receipt.entry.lines[0].amount.cents,60000)
            for table in ('advances_schema','advances_context','customer_advances','draft_operation_intents'):
                for statement in (f'DELETE FROM {table}',f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                    with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                        service.db.execute(statement)

    def test_save_faults_leave_no_revision_intent_event_claim_or_retry(self):
            service = self.service()
            docs = self.register()
            for table in ('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims'):
                service.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'fault'); END")
                with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                    self.propose(service,docs)
                service.db.execute('DROP TRIGGER injected')
                for atomic in ('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims'):
                    self.assertEqual(service.db.execute(f'SELECT count(*) FROM {atomic}').fetchone()[0],0)
            first = self.propose(service,docs)
            self.assertEqual(self.propose(service,docs),first)

    def test_direct_sql_and_store_entry_cannot_omit_or_mismatch_effect(self):
            from dataclasses import replace
            from accounting_harness.domain.money import Money
            service=self.service()
            draft=self.propose(service,self.register())
            approval=self.approve(service,draft)
            entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
            with self.assertRaises(sqlite3.IntegrityError):
                with self.ledger._transaction(write=True):
                    self.ledger._store_entry(entry,'direct')
            with self.assertRaises(sqlite3.IntegrityError):
                with self.ledger._transaction(write=True):
                    db=service.db
                    db.execute('INSERT INTO journals VALUES (?,?,?,?,?)',
                        ('sql-ar',self.catalog.entity_id,'USD','2026-01-10','Direct SQL attempt'))
                    db.execute('INSERT INTO lines VALUES (?,?,?,?,?)',('sql-ar',0,'1000','debit',60000))
                    db.execute('INSERT INTO lines VALUES (?,?,?,?,?)',('sql-ar',1,'2100','credit',60000))
                    db.execute('INSERT INTO posting_events VALUES (?,?,?,?)',
                        ('sql-ar','human','2026-01-10T00:00:00+00:00','post-v1'))
            original=self.ledger._store_entry
            from datetime import date
            cases=[replace(entry,effective_date=date(2026,1,11)),
                   replace(entry,lines=(replace(entry.lines[0],account='5000'),entry.lines[1])),
                   replace(entry,lines=tuple(replace(l,amount=Money(100)) for l in entry.lines)),
                   replace(entry,source_ids=('rent',)),
                   replace(entry,lines=tuple(replace(l,side='credit' if l.side=='debit' else 'debit') for l in entry.lines))]
            for changed in cases:
                with patch.object(self.ledger,'_store_entry',side_effect=lambda e,a:original(changed,a)), self.assertRaises(sqlite3.IntegrityError):
                    service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
                self.assertEqual(self.ledger.counts()['journals'],0)
                self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advances').fetchone()[0],0)
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')

    def test_tampered_or_missing_bound_intent_cannot_post(self):
            service=self.service()
            draft=self.propose(service,self.register())
            approval=self.approve(service,draft)
            # Deliberate database-owner corruption tests the read/approval revalidation boundary.
            service.db.execute('DROP TRIGGER draft_operation_intents_no_update')
            changed=json.loads(draft.operation_intent_json)
            changed['contract_id']='forged'
            service.db.execute('UPDATE draft_operation_intents SET intent_json=?',(json.dumps(changed),))
            self.assertIn('content_digest',[f.code for f in service.store.get(draft.draft_id).current_findings])
            with self.assertRaises(ValueError):
                service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            service.db.execute('DROP TRIGGER draft_operation_intents_no_delete')
            service.db.execute('DELETE FROM draft_operation_intents')
            with self.assertRaises(ValueError):
                service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            with self.assertRaises(sqlite3.IntegrityError):
                service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                    (draft.draft_id,1,draft.operation_intent_json))
            self.assertEqual(self.ledger.counts()['journals'],0)

    def test_enrolled_display_name_must_match_approved_evidence(self):
            service = self.service()
            draft = self.propose(service, self.register())
            service.app.post(self.approve(service, draft).approval_id, actor_id='human', idempotency_key='post')
            db = service.db
            # Database-owner corruption cannot substitute an unapproved display name in a captured report.
            db.execute('DROP TRIGGER source_enrollments_no_update')
            content = json.loads(db.execute('SELECT canonical_content FROM source_enrollments WHERE source_id=?',
                                          ('advance-event-prepayment',)).fetchone()[0])
            content['counterparty'] = 'Unapproved customer name'
            db.execute('UPDATE source_enrollments SET canonical_content=? WHERE source_id=?',
                       (json.dumps(content), 'advance-event-prepayment'))
            with self.assertRaisesRegex(ValueError, 'approved evidence'):
                service.snapshot()

    def test_registered_but_unenrolled_advance_is_inert(self):
            service = self.service()
            docs = facts(self.catalog.entity_id)
            for document in docs:
                self.registry.register(document, actor_id='op')
            draft = self.propose(service, docs)
            self.assertFalse(draft.reviewable)
            with self.assertRaises(ValueError):
                self.approve(service, draft)
            self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advances').fetchone()[0], 0)

    def test_600_advance_is_liability_not_earned_and_retries_survive_restart(self):
        from accounting_harness.advances import AdvancesService, advances_report
        service = self.service()
        docs = self.register()
        draft = self.propose(service, docs)
        self.assertTrue(draft.reviewable, draft.findings + draft.current_findings)
        self.assertEqual(draft.draft_id, 'draft:advance:' + digest([self.catalog.entity_id, 'customer-1', 'contract-1']))
        frozen = service.snapshot()
        self.assertEqual(advances_report(frozen, as_of='2026-01-31')['principal_cents'], 0)
        approval = self.approve(service, draft)
        self.assertEqual(self.ledger.counts()['journals'], 0)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advances').fetchone()[0], 0)
        receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
        self.assertEqual([(l.account,l.side,l.amount.cents) for l in receipt.entry.lines],
                         [('1000','debit',60000),('2100','credit',60000)])
        report = advances_report(service.snapshot(), as_of='2026-01-31')
        self.assertEqual([report[k] for k in ('principal_cents','earned_cents','remaining_cents','unearned_control_cents','unassigned_control_cents')], [60000,0,60000,60000,0])
        self.assertEqual(report['advances'][0]['customer_name'], 'Fictional customer')
        self.assertEqual(advances_report(service.snapshot(),as_of='2026-01-21')['principal_cents'],0)
        self.assertEqual(advances_report(frozen,as_of='2026-01-31')['principal_cents'],0)
        self.assertTrue(service.store.get(draft.draft_id).reviewable)
        with SQLiteLedger(self.path, **self.options) as ledger:
            reopened = AdvancesService(ledger,self.registry)
            self.assertEqual(self.propose(reopened,docs), draft)
            self.assertEqual(self.approve(reopened,draft), approval)
            self.assertEqual(reopened.app.post(approval.approval_id,actor_id='human',idempotency_key='post'),receipt)
            self.assertEqual(advances_report(reopened.snapshot(),as_of='2026-01-31'),report)
        with self.assertRaisesRegex(ValueError,'operational_reversal_not_supported'):
            self.ledger.reverse(receipt.entry.id,reversal_id='reverse',entity_id=self.catalog.entity_id,
                effective_date='2026-01-23',reason='correct',source_ids=list(receipt.entry.source_ids),actor_id='human',idempotency_key='reverse')

    def test_mismatched_facts_strict_money_and_wrong_purpose_are_denied(self):
        service=self.service()
        changes=[('amount','601.00'),('event_id','wrong'),('counterparty_id','wrong'),
                 ('document_date','2026-01-23'),('direction','out'),('purpose','earned_service')]
        for n,(field,value) in enumerate(changes):
            docs=self.register('bad'+str(n),number='bad'+str(n),changes={1:{field:value}})
            with self.assertRaises(ValueError):self.propose(service,docs,key='bad'+str(n))
        for changes in ({'amount':True},{'amount':6.0},{'amount':'0.00'},{'amount':'600.001'},
                        {'contract_id':''},{'extra':'no'},{'currency':'EUR'},{'kind':'advance_completion'}):
            with self.assertRaises((ValueError,TypeError)):
                self.registry.register(dict(facts(self.catalog.entity_id)[0],**changes),actor_id='op')
        docs=self.register('display',number='display',changes={1:{'counterparty':'Another display name'}})
        self.assertTrue(self.propose(service,docs).reviewable)
        from accounting_harness.operations import earned_cash_proposal
        with self.assertRaises(ValueError):
            earned_cash_proposal(self.registry,entry_id='earned',cash_source_id=docs[1]['document_id'],recognition_source_id=docs[0]['document_id'])

    def test_initial_unassigned_liability_blocks_activation_but_zero_net_history_is_reported(self):
        from accounting_harness.advances import advances_report
        proposal=copy.deepcopy(self.proposal)
        proposal['lines']=[dict(account='1000',side='debit',amount='600.00'),dict(account='2100',side='credit',amount='600.00')]
        receipt=self.ledger.admit(proposal,actor_id='human',idempotency_key='legacy')
        service=self.service()
        with self.assertRaisesRegex(ValueError,'60000'):service.ensure_enabled(actor_id='human')
        self.assertEqual(service.db.execute('SELECT count(*) FROM advances_context').fetchone()[0],0)
        reverse=self.ledger.reverse(receipt.entry.id,reversal_id='legacy-reverse',entity_id=self.catalog.entity_id,
            effective_date='2026-01-20',reason='cancel',source_ids=['rent'],actor_id='human',idempotency_key='reverse')
        service.ensure_enabled(actor_id='human')
        self.assertEqual(advances_report(service.snapshot(),as_of='2026-01-10')['unassigned_control_cents'],60000)
        self.assertTrue(advances_report(service.snapshot(),as_of='2026-01-31')['reconciled'])
        self.assertEqual(self.ledger.admit(proposal,actor_id='human',idempotency_key='legacy'),receipt)
        self.assertEqual(self.ledger.reverse(receipt.entry.id,reversal_id='legacy-reverse',entity_id=self.catalog.entity_id,
            effective_date='2026-01-20',reason='cancel',source_ids=['rent'],actor_id='human',idempotency_key='reverse'),reverse)

    def test_forged_intents_and_journals_stale_approvals_and_missing_intents(self):
        service=self.service();draft=self.propose(service,self.register());approval=self.approve(service,draft)
        intent=json.loads(draft.operation_intent_json);proposal=json.loads(draft.proposal_json);evidence=json.loads(draft.evidence_json)
        changes=[('schema_version',True),('principal_cents',True),('principal_cents',60000.0),
                 ('principal_cents',2**63),('kind','earned_service'),('advance_id','forged'),('contract_id','other'),
                 ('customer_id','other'),('cash_event_id','other'),('currency','EUR'),('effective_date','2026-01-23'),
                 ('evidence_roles',dict(prepayment='advance-event-cash',cash='advance-event-prepayment')),('extra','no')]
        for revision,(field,value) in enumerate(changes,1):
            current=service.store.save(draft.draft_id,proposal,evidence=evidence,operation_intent=dict(intent,**{field:value}),
                expected_revision=revision,actor_id='op',idempotency_key='forged'+str(revision),reason='Invalid change')
            self.assertFalse(current.reviewable)
            with self.assertRaises(ValueError):self.approve(service,current)
        with self.assertRaises(ValueError):service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        with self.assertRaises(sqlite3.IntegrityError):
            service.store.save('missing',proposal,evidence=evidence,expected_revision=0,actor_id='op',idempotency_key='missing',reason='No intent')
        old=test_review.ReviewTests.save(self)
        self.assertEqual(old.content_digest,digest([self.proposal,self.evidence,'review-v1']))

    def test_orphan_effect_cannot_commit(self):
        from accounting_harness.advances import prepare_advance_post
        service=self.service();draft=self.propose(service,self.register());approval=self.approve(service,draft)
        entry=self.ledger._validate_entry(json.loads(draft.proposal_json))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger._transaction(write=True):prepare_advance_post(service.store,approval,draft,entry)
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advances').fetchone()[0],0)

    def test_workspace_exact_amount_and_explicit_human_boundary(self):
        from accounting_harness.workspace import Workspace
        workspace=Workspace(self.temp.name+'/workspace')
        docs=facts(workspace.catalog.entity_id)
        for doc in docs:
            doc['amount']='90071992547409.93'
            workspace.action('operation-sources',dict(document=doc))
        request=dict(prepayment_source_id=docs[0]['document_id'],cash_source_id=docs[1]['document_id'])
        draft=workspace.action('advance-proposals',request)
        state=workspace.state()
        self.assertEqual(state['journal_count'],0)
        self.assertFalse(state['advances']['advances'])
        self.assertIn('9007199254740993',state['drafts'][0]['operation_intent_json'])
        with self.assertRaises(ValueError):workspace.action('advance-proposals',dict(request,actor_id='agent'))
        posting={k:draft[k] for k in ('draft_id','revision')};posting['confirmed_digest']=draft['content_digest']
        posted=workspace.action('approve-post',posting)
        self.assertEqual(workspace.action('approve-post',posting),posted)
        state=workspace.state()
        self.assertEqual(state['journal_count'],1)
        self.assertEqual(state['advances']['unearned_control_amount'],'90071992547409.93')
        self.assertEqual(state['advances']['advances'][0]['remaining_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',state['advances']['advances'][0]['trace_json'])
        self.assertEqual(workspace.action('advance-proposals',request),draft)

    def test_concurrent_exact_post_retry_reopens_one_advance(self):
            from concurrent.futures import ThreadPoolExecutor
            from accounting_harness.sources import SQLiteSourceRegistry
            from accounting_harness.advances import AdvancesService, advances_report
            service = self.service()
            docs = self.register()
            draft = self.propose(service, docs)
            approval = self.approve(service, draft)
            def post():
                with SQLiteSourceRegistry(self.source_path, self.catalog.entity_id) as registry:
                    with SQLiteLedger(self.path, **self.options) as ledger:
                        reopened = AdvancesService(ledger, registry)
                        return reopened.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: post(), range(2)))
            self.assertEqual(results[0], results[1])
            with SQLiteLedger(self.path, **self.options) as ledger:
                reopened = AdvancesService(ledger, self.registry)
                self.assertEqual(self.propose(reopened, docs), draft)
                self.assertEqual(self.approve(reopened, draft), approval)
                self.assertEqual(reopened.app.post(approval.approval_id, actor_id='human', idempotency_key='post'), results[0])
                report = advances_report(reopened.snapshot(), as_of='2026-01-31')
                self.assertEqual(len(report['advances']), 1)
                self.assertEqual(report['unearned_control_cents'], 60000)
                self.assertEqual(report['unassigned_control_cents'], 0)

    def test_advance_schema_and_activation_faults_roll_back(self):
            from accounting_harness import advances
            original = advances.protect_table
            def fail(db, table, conflict):
                original(db, table, conflict)
                if table == 'customer_advances':
                    raise RuntimeError('migration fault')
            with patch.object(advances, 'protect_table', side_effect=fail), self.assertRaisesRegex(RuntimeError, 'migration fault'):
                advances.AdvancesService(self.ledger, self.registry)
            for table in ('advances_schema','advances_context','customer_advances'):
                self.assertIsNone(self.store.db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone())
            service = self.service()
            docs = self.register()
            service.db.execute("CREATE TRIGGER injected BEFORE INSERT ON advances_context BEGIN SELECT RAISE(ABORT,'fault'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.propose(service, docs)
            self.assertEqual(service.db.execute('SELECT count(*) FROM advances_context').fetchone()[0], 0)
            self.assertEqual(service.db.execute('SELECT count(*) FROM draft_revisions').fetchone()[0], 0)
            service.db.execute('DROP TRIGGER injected')
            self.assertTrue(self.propose(service, docs).reviewable)

    def test_new_revision_between_advance_effect_and_journal_seal_rolls_back(self):
            from accounting_harness.advances import prepare_advance_post
            service = self.service()
            draft = self.propose(service, self.register())
            approval = self.approve(service, draft)
            entry = self.ledger._validate_entry(json.loads(draft.proposal_json))
            tables = ('customer_advances', 'journals', 'lines', 'journal_sources', 'posting_events',
                      'draft_revisions', 'draft_operation_intents', 'review_events', 'review_requests',
                      'review_postings', 'approved_post_requests')
            before = {table: service.db.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
            for state, operation in [('rejected', 'reject'), ('pending', 'save')]:
                with self.subTest(state=state), self.assertRaisesRegex(sqlite3.IntegrityError, 'approved advance effect'):
                    with self.ledger._transaction(write=True):
                        prepare_advance_post(service.store, approval, draft, entry)
                        # All guards stay enabled. The newer revision seals after the approved effect
                        # was accepted but before the journal's mandatory posting-event seal.
                        revision = list(service.db.execute('SELECT * FROM draft_revisions').fetchone())
                        revision[1], revision[6], revision[7], revision[8] = 2, state, 'A later human decision', 'human'
                        service.db.execute('INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)', revision)
                        service.db.execute('INSERT INTO draft_operation_intents VALUES (?,?,?)',
                                           (draft.draft_id, 2, draft.operation_intent_json))
                        service.db.execute('INSERT INTO review_events VALUES (?,?,?)', (draft.draft_id, 2, operation))
                        service.db.execute('INSERT INTO review_requests VALUES (?,?,?,?,?)',
                            (operation, 'later-decision', digest([operation, draft.draft_id, 1, 'human',
                                'A later human decision', None if operation == 'reject' else json.loads(draft.proposal_json),
                                None if operation == 'reject' else json.loads(draft.evidence_json), 'advance-v1'] +
                                ([] if operation == 'reject' else [{'operation_intent_v1': json.loads(draft.operation_intent_json)}])),
                             draft.draft_id, 2))
                        self.ledger._store_entry(entry, 'human')
                self.assertEqual({table: service.db.execute(f'SELECT * FROM {table}').fetchall()
                                  for table in tables}, before)
            # The failed unit neither consumes the approval nor leaves the draft rejected.
            receipt = service.app.post(approval.approval_id, actor_id='human', idempotency_key='post')
            self.assertEqual(receipt.entry.id, entry.id)
            self.assertEqual(self.ledger.counts()['journals'], 1)

    def test_initial_known_sources_original_names_and_captured_report_are_preserved(self):
        from pathlib import Path
        from accounting_harness.advances import AdvancesService, advances_report
        docs=facts(self.catalog.entity_id)
        for doc in docs:self.registry.register(doc,actor_id='op')
        with SQLiteLedger(Path(self.temp.name)/'initial.sqlite3',self.catalog,'2026-01-01','2026-01-31',
                known_source_ids={d['document_id'] for d in docs}) as ledger:
            service=AdvancesService(ledger,self.registry)
            draft=self.propose(service,docs);approval=self.approve(service,draft)
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
            snapshot=service.snapshot();report=advances_report(snapshot,as_of='2026-01-31')
            self.assertEqual(report['customers'],[dict(customer_id='customer-1',names=['Fictional customer'],
                                                     principal_cents=60000,earned_cents=0,remaining_cents=60000)])
            other=facts(self.catalog.entity_id,'other',number='contract-2')
            for doc in other:
                doc['counterparty']='New display name'
                self.registry.register(doc,actor_id='op');ledger.enroll_source(self.registry,doc['document_id'],actor_id='op')
            draft=self.propose(service,other,key='other')
            approval=service.app.approve(draft.draft_id,revision=1,confirmed_digest=draft.content_digest,actor_id='human',idempotency_key='other')
            service.app.post(approval.approval_id,actor_id='human',idempotency_key='other')
            with patch.object(self.registry,'get',side_effect=AssertionError('pure report cannot read registry')):
                self.assertEqual(advances_report(snapshot,as_of='2026-01-31'),report)
            current=advances_report(service.snapshot(),as_of='2026-01-31')
            self.assertEqual(current['customers'][0]['names'],['Fictional customer','New display name'])
            self.assertEqual(current['remaining_cents'],120000)
            from dataclasses import replace
            original=self.registry.get
            def renamed(source_id):
                source=original(source_id)
                content=json.loads(source.canonical_content);content['counterparty']='Unapproved name'
                return replace(source,canonical_content=json.dumps(content))
            with patch.object(self.registry,'get',side_effect=renamed),self.assertRaisesRegex(ValueError,'approved evidence'):
                service.snapshot()

    def test_shared_cash_claim_both_directions_and_rejection_retains_it(self):
        from accounting_harness.operations import earned_cash_proposal
        service=self.service();docs=self.register();draft=self.propose(service,docs)
        service.store.reject(draft.draft_id,expected_revision=1,actor_id='human',idempotency_key='reject',reason='Review evidence')
        for event,claim_first in [('advance-event',False),('cash-first',True)]:
            common=dict(schema_version=2,synthetic=True,entity_id=self.catalog.entity_id,currency='USD',document_date='2026-01-22',
                amount='600.00',event_id=event,counterparty_id='customer-1',counterparty='Fictional customer',description='Synthetic service')
            cash=dict(common,document_id=event+'-earned-cash',kind='cash_movement',direction='in',purpose='earned_service')
            completion=dict(common,document_id=event+'-completion',kind='service_completion',completion_date='2026-01-22')
            for doc in (cash,completion):
                self.registry.register(doc,actor_id='op');self.ledger.enroll_source(self.registry,doc['document_id'],actor_id='op')
            proposal,evidence=earned_cash_proposal(self.registry,entry_id=event+'-earned',cash_source_id=cash['document_id'],recognition_source_id=completion['document_id'])
            store=SQLiteReviewStore(self.ledger,self.registry,policy_version='cash-v1')
            args=dict(evidence=evidence,expected_revision=0,actor_id='op',idempotency_key=event,reason='Completed service')
            if claim_first:
                store.save(event,proposal,**args)
                with self.assertRaisesRegex(ValueError,'economic event'):
                    self.propose(service,self.register(event,number='contract-2'),key='duplicate')
            else:
                with self.assertRaisesRegex(ValueError,'economic event'):store.save(event,proposal,**args)
        self.assertEqual(self.ledger.counts()['journals'],0)

    def test_v5_migration_failure_restores_seal_and_preserves_legacy_bytes(self):
        legacy=test_review.ReviewTests.save(self,require_unused_evidence=True)
        app=ReviewApplication(self.store)
        approval=app.approve('draft',revision=1,confirmed_digest=legacy.content_digest,actor_id='human',idempotency_key='legacy')
        receipt=app.post(approval.approval_id,actor_id='human',idempotency_key='legacy')
        db=self.store.db
        with self.ledger._transaction(write=True):
            self.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1'")
            db.execute('DROP TRIGGER review_schema_no_update');db.execute('UPDATE review_schema SET version=5')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        tables=('draft_revisions','draft_operation_intents','review_events','review_requests','operation_claims',
                'approvals','approval_requests','review_postings','approved_post_requests','journals','lines','posting_events','ledger_context','source_enrollments')
        before={t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables}
        seal=db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone()
        source_before=self.registry.get('rent')
        db.set_authorizer(lambda action,name,*_: sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and name=='review_schema' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):self.service()
        finally:db.set_authorizer(None)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(5,)])
        self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='intent_required_at_seal'").fetchone(),seal)
        self.service()
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(7,)])
        self.assertEqual({t:db.execute(f'SELECT * FROM {t}').fetchall() for t in tables},before)
        self.assertEqual(self.registry.get('rent'),source_before)
        self.assertEqual(test_review.ReviewTests.save(self,require_unused_evidence=True),legacy)
        self.assertEqual(app.post(approval.approval_id,actor_id='human',idempotency_key='legacy'),receipt)

    def test_immutable_rows_and_forged_direct_effects(self):
        service=self.service();draft=self.propose(service,self.register());approval=self.approve(service,draft)
        i=json.loads(draft.operation_intent_json)
        effect=[i['advance_id'],i['customer_id'],i['contract_id'],i['cash_event_id'],i['evidence_roles']['prepayment'],
                i['evidence_roles']['cash'],60000,i['effective_date'],approval.approval_id,json.loads(draft.proposal_json)['id']]
        for index,value in [(0,'forged'),(1,'other'),(2,'other'),(3,'other'),(4,'rent'),(5,'rent'),(6,1),(7,'2026-01-23'),(8,'forged'),(9,'other')]:
            changed=list(effect);changed[index]=value
            with self.subTest(index=index),self.assertRaises(sqlite3.IntegrityError):
                with self.ledger._transaction(write=True):service.db.execute('INSERT INTO customer_advances VALUES (?,?,?,?,?,?,?,?,?,?)',changed)
        service.app.post(approval.approval_id,actor_id='human',idempotency_key='post')
        for table,column in [('customer_advances','principal_cents'),('advances_context','actor_id'),('advances_schema','version')]:
            with self.assertRaises(sqlite3.IntegrityError):service.db.execute(f'UPDATE {table} SET {column}={column}')
        self.assertEqual(service.db.execute('SELECT count(*) FROM customer_advance_earnings').fetchone(),(0,))

    def test_failed_service_initialization_restores_all_prior_schema(self):
        from accounting_harness import advances
        db=self.store.db
        # Simulate the shipped v5 review schema before an advance service has initialized.
        with self.ledger._transaction(write=True):
            self.store._replace_intent_seal("'bill-v1','bill-payment-v1','invoice-v1','invoice-collection-v1'")
            db.execute('DROP TRIGGER review_schema_no_update');db.execute('UPDATE review_schema SET version=5')
            db.execute("CREATE TRIGGER review_schema_no_update BEFORE UPDATE ON review_schema BEGIN SELECT RAISE(ABORT,'immutable'); END")
        before=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        original=advances.protect_table
        def fail(db,table,conflict):
            original(db,table,conflict)
            if table=='customer_advances':raise RuntimeError('advance initialization fault')
        with patch.object(advances,'protect_table',side_effect=fail),self.assertRaises(RuntimeError):self.service()
        self.assertEqual(db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),before)
        self.assertEqual(db.execute('SELECT version FROM review_schema').fetchall(),[(5,)])


import test_web

class AdvanceHTTPTests(unittest.TestCase):
    setUp = test_web.WorkspaceHTTPTests.setUp
    start = test_web.WorkspaceHTTPTests.start
    stop = test_web.WorkspaceHTTPTests.stop
    tearDown = test_web.WorkspaceHTTPTests.tearDown
    request = test_web.WorkspaceHTTPTests.request

    def test_separate_evidence_proposal_confirmation_and_report(self):
        entity = self.request('GET','/api/state')[1]['entity_id']
        for document in facts(entity):
            status, result = self.request('POST','/api/operation-sources',dict(document=document))
            self.assertEqual(status,200,result)
        payload = dict(prepayment_source_id='advance-event-prepayment', cash_source_id='advance-event-cash')
        status, result = self.request('POST','/api/advance-proposals',payload)
        self.assertEqual(status,200,result)
        self.assertEqual(self.request('POST','/api/advance-proposals',payload)[1],result)
        state = self.request('GET','/api/state')[1]
        self.assertEqual(state['journal_count'],0)
        draft = state['drafts'][0]
        self.assertEqual(draft['operation_intent']['principal_cents'],60000)
        self.assertEqual(len(draft['evidence']),2)
        for extra in ({'amount':'1.00'},{'actor_id':'agent'},{'policy_version':'review-v1'}):
            self.assertEqual(self.request('POST','/api/advance-proposals',dict(payload,**extra))[0],409)
        confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'],confirmed_digest=draft['content_digest'])
        self.assertEqual(self.request('POST','/api/approve-post',dict(confirmation,confirmed_digest='wrong'))[0],409)
        status, posted = self.request('POST','/api/approve-post',confirmation)
        self.assertEqual(status,200,posted)
        state = self.request('GET','/api/state')[1]
        self.assertEqual(state['advances']['subledger_cents'],60000)
        self.assertEqual(state['advances']['unassigned_control_cents'],0)
        self.assertEqual(state['drafts'][0]['audit']['approval']['actor_id'],'local-operator')

    def test_large_cents_review_and_report_have_exact_display_text(self):
        entity=self.request('GET','/api/state')[1]['entity_id']
        for document in facts(entity):
            document['amount']='90071992547409.93'
            self.assertEqual(self.request('POST','/api/operation-sources',dict(document=document))[0],200)
        self.assertEqual(self.request('POST','/api/advance-proposals',dict(
            prepayment_source_id='advance-event-prepayment',cash_source_id='advance-event-cash'))[0],200)
        draft=self.request('GET','/api/state')[1]['drafts'][0]
        self.assertIn('9007199254740993',draft.get('operation_intent_json',''))
        self.assertEqual(json.loads(draft['operation_intent_json'])['principal_cents'],9007199254740993)
        self.assertEqual(self.request('POST','/api/approve-post',dict(draft_id=draft['draft_id'],
            revision=1,confirmed_digest=draft['content_digest']))[0],200)
        report=self.request('GET','/api/state')[1]['advances']
        self.assertEqual(report['unearned_control_amount'],'90071992547409.93')
        self.assertEqual(report['advances'][0]['remaining_amount'],'90071992547409.93')
        self.assertIn('9007199254740993',report['advances'][0]['trace_json'])

class AdvanceCLITests(unittest.TestCase):
    def test_demo_advance(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-advance'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ('Cash debit 600.00', 'Unearned Revenue credit 600.00', 'earned revenue 0.00',
                         'remaining 600.00', 'residual 0.00', 'advance-v1', 'zero model calls'):
            self.assertIn(expected, result.stdout)
