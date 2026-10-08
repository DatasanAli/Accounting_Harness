"""Single-service assumptions and captured descriptive indicators; no posting effects."""
import calendar
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

from accounting_harness.budget import _cents, _month
from accounting_harness.domain.dates import accounting_date
from accounting_harness.financial_reports import _capture_financials, financial_statements, _total
from accounting_harness.persistence import _canonical
from accounting_harness.project_dimensions import _fields, _text
from accounting_harness.project_time import _capture_time, time_report
from accounting_harness.report_export import _financial, _timestamp
from accounting_harness.review import digest, protect_table
from accounting_harness.variance import _validate_time

POLICY = 'single-service-indicators-v1'
MENU = {'current_ratio':'Current ratio','quick_ratio':'Quick ratio','net_profit_margin':'Net profit margin',
        'recorded_service_minutes':'Recorded service minutes','revenue_per_service_hour':'Revenue per recorded service hour'}
LIQUIDITY_POLICY = dict(version='synthetic-current-accounts-v1',current_assets=['1000','1100','1150','1200'],
    quick_assets=['1000','1100','1150'],current_liabilities=['2000','2050','2100'],noncurrent_assets=['1500','1590'])
ROUNDING = 'Exact unreduced numerator / denominator; display two decimals half-up, signed ties away from zero. USD/hour rounds once to cents.'
FIELDS = ('entity_id','currency','scenario_id','name','month','price','variable_cost','fixed_cost','minimum_units','maximum_units','quantity',
          'selected_indicators','prior_version_id','reason','explanation','idempotency_key')
META = ('version_id','version','policy','period_start','period_end','actor_id','recorded_at','payload_digest')


def _assumptions(data):
    for field in ('entity_id','scenario_id','name','reason','idempotency_key'):
        _text(data[field],field,1000 if field=='reason' else 200)
    if data['currency']!='USD': raise ValueError('scenario currency must be USD')
    for field in ('price','variable_cost','fixed_cost'): _cents(data[field])
    for field in ('minimum_units','maximum_units','quantity'):
        if field=='quantity' and data[field] is None: continue
        if type(data[field]) is not int or not 0<=data[field]<=2**53-1: raise ValueError(field+' must be a nonnegative safe integer')
    if data['minimum_units']>data['maximum_units']: raise ValueError('minimum units exceed maximum units')
    selected=data['selected_indicators']
    if type(selected) is not list or any(type(k) is not str or k not in MENU for k in selected) or len(set(selected))!=len(selected):
        raise ValueError('selected_indicators must contain unique supported indicator IDs')
    if type(data['explanation']) is not str or len(data['explanation'])>2000: raise ValueError('explanation must be text of at most 2000 characters')
    if data['prior_version_id'] is not None: _text(data['prior_version_id'],'prior_version_id')


def _ratio(numerator,denominator,*,percent=False,cents=False,reason=None):
    result=dict(numerator=str(numerator),denominator=str(denominator),display=None,reason=reason)
    if denominator==0 and reason is None: result['reason']='Zero denominator; indicator unavailable.'
    if result['reason'] is not None: return result
    # Integer arithmetic also handles negative revenue and opposite-side balances.
    sign=-1 if numerator*denominator<0 else 1
    scale=1 if cents else 10000 if percent else 100
    rounded=(abs(numerator)*scale*2+abs(denominator))//(2*abs(denominator))
    result['display']=('-' if sign<0 and rounded else '')+f'{rounded//100}.{rounded%100:02d}'+('%' if percent else '')
    return result


