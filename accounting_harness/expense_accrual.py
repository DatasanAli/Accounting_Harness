"""The two supported whole accruals, sharing evidence and posting safeguards."""
import hashlib
import json
from dataclasses import asdict, dataclass
from contextlib import nullcontext

from accounting_harness.approval import ReviewApplication
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import Finding
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS, SQLiteLedger, _canonical
from accounting_harness.review import SQLiteReviewStore, digest, protect_table
from accounting_harness.sources import _content

POLICY = 'expense-accrual-v1'


def accrual_policy(policy):
    """The two delivered whole-amount accrual policies; no configurable templates."""
    if policy == POLICY:
        return dict(name='expense', role='incurrence', kind='incurred_expense', date='incurred_date',
                    party='vendor', claim='expense_recognition', control='2050', account='expense_account',
                    side='credit', recognition_side='debit', accounts="'5000','5100'")
    if policy == 'revenue-accrual-v1':
        return dict(name='revenue', role='completion', kind='service_completion', date='completion_date',
                    party='customer', claim='service_revenue_recognition', control='1150', account='revenue_account',
                    side='debit', recognition_side='credit', accounts="'4000'")
    raise ValueError('unsupported accrual policy')


def operation(store, incurrence_source_id, basis_source_id):
    policy = accrual_policy(store.policy_version)
    name, role = policy['name'], policy['role']
    if incurrence_source_id == basis_source_id:
        raise ValueError(role+' and basis must be distinct documents')
    records=[]; documents=[]
    for source_id in (incurrence_source_id,basis_source_id):
        record=store.registry.get(source_id)
        anchor=store.db.execute('SELECT content_digest,canonical_content FROM source_enrollments WHERE source_id=?',(source_id,)).fetchone()
        if anchor != (record.content_digest,record.canonical_content) or hashlib.sha256(record.canonical_content.encode()).hexdigest()!=record.content_digest:
            raise ValueError(name+' accrual requires unchanged anchored evidence')
        document=dict(json.loads(record.canonical_content),entity_id=record.entity_id,document_id=record.document_id)
        _content(document,record.entity_id)
        records.append(record);documents.append(document)
    incurrence,basis=documents
    if incurrence['kind']!=policy['kind'] or basis['kind']!=name+'_accrual_basis':
        raise ValueError('separate '+policy['kind']+' and '+name+' accrual basis required')
    for field in ('entity_id','currency','event_id','counterparty_id','amount'):
        if incurrence[field]!=basis[field]:raise ValueError(role+' and basis differ in '+field)
    period=store.ledger._empty
    cutoff=period.period_end.isoformat()
    if period.period_start.isoformat()!='2026-01-01' or cutoff!='2026-01-31':
        raise ValueError(name+' accrual supports the configured January 2026 period only')
    if (basis['document_date']!=cutoff or basis['cutoff_date']!=cutoff
            or incurrence[policy['date']]!=incurrence['document_date']
            or not period.period_start.isoformat()<=incurrence[policy['date']]<=cutoff):
        raise ValueError(role+' must be in January on/before the January 31 basis cutoff')
    principal=Money.parse(incurrence['amount']).cents
    if principal>MAX_CENTS:raise ValueError('principal exceeds storage limits')
    identity=digest([incurrence['entity_id'],incurrence['event_id']])
    intent=dict(schema_version=1,kind=name+'_accrual',entity_id=incurrence['entity_id'],event_id=incurrence['event_id'],
        currency=incurrence['currency'],principal_cents=principal,
        effective_date=cutoff,
        evidence_roles={role:incurrence_source_id,'basis':basis_source_id})
    intent[policy['party']+'_id']=incurrence['counterparty_id']
    account=incurrence['expense_account'] if name=='expense' else '4000'
    intent[policy['account']]=account
    proposal=dict(id='journal:'+name+'-accrual:'+identity,entity_id=incurrence['entity_id'],currency=incurrence['currency'],
        effective_date=cutoff,description='Supported unbilled '+name+': '+incurrence['event_id'],source_ids=[incurrence_source_id,basis_source_id],
        lines=([dict(account=account,side='debit',amount=incurrence['amount']),
                dict(account='2050',side='credit',amount=incurrence['amount'])] if name=='expense' else
               [dict(account='1150',side='debit',amount=incurrence['amount']),
                dict(account='4000',side='credit',amount=incurrence['amount'])]))
    return name+'-accrual:'+identity,intent,proposal,{r.document_id:r.content_digest for r in records}


