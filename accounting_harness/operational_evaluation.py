"""Offline evaluation prerequisites; no live provider selection or accuracy claim.

One immutable policy per file. Every attempt keeps its full reservation, including
failure or process death. Unknown outcomes block dispatch rather than resend.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import MappingProxyType

from accounting_harness.persistence import _canonical, PersistenceBusy
from accounting_harness.provider import bounded_request, ProviderFailure
from accounting_harness.review import digest, protect_table

FIXTURES = Path(__file__).resolve().parents[1] / 'data/fixtures'
CORPUS = FIXTURES / 'operational-agent-cases.json'
MANIFEST = FIXTURES / 'operational-evaluation-manifest.json'
CORPUS_DIGEST = '9131dee5dce67fcd6cb5d6d067d5fd54e0d05f2d882f4b32bd9d43344941e80e'
REPEATS = ('cash_expense-rent', 'vendor_bill-software', 'prepaid_consumption-january', 'hostile-model-handoff')
APPLICATION_ID = 0x41484556
SCHEMA_VERSION = 1
MAX_INTEGER = 2**63 - 1
POLICY_FIELDS = {'manifest_digest', 'mode', 'max_requests', 'max_requests_per_sample',
                 'max_cost_nanodollars', 'reservation_nanodollars', 'max_elapsed_ms'}
OUTCOMES = {'received', 'provider_failed', 'provider_timeout', 'cancelled', 'invalid_usage', 'time_budget', 'clock_regression'}


def load_manifest(path=MANIFEST, *, corpus_path=CORPUS):
    """Reject changed evidence/labels, dropped cases, duplicates or scripted faults."""
    raw = Path(corpus_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORPUS_DIGEST:
        raise ValueError('frozen evaluation corpus differs')
    corpus = json.loads(raw)
    cases = [c for c in corpus['cases'] if c['category'] in ('reference', 'handoff')]
    by_id = {c['id']: c for c in cases}
    samples = [dict(sample_id=c['id'], case_id=c['id'], category=c['category'], repeat=False,
                    expected_digest=digest(c['expect'])) for c in cases]
    samples += [dict(sample_id='repeat-' + key, case_id=key, category=by_id[key]['category'], repeat=True,
                     expected_digest=digest(by_id[key]['expect'])) for key in REPEATS]
    expected = dict(schema_version=1, manifest_version='operational-semantic-v1', fictional=True,
                    corpus_digest=CORPUS_DIGEST, samples=samples,
                    excluded_cases=[c['id'] for c in corpus['cases'] if c['category'] in ('protocol', 'provider')])
    from accounting_harness.sources import load_source_document
    manifest = load_source_document(path)
    if _canonical(manifest) != _canonical(expected):
        raise ValueError('frozen evaluation manifest differs')
    return dict(manifest, digest=digest(manifest))


def _integer(value, name, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ValueError('invalid ' + name)
    return value


class EvaluationBudget:
    """Persistent offline experiment limits, independent of financial databases.

    A file is one experiment, not a budget pool indexed by caller-chosen IDs.
    This is not an authentication layer or permission to make a live request.
    """
    def __init__(self, path, policy, *, clock_ms=None):
        manifest = load_manifest()
        if (type(policy) is not dict or set(policy) != POLICY_FIELDS
                or policy['mode'] != 'offline_contract' or policy['manifest_digest'] != manifest['digest']):
            raise ValueError('invalid offline evaluation policy')
        for key in POLICY_FIELDS - {'manifest_digest', 'mode'}:
            _integer(policy[key], key, 0 if key in ('reservation_nanodollars', 'max_cost_nanodollars') else 1)
        self._policy = MappingProxyType(dict(policy))
        self.samples = frozenset(s['sample_id'] for s in manifest['samples'])
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._opened_ms = self._clock()
        self._opened_monotonic = time.monotonic_ns()
        self.db = sqlite3.connect(path, timeout=1, isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        try:
            with self._transaction():
                self._initialize()
        except BaseException:
            self.close()
            raise

    @property
    def policy(self):
        return self._policy

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self):
        try:
            self.db.execute('BEGIN IMMEDIATE')
            yield
            self.db.commit()
        except BaseException as error:
            self.db.rollback()
            if (isinstance(error, sqlite3.OperationalError)
                    and getattr(error, 'sqlite_errorcode', 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
                raise PersistenceBusy('evaluation busy; reopen the same experiment') from error
            raise

    def _initialize(self):
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        application = self.db.execute('PRAGMA application_id').fetchone()[0]
        if (version, application) == (SCHEMA_VERSION, APPLICATION_ID):
            canonical, self.started_ms = self.db.execute('SELECT policy, started_ms FROM experiment').fetchone()
            if canonical != _canonical(dict(self.policy)):
                raise ValueError('evaluation policy differs; budgets cannot be reset')
            return
        if version or application or self.db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
            raise ValueError('unsupported evaluation database')
        self.started_ms = self._clock()
        _integer(self.started_ms + self.policy['max_elapsed_ms'], 'deadline')
        self.db.execute('''CREATE TABLE experiment (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), policy TEXT NOT NULL,
            started_ms INTEGER NOT NULL CHECK(started_ms>=0)) STRICT''')
        self.db.execute('INSERT INTO experiment VALUES (1, ?, ?)', (_canonical(dict(self.policy)), self.started_ms))
        self.db.execute('''CREATE TABLE attempts (
            attempt INTEGER PRIMARY KEY, sample TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved>=0),
            recorded_ms INTEGER NOT NULL CHECK(recorded_ms>=0)) STRICT''')
        self.db.execute('''CREATE TABLE results (
            attempt INTEGER PRIMARY KEY REFERENCES attempts(attempt), cost INTEGER CHECK(cost>=0),
            outcome TEXT NOT NULL, recorded_ms INTEGER NOT NULL CHECK(recorded_ms>=0)) STRICT''')
        self.db.execute('''CREATE TABLE cancellation (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), recorded_ms INTEGER NOT NULL) STRICT''')
        self.db.execute('CREATE TABLE stopped (singleton INTEGER PRIMARY KEY CHECK(singleton=1), reason TEXT NOT NULL) STRICT')
        for table, key in (('stopped', 'singleton'), ('experiment', 'singleton'), ('attempts', 'attempt'), ('results', 'attempt'),
                           ('cancellation', 'singleton')):
            protect_table(self.db, table, f'{key}=NEW.{key}')
        self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def _clock(self):
        return _integer(self.clock_ms(), 'clock milliseconds')

    def _now(self):
        # Wall time counts process downtime; monotonic time prevents an in-process
        # backward adjustment from extending an already running deadline.
        wall = self._clock()
        last = self.db.execute('''SELECT max(recorded_ms) FROM (
            SELECT started_ms AS recorded_ms FROM experiment UNION ALL SELECT recorded_ms FROM attempts
            UNION ALL SELECT recorded_ms FROM results UNION ALL SELECT recorded_ms FROM cancellation)''').fetchone()[0]
        if wall < last or wall < self._opened_ms:
            raise ValueError('clock_regression')
        return max(wall, self._opened_ms + (time.monotonic_ns() - self._opened_monotonic) // 1_000_000)

    def _remaining(self):
        return self.started_ms + self.policy['max_elapsed_ms'] - self._now()

    def _cancelled(self):
        return bool(self.db.execute('SELECT 1 FROM cancellation').fetchone())

    def report(self):
        # A single SQL read observes a coherent request/result snapshot.
        row = self.db.execute('''SELECT count(*), coalesce(sum(a.reserved),0), coalesce(sum(r.cost),0),
            coalesce(sum(r.attempt IS NULL),0), coalesce(sum(r.cost IS NULL),0),
            coalesce(sum(r.outcome!='received'),0), (SELECT count(*) FROM cancellation),
            (SELECT reason FROM stopped)
            FROM attempts a LEFT JOIN results r ON a.attempt=r.attempt''').fetchone()
        return dict(mode='offline_contract', manifest_digest=self.policy['manifest_digest'],
                    requests=row[0], reserved_nanodollars=row[1], observed_nanodollars=row[2],
                    unknown_attempts=row[3], cost_complete=row[4] == 0, failed_attempts=row[5],
                    cancelled=bool(row[6]), stop_reason=row[7], live_verified=False)

    def reserve(self, sample):
        if type(sample) is not str or sample not in self.samples:
            raise ValueError('sample is not in the frozen semantic manifest')
        with self._transaction():
            stopped = self.db.execute('SELECT reason FROM stopped').fetchone()
            reason = stopped[0] if stopped else 'cancelled' if self._cancelled() else None
            report = self.report()
            if not reason:
                try:
                    if self._remaining() <= 0:
                        reason = 'time_budget'
                except ValueError:
                    reason = 'clock_regression'
                if reason:
                    self.db.execute('INSERT INTO stopped VALUES (1, ?)', (reason,))
            if not reason and report['unknown_attempts']:
                reason = 'completion_unknown; no automatic resend'
            if not reason and (not report['cost_complete'] or report['failed_attempts']):
                reason = 'evaluation_incomplete; no automatic resend'
            if not reason and report['requests'] >= self.policy['max_requests']:
                reason = 'request_budget'
            count = self.db.execute('SELECT count(*) FROM attempts WHERE sample=?', (sample,)).fetchone()[0]
            if not reason and count >= self.policy['max_requests_per_sample']:
                reason = 'sample_request_budget'
            reserved = self.policy['reservation_nanodollars']
            if not reason and report['reserved_nanodollars'] + reserved > self.policy['max_cost_nanodollars']:
                reason = 'cost_budget'
            if not reason:
                attempt = report['requests'] + 1
                self.db.execute('INSERT INTO attempts VALUES (?, ?, ?, ?)', (attempt, sample, reserved, self._clock()))
        if reason:
            raise ValueError(reason)
        return attempt

    def settle(self, attempt, *, cost_nanodollars, outcome='received'):
        _integer(attempt, 'attempt', 1)
        if outcome not in OUTCOMES:
            raise ValueError('invalid outcome')
        if cost_nanodollars is not None:
            _integer(cost_nanodollars, 'observed cost')
        with self._transaction():
            reserved = self.db.execute('SELECT reserved FROM attempts WHERE attempt=?', (attempt,)).fetchone()
            if not reserved or (cost_nanodollars is not None and cost_nanodollars > reserved[0]):
                raise ValueError('invalid usage or unknown attempt')
            old = self.db.execute('SELECT cost, outcome FROM results WHERE attempt=?', (attempt,)).fetchone()
            if old is not None:
                if old != (cost_nanodollars, outcome):
                    raise ValueError('settlement differs')
                return
            self.db.execute('INSERT INTO results VALUES (?, ?, ?, ?)', (attempt, cost_nanodollars, outcome, self._clock()))

    def cancel(self):
        with self._transaction():
            if not self._cancelled():
                self.db.execute('INSERT INTO cancellation VALUES (1, ?)', (self._clock(),))

    def dispatch(self, sample, worker, arguments=()):
        """Run an explicit offline worker with the existing killable process boundary.

        Worker protocol is bounded_request's pipe protocol. Only its validated
        cost_nanodollars value is retained; all other response fields are discarded.
        No default worker, credential lookup, provider URL or network enable flag.
        """
        attempt = self.reserve(sample)
        outcome, cost = 'provider_failed', None
        stop_reason = None
        def should_stop():
            nonlocal stop_reason
            if self._cancelled():
                stop_reason = 'cancelled'
            else:
                try:
                    if self._remaining() <= 0:
                        stop_reason = 'time_budget'
                except ValueError:
                    stop_reason = 'clock_regression'
            return stop_reason is not None
        try:
            remaining = self._remaining()
            if remaining <= 0:
                outcome = 'time_budget'
                raise ValueError(outcome)
            response = bounded_request(worker, arguments, timeout_ms=remaining, cancelled=should_stop)
            if type(response) is not dict:
                outcome = 'invalid_usage'
                raise ValueError(outcome)
            cost = response.get('cost_nanodollars')
            if type(cost) is not int or not 0 <= cost <= self.policy['reservation_nanodollars']:
                cost, outcome = None, 'invalid_usage'
                raise ValueError(outcome)
            if self._cancelled():
                outcome = 'cancelled'
                raise ValueError(outcome)
            if self._remaining() <= 0:
                outcome = 'time_budget'
                raise ValueError(outcome)
            outcome = 'received'
        except ProviderFailure as error:
            outcome = stop_reason or {'provider_timeout': 'provider_timeout', 'provider_cancelled': 'cancelled'}.get(str(error), 'provider_failed')
            raise ValueError(outcome) from None
        except Exception:
            raise ValueError(outcome) from None
        finally:
            self.settle(attempt, cost_nanodollars=cost, outcome=outcome)


def demo_evaluation_budget():
    from tempfile import TemporaryDirectory
    manifest = load_manifest()
    policy = dict(manifest_digest=manifest['digest'], mode='offline_contract', max_requests=2,
                  max_requests_per_sample=2, max_cost_nanodollars=100, reservation_nanodollars=50,
                  max_elapsed_ms=10000)
    sample = manifest['samples'][0]['sample_id']
    with TemporaryDirectory(prefix='accounting-evaluation-budget-') as directory:
        path = Path(directory) / 'experiment.sqlite3'
        for cost in (7, 11):
            with EvaluationBudget(path, policy) as budget:
                budget.settle(budget.reserve(sample), cost_nanodollars=cost)
        with EvaluationBudget(path, policy) as budget:
            try:
                budget.reserve(sample)
            except ValueError as error:
                assert str(error) == 'request_budget'
            else:
                raise AssertionError('aggregate request limit did not stop dispatch')
            report = budget.report()
            assert (report['requests'], report['reserved_nanodollars'], report['observed_nanodollars']) == (2, 100, 18)
        crash = Path(directory) / 'unknown.sqlite3'
        with EvaluationBudget(crash, policy) as budget:
            budget.reserve(sample)
        with EvaluationBudget(crash, policy) as budget:
            try:
                budget.reserve(sample)
            except ValueError as error:
                assert 'completion_unknown' in str(error)
            else:
                raise AssertionError('uncertain request was resent')
            assert not budget.report()['cost_complete']
    print('Frozen semantic manifest: 20 cases (14 reference, 6 handoff), 4 repeats; 11 injected faults excluded.')
    print('Reopened experiment: 2 requests, 100 reserved / 18 observed USD nanodollars; third request refused.')
    print('Interrupted reservation: retained, billing incomplete, reopen refused automatic resend.')
    print('Offline controls only: zero network requests; authenticated scoring and live verification remain pending.')