def contribution(scenario):
    """Pure constant economics over an explicit range; outside-range values are labeled."""
    _assumptions(scenario)
    price,variable,fixed=(_cents(scenario[k]) for k in ('price','variable_cost','fixed_cost'))
    amount=price-variable; lower,upper=scenario['minimum_units'],scenario['maximum_units']; quantity=scenario['quantity']
    if amount>0:
        whole=(fixed+amount-1)//amount
        threshold=dict(numerator=str(fixed),denominator=str(amount),whole_units=str(whole),within_range=lower<=whole<=upper,reason=None)
    else:
        reason=('Zero fixed cost and zero contribution: indeterminate threshold; every quantity has zero model profit.' if amount==0 and fixed==0 else
                'Nonpositive contribution: no finite positive profitable break-even under this model.')
        threshold=dict(numerator=str(fixed),denominator=str(amount),whole_units=None,within_range=None,reason=reason)
    result=dict(price=scenario['price'],variable_cost=scenario['variable_cost'],fixed_cost=scenario['fixed_cost'],minimum_units=lower,maximum_units=upper,
        quantity=quantity,quantity_within_range=None if quantity is None else lower<=quantity<=upper,break_even=threshold,
        margin=_ratio(amount,price,percent=True),profit_cents=None,profit_amount=None,
        range_policy='One service, constant price and variable cost per whole service unit; fixed costs constant within the stated relevant range. No sales mix inferred.')
    _total(result,'contribution',amount)
    if quantity is not None: _total(result,'profit',quantity*amount-fixed)
    return result


