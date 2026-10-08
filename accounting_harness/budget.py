"""Immutable one-month operating assumptions and dated cash plans, never postings."""
import calendar
import json
import re
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from accounting_harness.domain.dates import accounting_date
from accounting_harness.financial_reports import _total
from accounting_harness.persistence import _canonical
from accounting_harness.project_dimensions import _fields, _text
from accounting_harness.review import digest, protect_table

POLICY = 'service-budget-v1'
UNIT_POLICY = dict(driver='service minutes',rate_unit='USD per service hour',minutes_per_hour=60)
ROUNDING_POLICY = 'half-up once per operating line; fixed amounts unchanged'


def initialize_budget(ledger):
    db=ledger._connection
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='budget_schema'").fetchone():
        if db.execute('SELECT version FROM budget_schema').fetchall() != [(1,)]:
            raise ValueError('unsupported budget schema')
        return
    db.execute('CREATE TABLE budget_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
    db.execute('INSERT INTO budget_schema VALUES(1)')
    db.execute('''CREATE TABLE budget_versions(
        version_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version>0), prior_version_id TEXT UNIQUE REFERENCES budget_versions(version_id),
        idempotency_key TEXT NOT NULL, result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        UNIQUE(entity_id,scenario_id,version), UNIQUE(entity_id,scenario_id,idempotency_key)) STRICT, WITHOUT ROWID''')
    protect_table(db,'budget_schema','1')
    protect_table(db,'budget_versions','''version_id=NEW.version_id OR prior_version_id=NEW.prior_version_id OR
        (entity_id=NEW.entity_id AND scenario_id=NEW.scenario_id AND (version=NEW.version OR idempotency_key=NEW.idempotency_key))''')


def _cents(value):
    if type(value) is not str or not re.fullmatch(r'(0|[1-9][0-9]{0,16})\.[0-9]{2}',value):
        raise ValueError('amount or hourly rate must be a nonnegative canonical USD string with exactly two decimals')
    cents=int(value.replace('.',''))
    if cents>2**63-1: raise ValueError('amount or rate cents exceed signed 64-bit range')
    return cents


def _month(value,ledger):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}',value):
        raise ValueError('month must be YYYY-MM')
    start=accounting_date(value+'-01')
    end=start.replace(day=calendar.monthrange(start.year,start.month)[1])
    if (start,end)!=(ledger._empty.period_start,ledger._empty.period_end):
        raise ValueError('budget month must match the supported January ledger month')
    return start.isoformat(),end.isoformat()


def _rows(value,kind):
    if type(value) is not list or len(value)>100:
        raise ValueError(kind+' must be a list of at most 100 rows')


