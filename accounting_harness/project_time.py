"""Audited nonfinancial service intervals, explicit voids and pure time captures."""
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from accounting_harness.domain.dates import accounting_date
from accounting_harness.persistence import _canonical
from accounting_harness.project_dimensions import _fields, _text
from accounting_harness.review import digest, protect_table

POLICY = 'service-time-v1'


def initialize_time(ledger):
    """Add time storage in the caller's shared migration transaction."""
    db = ledger._connection
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='project_time_schema'").fetchone():
        if db.execute('SELECT version FROM project_time_schema').fetchall() != [(1,)]:
            raise ValueError('unsupported project time schema')
        return
    db.execute('CREATE TABLE project_time_schema(version INTEGER PRIMARY KEY CHECK(version=1)) STRICT')
    db.execute('INSERT INTO project_time_schema VALUES(1)')
    # Each sealed row is also the scoped retry receipt; no separate partial receipt.
    db.execute('''CREATE TABLE project_time_records(
        record_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, worker_id TEXT NOT NULL,
        time_event_id TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES management_projects(project_id),
        work_date TEXT NOT NULL, start_minute INTEGER NOT NULL CHECK(start_minute BETWEEN 0 AND 1439),
        end_minute INTEGER NOT NULL CHECK(end_minute BETWEEN 1 AND 1440 AND end_minute>start_minute),
        replaces_record_id TEXT UNIQUE REFERENCES project_time_voids(record_id),
        result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        UNIQUE(entity_id,worker_id,time_event_id)) STRICT, WITHOUT ROWID''')
    db.execute('''CREATE TABLE project_time_voids(
        record_id TEXT PRIMARY KEY REFERENCES project_time_records(record_id),
        entity_id TEXT NOT NULL, void_event_id TEXT NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        UNIQUE(entity_id,void_event_id)) STRICT, WITHOUT ROWID''')
    db.execute('CREATE INDEX project_time_intervals ON project_time_records(entity_id,worker_id,work_date)')
    protect_table(db, 'project_time_schema', '1')
    protect_table(db, 'project_time_records', '''record_id=NEW.record_id OR
        (entity_id=NEW.entity_id AND worker_id=NEW.worker_id AND time_event_id=NEW.time_event_id)
        OR replaces_record_id=NEW.replaces_record_id''')
    protect_table(db, 'project_time_voids', 'record_id=NEW.record_id OR (entity_id=NEW.entity_id AND void_event_id=NEW.void_event_id)')


