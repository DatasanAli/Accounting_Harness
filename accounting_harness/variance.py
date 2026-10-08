"""Exact, portable static/flexible comparisons; assumptions never change actuals."""
import calendar
import json

from accounting_harness.budget import BudgetService, budget_report, _cents, _rows
from accounting_harness.domain.dates import accounting_date
from accounting_harness.financial_reports import _capture_financials, financial_statements, _total
from accounting_harness.persistence import _canonical
from accounting_harness.project_dimensions import _fields, _text
from accounting_harness.project_time import _capture_time, time_report, TimeCapture, POLICY as TIME_POLICY
from accounting_harness.report_export import _financial, _timestamp
from accounting_harness.review import digest

POLICY = 'service-flexible-variance-v1'
BUDGET_FIELDS = ('entity_id','currency','scenario_id','name','month','planned_minutes','opening_cash','operating_lines','cash_rows',
                 'prior_version_id','reason','explanation','idempotency_key')
REMAINING_POLICY = ('Remaining variance = actual minus flexible budget. Actual quantity by account and matching cost/rate '
                    'classification are not established by aggregate service time; no causal rate, spending, efficiency or responsibility claim.')


def capture_variance(ledger, version_id):
    """Selected budget, financial classifications and active time share one read view."""
    service = BudgetService(ledger)
    with ledger._transaction():
        budget = service.get(version_id)
        financial = financial_statements(_capture_financials(ledger, budget['period_end']))['capture']
        time = time_report(_capture_time(ledger, budget['period_end']))['capture']
    capture = dict(policy=POLICY,budget=budget,financial=financial,time=time)
    capture['input_digest'] = digest(capture)
    return capture


def _percent(difference, base, name):
    if base == 0:
        return dict(numerator=str(difference),denominator=None,display=None,base='absolute '+name+' budget')
    denominator = abs(base)
    hundredths = (abs(difference)*10000*2+denominator)//(2*denominator)
    display = ('-' if difference<0 and hundredths else '')+f'{hundredths//100}.{hundredths%100:02d}%'
    return dict(numerator=str(difference),denominator=str(denominator),display=display,base='absolute '+name+' budget')


def _label(impact):
    return 'Favorable' if impact>0 else 'Unfavorable' if impact<0 else 'Neutral'


def _comparison(static, flexible, actual, classification):
    direction = -1 if classification=='expense' else 1
    result = dict(classification=classification)
    for name,value in (('static',static),('flexible',flexible),('actual',actual),('variance',actual-static),
                       ('activity',flexible-static),('remaining',actual-flexible)):
        _total(result,name,value)
    for name,value in (('',actual-static),('activity_',flexible-static),('remaining_',actual-flexible)):
        _total(result,name+'favorable_impact',direction*value)
        result[name+'label'] = _label(direction*value)
    result['static_percent'] = _percent(actual-static,static,'static')
    result['flexible_percent'] = _percent(actual-flexible,flexible,'flexible')
    result['reconciled'] = int(result['activity_cents'])+int(result['remaining_cents'])==int(result['variance_cents'])
    return result