class BudgetService:
    def __init__(self,ledger):
        self.ledger,self.db=ledger,ledger._connection
        with (nullcontext() if self.db.in_transaction else ledger._transaction(write=True)):
            initialize_budget(ledger)

    def inputs(self,month):
        start,end=_month(month,self.ledger)
        with self.ledger._transaction():
            catalog=self.ledger.current_catalog()
            versions=[json.loads(row[0]) for row in self.db.execute('SELECT result_json FROM budget_versions ORDER BY scenario_id,version')]
            source_ids=sorted(self.ledger.known_source_ids())
        return dict(entity_id=catalog.entity_id,currency=catalog.currency,month=month,period_start=start,period_end=end,policy=POLICY,
            unit_policy=UNIT_POLICY,rounding_policy=ROUNDING_POLICY,
            accounts=[asdict(a) for a in catalog.list_accounts() if a.active and a.classification in ('revenue','expense')],
            source_ids=source_ids,source_policy='Enrolled source identity only; planned cash is still an assumption.',
            versions=[{k:r[k] for k in ('version_id','scenario_id','name','version','prior_version_id','month','actor_id','recorded_at')} for r in versions])

    def get(self,version_id):
        _text(version_id,'version_id')
        row=self.db.execute('SELECT result_json FROM budget_versions WHERE version_id=?',(version_id,)).fetchone()
        if not row: raise ValueError('budget scenario version does not exist')
        return json.loads(row[0])

    def save(self,data,*,actor_id):
        _fields(data,('entity_id','currency','scenario_id','name','month','planned_minutes','opening_cash','operating_lines','cash_rows',
            'prior_version_id','reason','explanation','idempotency_key'))
        for field in ('entity_id','scenario_id','name','reason','idempotency_key'):
            _text(data[field],field,1000 if field=='reason' else 200)
        _text(actor_id,'actor_id')
        if data['entity_id']!=self.ledger._empty.catalog.entity_id or data['currency']!='USD':
            raise ValueError('budget entity and USD currency must match the ledger')
        start,end=_month(data['month'],self.ledger)
        if type(data['planned_minutes']) is not int or not 0<=data['planned_minutes']<=2**53-1:
            raise ValueError('planned_minutes must be a nonnegative safe integer')
        _cents(data['opening_cash'])
        if type(data['explanation']) is not str or len(data['explanation'])>2000: raise ValueError('explanation must be text of at most 2000 characters')
        if data['prior_version_id'] is not None: _text(data['prior_version_id'],'prior_version_id')
        _rows(data['operating_lines'],'operating_lines'); _rows(data['cash_rows'],'cash_rows')
        identities=set()
        for row in data['operating_lines']:
            _fields(row,('line_id','account','behavior','amount')); _text(row['line_id'],'line_id'); _text(row['account'],'account')
            if row['line_id'] in identities: raise ValueError('duplicate operating line ID')
            identities.add(row['line_id'])
            if row['behavior'] not in ('fixed','variable'): raise ValueError('budget line behavior must be fixed or variable')
            _cents(row['amount'])
        cash_ids=set()
        for row in data['cash_rows']:
            _fields(row,('row_id','direction','amount','expected_date','category','budget_line_id','source_reference'))
            _text(row['row_id'],'row_id'); _text(row['category'],'category')
            if row['row_id'] in cash_ids: raise ValueError('duplicate cash row ID')
            cash_ids.add(row['row_id'])
            if row['direction'] not in ('receipt','payment'): raise ValueError('cash direction must be receipt or payment')
            if _cents(row['amount'])==0: raise ValueError('cash row amount must be positive')
            if type(row['expected_date']) is not str: raise ValueError('expected_date must be a calendar string')
            accounting_date(row['expected_date'])
            if row['budget_line_id'] is not None:
                _text(row['budget_line_id'],'budget_line_id')
                if row['budget_line_id'] not in identities: raise ValueError('cash budget linkage must name an operating line in this version')
            reference=row['source_reference']
            if reference is not None:
                _fields(reference,('kind','id')); _text(reference['id'],'source reference')
                if reference['kind'] not in ('actual','external'): raise ValueError('source reference kind must be actual or external')
        payload_digest=digest(dict(data,actor_id=actor_id))
        with self.ledger._transaction(write=True):
            retry=self.db.execute('SELECT result_json FROM budget_versions WHERE entity_id=? AND scenario_id=? AND idempotency_key=?',
                (data['entity_id'],data['scenario_id'],data['idempotency_key'])).fetchone()
            if retry:
                original=json.loads(retry[0])
                if original['payload_digest']!=payload_digest: raise ValueError('budget scenario retry conflict')
                return original
            current=self.db.execute('SELECT version_id,version FROM budget_versions WHERE entity_id=? AND scenario_id=? ORDER BY version DESC LIMIT 1',
                (data['entity_id'],data['scenario_id'])).fetchone()
            if data['prior_version_id']!=(current[0] if current else None): raise ValueError('stale scenario version; choose the current prior version')
            catalog=self.ledger.current_catalog(); captured={}
            for row in data['operating_lines']:
                account=catalog.get_for_posting(row['account'])
                if account.classification not in ('revenue','expense'): raise ValueError('budget account must be active revenue or expense')
                captured[account.code]=asdict(account)
            source_ids=self.ledger.known_source_ids()
            for row in data['cash_rows']:
                ref=row['source_reference']
                if ref and ref['kind']=='actual' and ref['id'] not in source_ids: raise ValueError('actual source reference must be an enrolled source identity')
            # Copy the complete request into its seal: caller-owned lists cannot mutate a returned version.
            result=dict(json.loads(_canonical(data)),version_id='budget-'+uuid4().hex,version=current[1]+1 if current else 1,
                policy=POLICY,unit_policy=UNIT_POLICY.copy(),rounding_policy=ROUNDING_POLICY,period_start=start,period_end=end,
                captured_accounts=captured,verified_source_ids=sorted({r['source_reference']['id'] for r in data['cash_rows'] if r['source_reference'] and r['source_reference']['kind']=='actual'}),
                actor_id=actor_id,recorded_at=datetime.now(timezone.utc).isoformat(),payload_digest=payload_digest)
            result['report']=budget_report(result)
            self.db.execute('INSERT INTO budget_versions VALUES(?,?,?,?,?,?,?)',(result['version_id'],data['entity_id'],data['scenario_id'],result['version'],
                data['prior_version_id'],data['idempotency_key'],_canonical(result)))
            return result