class ProjectTimeService:
    def __init__(self, ledger):
        self.ledger, self.db = ledger, ledger._connection
        with (nullcontext() if self.db.in_transaction else ledger._transaction(write=True)):
            initialize_time(ledger)

    def _entity(self, entity_id):
        _text(entity_id, 'entity_id')
        if entity_id != self.ledger._empty.catalog.entity_id:
            raise ValueError('time entity must match the ledger')

    def _status(self, record):
        void = self.db.execute('SELECT result_json FROM project_time_voids WHERE record_id=?', (record['record_id'],)).fetchone()
        return dict(record, status='voided' if void else 'active', void=json.loads(void[0]) if void else None)

    def record(self, data, *, actor_id):
        _fields(data, ('entity_id','project_id','worker_id','time_event_id','work_date','start_minute','end_minute','replaces_record_id'))
        self._entity(data['entity_id']); _text(actor_id, 'actor_id')
        for field in ('project_id','worker_id','time_event_id'):
            _text(data[field], field)
        if type(data['work_date']) is not str:
            raise ValueError('work_date must be a YYYY-MM-DD string')
        work_date = accounting_date(data['work_date'])
        if not self.ledger._empty.period_start <= work_date <= self.ledger._empty.period_end:
            raise ValueError('work_date must be within the supported accounting period')
        start, end = data['start_minute'], data['end_minute']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= 1440:
            raise ValueError('minutes must be integers with 0 <= start_minute < end_minute <= 1440; split overnight work by date')
        if data['replaces_record_id'] is not None:
            _text(data['replaces_record_id'], 'replaces_record_id')
        payload_digest = digest(data)
        # BEGIN IMMEDIATE serializes identity and overlap checks with both inserts and voids.
        with self.ledger._transaction(write=True):
            prior = self.db.execute('''SELECT result_json FROM project_time_records
                WHERE entity_id=? AND worker_id=? AND time_event_id=?''',
                (data['entity_id'],data['worker_id'],data['time_event_id'])).fetchone()
            if prior:
                original = json.loads(prior[0])
                if original['payload_digest'] != payload_digest:
                    raise ValueError('time event identity conflict')
                return self._status(original)
            project = self.db.execute('SELECT result_json FROM management_projects WHERE project_id=?',(data['project_id'],)).fetchone()
            if not project or json.loads(project[0])['entity_id'] != data['entity_id']:
                raise ValueError('time project must exist in the same entity')
            if data['replaces_record_id'] is not None:
                previous = self.db.execute('''SELECT r.entity_id,r.worker_id FROM project_time_records r
                    JOIN project_time_voids v ON v.record_id=r.record_id WHERE r.record_id=?''',(data['replaces_record_id'],)).fetchone()
                if not previous:
                    raise ValueError('replacement must reference a voided time record')
                if previous != (data['entity_id'],data['worker_id']):
                    raise ValueError('replacement must retain the same entity and worker')
                if self.db.execute('SELECT 1 FROM project_time_records WHERE replaces_record_id=?',(data['replaces_record_id'],)).fetchone():
                    raise ValueError('voided record already has a replacement')
            overlap = self.db.execute('''SELECT r.record_id FROM project_time_records r
                WHERE r.entity_id=? AND r.worker_id=? AND r.work_date=? AND r.start_minute<? AND r.end_minute>?
                AND NOT EXISTS(SELECT 1 FROM project_time_voids v WHERE v.record_id=r.record_id) LIMIT 1''',
                (data['entity_id'],data['worker_id'],data['work_date'],end,start)).fetchone()
            if overlap:
                raise ValueError('time interval overlaps active record '+overlap[0])
            result = dict(data, record_id='time-'+uuid4().hex, minutes=end-start, policy=POLICY,
                actor_id=actor_id, recorded_at=datetime.now(timezone.utc).isoformat(), payload_digest=payload_digest)
            self.db.execute('INSERT INTO project_time_records VALUES(?,?,?,?,?,?,?,?,?,?)',
                (result['record_id'],data['entity_id'],data['worker_id'],data['time_event_id'],data['project_id'],
                 data['work_date'],start,end,data['replaces_record_id'],_canonical(result)))
            return self._status(result)

    def void(self, data, *, actor_id):
        _fields(data, ('entity_id','record_id','void_event_id','reason'))
        self._entity(data['entity_id']); _text(actor_id, 'actor_id')
        for field in ('record_id','void_event_id','reason'):
            _text(data[field], field, 1000 if field == 'reason' else 200)
        payload_digest = digest(dict(data, actor_id=actor_id))
        with self.ledger._transaction(write=True):
            prior = self.db.execute('SELECT result_json FROM project_time_voids WHERE entity_id=? AND void_event_id=?',
                (data['entity_id'],data['void_event_id'])).fetchone()
            if prior:
                original = json.loads(prior[0])
                if original['payload_digest'] != payload_digest:
                    raise ValueError('time void retry conflict')
                return original
            record = self.db.execute('SELECT entity_id FROM project_time_records WHERE record_id=?',(data['record_id'],)).fetchone()
            if record != (data['entity_id'],):
                raise ValueError('time record must exist in the same entity')
            if self.db.execute('SELECT 1 FROM project_time_voids WHERE record_id=?',(data['record_id'],)).fetchone():
                raise ValueError('time record is already voided')
            result = dict(data, actor_id=actor_id, recorded_at=datetime.now(timezone.utc).isoformat(),payload_digest=payload_digest)
            self.db.execute('INSERT INTO project_time_voids VALUES(?,?,?,?)',
                (data['record_id'],data['entity_id'],data['void_event_id'],_canonical(result)))
            return result


@dataclass(frozen=True, slots=True)
class TimeCapture:
    entity_id: str
    period_start: str
    as_of: str
    projects_json: str
    records_json: str
    voids_json: str
    policy: str = POLICY


def _read_projects(ledger):
    return [json.loads(row[0]) for row in ledger._connection.execute('SELECT result_json FROM management_projects ORDER BY project_id')]


def capture_time(ledger, as_of):
    cutoff = accounting_date(as_of)
    if not ledger._empty.period_start <= cutoff <= ledger._empty.period_end:
        raise ValueError('time capture cutoff must be within the supported accounting period')
    with ledger._transaction():
        return _capture_time(ledger, as_of)


