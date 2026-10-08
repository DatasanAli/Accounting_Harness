"""Explicit full-month insurance coverage; exact allocations and captured support."""
import calendar
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import Finding
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS, SQLiteLedger, _canonical
from accounting_harness.review import SQLiteReviewStore, digest, protect_table

POLICY = 'prepaid-consumption-v1'
ALLOCATION = 'equal-months-cents-v1'


def coverage_months(start, end):
    start, end = accounting_date(start), accounting_date(end)
    count = (end.year-start.year)*12 + end.month-start.month+1
    if start.day != 1 or end.day != calendar.monthrange(end.year,end.month)[1] or not 1 <= count <= 120:
        raise ValueError('coverage requires one through 120 full calendar months')
    return start, end, count


def allocation(principal, start, end, month):
    if type(principal) is not int or not 1 <= principal <= MAX_CENTS:
        raise ValueError('principal requires positive integer cents within storage limits')
    start, end, count = coverage_months(start,end)
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month):
        raise ValueError('allocation month must be YYYY-MM')
    first=accounting_date(month+'-01')
    if not start <= first <= end:
        raise ValueError('allocation month is outside coverage')
    offset=(first.year-start.year)*12+first.month-start.month
    amount=principal//count + (1 if offset < principal%count else 0)
    return amount, first.replace(day=calendar.monthrange(first.year,first.month)[1]).isoformat()


def anchored_record(store, source_id):
    record=store.registry.get(source_id)
    anchor=store.db.execute('SELECT content_digest,canonical_content FROM source_enrollments WHERE source_id=?', (source_id,)).fetchone()
    if anchor != (record.content_digest,record.canonical_content) or hashlib.sha256(record.canonical_content.encode()).hexdigest()!=record.content_digest:
        raise ValueError('prepaid evidence must be registered and anchored with unchanged content')
    return record


def supported_policy(store, source_id):
    record=anchored_record(store,source_id)
    document=json.loads(record.canonical_content)
    if document['kind']!='prepaid_coverage' or document['allocation_policy']!=ALLOCATION:
        raise ValueError('explicit prepaid coverage and equal-months-cents-v1 required')
    start,end,count=coverage_months(document['coverage_start'],document['coverage_end'])
    principal=Money.parse(document['amount']).cents
    if principal>MAX_CENTS: raise ValueError('principal exceeds storage limits')
    original=anchored_record(store,document['original_source_id'])
    if Money.parse(json.loads(original.canonical_content)['amount']).cents!=principal:
        raise ValueError('coverage principal differs from original evidence')
    original_id=document['original_journal_id']
    row=store.db.execute('''SELECT j.entity_id,j.currency,j.effective_date FROM journals j
        JOIN posting_events p ON p.journal_id=j.id WHERE j.id=?''',(original_id,)).fetchone()
    entity=store.registry._entity_id
    if row is None or row[:2]!=(entity,'USD') or row[2]>start.isoformat():
        raise ValueError('original purchase must be posted for this entity/currency on or before coverage')
    if store.db.execute('SELECT 1 FROM reversals WHERE original_id=? OR reversal_id=?',(original_id,original_id)).fetchone():
        raise ValueError('original purchase has been reversed or is a reversal')
    lines=store.db.execute('SELECT account,side,cents FROM lines WHERE journal_id=? ORDER BY account',(original_id,)).fetchall()
    if lines!=[('1000','credit',principal),('1200','debit',principal)]:
        raise ValueError('original purchase must have exactly the principal prepaid debit and Cash credit')
    if not store.db.execute('SELECT 1 FROM journal_sources WHERE journal_id=? AND source_id=?',(original_id,original.document_id)).fetchone():
        raise ValueError('original purchase does not retain the named evidence')
    policy=dict(schema_version=1,entity_id=entity,original_journal_id=original_id,
        original_source_id=original.document_id,original_content_digest=original.content_digest,
        coverage_source_id=source_id,coverage_content_digest=record.content_digest,
        coverage_start=start.isoformat(),coverage_end=end.isoformat(),months=count,
        allocation_policy=ALLOCATION,principal_cents=principal)
    policy['policy_digest']=digest(policy)
    prior=store.db.execute('SELECT policy_json FROM prepaid_policies WHERE original_journal_id=?',(original_id,)).fetchone()
    if prior and prior[0]!=_canonical(policy):
        raise ValueError('original purchase already binds different coverage identity/content')
    return policy


