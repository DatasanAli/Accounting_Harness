"""Immutable management attribution of captured ordinary financial actuals."""
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from accounting_harness.financial_reports import FinancialCapture, _capture_financials, financial_statements, _total
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest, protect_table

POLICY = 'ordinary-project-attribution-v1'
AXES = ('project_id', 'customer_id', 'category', 'behavior', 'traceability')


def _text(value, name, limit=200):
    if type(value) is not str or not value or value != value.strip() or len(value) > limit:
        raise ValueError(f'{name} must be nonempty, unpadded text of at most {limit} characters')


def _fields(data, names):
    if type(data) is not dict or set(data) != set(names):
        raise ValueError('request requires exactly: ' + ', '.join(names))


def initialize_dimensions(ledger):
    """Caller owns the migration transaction; never change financial schemas."""
    db = ledger._connection
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='project_dimensions_schema'").fetchone():
        if db.execute('SELECT version FROM project_dimensions_schema').fetchall() != [(1,)]:
            raise ValueError('unsupported project dimensions schema')
        return
    db.execute('CREATE TABLE project_dimensions_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
    db.execute('INSERT INTO project_dimensions_schema VALUES(1)')
    db.execute('''CREATE TABLE management_projects(
        project_id TEXT PRIMARY KEY, result_json TEXT NOT NULL CHECK(json_valid(result_json))) STRICT, WITHOUT ROWID''')
    # Allocations and the original retry payload are sealed inside the revision.
    # One atomic row prevents an allocation being appended after its confirmation.
    db.execute('''CREATE TABLE project_assignment_revisions(
        revision_id TEXT PRIMARY KEY, journal_id TEXT NOT NULL REFERENCES posting_events(journal_id),
        line_number INTEGER NOT NULL CHECK(line_number>0), revision INTEGER NOT NULL CHECK(revision>0),
        prior_revision_id TEXT UNIQUE REFERENCES project_assignment_revisions(revision_id),
        idempotency_key TEXT NOT NULL UNIQUE, result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        UNIQUE(journal_id,line_number,revision)) STRICT, WITHOUT ROWID''')
    protect_table(db, 'project_dimensions_schema', '1')
    protect_table(db, 'management_projects', 'project_id=NEW.project_id')
    protect_table(db, 'project_assignment_revisions', '''revision_id=NEW.revision_id OR
        idempotency_key=NEW.idempotency_key OR prior_revision_id=NEW.prior_revision_id OR
        (journal_id=NEW.journal_id AND line_number=NEW.line_number AND revision=NEW.revision)''')


class ProjectDimensionsService:
    def __init__(self, ledger):
        self.ledger, self.db = ledger, ledger._connection
        with (nullcontext() if self.db.in_transaction else ledger._transaction(write=True)):
            initialize_dimensions(ledger)

    def create_project(self, data, *, actor_id):
        _fields(data, ('project_id','name','entity_id','customer_id'))
        for name in ('project_id','name','entity_id'):
            _text(data[name], name)
        _text(actor_id, 'actor_id')
        if data['customer_id'] is not None:
            _text(data['customer_id'], 'customer_id')
        if data['entity_id'] != self.ledger._empty.catalog.entity_id:
            raise ValueError('project entity must match the ledger')
        with self.ledger._transaction(write=True):
            found = self.db.execute('SELECT result_json FROM management_projects WHERE project_id=?', (data['project_id'],)).fetchone()
            if found:
                original = json.loads(found[0])
                if any(original[k] != v for k,v in data.items()):
                    raise ValueError('project identity conflict; metadata is immutable')
                return original
            result = dict(data, actor_id=actor_id, recorded_at=datetime.now(timezone.utc).isoformat())
            self.db.execute('INSERT INTO management_projects VALUES(?,?)', (data['project_id'],_canonical(result)))
            return result

    def assign(self, data, *, actor_id):
        _fields(data, ('entity_id','journal_id','line_number','source_digest','prior_revision_id','reason','idempotency_key','allocations'))
        for name in ('entity_id','journal_id','source_digest','reason','idempotency_key'):
            _text(data[name], name, 1000 if name == 'reason' else 200)
        _text(actor_id, 'actor_id')
        if data['entity_id'] != self.ledger._empty.catalog.entity_id:
            raise ValueError('assignment entity must match the ledger')
        if type(data['line_number']) is not int or not 1 <= data['line_number'] <= 10000:
            raise ValueError('line_number must be a positive integer up to 10000')
        if data['prior_revision_id'] is not None:
            _text(data['prior_revision_id'], 'prior_revision_id')
        if not re.fullmatch('[0-9a-f]{64}', data['source_digest']):
            raise ValueError('source_digest must be a captured SHA-256')
        if type(data['allocations']) is not list or len(data['allocations']) > 100:
            raise ValueError('allocations must be a complete list of at most 100 portions')
        for row in data['allocations']:
            _fields(row, (*AXES,'cents'))
            _text(row['project_id'],'project_id')
            if row['customer_id'] is not None:
                _text(row['customer_id'],'customer_id')
            _text(row['category'],'category',100)
            if row['behavior'] not in ('fixed','variable','unclassified'):
                raise ValueError('behavior must be fixed, variable or unclassified')
            if row['traceability'] not in ('direct','indirect','unclassified'):
                raise ValueError('traceability must be direct, indirect or unclassified')
            if type(row['cents']) is not str or not re.fullmatch('[1-9][0-9]{0,18}',row['cents']) or int(row['cents']) > 2**63-1:
                raise ValueError('cents must be a positive canonical integer string within signed 64-bit range')
        payload_digest = digest(dict(data,actor_id=actor_id))
        with self.ledger._transaction(write=True):
            retry = self.db.execute('SELECT result_json FROM project_assignment_revisions WHERE idempotency_key=?',
                                    (data['idempotency_key'],)).fetchone()
            if retry:
                original = json.loads(retry[0])
                if original['payload_digest'] != payload_digest:
                    raise ValueError('assignment retry conflict')
                return original
            financial = _capture_financials(self.ledger,self.ledger._empty.period_end)
            sources = _source_rows(financial)
            source = next((s for s in sources if (s['journal_id'],s['line_number']) == (data['journal_id'],data['line_number'])),None)
            if source is None:
                raise ValueError('assignment requires an existing posted ordinary revenue or expense line')
            if data['source_digest'] != source['source_digest']:
                raise ValueError('source digest does not match the immutable posted line')
            current = self.db.execute('''SELECT revision_id,revision FROM project_assignment_revisions
                WHERE journal_id=? AND line_number=? ORDER BY revision DESC LIMIT 1''',
                (data['journal_id'],data['line_number'])).fetchone()
            if data['prior_revision_id'] != (current[0] if current else None):
                raise ValueError('stale attribution; capture the current prior revision before correcting')
            for row in data['allocations']:
                project = self.db.execute('SELECT result_json FROM management_projects WHERE project_id=?',(row['project_id'],)).fetchone()
                if not project:
                    raise ValueError('allocation project does not exist')
                project = json.loads(project[0])
                if project['entity_id'] != data['entity_id']:
                    raise ValueError('allocation project belongs to a different entity')
                if row['customer_id'] is not None and row['customer_id'] != project['customer_id']:
                    raise ValueError('allocation customer must match the project management reference')
            if sum(int(row['cents']) for row in data['allocations']) > abs(int(source['actual_cents'])):
                raise ValueError('allocation portions exceed the posted line amount')
            result = dict(data, revision_id='attribution-'+uuid4().hex, revision=current[1]+1 if current else 1,
                          actor_id=actor_id, recorded_at=datetime.now(timezone.utc).isoformat(),payload_digest=payload_digest)
            self.db.execute('INSERT INTO project_assignment_revisions VALUES(?,?,?,?,?,?,?)',
                (result['revision_id'],data['journal_id'],data['line_number'],result['revision'],data['prior_revision_id'],
                 data['idempotency_key'],_canonical(result)))
            return result


@dataclass(frozen=True, slots=True)
class DimensionsCapture:
    financial: FinancialCapture
    projects_json: str
    revisions_json: str
    policy: str = POLICY


def capture_dimensions(ledger, as_of):
    """Capture current attribution knowledge and financial activity in one read."""
    with ledger._transaction():
        financial = _capture_financials(ledger,as_of)
        projects = [json.loads(r[0]) for r in ledger._connection.execute('SELECT result_json FROM management_projects ORDER BY project_id')]
        revisions = [json.loads(r[0]) for r in ledger._connection.execute('''SELECT r.result_json
            FROM project_assignment_revisions r WHERE NOT EXISTS(
                SELECT 1 FROM project_assignment_revisions newer WHERE newer.journal_id=r.journal_id
                AND newer.line_number=r.line_number AND newer.revision>r.revision)
            ORDER BY r.journal_id,r.line_number''')]
        return DimensionsCapture(financial,_canonical(projects),_canonical(revisions))


def _source_rows(financial, statements=None):
    statements = statements or financial_statements(financial)
    entries = {e['journal_id']:e for e in statements['capture']['entries']}
    rows = []
    for account in statements['income_statement']['revenue'] + statements['income_statement']['expenses']:
        for line in account['drilldown']:
            rows.append(dict(line,account=account['account'],account_name=account['name'],kind=account['classification'],
                actual_cents=line['net_cents'],actual_amount=line['amount'],
                source_digest=digest(dict(journal=entries[line['journal_id']],line_number=line['line_number']))))
    return rows


def project_report(capture):
    """Pure report: each classification axis partitions the same allocation rows."""
    if not isinstance(capture,DimensionsCapture) or capture.policy != POLICY:
        raise ValueError('unsupported project attribution capture or policy')
    financial = financial_statements(capture.financial)
    projects, revisions = json.loads(capture.projects_json),json.loads(capture.revisions_json)
    current = {(r['journal_id'],r['line_number']):r for r in revisions}
    sources, allocations = _source_rows(capture.financial,financial),[]
    for source in sources:
        revision = current.get((source['journal_id'],source['line_number']))
        source['revision_id'] = revision['revision_id'] if revision else None
        source['attribution'] = revision
        sign = 1 if int(source['actual_cents']) > 0 else -1
        portion_rows = []
        for position, portion in enumerate(revision['allocations'] if revision else [],1):
            row = dict(portion,journal_id=source['journal_id'],line_number=source['line_number'],allocation_number=position,
                       revision_id=source['revision_id'],kind=source['kind'],account=source['account'],source_ids=source['source_ids'])
            _total(row,'signed',sign*int(portion['cents']))
            allocations.append(row); portion_rows.append(row)
        source['allocations'] = portion_rows
        allocated = sum(int(r['signed_cents']) for r in portion_rows)
        _total(source,'allocated',allocated)
        _total(source,'unallocated',int(source['actual_cents'])-allocated)

    def reconciled_row(actual, selected):
        result = {}
        allocated = sum(int(r['allocated_cents']) for r in selected)
        unallocated = sum(int(r['unallocated_cents']) for r in selected)
        for name,value in [('actual',actual),('allocated',allocated),('unallocated',unallocated),('residual',actual-allocated-unallocated)]:
            _total(result,name,value)
        result['reconciled'] = result['residual_cents'] == '0'
        return result

    accounts = [dict(account=a['account'],name=a['name'],kind=a['classification'],
        **reconciled_row(int(a['net_cents']),[s for s in sources if s['account']==a['account']]))
        for a in financial['income_statement']['revenue'] + financial['income_statement']['expenses']]
    totals = {kind:reconciled_row(int(financial['income_statement'][field]),[s for s in sources if s['kind']==kind])
              for kind,field in [('revenue','revenue_cents'),('expense','expenses_cents')]}
    groups = {}
    for axis in AXES:
        grouped = {}
        for allocation in allocations:
            key = allocation[axis]
            grouped.setdefault(key,{'revenue':0,'expense':0})[allocation['kind']] += int(allocation['signed_cents'])
        groups[axis] = []
        for key in sorted(grouped,key=lambda k:(k is not None,k or '')):
            row = dict(key=key)
            for kind,value in grouped[key].items(): _total(row,kind,value)
            groups[axis].append(row)
    captured = dict(financial=financial['capture'],projects=projects,current_revisions=revisions,policy=capture.policy)
    report = dict(entity_id=financial['entity_id'],currency=financial['currency'],as_of=financial['as_of'],
        period_start=financial['period_start'],policy=capture.policy,policy_digest=digest(capture.policy),
        financial_snapshot_digest=financial['snapshot_digest'],financial_report_digest=financial['report_digest'],
        snapshot_digest=digest(captured),revision_ids=[r['revision_id'] for r in revisions],
        projects=projects,accounts=accounts,totals=totals,groups=groups,sources=sources,allocations=allocations,
        excluded_closing_journal_ids=financial['excluded_closing_journal_ids'],capture=captured,
        reconciled=all(r['reconciled'] for r in accounts))
    report['report_digest'] = digest(report)
    return report


def demo_project_dimensions():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='project-dimensions-demo-') as directory:
        workspace = Workspace(directory)
        build_adjusted_month(workspace)
        before = workspace.report_package('2026-01-31')
        for identity in ('A','B'):
            workspace.action('projects',dict(project_id=identity,name='Project '+identity,
                entity_id=workspace.catalog.entity_id,customer_id=None))
        report = workspace.project_dimensions('2026-01-31')
        source = next(s for s in report['sources'] if s['account']=='5100')
        request = dict(entity_id=report['entity_id'],journal_id=source['journal_id'],line_number=source['line_number'],
            source_digest=source['source_digest'],prior_revision_id=None,reason='Synthetic reviewed software attribution',
            idempotency_key='demo-software-split',allocations=[
                dict(project_id=p,customer_id=None,category='software',behavior='fixed',traceability='direct',cents=c)
                for p,c in [('A','12000'),('B','10000')]])
        revision = workspace.action('project-assignments',request)
        report = workspace.project_dimensions('2026-01-31')
        expense = next(a for a in report['accounts'] if a['account']=='5100')
        assert (expense['actual_amount'],expense['allocated_amount'],expense['unallocated_amount']) == ('300.00','220.00','80.00')
        assert workspace.report_package('2026-01-31') == before
        assert workspace.action('project-assignments',request) == revision
        print('Recorded software expense 300.00 USD = Project A 120.00 + Project B 100.00 + unallocated 80.00.')
        print('Overall expenses:',report['totals']['expense']['actual_amount'],'USD; every account and classification axis reconciles.')
        print('Financial statements, cash flow and portable reports unchanged; exact retry retained the original revision.')
        print('Attribution report:',report['report_digest'],'Financial snapshot:',report['financial_snapshot_digest'])
