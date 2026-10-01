"""Durable, bounded fake-provider runs over the existing proposal-only tools."""

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from accounting_harness.agent_tools import AgentTools, ToolError, _check
from accounting_harness.domain.accounts import _validate_text
from accounting_harness.persistence import PersistenceBusy, _canonical
from accounting_harness.review import digest, protect_table

APPLICATION_ID = 0x4148524E  # AHRN; separate from ledger and source registry files.
SCHEMA_VERSION = 1
TERMINAL = frozenset(('completed', 'failed', 'exhausted', 'cancelled'))


def _integer(value, label, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer from {minimum} through {maximum}')


@dataclass(frozen=True, slots=True)
class RunLimits:
    tool_calls: int
    elapsed_ms: int
    cost_units: int
    retries: int

    def __post_init__(self):
        _integer(self.tool_calls, 'tool_calls', maximum=10000)
        _integer(self.elapsed_ms, 'elapsed_ms', minimum=1, maximum=86400000)
        _integer(self.cost_units, 'cost_units')
        _integer(self.retries, 'retries', maximum=10)


@dataclass(frozen=True, slots=True, init=False)
class FakeProvider:
    """Immutable offline fixture, never a network client or provider credential."""
    _script_json: str
    _timeouts_json: str
    cost_units: int
    latency_ms: int
    prompt_version: str

    def __init__(self, outputs, *, timeouts=None, cost_units=1, latency_ms=1, prompt_version='script-v1'):
        if type(outputs) is not list or len(outputs) > 10000:
            raise ValueError('fake outputs must be a list of at most 10000 frames')
        _integer(cost_units, 'fake cost units')
        _integer(latency_ms, 'fake latency milliseconds', maximum=86400000)
        _validate_text(prompt_version, 'prompt version')
        timeouts = {} if timeouts is None else timeouts
        if type(timeouts) is not dict:
            raise ValueError('timeouts must map script indices to timeout counts')
        for index, count in timeouts.items():
            _integer(index, 'timeout index', maximum=len(outputs) - 1)
            _integer(count, 'timeout count', maximum=100)
        object.__setattr__(self, '_script_json', json.dumps(outputs, sort_keys=True, allow_nan=False))
        object.__setattr__(self, '_timeouts_json', _canonical(timeouts))
        object.__setattr__(self, 'cost_units', cost_units)
        object.__setattr__(self, 'latency_ms', latency_ms)
        object.__setattr__(self, 'prompt_version', prompt_version)

    @property
    def identity(self):
        return dict(provider_version='fake-v1', prompt_version=self.prompt_version,
                    fingerprint=digest([self._script_json, self._timeouts_json, self.cost_units,
                                        self.latency_ms, self.prompt_version]),
                    cost_units=self.cost_units, latency_ms=self.latency_ms)

    def has_step(self, index):
        return index < len(json.loads(self._script_json))

    def request(self, index, attempt):
        if attempt <= json.loads(self._timeouts_json).get(str(index), 0):
            raise TimeoutError('synthetic timeout')
        return json.loads(self._script_json)[index]


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    run_id: str
    sequence: int
    state: str
    next_step: int
    provider_attempts: int
    tool_calls: int
    cost_units: int
    elapsed_ms: int
    provider_retries: int
    dispatch_attempts: int
    intent_json: str | None
    result_json: str | None
    review_json: str | None
    reason: str
    recorded_at_ms: int
    actor_id: str


class SQLiteRunEngine:
    """Single-entity run log; one connection per thread, no daemon or scheduler.

    A durable intent and dispatch reservation precede any tool side effect.
    Run DB locks serialize callers; draft commits use their existing ledger
    transaction and are recovered by immutable receipt after process death.
    """
    def __init__(self, path, store, *, clock_ms=None, busy_timeout_ms=2000):
        _integer(busy_timeout_ms, 'busy timeout', maximum=60000)
        self.store = store
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._busy_timeout_ms = busy_timeout_ms
        ledger_path = store.db.execute('PRAGMA database_list').fetchone()[2]
        registry_path = store.registry._connection.execute('PRAGMA database_list').fetchone()[2]
        if not ledger_path or not registry_path or str(path) == ':memory:':
            raise ValueError('resumable runs require file-backed ledger, registry and run storage')
        self._path = str(Path(path).resolve())
        if self._path in (str(Path(ledger_path).resolve()), str(Path(registry_path).resolve())):
            raise ValueError('run log must be separate from ledger and registry')
        self._scope = _canonical(dict(entity_id=store.ledger._empty.catalog.entity_id,
                                      ledger_path=str(Path(ledger_path).resolve()),
                                      registry_path=str(Path(registry_path).resolve()),
                                      ledger_context=store.ledger._context, policy_version=store.policy_version,
                                      tool_schema_digest=digest(AgentTools.schemas()),
                                      allowed_tools=sorted(AgentTools.schemas())))
        self.db = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, isolation_level=None)
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA synchronous=FULL')
            with self._transaction():
                self._initialize()
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _transaction(self):
        try:
            # ponytail: one write lock for all local runs; shard run files if contention matters.
            self.db.execute('BEGIN IMMEDIATE')
            yield
            self.db.commit()
        except BaseException as error:
            self.db.rollback()
            if (isinstance(error, sqlite3.OperationalError)
                    and getattr(error, 'sqlite_errorcode', 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
                raise PersistenceBusy('run log busy; retry the same run ID') from error
            raise

    def _initialize(self):
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        application = self.db.execute('PRAGMA application_id').fetchone()[0]
        if version == SCHEMA_VERSION and application == APPLICATION_ID:
            if self.db.execute('SELECT canonical FROM run_context').fetchall() != [(self._scope,)]:
                raise ValueError('run log entity/ledger/registry/policy/tool scope differs')
            return
        if version or application:
            raise ValueError('unsupported run log schema/application')
        if self.db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
            raise ValueError('refusing a nonempty unversioned run database')
        self.db.execute('CREATE TABLE run_context (canonical TEXT PRIMARY KEY) STRICT')
        self.db.execute('INSERT INTO run_context VALUES (?)', (self._scope,))
        self.db.execute('CREATE TABLE runs (run_id TEXT PRIMARY KEY, config_json TEXT NOT NULL) STRICT, WITHOUT ROWID')
        self.db.execute('''CREATE TABLE run_checkpoints (
            run_id TEXT NOT NULL REFERENCES runs(run_id), sequence INTEGER NOT NULL CHECK(sequence>=0),
            checkpoint_json TEXT NOT NULL, PRIMARY KEY(run_id, sequence)
        ) STRICT, WITHOUT ROWID''')
        for table, condition in (('run_context', '1'), ('runs', 'run_id=NEW.run_id'),
                                 ('run_checkpoints', 'run_id=NEW.run_id AND sequence=NEW.sequence')):
            protect_table(self.db, table, condition)
        self.db.execute('''CREATE TRIGGER checkpoint_sequence BEFORE INSERT ON run_checkpoints
            WHEN NEW.sequence != (SELECT coalesce(max(sequence)+1,0) FROM run_checkpoints WHERE run_id=NEW.run_id)
            BEGIN SELECT RAISE(ABORT, 'checkpoint sequence must be contiguous'); END''')
        self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def _now(self):
        now = self._clock_ms()
        _integer(now, 'clock milliseconds')
        return now

    @staticmethod
    def _provider(provider):
        if type(provider) is not FakeProvider:
            raise TypeError('Step 11 supports only the offline FakeProvider')
        return provider.identity

    def start(self, run_id, *, task_id, provider, actor_id, limits):
        for value, name in ((run_id, 'run ID'), (task_id, 'task ID'), (actor_id, 'actor ID')):
            _validate_text(value, name)
        if type(limits) is not RunLimits:
            raise TypeError('limits must be RunLimits')
        config = dict(task_id=task_id, actor_id=actor_id, limits=asdict(limits), provider=self._provider(provider),
                      scope=self._scope)
        with self._transaction():
            row = self.db.execute('SELECT config_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if row:
                previous = json.loads(row[0])
                previous.pop('created_at_ms')
                if previous != config:
                    raise ValueError('run ID already binds different configuration')
                return self._get(run_id)
            now = self._now()
            config['created_at_ms'] = now
            self.db.execute('INSERT INTO runs VALUES (?,?)', (run_id, _canonical(config)))
            first = RunCheckpoint(run_id, 0, 'ready', 0, 0, 0, 0, 0, 0, 0,
                                  None, None, None, 'started', now, actor_id)
            self._insert(first)
            return first

    def _insert(self, checkpoint):
        self.db.execute('INSERT INTO run_checkpoints VALUES (?,?,?)',
                        (checkpoint.run_id, checkpoint.sequence, _canonical(asdict(checkpoint))))

    def _get(self, run_id):
        row = self.db.execute('SELECT checkpoint_json FROM run_checkpoints WHERE run_id=? ORDER BY sequence DESC LIMIT 1',
                              (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunCheckpoint(**json.loads(row[0]))

    def configuration(self, run_id):
        """Canonical immutable task/scope/provider/limit metadata; no raw script."""
        return _canonical(self._config(run_id))

    def get(self, run_id):
        return self._get(run_id)

    def trace(self, run_id):
        rows = self.db.execute('SELECT checkpoint_json FROM run_checkpoints WHERE run_id=? ORDER BY sequence',
                               (run_id,)).fetchall()
        if not rows:
            raise KeyError(run_id)
        return tuple(RunCheckpoint(**json.loads(row[0])) for row in rows)

    def _config(self, run_id, provider=None):
        row = self.db.execute('SELECT config_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        config = json.loads(row[0])
        if config['scope'] != self._scope or config['scope'] != self.db.execute('SELECT canonical FROM run_context').fetchone()[0]:
            raise ValueError('run scope differs')
        if self.store.policy_version != json.loads(self._scope)['policy_version']:
            raise ValueError('run policy changed')
        if provider is not None and config['provider'] != self._provider(provider):
            raise ValueError('provider/script/prompt/usage differs from original run')
        return config

    def _elapsed(self, current, config):
        return max(current.elapsed_ms, self._now() - config['created_at_ms'])

    def _append(self, current, config, **changes):
        changes.setdefault('elapsed_ms', self._elapsed(current, config))
        result = replace(current, sequence=current.sequence + 1,
                         recorded_at_ms=max(current.recorded_at_ms, self._now()), **changes)
        self._insert(result)
        return result

    def _exhaust(self, current, config, reason):
        return self._append(current, config, state='exhausted', reason=reason)

    def _prepare(self, current, config, provider):
        limits = config['limits']
        elapsed = self._elapsed(current, config)
        if elapsed >= limits['elapsed_ms']:
            return self._exhaust(current, config, 'time_budget')
        if not provider.has_step(current.next_step):
            return self._append(current, config, state='awaiting_review' if current.review_json else 'completed', reason='script_finished')
        if current.tool_calls >= limits['tool_calls']:
            return self._exhaust(current, config, 'tool_call_budget')
        if current.cost_units + provider.cost_units > limits['cost_units']:
            return self._exhaust(current, config, 'cost_budget')
        simulated_ms = (current.provider_attempts + 1) * provider.latency_ms
        if max(elapsed, simulated_ms) > limits['elapsed_ms']:
            return self._exhaust(current, config, 'time_budget')
        charged = replace(current, provider_attempts=current.provider_attempts + 1,
                          cost_units=current.cost_units + provider.cost_units, elapsed_ms=max(elapsed, simulated_ms))
        try:
            output = provider.request(current.next_step, current.provider_retries + 1)
        except TimeoutError:
            retries = current.provider_retries + 1
            return self._append(charged, config, state='failed' if retries > limits['retries'] else 'ready',
                                provider_retries=retries,
                                reason='provider_retry_exhausted' if retries > limits['retries'] else 'provider_timeout')
        if type(output) is dict and set(output) == {'stop'}:
            try:
                _validate_text(output['stop'], 'stop reason')
                if len(output['stop']) > 240:
                    raise ValueError('stop reason too long')
            except (TypeError, ValueError):
                return self._append(charged, config, state='failed', reason='invalid_provider_output')
            return self._append(charged, config, state='awaiting_review' if current.review_json else 'completed', reason=output['stop'])
        if type(output) is not dict or set(output) != {'tool', 'arguments'}:
            return self._append(charged, config, state='failed', reason='invalid_provider_output')
        schemas = AgentTools.schemas()
        try:
            name = output['tool']
            if type(name) is not str or name not in schemas:
                raise ToolError('tool not allowed')
            _check(schemas[name], output['arguments'])
            if output['arguments']['entity_id'] != self.store.ledger._empty.catalog.entity_id:
                raise ToolError('entity outside scope')
            if name == 'save_draft':
                output['arguments']['idempotency_key'] = 'run:' + digest([self._path, self._scope, current.run_id, current.next_step])
        except ToolError:
            return self._append(charged, config, state='failed', reason='invalid_tool_call')
        return self._append(charged, config, state='pending_tool', intent_json=_canonical(output),
                            tool_calls=current.tool_calls + 1, dispatch_attempts=0, provider_retries=0,
                            reason='tool_intent')

    def _recover(self, current, config):
        if not current.intent_json:
            return None
        intent = json.loads(current.intent_json)
        if intent['tool'] != 'save_draft':
            return None
        args = intent['arguments']
        with self.store.ledger._transaction():
            row = self.store.db.execute("SELECT digest, draft_id, revision FROM review_requests WHERE operation='save' AND key=?",
                                         (args['idempotency_key'],)).fetchone()
            if row is None:
                return None
            expected = digest(['save', args['draft_id'], args['expected_revision'], config['actor_id'], args['reason'],
                               args['proposal'], args['evidence'], self.store.policy_version])
            if row[0] != expected:
                raise ToolError('recovery receipt does not match persisted intent')
            return AgentTools._revision(self.store._get(row[1], row[2]))

    def _result(self, current, config, result, *, recovered=False):
        intent = json.loads(current.intent_json)
        name = intent['tool']
        if name == 'read_accounts':
            reference = dict(entity_id=result['entity_id'], catalog_digest=digest(result['accounts']))
        elif name == 'get_evidence':
            reference = {k: result[k] for k in ('entity_id', 'source_id', 'content_digest')}
        else:
            reference = {k: v for k, v in result.items() if k != 'findings'}
            reference['finding_codes'] = [f['code'] for f in result['findings']]
            if name == 'validate_proposal':
                reference['proposal_digest'] = digest(intent['arguments']['proposal'])
        reference['tool'] = name
        review_json = _canonical(reference) if name in ('save_draft', 'request_review') else current.review_json
        state = 'awaiting_review' if name == 'request_review' else 'ready'
        reason = 'tool_result_recovered' if recovered else 'tool_completed'
        if self._elapsed(current, config) >= config['limits']['elapsed_ms']:
            state, reason = 'exhausted', 'time_budget_after_result'
        return self._append(current, config, state=state, next_step=current.next_step + 1,
                            result_json=_canonical(reference), review_json=review_json, intent_json=None,
                            dispatch_attempts=0, reason=reason)

    @contextmanager
    def _dispatch_lock(self):
        # macOS/Linux advisory lock spans the two SQLite transactions. Keep the
        # file in place: unlinking it can split contenders across different inodes.
        try:
            import fcntl
        except ImportError as error:
            raise ValueError('run execution requires macOS/Linux advisory locks') from error
        with open(self._path + '.dispatch.lock', 'a+b') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise PersistenceBusy('another worker is advancing this run log') from error
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def advance(self, run_id, provider):
        self._provider(provider)
        with self._dispatch_lock():
            return self._advance(run_id, provider)

    def _advance(self, run_id, provider):
        with self._transaction():
            config = self._config(run_id, provider)
            current = self._get(run_id)
            if current.state in TERMINAL or current.state == 'awaiting_review':
                return current
            if current.state == 'ready':
                return self._prepare(current, config, provider)
            try:
                recovered = self._recover(current, config)
            except ToolError:
                return self._append(current, config, state='failed', reason='recovery_conflict')
            if recovered is not None:
                return self._result(current, config, recovered, recovered=True)
            if self._elapsed(current, config) >= config['limits']['elapsed_ms']:
                return self._exhaust(current, config, 'time_budget')
            if current.dispatch_attempts >= config['limits']['retries'] + 1:
                return self._append(current, config, state='failed', reason='tool_retry_exhausted')
            reserved = self._append(current, config, state='executing_tool',
                                    dispatch_attempts=current.dispatch_attempts + 1, reason='tool_dispatch')
        return self._dispatch(run_id, reserved.sequence, provider)

    def _dispatch(self, run_id, sequence, provider):
        with self._transaction():
            config = self._config(run_id, provider)
            current = self._get(run_id)
            # A cancellation or another worker may have won between transactions.
            if current.sequence != sequence or current.state != 'executing_tool':
                return current
            if self._elapsed(current, config) >= config['limits']['elapsed_ms']:
                return self._exhaust(current, config, 'time_budget')
            intent = json.loads(current.intent_json)
            try:
                result = AgentTools(self.store, actor_id=config['actor_id']).call(intent['tool'], intent['arguments'])
            except PersistenceBusy:
                failed = current.dispatch_attempts >= config['limits']['retries'] + 1
                return self._append(current, config, state='failed' if failed else 'pending_tool',
                                    reason='tool_retry_exhausted' if failed else 'tool_busy')
            except ToolError:
                return self._append(current, config, state='failed', reason='tool_denied')
            return self._result(current, config, result)

    def run(self, run_id, provider):
        while True:
            checkpoint = self.advance(run_id, provider)
            if checkpoint.state in TERMINAL or checkpoint.state == 'awaiting_review':
                return checkpoint

    def resume(self, run_id, provider):
        self._provider(provider)
        with self._transaction():
            config = self._config(run_id, provider)
            current = self._get(run_id)
            if current.state == 'awaiting_review':
                return self._append(current, config, state='completed', reason='review_handoff_acknowledged')
            if current.state in TERMINAL:
                return current
        return self.run(run_id, provider)

    def cancel(self, run_id, *, actor_id, reason):
        _validate_text(actor_id, 'cancelling actor')
        _validate_text(reason, 'cancellation reason')
        if len(reason) > 240:
            raise ValueError('cancellation reason must be at most 240 characters')
        with self._transaction():
            config = self._config(run_id)
            current = self._get(run_id)
            if current.state in TERMINAL:
                return current
            recovered = self._recover(current, config)
            if recovered is not None:
                current = self._result(current, config, recovered, recovered=True)
            return self._append(current, config, state='cancelled', actor_id=actor_id, reason=reason)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