def _validate_budget(budget, financial):
    _fields(budget,BUDGET_FIELDS+('version_id','version','policy','unit_policy','rounding_policy','period_start','period_end',
        'captured_accounts','verified_source_ids','actor_id','recorded_at','payload_digest','report'))
    for field in ('entity_id','currency','period_start','period_end'):
        if budget[field]!=financial[field]: raise ValueError('budget and financial '+field+' must match')
    start=accounting_date(budget['period_start']); end=accounting_date(budget['period_end'])
    if (budget['month']!=start.isoformat()[:7] or start.day!=1 or end!=start.replace(day=calendar.monthrange(start.year,start.month)[1])):
        raise ValueError('budget must cover the captured whole month')
    if type(budget['planned_minutes']) is not int or not 0<=budget['planned_minutes']<=2**53-1:
        raise ValueError('invalid planned minutes')
    if type(budget['version']) is not int or budget['version']<1: raise ValueError('invalid budget version')
    for field in ('version_id','scenario_id','name','reason','idempotency_key','actor_id'):
        _text(budget[field],field,1000 if field=='reason' else 200)
    _timestamp(budget['recorded_at'])
    if type(budget['explanation']) is not str or len(budget['explanation'])>2000: raise ValueError('invalid operator explanation')
    if digest(dict({k:budget[k] for k in BUDGET_FIELDS},actor_id=budget['actor_id']))!=budget['payload_digest']:
        raise ValueError('budget payload digest mismatch')
    _rows(budget['operating_lines'],'operating_lines'); _rows(budget['cash_rows'],'cash_rows')
    catalog={a['code']:a for a in financial['catalog']}; identities=set(); used=set()
    for line in budget['operating_lines']:
        _fields(line,('line_id','account','behavior','amount')); _text(line['line_id'],'line_id'); _cents(line['amount'])
        if line['line_id'] in identities or line['behavior'] not in ('fixed','variable'): raise ValueError('invalid budget line identity or behavior')
        identities.add(line['line_id']); used.add(line['account'])
        account=budget['captured_accounts'][line['account']]
        if (account!=catalog.get(line['account']) or account['classification'] not in ('revenue','expense') or account['active'] is not True):
            raise ValueError('budget account scope or captured catalog mismatch')
    if set(budget['captured_accounts'])!=used: raise ValueError('budget captured account set mismatch')
    if budget['prior_version_id'] is not None: _text(budget['prior_version_id'],'prior_version_id')
    if type(budget['verified_source_ids']) is not list or len(set(budget['verified_source_ids']))!=len(budget['verified_source_ids']):
        raise ValueError('invalid captured source references')
    cash_ids=set(); source_ids=set()
    for row in budget['cash_rows']:
        _fields(row,('row_id','direction','amount','expected_date','category','budget_line_id','source_reference'))
        _text(row['row_id'],'row_id'); _text(row['category'],'category')
        if row['row_id'] in cash_ids or row['direction'] not in ('receipt','payment') or _cents(row['amount'])==0:
            raise ValueError('invalid captured cash assumption')
        cash_ids.add(row['row_id'])
        if type(row['expected_date']) is not str: raise ValueError('cash date must be text')
        accounting_date(row['expected_date'])
        if row['budget_line_id'] is not None and row['budget_line_id'] not in identities: raise ValueError('invalid cash budget linkage')
        ref=row['source_reference']
        if ref is not None:
            _fields(ref,('kind','id')); _text(ref['id'],'source reference')
            if ref['kind'] not in ('actual','external'): raise ValueError('invalid cash reference kind')
            if ref['kind']=='actual': source_ids.add(ref['id'])
    if source_ids!=set(budget['verified_source_ids']): raise ValueError('captured source identities do not match budget references')
    report=budget_report(budget)
    if report!=budget['report']: raise ValueError('budget report or policy mismatch')
    return report


def _validate_time(data, financial):
    _fields(data,('entity_id','period_start','as_of','projects','records','voids','policy'))
    if (data['entity_id']!=financial['entity_id'] or data['period_start']!=financial['period_start'] or
        data['as_of']!=financial['period_end'] or data['policy']!=TIME_POLICY):
        raise ValueError('time capture scope or policy mismatch')
    if any(type(data[k]) is not list for k in ('projects','records','voids')): raise ValueError('time capture arrays required')
    projects={}
    for project in data['projects']:
        _fields(project,('project_id','name','entity_id','customer_id','actor_id','recorded_at'))
        for field in ('project_id','name','entity_id','actor_id'): _text(project[field],field)
        if project['customer_id'] is not None: _text(project['customer_id'],'customer_id')
        _timestamp(project['recorded_at'])
        if project['project_id'] in projects or project['entity_id']!=data['entity_id']: raise ValueError('invalid captured project identity')
        projects[project['project_id']]=project
    records={}; events=set()
    request_fields=('entity_id','project_id','worker_id','time_event_id','work_date','start_minute','end_minute','replaces_record_id')
    for record in data['records']:
        _fields(record,request_fields+('record_id','minutes','policy','actor_id','recorded_at','payload_digest'))
        for field in ('record_id','worker_id','time_event_id','actor_id'): _text(record[field],field)
        _timestamp(record['recorded_at']); accounting_date(record['work_date'])
        start,end=record['start_minute'],record['end_minute']; key=(record['worker_id'],record['time_event_id'])
        if (record['record_id'] in records or key in events or record['entity_id']!=data['entity_id'] or
            record['project_id'] not in projects or record['policy']!=TIME_POLICY or
            not data['period_start']<=record['work_date']<=data['as_of'] or type(start) is not int or type(end) is not int or
            not 0<=start<end<=1440 or type(record['minutes']) is not int or record['minutes']!=end-start or
            digest({k:record[k] for k in request_fields})!=record['payload_digest']):
            raise ValueError('invalid captured time record')
        records[record['record_id']]=record; events.add(key)
    voids={}; events=set()
    for row in data['voids']:
        _fields(row,('entity_id','record_id','void_event_id','reason','actor_id','recorded_at','payload_digest'))
        for field in ('record_id','void_event_id','actor_id','reason'): _text(row[field],field,1000 if field=='reason' else 200)
        _timestamp(row['recorded_at'])
        if (row['record_id'] not in records or row['record_id'] in voids or row['void_event_id'] in events or row['entity_id']!=data['entity_id'] or
            digest({k:v for k,v in row.items() if k not in ('recorded_at','payload_digest')})!=row['payload_digest']):
            raise ValueError('invalid captured time void')
        voids[row['record_id']]=row; events.add(row['void_event_id'])
    replacements=set(); active=[]
    for row in records.values():
        prior=row['replaces_record_id']
        if prior is not None:
            if (prior not in voids or prior in replacements or records[prior]['worker_id']!=row['worker_id'] or
                records[prior]['recorded_at']>=row['recorded_at']): raise ValueError('invalid captured time replacement')
            replacements.add(prior)
        if row['record_id'] not in voids:
            if any(r['worker_id']==row['worker_id'] and r['work_date']==row['work_date'] and
                   r['start_minute']<row['end_minute'] and r['end_minute']>row['start_minute'] for r in active):
                raise ValueError('overlapping captured active time')
            active.append(row)
    return time_report(TimeCapture(data['entity_id'],data['period_start'],data['as_of'],
        _canonical(data['projects']),_canonical(data['records']),_canonical(data['voids']),data['policy']))