def budget_report(scenario):
    """Pure rendering uses only the sealed assumptions, metadata, and date policy."""
    if scenario['policy']!=POLICY or scenario['unit_policy']!=UNIT_POLICY or scenario['rounding_policy']!=ROUNDING_POLICY:
        raise ValueError('unsupported budget policy')
    report={k:scenario[k] for k in ('entity_id','currency','scenario_id','version_id','version','name','month','period_start','period_end',
        'policy','unit_policy','rounding_policy','planned_minutes','prior_version_id','reason','explanation','actor_id','recorded_at')}
    report.update(scope='Management assumptions only. Budget income, planned collections and recorded cash are separate facts. No posting, payment, borrowing or accounting approval.',
        operating_lines=[],accounts=[],cash_rows=[],deferred_rows=[])
    totals=dict(revenue=0,expense=0,receipts=0,payments=0,deferred_receipts=0,deferred_payments=0)
    accounts={}
    for line in scenario['operating_lines']:
        account=scenario['captured_accounts'][line['account']]; rate=_cents(line['amount'])
        numerator=rate*scenario['planned_minutes'] if line['behavior']=='variable' else rate
        denominator=60 if line['behavior']=='variable' else 1
        cents=(numerator+denominator//2)//denominator
        row=dict(line,account_metadata=account,numerator=str(numerator),denominator=denominator,
            rate_cents=str(rate) if line['behavior']=='variable' else None,rounding=ROUNDING_POLICY,
            rounding_delta_numerator=str(cents*denominator-numerator))
        _total(row,'planned',cents); report['operating_lines'].append(row)
        totals[account['classification']]+=cents
        aggregate=accounts.setdefault(account['code'],dict(account,line_ids=[],total=0))
        aggregate['line_ids'].append(line['line_id']); aggregate['total']+=cents
    for account in accounts.values():
        _total(account,'planned',account.pop('total')); report['accounts'].append(account)
    for line in scenario['cash_rows']:
        reference=line['source_reference']
        if reference is None: status='no source reference; explicit cash assumption'
        elif reference['kind']=='external': status='unsupported external reference; not verified actual evidence'
        elif reference['id'] in scenario['verified_source_ids']: status='verified enrolled source identity; planned cash is still an assumption'
        else: raise ValueError('uncaptured actual source reference')
        current=scenario['period_start']<=line['expected_date']<=scenario['period_end']
        row=dict(line,source_status=status,in_plan_month=current); cents=_cents(line['amount']); _total(row,'planned',cents)
        report['cash_rows' if current else 'deferred_rows'].append(row)
        totals[('' if current else 'deferred_')+('receipts' if line['direction']=='receipt' else 'payments')]+=cents
    totals['income']=totals['revenue']-totals['expense']; totals['opening_cash']=_cents(scenario['opening_cash'])
    totals['ending_cash']=totals['opening_cash']+totals['receipts']-totals['payments']; totals['funding_gap']=max(0,-totals['ending_cash'])
    for name,cents in totals.items(): _total(report,name,cents)
    report['report_digest']=digest(report)
    return report


def demo_budget():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='budget-demo-') as directory:
        workspace=Workspace(directory); before=workspace.report_package('2026-01-31')
        data=dict(entity_id=workspace.catalog.entity_id,currency='USD',scenario_id='cash-plan',name='January cash plan',month='2026-01',
            planned_minutes=0,opening_cash='1000.00',operating_lines=[],cash_rows=[
                dict(row_id='collection',direction='receipt',amount='1500.00',expected_date='2026-01-20',category='customer-collections',budget_line_id=None,source_reference=None),
                dict(row_id='payment',direction='payment',amount='1200.00',expected_date='2026-01-25',category='supplier-payments',budget_line_id=None,source_reference=None)],
            prior_version_id=None,reason='Explicit initial assumptions',explanation='',idempotency_key='cash-v1')
        first=workspace.action('budget',data)
        changed=json.loads(_canonical(data)); changed.update(prior_version_id=first['version_id'],reason='Collection deferred',idempotency_key='cash-v2')
        changed['cash_rows'][0]['expected_date']='2026-02-20'; second=workspace.action('budget',changed)
        operating=dict(data,scenario_id='operating',name='Service activity plan',planned_minutes=480,cash_rows=[],opening_cash='0.00',operating_lines=[
            dict(line_id='sales',account='4000',behavior='variable',amount='125.00'),dict(line_id='variable-cost',account='5100',behavior='variable',amount='50.00'),
            dict(line_id='fixed-cost',account='5100',behavior='fixed',amount='100.00')])
        third=workspace.action('budget',operating)
        assert first['report']['ending_cash_amount']=='1300.00'
        assert (second['report']['ending_cash_amount'],second['report']['funding_gap_amount'],second['report']['deferred_receipts_amount'])==('-200.00','200.00','1500.00')
        assert (third['report']['revenue_amount'],third['report']['expense_amount'])==('1000.00','500.00')
        assert workspace.budget(first['version_id'])==first and workspace.action('budget',data)==first
        assert workspace.report_package('2026-01-31')==before
        print('Cash version 1: opening 1000.00 + receipts 1500.00 - payments 1200.00 = ending 1300.00 USD.')
        print('Cash version 2: February collection; January ending -200.00, funding gap 200.00, deferred receipt 1500.00 USD. No borrowing inserted.')
        print('Separate operating plan: 480 service minutes, revenue 1000.00, expenses 500.00, income 500.00 USD.')
        print('Original version/retry preserved; recorded actuals unchanged. Management assumptions only.')