def _capture_time(ledger, as_of):
    cutoff = accounting_date(as_of)
    if not ledger._empty.period_start <= cutoff <= ledger._empty.period_end:
        raise ValueError("time capture cutoff must be within the supported accounting period")
    projects = _read_projects(ledger)
    records = [json.loads(r[0]) for r in ledger._connection.execute('SELECT result_json FROM project_time_records ORDER BY work_date,worker_id,start_minute,record_id')]
    voids = [json.loads(r[0]) for r in ledger._connection.execute('SELECT result_json FROM project_time_voids ORDER BY record_id')]
    return TimeCapture(ledger._empty.catalog.entity_id,ledger._empty.period_start.isoformat(),cutoff.isoformat(),
                       _canonical(projects),_canonical(records),_canonical(voids))


def _duration(minutes):
    hours, remainder = divmod(minutes, 60)
    return f'{hours}h {remainder}m'


def time_report(capture):
    """Current recorded knowledge at a work-date cutoff; no wages or ledger effects."""
    if not isinstance(capture,TimeCapture) or capture.policy != POLICY:
        raise ValueError('unsupported time capture or policy')
    projects, all_records, all_voids = map(json.loads,(capture.projects_json,capture.records_json,capture.voids_json))
    void_by_id = {v['record_id']:v for v in all_voids}
    replacements = {r['replaces_record_id']:r['record_id'] for r in all_records if r['replaces_record_id']}
    records = [dict(r,status='voided' if r['record_id'] in void_by_id else 'active',
                    void=void_by_id.get(r['record_id']),replacement_record_id=replacements.get(r['record_id']))
               for r in all_records if capture.period_start <= r['work_date'] <= capture.as_of]
    active = [r for r in records if r['status']=='active']
    recorded = sum(r['minutes'] for r in records)
    voided = sum(r['minutes'] for r in records if r['status']=='voided')
    total = sum(r['minutes'] for r in active)
    grouped = {}
    for row in active:
        key = (row['project_id'],row['worker_id'],row['work_date'])
        grouped[key] = grouped.get(key,0)+row['minutes']
    groups = [dict(project_id=p,worker_id=w,work_date=d,total_minutes=m,duration=_duration(m)) for (p,w,d),m in sorted(grouped.items())]
    captured = dict(entity_id=capture.entity_id,period_start=capture.period_start,as_of=capture.as_of,
                    projects=projects,records=all_records,voids=all_voids,policy=capture.policy)
    report = dict(entity_id=capture.entity_id,period_start=capture.period_start,as_of=capture.as_of,
        policy=capture.policy,policy_digest=digest(capture.policy),snapshot_digest=digest(captured),capture=captured,
        scope='Operational service time; separate from recorded financial costs and assumed costing rates. No wage or expense posting.',
        projects=projects,records=records,voids=[r['void'] for r in records if r['void']],active_intervals=active,groups=groups,
        recorded_minutes=recorded,voided_minutes=voided,total_minutes=total,duration=_duration(total),reconciled=recorded-voided==total)
    report['report_digest'] = digest(report)
    return report


def demo_project_time():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='project-time-demo-') as directory:
        workspace = Workspace(directory)
        before = workspace.report_package('2026-01-31')
        workspace.action('projects',dict(project_id='A',name='Project A',entity_id=workspace.catalog.entity_id,customer_id=None))
        data = dict(entity_id=workspace.catalog.entity_id,project_id='A',worker_id='worker-1',time_event_id='service-1',
                    work_date='2026-01-10',start_minute=540,end_minute=840,replaces_record_id=None)
        first = workspace.action('project-time',data)
        workspace.action('project-time',dict(data,time_event_id='service-2',work_date='2026-01-11'))
        assert workspace.action('project-time',data) == first
        try:
            workspace.action('project-time',dict(data,time_event_id='duplicate-interval'))
        except ValueError as error:
            assert 'overlap' in str(error)
        else:
            raise AssertionError('overlap was accepted')
        report = workspace.project_time('2026-01-31')
        assert report['total_minutes'] == 600
        assert workspace.report_package('2026-01-31') == before
        print('Project A: 600 minutes = 10h 0m. Exact event retry retained original audit; duplicate overlap rejected.')
        print('Operational time only. Financial actuals and portable reports unchanged; no wage or expense posting.')
        print('Time report:',report['report_digest'])