def initialize_indicators(ledger):
    db=ledger._connection
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='indicator_schema'").fetchone():
        if db.execute('SELECT version FROM indicator_schema').fetchall()!=[(1,)]: raise ValueError('unsupported indicator schema')
        return
    db.execute('CREATE TABLE indicator_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
    db.execute('INSERT INTO indicator_schema VALUES(1)')
    db.execute('''CREATE TABLE indicator_versions(
        version_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version>0), prior_version_id TEXT UNIQUE REFERENCES indicator_versions(version_id),
        idempotency_key TEXT NOT NULL, result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        UNIQUE(entity_id,scenario_id,version), UNIQUE(entity_id,scenario_id,idempotency_key)) STRICT, WITHOUT ROWID''')
    protect_table(db,'indicator_schema','1')
    protect_table(db,'indicator_versions','''version_id=NEW.version_id OR prior_version_id=NEW.prior_version_id OR
        (entity_id=NEW.entity_id AND scenario_id=NEW.scenario_id AND (version=NEW.version OR idempotency_key=NEW.idempotency_key))''')


class IndicatorService:
    def __init__(self,ledger):
        self.ledger,self.db=ledger,ledger._connection
        with (nullcontext() if self.db.in_transaction else ledger._transaction(write=True)):
            initialize_indicators(ledger)

    def inputs(self,month):
        start,end=_month(month,self.ledger)
        with self.ledger._transaction():
            versions=[json.loads(r[0]) for r in self.db.execute('SELECT result_json FROM indicator_versions ORDER BY scenario_id,version')]
        return dict(entity_id=self.ledger._empty.catalog.entity_id,currency='USD',month=month,period_start=start,period_end=end,policy=POLICY,
            menu=MENU.copy(),versions=[{k:r[k] for k in ('version_id','scenario_id','name','version','prior_version_id','month','actor_id','recorded_at')} for r in versions])

    def get(self,version_id):
        _text(version_id,'version_id')
        row=self.db.execute('SELECT result_json FROM indicator_versions WHERE version_id=?',(version_id,)).fetchone()
        if not row: raise ValueError('indicator scenario version does not exist')
        return json.loads(row[0])

    def save(self,data,*,actor_id):
        _fields(data,FIELDS); _assumptions(data); _text(actor_id,'actor_id')
        if data['entity_id']!=self.ledger._empty.catalog.entity_id: raise ValueError('scenario entity must match ledger')
        start,end=_month(data['month'],self.ledger); payload_digest=digest(dict(data,actor_id=actor_id))
        with self.ledger._transaction(write=True):
            retry=self.db.execute('SELECT result_json FROM indicator_versions WHERE entity_id=? AND scenario_id=? AND idempotency_key=?',
                (data['entity_id'],data['scenario_id'],data['idempotency_key'])).fetchone()
            if retry:
                original=json.loads(retry[0])
                if original['payload_digest']!=payload_digest: raise ValueError('indicator scenario retry conflict')
                return original
            current=self.db.execute('SELECT version_id,version FROM indicator_versions WHERE entity_id=? AND scenario_id=? ORDER BY version DESC LIMIT 1',
                (data['entity_id'],data['scenario_id'])).fetchone()
            if data['prior_version_id']!=(current[0] if current else None): raise ValueError('stale scenario version; select current prior version')
            scenario=dict(json.loads(_canonical(data)),version_id='indicator-'+uuid4().hex,version=current[1]+1 if current else 1,
                policy=POLICY,period_start=start,period_end=end,actor_id=actor_id,recorded_at=datetime.now(timezone.utc).isoformat(),payload_digest=payload_digest)
            capture=dict(policy=POLICY,scenario=scenario,
                financial=financial_statements(_capture_financials(self.ledger,end))['capture'],time=time_report(_capture_time(self.ledger,end))['capture'])
            capture['input_digest']=digest(capture)
            result=dict(scenario,report=indicators_report(capture))
            self.db.execute('INSERT INTO indicator_versions VALUES(?,?,?,?,?,?,?)',(scenario['version_id'],data['entity_id'],data['scenario_id'],scenario['version'],
                data['prior_version_id'],data['idempotency_key'],_canonical(result)))
            return result


def indicators_report(capture):
    """Pure rehydration; consistency hashes are not signatures or proof of provenance."""
    try:
        _fields(capture,('policy','scenario','financial','time','input_digest'))
        if capture['policy']!=POLICY: raise ValueError('unsupported indicator policy')
        if digest({k:v for k,v in capture.items() if k!='input_digest'})!=capture['input_digest']: raise ValueError('indicator input digest mismatch')
        capture=json.loads(_canonical(capture)); scenario=capture['scenario']; _fields(scenario,FIELDS+META); _assumptions(scenario)
        if scenario['policy']!=POLICY: raise ValueError('unsupported scenario policy')
        for key in ('version_id','actor_id'): _text(scenario[key],key)
        _timestamp(scenario['recorded_at'])
        if type(scenario['version']) is not int or scenario['version']<1: raise ValueError('invalid scenario version')
        if digest(dict({k:scenario[k] for k in FIELDS},actor_id=scenario['actor_id']))!=scenario['payload_digest']: raise ValueError('scenario payload digest mismatch')
        financial=financial_statements(_financial(capture['financial'],scenario['period_end']))
        for key in ('entity_id','currency','period_start','period_end'):
            if scenario[key]!=financial[key]: raise ValueError('scenario and captured financial scope must match')
        start=accounting_date(scenario['period_start']); end=start.replace(day=calendar.monthrange(start.year,start.month)[1])
        if start.day!=1 or scenario['month']!=start.isoformat()[:7] or scenario['period_end']!=end.isoformat(): raise ValueError('scenario requires a whole-month capture')
        time=_validate_time(capture['time'],capture['financial'])
    except (KeyError,TypeError,AttributeError,OverflowError) as error:
        raise ValueError('malformed indicator capture') from error
    balance=financial['balance_sheet']; income=financial['income_statement']; findings=[]; accounts=[]
    for row in balance['assets']+balance['liabilities']:
        code=row['account']; kind=row['classification']
        if kind=='asset' and code in LIQUIDITY_POLICY['quick_assets']: treatment='quick'
        elif kind=='asset' and code in LIQUIDITY_POLICY['current_assets']: treatment='current_only'
        elif kind=='liability' and code in LIQUIDITY_POLICY['current_liabilities']: treatment='current_liability'
        elif kind=='asset' and code in LIQUIDITY_POLICY['noncurrent_assets']: treatment='noncurrent'
        else:
            treatment='unknown'; findings.append('Account '+code+' lacks explicit current/noncurrent classification in '+LIQUIDITY_POLICY['version']+'.')
        accounts.append(dict(row,treatment=treatment))
    current=sum(int(r['net_cents']) for r in accounts if r['treatment'] in ('quick','current_only'))
    quick=sum(int(r['net_cents']) for r in accounts if r['treatment']=='quick')
    liabilities=sum(int(r['net_cents']) for r in accounts if r['treatment']=='current_liability')
    liquidity_reason=('Unknown account classification; liquidity ratios unavailable.' if findings else
        'Current liabilities are nonpositive; liquidity ratios unavailable under this bounded policy.' if liabilities<=0 else None)
    revenue,profit=int(income['revenue_cents']),int(income['net_income_cents']); minutes=time['total_minutes']
    candidates={
        'current_ratio':dict(_ratio(current,liabilities,reason=liquidity_reason),unit='ratio',sources=[r for r in accounts if r['treatment']!='noncurrent']),
        'quick_ratio':dict(_ratio(quick,liabilities,reason=liquidity_reason),unit='ratio',sources=[r for r in accounts if r['treatment'] in ('quick','current_liability','unknown')]),
        'net_profit_margin':dict(_ratio(profit,revenue,percent=True),unit='percent',sources=income['revenue']+income['expenses']),
        'recorded_service_minutes':dict(numerator=str(minutes),denominator='1',display=str(minutes),reason=None,unit='minutes',sources=time['active_intervals'],
            note='Recorded active service time only; capacity, completeness and utilization are not measured.'),
        'revenue_per_service_hour':dict(_ratio(revenue*60,minutes,cents=True),unit='USD per recorded service hour',sources=income['revenue']+time['active_intervals'],
            note='Descriptive revenue / recorded service time. No claim of hourly billing or productivity; time may be incomplete.')}
    report={k:scenario[k] for k in ('entity_id','currency','scenario_id','version_id','version','name','month','period_start','period_end','reason','explanation','actor_id','recorded_at','prior_version_id')}
    report.update(policy=POLICY,liquidity_policy=json.loads(_canonical(LIQUIDITY_POLICY)),rounding_policy=ROUNDING,
        policy_digest=digest(dict(policy=POLICY,liquidity=LIQUIDITY_POLICY,rounding=ROUNDING)),snapshot_digest=capture['input_digest'],capture=capture,
        scope='Management assumptions, recorded financial actuals and recorded operational minutes are separate. Descriptive ratios are not financial-health or investment recommendations. No accounting entries.',
        contribution=contribution(scenario),indicators=[dict(candidates[k],id=k,name=MENU[k],period_start=scenario['period_start'],period_end=scenario['period_end']) for k in scenario['selected_indicators']],
        liquidity_accounts=accounts,findings=findings,financial_report_digest=financial['report_digest'],time_report_digest=time['report_digest'],
        excluded_closing_journal_ids=financial['excluded_closing_journal_ids'])
    report['report_digest']=digest(report)
    return report


def demo_indicators():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='indicators-demo-') as directory:
        workspace=Workspace(directory); build_adjusted_month(workspace); before=workspace.report_package('2026-01-31')
        data=dict(entity_id=workspace.catalog.entity_id,currency='USD',scenario_id='service',name='Synthetic single service',month='2026-01',
            price='100.00',variable_cost='40.00',fixed_cost='1200.00',minimum_units=0,maximum_units=100,quantity=20,
            selected_indicators=list(MENU),prior_version_id=None,reason='Explicit synthetic assumptions',explanation='',idempotency_key='v1')
        result=workspace.action('indicators',data); report=result['report']; model=report['contribution']
        assert model['contribution_amount']=='60.00' and model['break_even']['whole_units']=='20'
        assert [contribution(dict(data,quantity=q))['profit_amount'] for q in (19,20,21)]==['-60.00','0.00','60.00']
        print('100.00 price - 40.00 variable cost = 60.00 contribution. Fixed 1200.00: 20 whole units.')
        print('Model profit at 19 / 20 / 21 units: -60.00 / 0.00 / 60.00 USD; relevant range 0–100 service units.')
        for row in report['indicators']: print(row['name']+':',row['display'] if row['display'] is not None else 'unavailable — '+row['reason'],row['unit'])
        zero=contribution(dict(data,price='0.00',variable_cost='0.00',fixed_cost='0.00'))
        assert zero['margin']['display'] is None and zero['break_even']['whole_units'] is None
        print('Zero price margin unavailable; zero fixed/zero contribution:',zero['break_even']['reason'])
        assert indicators_report(report['capture'])==report and workspace.indicators(result['version_id'])==result
        assert workspace.report_package('2026-01-31')==before
        print('Pure historical report reproduced; actuals unchanged. No hourly billing, capacity or financial-health inference.')