def operation(policy, month):
    cents,effective=allocation(policy['principal_cents'],policy['coverage_start'],policy['coverage_end'],month)
    claim=digest([policy['entity_id'],policy['original_journal_id'],month])
    draft_id='prepaid:'+claim
    intent=dict(schema_version=1,kind='prepaid_consumption',policy_digest=policy['policy_digest'],
        original_journal_id=policy['original_journal_id'],original_content_digest=policy['original_content_digest'],
        allocation_month=month,allocated_cents=cents,effective_date=effective,allocation_policy=ALLOCATION,
        evidence_roles=dict(coverage=policy['coverage_source_id'],original=policy['original_source_id']))
    proposal=dict(id='journal:'+claim,entity_id=policy['entity_id'],currency='USD',effective_date=effective,
        description='Supported prepaid insurance consumption '+month,
        source_ids=[policy['coverage_source_id'],policy['original_source_id']],
        lines=[dict(account='5200',side='debit',amount=str(Money(cents))),dict(account='1200',side='credit',amount=str(Money(cents)))])
    evidence={policy['coverage_source_id']:policy['coverage_content_digest'],policy['original_source_id']:policy['original_content_digest']}
    return draft_id,intent,proposal,evidence


def validate_prepaid(store,proposal,records,intent,draft_id):
    try:
        if type(intent) is not dict or type(intent.get('schema_version')) is not int or type(intent.get('allocated_cents')) is not int:
            raise ValueError('prepaid consumption requires strict integer intent')
        policy=supported_policy(store,intent['evidence_roles']['coverage'])
        expected_id,expected_intent,expected_proposal,evidence=operation(policy,intent['allocation_month'])
        if intent!=expected_intent or proposal!=expected_proposal or draft_id!=expected_id:
            raise ValueError('prepaid intent, identity or journal differs from supported allocation')
        if {r.document_id:r.content_digest for r in records}!=evidence:
            raise ValueError('prepaid approval requires exact coverage and original evidence')
        if not intent['allocated_cents']:
            raise ValueError('zero allocation: no journal required')
        used=sum(r[0] for r in store.db.execute('SELECT allocated_cents FROM prepaid_effects WHERE original_journal_id=? AND journal_id!=?',
            (policy['original_journal_id'],proposal['id'])))
        if used+intent['allocated_cents']>policy['principal_cents']:
            raise ValueError('consumption exceeds supported principal')
    except (ValueError,TypeError,KeyError) as error:
        return (Finding('unsupported_prepaid_consumption','operation_intent',str(error)),)
    return ()


def anchor_policy(store,policy,actor):
    if not store.db.execute('SELECT 1 FROM prepaid_policies WHERE original_journal_id=?',(policy['original_journal_id'],)).fetchone():
        store.db.execute('INSERT INTO prepaid_policies VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (policy['original_journal_id'],policy['entity_id'],policy['coverage_source_id'],policy['original_source_id'],
             policy['principal_cents'],policy['coverage_start'],policy['coverage_end'],policy['months'],_canonical(policy),actor,
             datetime.now(timezone.utc).isoformat()))