def validate_expense_accrual(store,proposal,records,intent,draft_id):
    try:
        if type(intent) is not dict or type(intent.get('schema_version')) is not int or type(intent.get('principal_cents')) is not int:
            raise ValueError('expense accrual requires strict integer intent')
        expected=operation(store,intent['evidence_roles'][accrual_policy(store.policy_version)['role']],intent['evidence_roles']['basis'])
        if (draft_id,intent,proposal,{r.document_id:r.content_digest for r in records})!=expected:
            raise ValueError('expense accrual identity, intent or journal differs from supported facts')
    except (ValueError,TypeError,KeyError) as error:
        return (Finding('unsupported_'+accrual_policy(store.policy_version)['name']+'_accrual','operation_intent',str(error)),)
    return ()


def anchor_preparation(store,draft_id,revision,proposal,evidence,intent):
    # Bind each independently reconstructed revision; rejection keeps the shared event claim.
    name=accrual_policy(store.policy_version)['name']
    store.db.execute(f'INSERT INTO {name}_accrual_preparations VALUES(?,?,?,?,?)',
        (draft_id,revision,_canonical(proposal),_canonical(intent),_canonical(evidence)))


class ExpenseAccrualService:
    policy_version = POLICY
    def __init__(self,ledger,registry):
        self.ledger,self.registry,self.db=ledger,registry,ledger._connection
        with (nullcontext() if self.db.in_transaction else ledger._transaction(write=True)):
            ledger._migrate_v5()
            self.store=SQLiteReviewStore(ledger,registry,policy_version=self.policy_version)
            self.app=ReviewApplication(self.store)
            self._initialize()

    @classmethod
    def approval_match(cls,effect):
        p=accrual_policy(cls.policy_version)
        return f'''EXISTS (SELECT 1 FROM approvals a JOIN draft_revisions r USING(draft_id,revision)
            JOIN draft_operation_intents i USING(draft_id,revision)
            JOIN {p['name']}_accrual_preparations p USING(draft_id,revision)
            JOIN operation_claims c ON c.draft_id=r.draft_id AND c.role='{p['claim']}'
            WHERE a.approval_id={effect}.approval_id AND r.draft_id={effect}.draft_id AND r.revision={effect}.revision
              AND r.policy_version='{cls.policy_version}' AND r.state='pending'
              AND r.revision=(SELECT max(revision) FROM draft_revisions WHERE draft_id=r.draft_id)
              AND json_extract(a.binding_json,'$.revision_digest')=r.content_digest
              AND json_extract(a.binding_json,'$.policy_version')='{cls.policy_version}'
              AND json_extract(a.binding_json,'$.action')='post'
              AND json_extract(a.binding_json,'$.entity_id')={effect}.entity_id
              AND json_extract(a.binding_json,'$.draft_id')=r.draft_id
              AND json_extract(a.binding_json,'$.revision')=r.revision
              AND json_extract(a.binding_json,'$.evidence')=p.evidence_json
              AND r.proposal_json=p.proposal_json AND r.evidence_json=p.evidence_json AND i.intent_json=p.intent_json
              AND json_extract(p.proposal_json,'$.id')={effect}.journal_id
              AND json_extract(i.intent_json,'$.entity_id')={effect}.entity_id
              AND json_extract(i.intent_json,'$.event_id')={effect}.event_id
              AND c.entity_id={effect}.entity_id AND c.event_id={effect}.event_id
              AND json_extract(i.intent_json,'$.{p['party']}_id')={effect}.{p['party']}_id
              AND json_extract(i.intent_json,'$.principal_cents')={effect}.principal_cents
              AND json_extract(i.intent_json,'$.{p['account']}')={effect}.{p['account']}
              AND json_extract(i.intent_json,'$.effective_date')={effect}.cutoff_date
              AND json_extract(i.intent_json,'$.evidence_roles.{p['role']}')={effect}.{p['role']}_source_id
              AND json_extract(i.intent_json,'$.evidence_roles.basis')={effect}.basis_source_id)'''

    def _initialize(self):
        p=accrual_policy(self.policy_version)
        if self.db.execute(f"SELECT 1 FROM sqlite_master WHERE name='{p['name']}_accrual_schema'").fetchone():
            if self.db.execute(f'SELECT version FROM {p['name']}_accrual_schema').fetchall()!=[(1,)]:raise ValueError('unsupported '+p['name']+' accrual schema')
            return
        if self.db.execute(f"SELECT 1 FROM lines WHERE account='{p['control']}'").fetchone():
            raise ValueError('accrual control requires zero unexplained opening balance')
        self.db.execute(f'CREATE TABLE {p['name']}_accrual_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
        self.db.execute(f'INSERT INTO {p['name']}_accrual_schema VALUES(1)')
        self.db.execute(f'''CREATE TABLE {p['name']}_accrual_preparations(
            draft_id TEXT NOT NULL,revision INTEGER NOT NULL,proposal_json TEXT NOT NULL,intent_json TEXT NOT NULL,evidence_json TEXT NOT NULL,
            PRIMARY KEY(draft_id,revision), FOREIGN KEY(draft_id,revision) REFERENCES draft_revisions(draft_id,revision)
            DEFERRABLE INITIALLY DEFERRED) STRICT, WITHOUT ROWID''')
        self.db.execute(f'''CREATE TABLE {p['name']}_accrual_effects(
            entity_id TEXT NOT NULL REFERENCES ledger_context(entity_id),event_id TEXT NOT NULL,{p['party']}_id TEXT NOT NULL,
            {p['role']}_source_id TEXT NOT NULL REFERENCES source_enrollments(source_id),
            basis_source_id TEXT NOT NULL REFERENCES source_enrollments(source_id),
            principal_cents INTEGER NOT NULL CHECK(principal_cents>0),{p['account']} TEXT NOT NULL CHECK({p['account']} IN ({p['accounts']})),
            cutoff_date TEXT NOT NULL,draft_id TEXT NOT NULL,revision INTEGER NOT NULL,
            approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
            journal_id TEXT NOT NULL UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
            PRIMARY KEY(entity_id,event_id), FOREIGN KEY(draft_id,revision) REFERENCES {p['name']}_accrual_preparations(draft_id,revision)
            ) STRICT, WITHOUT ROWID''')
        for table,conflict in [(f"{p['name']}_accrual_schema",'1'),
            (f"{p['name']}_accrual_preparations",'draft_id=NEW.draft_id AND revision=NEW.revision'),
            (f"{p['name']}_accrual_effects",'approval_id=NEW.approval_id OR journal_id=NEW.journal_id OR (entity_id=NEW.entity_id AND event_id=NEW.event_id)')]:
            protect_table(self.db,table,conflict)
        self.db.execute(f'''CREATE TRIGGER {p['name']}_accrual_approved_effect BEFORE INSERT ON {p['name']}_accrual_effects
            WHEN NOT {self.approval_match('NEW')} OR EXISTS(SELECT 1 FROM posting_events WHERE journal_id=NEW.journal_id)
            BEGIN SELECT RAISE(ABORT,'{p['name']} accrual effect requires current exact approval'); END''')
        self.db.execute(f'''CREATE TRIGGER {p['name']}_accrual_post_guard BEFORE INSERT ON posting_events
            WHEN EXISTS(SELECT 1 FROM lines WHERE journal_id=NEW.journal_id AND account='{p['control']}')
              OR EXISTS(SELECT 1 FROM {p['name']}_accrual_effects WHERE journal_id=NEW.journal_id)
              OR EXISTS(SELECT 1 FROM journal_sources js JOIN source_enrollments s ON js.source_id=s.source_id
                WHERE js.journal_id=NEW.journal_id AND json_extract(s.canonical_content,'$.kind')='{p['name']}_accrual_basis')
            BEGIN SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM {p['name']}_accrual_effects f JOIN journals j ON j.id=f.journal_id
                WHERE f.journal_id=NEW.journal_id AND j.entity_id=f.entity_id AND j.currency='USD' AND j.effective_date=f.cutoff_date
                  AND {self.approval_match('f')}
                  AND (SELECT count(*) FROM lines WHERE journal_id=j.id)=2
                  AND EXISTS(SELECT 1 FROM lines WHERE journal_id=j.id AND account=f.{p['account']} AND side='{p['recognition_side']}' AND cents=f.principal_cents)
                  AND EXISTS(SELECT 1 FROM lines WHERE journal_id=j.id AND account='{p['control']}' AND side='{p['side']}' AND cents=f.principal_cents)
                  AND (SELECT count(*) FROM journal_sources WHERE journal_id=j.id)=2
                  AND EXISTS(SELECT 1 FROM journal_sources WHERE journal_id=j.id AND source_id=f.{p['role']}_source_id)
                  AND EXISTS(SELECT 1 FROM journal_sources WHERE journal_id=j.id AND source_id=f.basis_source_id)
            ) THEN RAISE(ABORT,'{p['control']} posting requires exact current approved {p['name']} accrual effect') END; END''')
        self.db.execute(f'''CREATE TRIGGER {p['name']}_accrual_reversal_dependency BEFORE INSERT ON reversals
            WHEN EXISTS(SELECT 1 FROM {p['name']}_accrual_effects WHERE journal_id=NEW.original_id)
            BEGIN SELECT RAISE(ABORT,'{p['name']} accrual requires linked correction policy'); END''')

    def propose(self,*,incurrence_source_id,basis_source_id,expected_revision,actor_id,idempotency_key):
        return self._propose(incurrence_source_id,basis_source_id,expected_revision,actor_id,idempotency_key)

    def _propose(self,source_id,basis_source_id,expected_revision,actor_id,idempotency_key):
        self.store._inputs(source_id,expected_revision,actor_id,idempotency_key,'prepare accrual')
        with self.ledger._transaction(write=True):
            draft_id,intent,proposal,evidence=operation(self.store,source_id,basis_source_id)
            if self.policy_version == POLICY:
                self.ledger._ensure_expense_accrual_account(actor_id=actor_id)
            else:
                self.ledger._ensure_revenue_accrual_account(actor_id=actor_id)
            return self.store.save(draft_id,proposal,evidence=evidence,operation_intent=intent,
                expected_revision=expected_revision,actor_id=actor_id,idempotency_key=idempotency_key,
                reason=('Explicit incurred unbilled/unpaid expense; separate human confirmation required' if self.policy_version==POLICY else
                        'Explicit completed unbilled/uncollected service; separate human confirmation required'))

    def _snapshot(self,policy=None):
        p=accrual_policy(policy or self.policy_version)
        effects=tuple(self.db.execute(f"SELECT * FROM {p['name']}_accrual_effects ORDER BY entity_id,event_id"))
        sources=tuple(self.db.execute(f"""SELECT source_id,canonical_content,content_digest FROM source_enrollments
            WHERE source_id IN (SELECT {p['role']}_source_id FROM {p['name']}_accrual_effects)
            OR source_id IN (SELECT basis_source_id FROM {p['name']}_accrual_effects) ORDER BY source_id"""))
        return ExpenseAccrualSnapshot(self.ledger._snapshot(),effects,sources,self.ledger._context)

    def snapshot(self):
        with self.ledger._transaction():
            return self._snapshot()


def prepare_expense_accrual_post(store,approval,revision,entry):
    intent=json.loads(revision.operation_intent_json)
    findings=store.validate(json.loads(revision.proposal_json),json.loads(revision.evidence_json),operation_intent=intent,draft_id=revision.draft_id)
    if findings:raise ValueError('expense accrual no longer valid: '+findings[0].message)
    p=accrual_policy(store.policy_version)
    store.db.execute(f"INSERT INTO {p['name']}_accrual_effects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (intent['entity_id'],intent['event_id'],intent[p['party']+'_id'],intent['evidence_roles'][p['role']],intent['evidence_roles']['basis'],
         intent['principal_cents'],intent[p['account']],intent['effective_date'],revision.draft_id,revision.revision,approval.approval_id,entry.id))