def variance_report(capture):
    """Pure, self-contained rendering; hashes check consistency, not provenance."""
    try:
        _fields(capture,('policy','budget','financial','time','input_digest'))
        if capture['policy']!=POLICY: raise ValueError('unsupported variance policy')
        if digest({k:v for k,v in capture.items() if k!='input_digest'})!=capture['input_digest']:
            raise ValueError('variance input digest mismatch')
        # Detach caller-owned structures so the report is a complete portable value.
        capture=json.loads(_canonical(capture))
        financial=financial_statements(_financial(capture['financial'],capture['financial']['period_end']))
        budget=_validate_budget(capture['budget'],capture['financial'])
        time=_validate_time(capture['time'],capture['financial'])
    except (KeyError,TypeError,AttributeError,OverflowError) as error:
        raise ValueError('malformed variance capture') from error
    minutes=time['total_minutes']; lines=[]; grouped={}
    for line in budget['operating_lines']:
        numerator=int(line['rate_cents'])*minutes if line['behavior']=='variable' else int(line['planned_cents'])
        denominator=60 if line['behavior']=='variable' else 1
        flexible=(numerator+denominator//2)//denominator; static=int(line['planned_cents'])
        row=dict(line,flexible_numerator=str(numerator),flexible_denominator=denominator,
            flexible_rounding_delta_numerator=str(flexible*denominator-numerator))
        for name,cents in (('static',static),('flexible',flexible),('activity',flexible-static)): _total(row,name,cents)
        lines.append(row); grouped.setdefault(line['account'],[]).append(row)
    income=financial['income_statement']; accounts=[]
    for actual in income['revenue']+income['expenses']:
        code=actual['account']; inputs=grouped.get(code,[])
        if not inputs and not actual['drilldown']: continue
        static=sum(int(l['static_cents']) for l in inputs); flexible=sum(int(l['flexible_cents']) for l in inputs)
        row=_comparison(static,flexible,int(actual['net_cents']),actual['classification'])
        row.update(account=code,name=actual['name'],status='unbudgeted' if not inputs else 'budget-only' if not actual['drilldown'] else 'budgeted',
            budget_line_ids=[l['line_id'] for l in inputs],actual_drilldown=actual['drilldown'])
        accounts.append(row)
    totals={}
    for kind in ('revenue','expense'):
        sums=[sum(int(row[name+'_cents']) for row in accounts if row['classification']==kind) for name in ('static','flexible','actual')]
        totals[kind]=_comparison(*sums,kind)
    totals['income']=_comparison(*(int(totals['revenue'][k+'_cents'])-int(totals['expense'][k+'_cents']) for k in ('static','flexible','actual')),'income')
    findings=['Account-level actual quantity and matching classification support is missing; remaining variance is not a causal rate/spending explanation.']
    if minutes==0: findings.append('No active service time in this captured month; variable lines flex to zero and fixed lines remain unchanged.')
    findings.extend('Unbudgeted account '+r['account']+' uses a zero comparison base; percentage unavailable.' for r in accounts if r['status']=='unbudgeted')
    result=dict(policy=POLICY,policy_digest=digest(POLICY),snapshot_digest=capture['input_digest'],capture=capture,
        entity_id=budget['entity_id'],currency=budget['currency'],month=budget['month'],period_start=budget['period_start'],period_end=budget['period_end'],
        version_id=budget['version_id'],scenario_id=budget['scenario_id'],name=budget['name'],version=budget['version'],
        planned_minutes=budget['planned_minutes'],actual_minutes=minutes,unit_policy=budget['unit_policy'],rounding_policy=budget['rounding_policy'],
        budget_report_digest=budget['report_digest'],financial_report_digest=financial['report_digest'],time_report_digest=time['report_digest'],
        scope='Captured management comparison. No journal, budget, time or classification changes. Activity bridge is arithmetic, not proof of cause.',
        remaining_policy=REMAINING_POLICY,percentage_policy='Difference / absolute named budget base; two decimals half-up; zero base unavailable.',
        operator_note=dict(text=budget['explanation'],actor_id=budget['actor_id'],recorded_at=budget['recorded_at'],source='Selected budget version; operator assumption, not computed evidence'),
        budget_lines=lines,accounts=accounts,totals=totals,time_records=time['active_intervals'],findings=findings,
        excluded_closing_journal_ids=financial['excluded_closing_journal_ids'],reconciled=all(r['reconciled'] for r in accounts+list(totals.values())))
    result['report_digest']=digest(result)
    return result


def demo_variance():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='variance-demo-') as directory:
        workspace=Workspace(directory)
        for event,amount,expense in [('service','1100.00',False),('cost','600.00',True)]:
            common=dict(schema_version=2,synthetic=True,entity_id=workspace.catalog.entity_id,currency='USD',document_date='2026-01-10',
                amount=amount,event_id=event,counterparty='Synthetic variance counterparty',counterparty_id=event+'-party',description='Synthetic supported '+event)
            cash=dict(common,document_id=event+'-cash',kind='cash_movement',direction='out' if expense else 'in',purpose='incurred_expense' if expense else 'earned_service')
            fact=dict(common,document_id=event+'-fact',kind='incurred_expense' if expense else 'service_completion')
            fact.update(dict(incurred_date='2026-01-10',expense_account='5100') if expense else dict(completion_date='2026-01-10'))
            for document in (cash,fact): workspace.action('operation-sources',dict(document=document))
            workspace.action('cash-proposals',dict(operation='cash_expense' if expense else 'earned_cash',cash_source_id=cash['document_id'],recognition_source_id=fact['document_id']))
        for draft in workspace.state()['drafts']:
            # Separate simulated human confirmation of the synthetic fixture.
            workspace.action('approve-post',dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest']))
        workspace.action('projects',dict(project_id='A',name='Synthetic service',entity_id=workspace.catalog.entity_id,customer_id=None))
        workspace.action('project-time',dict(entity_id=workspace.catalog.entity_id,project_id='A',worker_id='synthetic-worker',time_event_id='service-time',
            work_date='2026-01-10',start_minute=0,end_minute=600,replaces_record_id=None))
        budget=workspace.action('budget',dict(entity_id=workspace.catalog.entity_id,currency='USD',scenario_id='service-plan',name='Service plan',
            month='2026-01',planned_minutes=480,opening_cash='0.00',cash_rows=[],prior_version_id=None,reason='Synthetic reference assumptions',
            explanation='',idempotency_key='reference',operating_lines=[dict(line_id='sales',account='4000',behavior='variable',amount='125.00'),
                dict(line_id='variable-cost',account='5100',behavior='variable',amount='50.00'),dict(line_id='fixed-cost',account='5100',behavior='fixed',amount='100.00')]))
        before=workspace.report_package('2026-01-31'); report=workspace.variance(budget['version_id'])
        assert [report['totals'][k]['variance_amount'] for k in ('revenue','expense','income')]==['100.00','100.00','0.00']
        assert [report['totals'][k]['label'] for k in ('revenue','expense','income')]==['Favorable','Unfavorable','Neutral']
        assert [report['totals'][k]['flexible_amount'] for k in ('revenue','expense','income')]==['1250.00','600.00','650.00']
        assert report['reconciled'] and variance_report(report['capture'])==report
        assert workspace.report_package('2026-01-31')==before and workspace.budget(budget['version_id'])==budget
        print('Planned 480 minutes; observed 600 minutes. Static / flexible / actual USD:')
        for kind,row in report['totals'].items():
            print(kind+':',row['static_amount'],'/',row['flexible_amount'],'/',row['actual_amount'],
                '· variance',row['variance_amount'],row['label'],'· activity',row['activity_amount'],'+ remaining',row['remaining_amount'],'=',row['variance_amount'])
        print('Exact bridges reconcile; complete captured inputs re-render identically. Actuals and budget unchanged.')
        print('Remaining variance lacks account-level quantity/classification support; no causal claim. Report:',report['report_digest'])