def anchor_preparation(store,draft_id,revision,proposal,evidence,intent,actor):
    policy=supported_policy(store,intent['evidence_roles']['coverage'])
    anchor_policy(store,policy,actor)
    prior=store.db.execute('SELECT draft_id FROM prepaid_claims WHERE original_journal_id=? AND allocation_month=?',
        (policy['original_journal_id'],intent['allocation_month'])).fetchone()
    if prior and prior!=(draft_id,): raise ValueError('duplicate purchase/month consumption claim')
    if not prior:
        store.db.execute('INSERT INTO prepaid_claims VALUES(?,?,?,?,?,?,?,?,?)',
            (policy['original_journal_id'],intent['allocation_month'],draft_id,intent['allocated_cents'],intent['effective_date'],
             _canonical(proposal),_canonical(intent),_canonical(evidence),revision))


class PrepaidService:
    def __init__(self,ledger,registry):
        self.ledger,self.registry,self.db=ledger,registry,ledger._connection
        with ledger._transaction(write=True):
            self.store=SQLiteReviewStore(ledger,registry,policy_version=POLICY)
            self.app=ReviewApplication(self.store)
            self._initialize()

    @staticmethod
    def valid_original(effect):
        return f'''NOT EXISTS (SELECT 1 FROM reversals v WHERE v.original_id={effect}.original_journal_id
            OR v.reversal_id={effect}.original_journal_id)'''

    @staticmethod
    def approval_match(effect):
        return f'''EXISTS (SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
            JOIN draft_operation_intents i USING(draft_id,revision)
            JOIN prepaid_claims c ON c.draft_id=r.draft_id
            JOIN prepaid_policies p ON p.original_journal_id=c.original_journal_id
            WHERE a.approval_id={effect}.approval_id AND r.policy_version='{POLICY}' AND r.state='pending'
              AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
              AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
              AND json_extract(a.binding_json,'$.policy_version')='{POLICY}'
              AND json_extract(a.binding_json,'$.action')='post'
              AND json_extract(a.binding_json,'$.entity_id')=p.entity_id
              AND json_extract(a.binding_json,'$.draft_id')=r.draft_id
              AND json_extract(a.binding_json,'$.revision')=r.revision
              AND json_extract(a.binding_json,'$.evidence')=c.evidence_json
              AND r.evidence_json=c.evidence_json AND r.proposal_json=c.proposal_json AND i.intent_json=c.intent_json
              AND json_extract(r.proposal_json,'$.id')={effect}.journal_id
              AND c.original_journal_id={effect}.original_journal_id AND c.allocation_month={effect}.allocation_month
              AND c.allocated_cents={effect}.allocated_cents AND c.effective_date={effect}.effective_date)'''

    def _initialize(self):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='prepaid_schema'").fetchone():
            if self.db.execute('SELECT version FROM prepaid_schema').fetchall()!=[(1,)]: raise ValueError('unsupported prepaid schema')
            return
        self.db.execute('CREATE TABLE prepaid_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
        self.db.execute('INSERT INTO prepaid_schema VALUES(1)')
        self.db.execute('''CREATE TABLE prepaid_policies(
            original_journal_id TEXT PRIMARY KEY REFERENCES posting_events(journal_id),entity_id TEXT NOT NULL,
            coverage_source_id TEXT NOT NULL UNIQUE REFERENCES source_enrollments(source_id),
            original_source_id TEXT NOT NULL REFERENCES source_enrollments(source_id),principal_cents INTEGER NOT NULL CHECK(principal_cents>0),
            coverage_start TEXT NOT NULL,coverage_end TEXT NOT NULL,months INTEGER NOT NULL CHECK(months BETWEEN 1 AND 120),
            policy_json TEXT NOT NULL,actor_id TEXT NOT NULL,recorded_at TEXT NOT NULL) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE prepaid_claims(
            original_journal_id TEXT NOT NULL REFERENCES prepaid_policies(original_journal_id),allocation_month TEXT NOT NULL,
            draft_id TEXT NOT NULL UNIQUE,allocated_cents INTEGER NOT NULL CHECK(allocated_cents>0),effective_date TEXT NOT NULL,
            proposal_json TEXT NOT NULL,intent_json TEXT NOT NULL,evidence_json TEXT NOT NULL,first_revision INTEGER NOT NULL,
            PRIMARY KEY(original_journal_id,allocation_month),
            FOREIGN KEY(draft_id,first_revision) REFERENCES draft_revisions(draft_id,revision) DEFERRABLE INITIALLY DEFERRED) STRICT, WITHOUT ROWID''')
        self.db.execute('''CREATE TABLE prepaid_effects(
            original_journal_id TEXT NOT NULL,allocation_month TEXT NOT NULL,allocated_cents INTEGER NOT NULL CHECK(allocated_cents>0),
            effective_date TEXT NOT NULL,approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
            PRIMARY KEY(original_journal_id,allocation_month),
            FOREIGN KEY(original_journal_id,allocation_month) REFERENCES prepaid_claims(original_journal_id,allocation_month)) STRICT, WITHOUT ROWID''')
        for table,conflict in [('prepaid_schema','1'),('prepaid_policies','original_journal_id=NEW.original_journal_id OR coverage_source_id=NEW.coverage_source_id'),
            ('prepaid_claims','draft_id=NEW.draft_id OR (original_journal_id=NEW.original_journal_id AND allocation_month=NEW.allocation_month)'),
            ('prepaid_effects','approval_id=NEW.approval_id OR journal_id=NEW.journal_id OR (original_journal_id=NEW.original_journal_id AND allocation_month=NEW.allocation_month)')]:
            protect_table(self.db,table,conflict)
        self.db.execute(f'''CREATE TRIGGER prepaid_approved_effect BEFORE INSERT ON prepaid_effects
            WHEN NOT {self.approval_match('NEW')} OR NOT {self.valid_original('NEW')}
              OR EXISTS(SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
              OR NEW.allocated_cents>(SELECT principal_cents FROM prepaid_policies WHERE original_journal_id=NEW.original_journal_id)
                 -(SELECT coalesce(sum(allocated_cents),0) FROM prepaid_effects WHERE original_journal_id=NEW.original_journal_id)
            BEGIN SELECT RAISE(ABORT,'prepaid effect requires current approval and available original principal'); END''')
        self.db.execute(f'''CREATE TRIGGER prepaid_post_guard BEFORE INSERT ON posting_events
            WHEN EXISTS(SELECT 1 FROM prepaid_effects WHERE journal_id=NEW.journal_id)
              OR EXISTS(SELECT 1 FROM journal_sources js JOIN source_enrollments s ON js.source_id=s.source_id
                WHERE js.journal_id=NEW.journal_id AND json_extract(s.canonical_content,'$.kind')='prepaid_coverage')
            BEGIN SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM prepaid_effects f JOIN prepaid_policies p USING(original_journal_id) JOIN journals j ON j.id=f.journal_id
                WHERE f.journal_id=NEW.journal_id AND j.entity_id=p.entity_id AND j.currency='USD' AND j.effective_date=f.effective_date
                  AND {self.approval_match('f')} AND {self.valid_original('f')}
                  AND (SELECT sum(allocated_cents) FROM prepaid_effects WHERE original_journal_id=f.original_journal_id)<=p.principal_cents
                  AND (SELECT count(*) FROM lines WHERE journal_id=j.id)=2
                  AND EXISTS(SELECT 1 FROM lines WHERE journal_id=j.id AND account='5200' AND side='debit' AND cents=f.allocated_cents)
                  AND EXISTS(SELECT 1 FROM lines WHERE journal_id=j.id AND account='1200' AND side='credit' AND cents=f.allocated_cents)
                  AND (SELECT count(*) FROM journal_sources WHERE journal_id=j.id)=2
                  AND EXISTS(SELECT 1 FROM journal_sources WHERE journal_id=j.id AND source_id=p.coverage_source_id)
                  AND EXISTS(SELECT 1 FROM journal_sources WHERE journal_id=j.id AND source_id=p.original_source_id)
            ) THEN RAISE(ABORT,'prepaid posting requires exact current approved consumption effect') END; END''')
        self.db.execute('''CREATE TRIGGER prepaid_reversal_dependency BEFORE INSERT ON reversals
            WHEN EXISTS(SELECT 1 FROM prepaid_effects WHERE original_journal_id=NEW.original_id OR journal_id=NEW.original_id)
            BEGIN SELECT RAISE(ABORT,'prepaid dependency requires linked correction policy'); END''')

    def propose(self,*,coverage_source_id,allocation_month,expected_revision,actor_id,idempotency_key):
        self.store._inputs(coverage_source_id,expected_revision,actor_id,idempotency_key,'prepare prepaid')
        policy=supported_policy(self.store,coverage_source_id)
        draft_id,intent,proposal,evidence=operation(policy,allocation_month)
        if not intent['allocated_cents']:
            with self.ledger._transaction(write=True):
                policy=supported_policy(self.store,coverage_source_id)
                anchor_policy(self.store,policy,actor_id)
            return dict(state='no_journal_required',allocated_amount='0.00',allocation_month=allocation_month)
        return self.store.save(draft_id,proposal,evidence=evidence,operation_intent=intent,
            expected_revision=expected_revision,actor_id=actor_id,idempotency_key=idempotency_key,
            reason='Explicit full-month prepaid allocation; separate human confirmation required')

    def snapshot(self):
        with self.ledger._transaction():
            return self._snapshot()

    def _snapshot(self):
        policies=tuple(r[0] for r in self.db.execute('SELECT policy_json FROM prepaid_policies ORDER BY original_journal_id'))
        effects=tuple(self.db.execute('SELECT * FROM prepaid_effects ORDER BY original_journal_id,allocation_month'))
        return PrepaidSnapshot(self.ledger._snapshot(),policies,effects,self.ledger._context)


def prepare_prepaid_post(store,approval,revision,entry):
    intent=json.loads(revision.operation_intent_json)
    findings=store.validate(json.loads(revision.proposal_json),json.loads(revision.evidence_json),operation_intent=intent,draft_id=revision.draft_id)
    if findings: raise ValueError('prepaid operation no longer valid: '+findings[0].message)
    store.db.execute('INSERT INTO prepaid_effects VALUES(?,?,?,?,?,?)',
        (intent['original_journal_id'],intent['allocation_month'],intent['allocated_cents'],intent['effective_date'],approval.approval_id,entry.id))


@dataclass(frozen=True,slots=True)
class PrepaidSnapshot:
    ledger: object
    policies: tuple
    effects: tuple
    ledger_context: str


def prepaid_report(snapshot,*,as_of):
    cutoff=accounting_date(as_of).isoformat()
    if not snapshot.ledger.period_start.isoformat() <= cutoff <= snapshot.ledger.period_end.isoformat():
        raise ValueError('report cutoff must be inside captured ledger period')
    entries=[e for e in snapshot.ledger.entries if e.effective_date.isoformat()<=cutoff]
    control=sum(l.amount.cents*(1 if l.side=='debit' else -1) for e in entries for l in e.lines if l.account=='1200')
    rows=[]
    for encoded in snapshot.policies:
        policy=json.loads(encoded)
        if policy['original_journal_id'] not in {e.id for e in entries}: continue
        effects=[dict(zip(('original_journal_id','allocation_month','allocated_cents','effective_date','approval_id','journal_id'),e))
            for e in snapshot.effects if e[0]==policy['original_journal_id'] and e[3]<=cutoff]
        consumed=sum(e['allocated_cents'] for e in effects)
        row=dict(policy,allocations=effects,consumed_cents=consumed,remaining_cents=policy['principal_cents']-consumed)
        for key in ('principal','consumed','remaining'): row[key+'_amount']=str(Money(row[key+'_cents']))
        row['trace_json']=json.dumps(row,sort_keys=True,indent=2)
        rows.append(row)
    principal=sum(r['principal_cents'] for r in rows); consumed=sum(r['consumed_cents'] for r in rows)
    report=dict(schema_version=1,report_policy='prepaid-remaining-v1',allocation_policy=ALLOCATION,as_of=cutoff,
        policies=rows,principal_cents=principal,consumed_cents=consumed,remaining_cents=principal-consumed,
        control_cents=control,unassigned_control_cents=control-(principal-consumed),
        snapshot_digest=digest([snapshot.ledger_context,asdict(snapshot.ledger.catalog),snapshot.policies,snapshot.effects,
            [SQLiteLedger._entry_payload(e) for e in snapshot.ledger.entries]]))
    for key in ('principal','consumed','remaining','control','unassigned_control'):
        cents=report[key+'_cents'];report[key+'_amount']=('-' if cents<0 else '')+str(Money(abs(cents)))
    report['report_digest']=digest(report)
    return report


def demo_prepaid_consumption():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='accounting-prepaid-') as directory:
        workspace=Workspace(directory)
        source=dict(schema_version=1,synthetic=True,entity_id=workspace.catalog.entity_id,
            document_id='insurance-purchase-source',kind='receipt',document_date='2026-01-01',currency='USD',
            amount='1200.00',counterparty='Fictional insurer',description='Synthetic annual insurance purchase')
        with workspace.storage() as (registry,ledger,_,_,_):
            registry.register(source,actor_id='fixture-operator')
            ledger.enroll_source(registry,source['document_id'],actor_id='fixture-operator')
            ledger.admit(dict(id='insurance-purchase',entity_id=workspace.catalog.entity_id,currency='USD',effective_date='2026-01-01',
                description='Synthetic posted prepaid purchase',source_ids=[source['document_id']],
                lines=[dict(account='1200',side='debit',amount='1200.00'),dict(account='1000',side='credit',amount='1200.00')]),
                actor_id='fixture-operator',idempotency_key='purchase')
        coverage=dict(source,schema_version=2,kind='prepaid_coverage',document_id='annual-coverage',
            original_journal_id='insurance-purchase',original_source_id=source['document_id'],
            coverage_start='2026-01-01',coverage_end='2026-12-31',allocation_policy=ALLOCATION)
        workspace.action('operation-sources',dict(document=coverage))
        request=dict(coverage_source_id='annual-coverage',allocation_month='2026-01',expected_revision=0)
        draft=workspace.action('prepaid-proposals',request)
        assert workspace.state()['journal_count']==1
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        receipt=workspace.action('approve-post',confirmation)
        workspace=Workspace(directory)
        assert workspace.action('prepaid-proposals',request)==draft
        assert workspace.action('approve-post',confirmation)==receipt
        state=workspace.state();report=state['prepaid']
        assert [report[k] for k in ('principal_amount','consumed_amount','remaining_amount','control_amount','unassigned_control_amount')]==['1200.00','100.00','1100.00','1100.00','0.00']
        assert state['journal_count']==2
        cash=[line for journal in state['journals'] for line in journal['lines'] if line['account']=='1000']
        assert cash==[dict(account='1000',side='credit',amount='1200.00')]
        workspace.action('operation-sources',dict(document=dict(coverage,document_id='duplicate-coverage')))
        try: workspace.action('prepaid-proposals',dict(request,coverage_source_id='duplicate-coverage'))
        except ValueError: pass
        else: raise AssertionError('duplicate coverage was accepted')
        print('Original prepaid principal 1200.00 USD; explicit January–December equal-months-cents-v1 coverage.')
        print('Before human confirmation: one purchase journal. After: debit 5200 / credit 1200 exactly 100.00 USD.')
        print('Supported remaining 1100.00 USD; 1200 control 1100.00 USD; unassigned residual 0.00 USD.')
        print('Original Cash credit 1200.00 USD remains the only cash movement; duplicate coverage refused.')
        print('Restart and exact retries preserve one consumption; approval:',receipt['approval_id'])
        print('Snapshot:',report['snapshot_digest'],'; zero model calls.')