@dataclass(frozen=True,slots=True)
class ExpenseAccrualSnapshot:
    ledger: object
    effects: tuple
    sources: tuple
    ledger_context: str


def expense_accrual_report(snapshot,*,as_of):
    return _accrual_report(snapshot,as_of=as_of,policy=POLICY)


def _accrual_report(snapshot,*,as_of,policy):
    p=accrual_policy(policy)
    cutoff=accounting_date(as_of).isoformat()
    if not snapshot.ledger.period_start.isoformat()<=cutoff<=snapshot.ledger.period_end.isoformat():
        raise ValueError('report cutoff must be inside captured ledger period')
    entries=[e for e in snapshot.ledger.entries if e.effective_date.isoformat()<=cutoff]
    control=sum(l.amount.cents*(1 if l.side==p['side'] else -1) for e in entries for l in e.lines if l.account==p['control'])
    sources={s[0]:dict(document=json.loads(s[1]),content_digest=s[2]) for s in snapshot.sources}
    rows=[]
    for effect in snapshot.effects:
        if effect[7]>cutoff:continue
        row=dict(zip(('entity_id','event_id',p['party']+'_id',p['role']+'_source_id','basis_source_id','principal_cents',p['account'],
            'cutoff_date','draft_id','revision','approval_id','journal_id'),effect))
        row['principal_amount']=str(Money(row['principal_cents']))
        row['evidence']={key:sources[key] for key in (row[p['role']+'_source_id'],row['basis_source_id'])}
        row[p['party']+'_name']=sources[row[p['role']+'_source_id']]['document']['counterparty']
        row['trace_json']=json.dumps(row,sort_keys=True,indent=2)
        rows.append(row)
    principal=sum(r['principal_cents'] for r in rows)
    report=dict(schema_version=1,report_policy='outstanding-expense-accruals-v1',as_of=cutoff,obligations=rows,
        principal_cents=principal,control_cents=control,unassigned_control_cents=control-principal,
        snapshot_digest=digest([snapshot.ledger_context,asdict(snapshot.ledger.catalog),snapshot.effects,snapshot.sources,
            [SQLiteLedger._entry_payload(e) for e in snapshot.ledger.entries]]))
    if policy != POLICY:
        report.update(schema_version=2,report_policy='outstanding-revenue-accruals-v2',assets=report.pop('obligations'))
    for key in ('principal','control','unassigned_control'):
        cents=report[key+'_cents'];report[key+'_amount']=('-' if cents<0 else '')+str(Money(abs(cents)))
    report['report_digest']=digest(report)
    return report


