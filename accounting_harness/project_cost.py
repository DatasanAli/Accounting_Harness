"""Immutable management scenarios; exact costing without accounting effects."""
import json
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

from accounting_harness.financial_reports import _total
from accounting_harness.persistence import _canonical
from accounting_harness.project_dimensions import _capture_dimensions, project_report, _fields, _text
from accounting_harness.project_time import _capture_time, time_report, _duration
from accounting_harness.review import digest, protect_table

POLICY = 'service-cost-v1'
CATEGORY_POLICY = dict(version='direct-nonlabor-v1',
    direct_nonlabor=['software','materials','travel','subcontractor','other-nonlabor'],
    labor=['labor','payroll','wages'],
    explanation='Only explicitly direct expense portions in these nonlabor categories are eligible. Software qualifies by its explicit category. Labor and indirect actuals remain visible but modeled labor and overhead replace them in this management model. Unknown categories remain findings.')


def initialize_cost(ledger):
    db = ledger._connection
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='project_cost_schema'").fetchone():
        if db.execute('SELECT version FROM project_cost_schema').fetchall() != [(1,)]:
            raise ValueError('unsupported project cost schema')
        return
    db.execute('CREATE TABLE project_cost_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
    db.execute('INSERT INTO project_cost_schema VALUES(1)')
    db.execute('''CREATE TABLE project_cost_versions(
        version_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
        project_id TEXT NOT NULL REFERENCES management_projects(project_id), version INTEGER NOT NULL CHECK(version>0),
        prior_version_id TEXT UNIQUE REFERENCES project_cost_versions(version_id), idempotency_key TEXT NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        UNIQUE(entity_id,scenario_id,version), UNIQUE(entity_id,scenario_id,idempotency_key)) STRICT, WITHOUT ROWID''')
    protect_table(db,'project_cost_schema','1')
    protect_table(db,'project_cost_versions','''version_id=NEW.version_id OR prior_version_id=NEW.prior_version_id OR
        (entity_id=NEW.entity_id AND scenario_id=NEW.scenario_id AND (version=NEW.version OR idempotency_key=NEW.idempotency_key))''')


def _rate(value):
    if type(value) is not str or not re.fullmatch(r'(0|[1-9][0-9]{0,16})\.[0-9]{2}',value):
        raise ValueError('rate must be a nonnegative canonical USD/hour string with exactly two decimal places')
    cents = int(value.replace('.',''))
    if cents > 2**63-1:
        raise ValueError('rate cents exceed signed 64-bit range')
    return cents


def _eligible(row):
    return row['kind']=='expense' and row['traceability']=='direct' and row['category'] in CATEGORY_POLICY['direct_nonlabor']


def _reference(row):
    return dict(revision_id=row['revision_id'],allocation_number=row['allocation_number'])


def _capture_inputs(ledger, as_of):
    # Caller owns one transaction for both financial/attribution and time knowledge.
    actuals = project_report(_capture_dimensions(ledger,as_of))
    time = time_report(_capture_time(ledger,as_of))
    return actuals, time


class ProjectCostService:
    def __init__(self, ledger):
        self.ledger, self.db = ledger, ledger._connection
        with (nullcontext() if self.db.in_transaction else ledger._transaction(write=True)):
            initialize_cost(ledger)

    def inputs(self, as_of):
        with self.ledger._transaction():
            actuals, time = _capture_inputs(self.ledger,as_of)
            versions = [json.loads(r[0]) for r in self.db.execute('SELECT result_json FROM project_cost_versions ORDER BY scenario_id,version')]
        return dict(actuals=actuals,time=time,policy=POLICY,category_policy=CATEGORY_POLICY,
            eligible_direct_costs=[dict(row,reference=_reference(row)) for row in actuals['allocations'] if _eligible(row)],
            versions=[{k:r[k] for k in ('version_id','entity_id','scenario_id','name','project_id','version','prior_version_id','as_of','actor_id','recorded_at')} for r in versions])

    def get(self, version_id):
        _text(version_id,'version_id')
        row = self.db.execute('SELECT result_json FROM project_cost_versions WHERE version_id=?',(version_id,)).fetchone()
        if not row:
            raise ValueError('cost scenario version does not exist')
        return json.loads(row[0])

    def save(self, data, *, actor_id):
        _fields(data, ('entity_id','scenario_id','name','project_id','as_of','labor_rate','overhead_rate','actual_snapshot_digest',
            'time_snapshot_digest','direct_cost_portions','prior_version_id','reason','explanation','idempotency_key'))
        for field in ('entity_id','scenario_id','name','project_id','as_of','actual_snapshot_digest','time_snapshot_digest','reason','idempotency_key'):
            _text(data[field],field,1000 if field=='reason' else 200)
        _text(actor_id,'actor_id')
        if data['entity_id'] != self.ledger._empty.catalog.entity_id:
            raise ValueError('cost scenario entity must match the ledger')
        if type(data['explanation']) is not str or len(data['explanation'])>2000:
            raise ValueError('explanation must be text of at most 2000 characters')
        if data['prior_version_id'] is not None:
            _text(data['prior_version_id'],'prior_version_id')
        _rate(data['labor_rate']); _rate(data['overhead_rate'])
        for field in ('actual_snapshot_digest','time_snapshot_digest'):
            if not re.fullmatch('[0-9a-f]{64}',data[field]): raise ValueError(field+' must be a captured SHA-256')
        portions = data['direct_cost_portions']
        if type(portions) is not list or len(portions)>100:
            raise ValueError('direct_cost_portions must be a list of at most 100 unique references')
        identities = set()
        for row in portions:
            _fields(row,('revision_id','allocation_number')); _text(row['revision_id'],'revision_id')
            if type(row['allocation_number']) is not int or not 1<=row['allocation_number']<=100:
                raise ValueError('allocation_number must be an integer from 1 to 100')
            key = (row['revision_id'],row['allocation_number'])
            if key in identities: raise ValueError('duplicate direct-cost portion')
            identities.add(key)
        payload_digest = digest(dict(data,actor_id=actor_id))
        with self.ledger._transaction(write=True):
            retry = self.db.execute('SELECT result_json FROM project_cost_versions WHERE entity_id=? AND scenario_id=? AND idempotency_key=?',
                (data['entity_id'],data['scenario_id'],data['idempotency_key'])).fetchone()
            if retry:
                original = json.loads(retry[0])
                if original['payload_digest'] != payload_digest: raise ValueError('cost scenario retry conflict')
                return original
            current = self.db.execute('SELECT version_id,version,project_id FROM project_cost_versions WHERE entity_id=? AND scenario_id=? ORDER BY version DESC LIMIT 1',
                (data['entity_id'],data['scenario_id'])).fetchone()
            if data['prior_version_id'] != (current[0] if current else None):
                raise ValueError('stale scenario version; select the current prior version')
            if current and data['project_id'] != current[2]:
                raise ValueError('scenario project identity cannot change')
            actuals,time = _capture_inputs(self.ledger,data['as_of'])
            if (data['actual_snapshot_digest'],data['time_snapshot_digest']) != (actuals['snapshot_digest'],time['snapshot_digest']):
                raise ValueError('stale actual or time capture; capture current inputs before saving a new version')
            if not any(p['project_id']==data['project_id'] and p['entity_id']==data['entity_id'] for p in actuals['projects']):
                raise ValueError('scenario project must exist in the same entity')
            eligible = {(r['revision_id'],r['allocation_number']) for r in actuals['allocations'] if r['project_id']==data['project_id'] and _eligible(r)}
            if not identities <= eligible:
                raise ValueError('selected portion must be a current direct nonlabor expense allocation for this project')
            result = dict(data,version_id='cost-'+uuid4().hex,version=current[1]+1 if current else 1,policy=POLICY,
                actor_id=actor_id,recorded_at=datetime.now(timezone.utc).isoformat(),payload_digest=payload_digest,
                actuals=actuals,time=time)
            result['cost_sheet'] = cost_sheet(result)
            self.db.execute('INSERT INTO project_cost_versions VALUES(?,?,?,?,?,?,?,?)',
                (result['version_id'],data['entity_id'],data['scenario_id'],data['project_id'],result['version'],data['prior_version_id'],data['idempotency_key'],_canonical(result)))
            return result


def cost_sheet(scenario):
    """Pure rendering of sealed scenario facts; never reads later ledger/time state."""
    if scenario['policy'] != POLICY:
        raise ValueError('unsupported project cost policy')
    actuals,time = scenario['actuals'],scenario['time']
    if any(actuals[k] != time[k] or actuals[k] != scenario[k] for k in ('entity_id','as_of')) or actuals['period_start'] != time['period_start']:
        raise ValueError('inconsistent actual/time/project capture scope')
    if actuals['projects'] != time['projects'] or scenario['actual_snapshot_digest'] != actuals['snapshot_digest'] or scenario['time_snapshot_digest'] != time['snapshot_digest']:
        raise ValueError('inconsistent captured dimensions or digests')
    if not any(p['project_id']==scenario['project_id'] and p['entity_id']==scenario['entity_id'] for p in actuals['projects']):
        raise ValueError('scenario project must exist in the captured entity')
    rows = [r for r in actuals['allocations'] if r['project_id']==scenario['project_id']]
    records = [r for r in time['active_intervals'] if r['project_id']==scenario['project_id']]
    minutes = sum(r['minutes'] for r in records)
    selected = {(r['revision_id'],r['allocation_number']) for r in scenario['direct_cost_portions']}
    bridge, findings = [],[]
    for row in rows:
        key = (row['revision_id'],row['allocation_number'])
        if row['kind']=='revenue': treatment,reason='revenue','Attributed recorded revenue used for modeled margin.'
        elif key in selected: treatment,reason='selected_direct_nonlabor','Explicitly selected direct nonlabor actual expense.'
        elif row['category'] in CATEGORY_POLICY['labor']: treatment,reason='modeled_labor','Actual labor is visible; modeled labor supplies this component.'
        elif row['traceability']=='indirect': treatment,reason='modeled_overhead','Actual indirect expense is visible; modeled overhead supplies this component.'
        elif _eligible(row): treatment,reason='not_selected','Eligible direct nonlabor actual was not selected.'
        else: treatment,reason='unclassified','Category or traceability is outside the explicit direct nonlabor policy.'
        bridge.append(dict(row,reference=_reference(row),treatment=treatment,reason=reason,included_in_model=treatment=='selected_direct_nonlabor'))
        if treatment in ('unclassified','not_selected'): findings.append(row['journal_id']+': '+reason)
        if row['kind']=='expense' and row['behavior']=='unclassified':
            findings.append(row['journal_id']+': cost behavior is unclassified; no fixed/variable assumption is inferred.')
    if any(int(s['unallocated_cents']) for s in actuals['sources']):
        findings.append('Unallocated ledger actuals remain in the captured ledger bridge; they are not assumed to belong to this project.')
    calculations = {}
    for component in ('labor','overhead'):
        rate = _rate(scenario[component+'_rate']); numerator=minutes*rate
        rounded=(numerator+30)//60
        calculations[component]=dict(minutes=minutes,rate_cents=str(rate),rate_amount=scenario[component+'_rate'],numerator=str(numerator),denominator=60,
            rounding='half-up once per project/period component',rounded_cents=str(rounded),rounding_delta_numerator=str(rounded*60-numerator),rounding_delta_denominator=60)
    labor,overhead = (int(calculations[k]['rounded_cents']) for k in ('labor','overhead'))
    direct = sum(int(r['signed_cents']) for r in bridge if r['included_in_model'])
    revenue = sum(int(r['signed_cents']) for r in rows if r['kind']=='revenue')
    expense = sum(int(r['signed_cents']) for r in rows if r['kind']=='expense')
    total=labor+direct+overhead
    report = dict(entity_id=scenario['entity_id'],currency='USD',scenario_id=scenario['scenario_id'],version_id=scenario['version_id'],version=scenario['version'],
        name=scenario['name'],project_id=scenario['project_id'],period_start=actuals['period_start'],as_of=scenario['as_of'],policy=POLICY,category_policy=CATEGORY_POLICY,
        actor_id=scenario['actor_id'],recorded_at=scenario['recorded_at'],reason=scenario['reason'],explanation=scenario['explanation'],prior_version_id=scenario['prior_version_id'],
        scope='Management costing and modeled project margin, distinct from financial net income. Rates are assumptions, not evidence of wages paid or accrued. No financial posting.',
        total_minutes=minutes,duration=_duration(minutes),time_records=records,calculations=calculations,actuals_bridge=bridge,findings=findings,actuals=actuals,
        actual_snapshot_digest=actuals['snapshot_digest'],time_snapshot_digest=time['snapshot_digest'],financial_snapshot_digest=actuals['financial_snapshot_digest'])
    for name,value in [('labor',labor),('overhead',overhead),('direct_nonlabor',direct),('total_cost',total),('revenue',revenue),('margin',revenue-total),
                       ('actual_expense',expense),('excluded_actual_expense',expense-direct),('model_minus_actual',total-expense)]:
        _total(report,name,value)
    report['report_digest'] = digest(report)
    return report


def demo_project_cost():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='project-cost-demo-') as directory:
        workspace=Workspace(directory); build_adjusted_month(workspace)
        before=workspace.report_package('2026-01-31')
        workspace.action('projects',dict(entity_id=workspace.catalog.entity_id,project_id='A',name='Project A',customer_id=None))
        actuals=workspace.project_dimensions('2026-01-31')
        for account,cents,category in [('5100','10000','software'),('4000','100000','service-revenue')]:
            source=next(r for r in actuals['sources'] if r['account']==account)
            workspace.action('project-assignments',dict(entity_id=actuals['entity_id'],journal_id=source['journal_id'],line_number=source['line_number'],
                source_digest=source['source_digest'],prior_revision_id=None,reason='Synthetic project cost input',idempotency_key='cost-'+account,
                allocations=[dict(project_id='A',customer_id=None,category=category,behavior='fixed',traceability='direct',cents=cents)]))
        for day in ('2026-01-10','2026-01-11'):
            workspace.action('project-time',dict(entity_id=actuals['entity_id'],project_id='A',worker_id='worker',time_event_id=day,work_date=day,
                start_minute=540,end_minute=840,replaces_record_id=None))
        inputs=workspace.project_cost_inputs('2026-01-31')
        data=dict(entity_id=actuals['entity_id'],scenario_id='project-A-cost',name='Project A service cost',project_id='A',as_of='2026-01-31',
            labor_rate='40.00',overhead_rate='20.00',actual_snapshot_digest=inputs['actuals']['snapshot_digest'],time_snapshot_digest=inputs['time']['snapshot_digest'],
            direct_cost_portions=[r['reference'] for r in inputs['eligible_direct_costs']],prior_version_id=None,reason='Initial management estimate',explanation='',idempotency_key='demo-cost')
        scenario=workspace.action('project-cost',data); sheet=scenario['cost_sheet']
        assert (sheet['total_cost_amount'],sheet['margin_amount']) == ('700.00','300.00')
        assert workspace.action('project-cost',data)==scenario
        assert workspace.report_package('2026-01-31')==before
        print('Project A: 600 minutes at 40.00 labor/hour = 400.00; selected direct actuals 100.00; 20.00 overhead/hour = 200.00 USD.')
        print('Modeled project cost 700.00 USD; attributed actual revenue 1000.00; modeled margin 300.00 USD.')
        print('Management assumptions remain distinct from recorded actuals. Exact retry preserved the scenario; financial reports unchanged.')
        print('Cost sheet:',sheet['report_digest'])
