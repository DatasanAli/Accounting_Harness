"""Explicit local human close of the configured owner-capital period."""
import hashlib
import json
from datetime import datetime, timezone

from accounting_harness.bank import identifier
from accounting_harness.domain.money import Money
from accounting_harness.financial_reports import _capture_financials, financial_statements, _amount
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest, protect_table

POLICY = 'owner-capital-complete-period-close-v1'


def initialize_close(ledger):
    """Called inside ledger initialization; all DDL rolls back with its caller."""
    db = ledger._connection
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='period_close_schema'").fetchone():
        if db.execute('SELECT version FROM period_close_schema').fetchall() != [(1,)]:
            raise ValueError('unsupported period close schema')
        return
    db.execute('CREATE TABLE period_close_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
    db.execute('INSERT INTO period_close_schema VALUES(1)')
    db.execute('''CREATE TABLE period_closes(
        period_start TEXT PRIMARY KEY, period_end TEXT NOT NULL UNIQUE,
        journal_id TEXT UNIQUE REFERENCES posting_events(journal_id) DEFERRABLE INITIALLY DEFERRED,
        actor_id TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
        payload_digest TEXT NOT NULL, result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        CHECK(period_start<=period_end)) STRICT, WITHOUT ROWID''')
    protect_table(db,'period_close_schema','1')
    protect_table(db,'period_closes','period_start=NEW.period_start OR period_end=NEW.period_end OR idempotency_key=NEW.idempotency_key OR journal_id=NEW.journal_id')
    # The close record precedes its exact journal in the same transaction. A
    # deferred FK prevents committing its lock without the journal's final seal.
    db.execute('''CREATE TRIGGER closed_period_posting_seal BEFORE INSERT ON posting_events
        WHEN EXISTS(SELECT 1 FROM period_closes c JOIN journals j ON j.id=NEW.journal_id
            WHERE j.effective_date BETWEEN c.period_start AND c.period_end AND NOT (
                c.journal_id IS NOT NULL AND c.journal_id=NEW.journal_id AND c.actor_id=NEW.actor_id
                AND j.effective_date=c.period_end
                AND j.description=json_extract(c.result_json,'$.preview.journal.description')
                AND (SELECT count(*) FROM lines WHERE journal_id=j.id)=json_array_length(c.result_json,'$.preview.journal.lines')
                AND NOT EXISTS(SELECT 1 FROM lines l WHERE l.journal_id=j.id AND NOT EXISTS(
                    SELECT 1 FROM json_each(c.result_json,'$.preview.journal.lines') p
                    WHERE CAST(p.key AS INTEGER)=l.position AND json_extract(p.value,'$.account')=l.account
                    AND json_extract(p.value,'$.side')=l.side
                    AND CAST(json_extract(p.value,'$.cents') AS INTEGER)=l.cents))
                AND (SELECT count(*) FROM journal_sources WHERE journal_id=j.id)=1
                AND (SELECT source_id FROM journal_sources WHERE journal_id=j.id)=json_extract(c.result_json,'$.preview.artifact.document_id')
            ))
        BEGIN SELECT RAISE(ABORT,'period is closed; posting date is locked'); END''')


class CloseService:
    def __init__(self, ledger, registry):
        self.ledger, self.db, self.registry = ledger, ledger._connection, registry
        # Reuse the delivered services and their capture policies. Constructors
        # initialize schema only; they do not activate subsidiary controls.
        from accounting_harness.payables import PayablesService
        from accounting_harness.receivables import ReceivablesService
        from accounting_harness.advances import AdvancesService
        from accounting_harness.prepaid import PrepaidService
        from accounting_harness.revenue_accrual import RevenueAccrualService
        from accounting_harness.reconciliation import ReconciliationService
        PayablesService(ledger,registry); ReceivablesService(ledger,registry); AdvancesService(ledger,registry)
        self.prepaid=PrepaidService(ledger,registry)
        self.accrual=RevenueAccrualService(ledger,registry)
        self.bank=ReconciliationService(ledger)

    def recorded(self):
        row=self.db.execute('SELECT result_json FROM period_closes').fetchone()
        return json.loads(row[0]) if row else None

    def _request(self,data,confirm=False):
        expected={'period_start','period_end','selections'}
        if confirm: expected|={'confirmed_digest','confirmed','idempotency_key'}
        if type(data) is not dict or set(data)!=expected:
            raise ValueError('close request requires exactly: '+', '.join(sorted(expected)))
        if (data['period_start'],data['period_end']) != ('2026-01-01','2026-01-31') or (
            self.ledger._empty.period_start.isoformat(),self.ledger._empty.period_end.isoformat()) != ('2026-01-01','2026-01-31'):
            raise ValueError('close supports only the complete configured period January 1–31, 2026')
        if type(data['selections']) is not list:
            raise ValueError('selections must be a list')
        accounts=set()
        for selection in data['selections']:
            if type(selection) is not dict or set(selection)!={'bank_account_id','statement_id','completion_id'}:
                raise ValueError('each selection requires bank_account_id, statement_id and completion_id')
            for key,value in selection.items(): identifier(value,key)
            if selection['bank_account_id'] in accounts: raise ValueError('only one statement per bank account may be selected')
            accounts.add(selection['bank_account_id'])
        if confirm:
            if data['confirmed'] is not True: raise ValueError('separate explicit human confirmation required')
            identifier(data['confirmed_digest'],'confirmed_digest'); identifier(data['idempotency_key'],'idempotency_key')

    def _readiness(self,selections):
        from accounting_harness import payables, receivables, advances
        from accounting_harness.prepaid import prepaid_report
        from accounting_harness.expense_accrual import expense_accrual_report
        from accounting_harness.revenue_accrual import revenue_accrual_report
        from accounting_harness.reconciliation import reconciliation_report
        controls=[]; findings=[]
        for module,context in [(payables,'payables_context'),(receivables,'receivables_context'),(advances,'advances_context')]:
            report=getattr(module,module.__name__.rsplit('.',1)[-1]+'_report')(module._snapshot(self.ledger,self.registry),as_of='2026-01-31')
            activated=bool(self.db.execute('SELECT 1 FROM '+context).fetchone())
            controls.append(dict(control=context,activated=activated,residual_cents=str(report['unassigned_control_cents']),snapshot_digest=report['snapshot_digest']))
        report=prepaid_report(self.prepaid._snapshot(),as_of='2026-01-31')
        controls.append(dict(control='prepaid',activated=bool(report['policies']),residual_cents=str(report['unassigned_control_cents']),snapshot_digest=report['snapshot_digest']))
        for name,policy,render in [('expense_accrual','expense-accrual-v1',expense_accrual_report),('revenue_accrual','revenue-accrual-v1',revenue_accrual_report)]:
            snapshot=self.accrual._snapshot(policy=policy)
            report=render(snapshot,as_of='2026-01-31')
            controls.append(dict(control=name,activated=bool(snapshot.effects),residual_cents=str(report['unassigned_control_cents']),snapshot_digest=report['snapshot_digest']))
        for item in controls:
            if item['activated'] and int(item['residual_cents']): findings.append(item['control']+' subsidiary control does not reconcile')
        statements=[json.loads(r[0]) for r in self.db.execute('SELECT statement_json FROM bank_statements ORDER BY bank_account_id,statement_id')]
        covering=[s for s in statements if s['period_start']<='2026-01-01' and s['period_end']>='2026-01-31']
        overlapping=[s for s in statements if s['period_start']<='2026-01-31' and s['period_end']>='2026-01-01']
        selected={s['bank_account_id']:s for s in selections}; bank=[]
        required={s['bank_account_id'] for s in covering}
        if set(selected)-required: raise ValueError('selected statement must cover the configured period')
        for account in sorted(required):
            options=[s for s in covering if s['bank_account_id']==account]
            selection=selected.get(account)
            if not selection:
                findings.append('Select a statement and recorded completion for bank account '+account)
                bank.append(dict(bank_account_id=account,options=options,selection=None));continue
            if selection['statement_id'] not in {s['statement_id'] for s in options}:
                raise ValueError('selected statement must cover the configured period')
            capture=self.bank._capture(account,selection['statement_id'])
            report=reconciliation_report(capture)
            completions=[json.loads(r[0]) for r in self.db.execute('SELECT completion_json FROM reconciliation_completions WHERE bank_account_id=? AND statement_id=? ORDER BY completion_id',(account,selection['statement_id']))]
            completion=next((c for c in completions if c['completion_id']==selection['completion_id']),None)
            current=bool(completion and completion['report']['digest']==report['digest'] and report['can_complete'])
            if not current: findings.append('Bank reconciliation is unresolved or stale for '+account)
            bank.append(dict(bank_account_id=account,options=options,selection=selection,current=current,report=report,completion=completion))
        return dict(controls=controls,bank=bank,overlapping_statements=overlapping),findings

    def _preview(self,data):
        statements=financial_statements(_capture_financials(self.ledger,'2026-01-31'))
        catalog=statements['catalog']; balances=[]; lines=[]; net=0
        for account in catalog:
            if not account['active'] or not account['temporary']: continue
            if account['classification'] not in ('revenue','expense') and account['code']!='3100':
                raise ValueError('unsupported temporary account for owner close policy')
            cents=sum(int(l['cents'])*(1 if l['side']=='debit' else -1)
                for e in statements['capture']['entries'] if e['context']['classification']=='ordinary'
                for l in e['lines'] if l['account']==account['code'])
            balances.append(dict(account=account['code'],name=account['name'],net_debit_cents=str(cents),amount=_amount(cents)))
            if cents:
                lines.append(dict(account=account['code'],side='credit' if cents>0 else 'debit',cents=str(abs(cents)),amount=str(Money(abs(cents)))))
                net+=cents
        capital=next(a for a in catalog if a['code']=='3000')
        if capital['temporary'] or not capital['active']: raise ValueError('Owner Capital must be permanent and active')
        if net: lines.append(dict(account='3000',side='debit' if net>0 else 'credit',cents=str(abs(net)),amount=str(Money(abs(net)))))
        readiness,findings=self._readiness(data['selections'])
        if not statements['balance_sheet']['reconciled']: findings.append('Financial statements do not reconcile')
        core=dict(policy=POLICY,period_start=data['period_start'],period_end=data['period_end'],
            effective_date=data['period_end'],entity_id=statements['entity_id'],currency='USD',
            selections=data['selections'],statements=statements,temporary_balances=balances,
            capital_transfer_cents=str(-net),capital_transfer_amount=_amount(-net),proposed_lines=lines,
            readiness=readiness,findings=findings,can_close=not findings,
            source_ids=sorted({s for e in statements['capture']['entries'] for s in e['source_ids']}),
            journal_ids=statements['included_journal_ids'])
        calculation_digest=digest(core)
        artifact=journal=None
        if lines:
            from accounting_harness.sources import _content
            artifact=dict(schema_version=2,synthetic=True,entity_id=core['entity_id'],document_id='close-calculation-'+calculation_digest,
                kind='close_calculation',document_date=data['period_end'],currency='USD',
                amount=str(Money(sum(int(l['cents']) for l in lines if l['side']=='debit'))),
                counterparty='Internal period-close calculation',description='Generated calculation only; not external recognition evidence or posting permission',
                calculation_json=_canonical(core),calculation_digest=calculation_digest)
            _,content=_content(artifact,core['entity_id'])
            artifact=dict(artifact,content_digest=hashlib.sha256(content.encode()).hexdigest())
            journal=dict(id='close-'+calculation_digest,entity_id=core['entity_id'],currency='USD',effective_date=data['period_end'],
                description='Closing temporary accounts to Owner Capital · '+POLICY,source_ids=[artifact['document_id']],lines=lines)
        preview=dict(core,artifact=artifact,journal=journal,calculation_digest=calculation_digest)
        preview['digest']=digest(preview)
        return preview

    def preview(self,data):
        self._request(data)
        with self.ledger._transaction():
            if self.recorded(): raise ValueError('period is already closed')
            preview=self._preview(data)
        if preview['can_close'] and preview['artifact']:
            artifact={k:v for k,v in preview['artifact'].items() if k!='content_digest'}
            result=self.registry.register(artifact,actor_id='close-calculation-service')
            # Separate source file: registration may survive enrollment failure.
            # A retry with the same preview or startup recovery enrolls it.
            from accounting_harness.workspace import Workspace
            Workspace._enroll_registered(self.registry,self.ledger,result)
        return preview

    def confirm(self,data,*,actor_id):
        self._request(data,confirm=True); identifier(actor_id,'actor_id')
        payload_digest=digest(dict(data=data,actor_id=actor_id,policy=POLICY))
        with self.ledger._transaction(write=True):
            prior=self.db.execute('SELECT payload_digest,result_json FROM period_closes WHERE idempotency_key=?',(data['idempotency_key'],)).fetchone()
            if prior:
                if prior[0]!=payload_digest: raise ValueError('close retry conflicts with original payload or actor')
                return json.loads(prior[1])
            if self.recorded(): raise ValueError('period is already closed')
            preview=self._preview(data)
            if preview['digest']!=data['confirmed_digest']: raise ValueError('close preview is stale; capture and review again')
            if not preview['can_close']: raise ValueError('close readiness failed: '+'; '.join(preview['findings']))
            artifact=preview['artifact']; entry=None
            if artifact:
                enrolled=self.db.execute('SELECT content_digest FROM source_enrollments WHERE source_id=?',(artifact['document_id'],)).fetchone()
                if enrolled!=(artifact['content_digest'],): raise ValueError('close calculation enrollment pending; prepare preview again')
                proposal=dict(preview['journal'],lines=[{k:v for k,v in line.items() if k!='cents'} for line in preview['journal']['lines']])
                entry=self.ledger._validate_entry(proposal)
            now=datetime.now(timezone.utc).isoformat()
            result=dict(close_id='period-close-'+digest([preview['digest'],actor_id,data['idempotency_key']]),
                state='closed',period_start=data['period_start'],period_end=data['period_end'],
                actor_id=actor_id,recorded_at=now,policy=POLICY,confirmed_digest=data['confirmed_digest'],
                approval_id='close-approval-'+payload_digest,idempotency_key=data['idempotency_key'],
                journal_id=entry.id if entry else None,preview=preview)
            self.db.execute('INSERT INTO period_closes VALUES(?,?,?,?,?,?,?)',
                (data['period_start'],data['period_end'],result['journal_id'],actor_id,data['idempotency_key'],payload_digest,_canonical(result)))
            if entry: self.ledger._store_entry(entry,actor_id)
            return result


def demo_close():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='close-demo-') as directory:
        workspace=Workspace(directory); build_adjusted_month(workspace)
        preview=workspace.action('close-preview',dict(period_start='2026-01-01',period_end='2026-01-31',selections=[]))
        request=dict(period_start=preview['period_start'],period_end=preview['period_end'],selections=[],
            confirmed=True,confirmed_digest=preview['digest'],idempotency_key='demo-close')
        result=workspace.action('close-confirm',request)
        assert workspace.action('close-confirm',request)==result
        state=workspace.state(); rows={r['account']:r for r in state['trial_balance']['rows']}
        assert rows['3000']['credit']=='10900.00' and rows['1000']['debit']=='9400.00'
        assert state['trial_balance']['total_debits']==state['trial_balance']['total_credits']=='11500.00'
        assert workspace.financial_statements('2026-01-31')['income_statement']['net_income_amount']=='1100.00'
        import sqlite3
        with workspace.storage() as (_,ledger,_,_,_):
            proposal=dict(id='refused-late',entity_id=workspace.catalog.entity_id,currency='USD',effective_date='2026-01-31',
                description='Refused synthetic backdate',source_ids=[next(iter(workspace.sources))],lines=[
                    dict(account='1000',side='debit',amount='1.00'),dict(account='4000',side='credit',amount='1.00')])
            try: ledger.admit(proposal,actor_id='demo-human',idempotency_key='refused-late')
            except ValueError as error: assert 'closed' in str(error)
            else: raise AssertionError('closed date accepted a posting')
        print('January closed and locked after separate simulated human confirmation.')
        print('Capital 10900.00; Cash 9400.00; trial balance 11500.00 each; preserved income 1100.00 USD.')
        print('Exact retry preserved one close; backdated posting refused. Approval:',result['approval_id'])