def demo_expense_accrual():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='accounting-expense-accrual-') as directory:
        workspace=Workspace(directory)
        common=dict(schema_version=2,synthetic=True,entity_id=workspace.catalog.entity_id,currency='USD',
            event_id='software-january',counterparty_id='fictional-software-vendor',counterparty='Fictional Software Vendor',amount='150.00')
        incurrence=dict(common,document_id='software-incurrence',kind='incurred_expense',document_date='2026-01-28',
            incurred_date='2026-01-28',expense_account='5100',description='Synthetic software service incurred January 28')
        basis=dict(common,document_id='software-cutoff',kind='expense_accrual_basis',document_date='2026-01-31',
            cutoff_date='2026-01-31',status='unbilled_unpaid',description='Operator-supported whole expense remains unbilled and unpaid at cutoff')
        for document in (incurrence,basis):workspace.action('operation-sources',dict(document=document))
        request=dict(incurrence_source_id=incurrence['document_id'],basis_source_id=basis['document_id'],expected_revision=0)
        draft=workspace.action('expense-accrual-proposals',request)
        assert workspace.state()['journal_count']==0
        print('Pending expense accrual: 150.00 USD; posted journals: 0; separate human confirmation required.')
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        posted=workspace.action('approve-post',confirmation)
        state=workspace.state();report=state['expense_accruals']
        assert report['principal_cents']==report['control_cents']==15000 and report['unassigned_control_cents']==0
        with workspace.storage() as (_,ledger,_,_,_):
            lines=ledger.snapshot.entries[0].lines
            assert [(l.account,l.side,l.amount.cents) for l in lines]==[('5100','debit',15000),('2050','credit',15000)]
        print('Software Expense debit 150.00; Accrued Expenses credit 150.00; Cash/AP unchanged.')
        print('Outstanding unbilled obligations: 150.00; 2050 control: 150.00; residual: 0.00.')
        bill=dict(common,document_id='later-bill',kind='vendor_bill',document_date='2026-01-28',due_date='2026-01-31',
            bill_number='LATER-001',description='Synthetic later vendor bill for the same incurrence event')
        workspace.action('operation-sources',dict(document=bill))
        try:workspace.action('bill-proposals',dict(bill_source_id=bill['document_id'],incurrence_source_id=incurrence['document_id']))
        except ValueError as error:
            assert 'duplicate economic event' in str(error)
            print('Duplicate bill recognition refused:',error)
        else:raise AssertionError('duplicate bill recognized the expense twice')
        workspace=Workspace(directory)
        assert workspace.action('approve-post',confirmation)==posted
        assert workspace.action('expense-accrual-proposals',request)==draft
        assert workspace.state()['journal_count']==1
        print('Restart and exact retries retain one immutable obligation and journal.')
        print('Report:',report['report_policy'],report['snapshot_digest'])
