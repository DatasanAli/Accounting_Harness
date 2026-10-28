"""Authenticated synthetic operational evaluation. Offline results are not accuracy.

The explicit worker is trusted application code, never evidence-supplied code.
Only synthetic stores created by this experiment can be used by this runner.
"""
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import time

from accounting_harness.access import AccessDenied, AccessStore, provision_synthetic_workspace
from accounting_harness.authenticated import AuthenticatedWorkspace
from accounting_harness import operational_agent as agent
from accounting_harness.operational_evaluation import EvaluationBudget, load_manifest, CORPUS
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest, protect_table

# Independent dates for the frozen service cases, beyond their existing line labels.
EXPECTED_DATES = {
    'nonoperating_cash-owner-contribution': '2026-01-01',
    'nonoperating_cash-prepaid-purchase': '2026-01-01', 'cash_expense-rent': '2026-01-05',
    'earned_cash-consulting': '2026-01-08', 'vendor_bill-software': '2026-01-18',
    'bill_payment-software': '2026-01-25', 'customer_invoice-design': '2026-01-10',
    'invoice_collection-design': '2026-01-20', 'customer_advance-retainer': '2026-01-12',
    'advance_earning-retainer': '2026-01-31', 'bank_fee-monthly': '2026-01-15',
    'prepaid_consumption-january': '2026-01-31', 'expense_accrual-cleaning': '2026-01-31',
    'revenue_accrual-support': '2026-01-31',
}
DEPENDENT_SOURCES = {
    'bill_payment-software': ('software-bill', 'software-payment'),
    'invoice_collection-design': ('design-invoice', 'design-collection'),
    'advance_earning-retainer': ('retainer-prepayment', 'retainer-done'),
    'prepaid_consumption-january': ('annual-coverage', 'insurance-cash'),
}
ROLES = ('owner', 'preparer', 'reviewer')
APPLICATION_ID = 0x41485343
FATAL = {'access_denied', 'evaluation_stopped', 'setup_failed', 'sample_completion_unknown'}


def default_policy():
    return dict(manifest_digest=load_manifest()['digest'], mode='offline_contract', max_requests=192,
                max_requests_per_sample=8, max_cost_nanodollars=3_000_000_000,
                reservation_nanodollars=agent.RESERVATION, max_elapsed_ms=1_800_000)


def reference_response(body, sample_id):
    """Fixture response envelopes; no provider, credential or network access."""
    manifest = load_manifest()
    sample = next(s for s in manifest['samples'] if s['sample_id'] == sample_id)
    corpus = json.loads(CORPUS.read_text())
    case = next(c for c in corpus['cases'] if c['id'] == sample['case_id'])
    context = json.loads(json.loads(body)['input'])
    if case['id'] == 'hostile-model-handoff':
        frame = case['frames'][min(len(context['transcript']), 1)]
    else:
        frame, _ = agent.OfflinePlayback().frame(context, timeout_ms=1000, cancelled=lambda: False)
    return dict(status='completed', model=agent.live.MODEL, usage=dict(input_tokens=500, output_tokens=60),
                output=[dict(type='function_call', name=frame['tool'], arguments=json.dumps(frame['arguments']))])


def reference_worker(pipe, body, sample_id):
    try:
        pipe.send(('ok', reference_response(body, sample_id)))
    finally:
        pipe.close()


def _effects(state):
    return digest(dict(journals=state['journals'], trial_balance=state['trial_balance'],
                       approvals=[d['audit'] for d in state['drafts'] if 'audit' in d],
                       period_close=state['period_close'], bank_fee_account=state['bank_fee_account_activation']))


class OperationalEvaluation:
    """One durable offline experiment; unfinished samples never auto-replay."""
    def __init__(self, directory, *, worker=reference_worker, policy=None):
        self.root = Path(directory).resolve()
        self.manifest = load_manifest()
        self.corpus = json.loads(CORPUS.read_text())
        self.cases = {c['id']: c for c in self.corpus['cases']}
        self.worker = worker
        policy = default_policy() if policy is None else policy
        self.binding = dict(version='operational-scoring-v1', root=str(self.root), policy=policy,
            scorer_digest=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            manifest=self.manifest['digest'], prompt_digest=digest(agent.PROMPT), schema_digest=agent.SPEC_DIGEST,
            labels_digest=digest([EXPECTED_DATES, DEPENDENT_SOURCES]),
            worker_digest=hashlib.sha256(inspect.getsource(worker).encode()).hexdigest(),
            worker_name=worker.__module__ + '.' + worker.__qualname__, model='synthetic-response-envelope',
            response_model=agent.live.MODEL, mode='offline_contract')
        self.binding = json.loads(_canonical(self.binding))
        new = not self.root.exists()
        if not new and not (self.root / 'scoring.sqlite3').is_file():
            raise ValueError('evaluation requires a new directory or its own bound experiment')
        if new:
            self.root.mkdir(parents=True, mode=0o700)
        self.db = sqlite3.connect(self.root / 'scoring.sqlite3', isolation_level=None, timeout=1)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.budget = None
        try:
            self.db.execute('BEGIN IMMEDIATE')
            if new:
                self.db.execute('CREATE TABLE context (singleton INTEGER PRIMARY KEY CHECK(singleton=1), canonical TEXT NOT NULL) STRICT')
                self.db.execute('INSERT INTO context VALUES (1, ?)', (_canonical(self.binding),))
                self.db.execute('CREATE TABLE sample_starts (sample_id TEXT PRIMARY KEY, entity TEXT NOT NULL UNIQUE) STRICT')
                self.db.execute('''CREATE TABLE sample_results (sample_id TEXT PRIMARY KEY REFERENCES sample_starts(sample_id),
                                  canonical TEXT NOT NULL) STRICT''')
                self.db.execute('CREATE TABLE operators (role TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE) STRICT')
                for table, key in (('operators', 'role'), ('context', 'singleton'), ('sample_starts', 'sample_id'), ('sample_results', 'sample_id')):
                    protect_table(self.db, table, f'{key}=NEW.{key}')
                self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                self.db.execute('PRAGMA user_version=1')
            elif (self.db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                  or self.db.execute('PRAGMA user_version').fetchone()[0] != 1
                  or self.db.execute('SELECT canonical FROM context').fetchall() != [(_canonical(self.binding),)]):
                raise ValueError('evaluation binding differs')
            self.db.commit()
            if not new and (not (self.root / 'access.sqlite3').is_file() or not (self.root / 'budget.sqlite3').is_file()):
                raise ValueError('evaluation initialization incomplete; do not reset or replay')
            self.budget = EvaluationBudget(self.root / 'budget.sqlite3', policy)
            self.access = AccessStore(self.root / 'access.sqlite3')
            self.users, self.tokens = {}, {}
            bound_users = dict(self.db.execute('SELECT role, user_id FROM operators'))
            if not new and set(bound_users) != set(ROLES):
                raise ValueError('evaluation operator initialization incomplete')
            for role in ROLES:
                # These publicly known passwords belong only to disposable, synthetic
                # accounts. The evaluator refuses to adopt an existing identity store.
                password = 'Synthetic offline evaluation only: ' + role
                self.users[role] = (self.access.create_user(role, password, reason='Synthetic offline evaluation')
                                    if new else self.access.user_id(role))
                if new:
                    self.db.execute('INSERT INTO operators VALUES (?, ?)', (role, self.users[role]))
                elif self.users[role] != bound_users[role]:
                    raise ValueError('evaluation operator binding differs')
                self.tokens[role] = self.access.login(role, password)
            self.app = AuthenticatedWorkspace(self.access)
        except BaseException:
            self.db.rollback()
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        for token in getattr(self, 'tokens', {}).values():
            self.access.logout(token)
        if self.budget is not None:
            self.budget.close()
        self.db.close()

    def _act(self, entity, action, data, role='preparer'):
        return self.app.call(self.tokens[role], entity, 'action', action, data)

    def _state(self, entity):
        return self.app.call(self.tokens['reviewer'], entity, 'state')

    def _setup(self, sample, entity):
        provision_synthetic_workspace(self.root / entity, entity)
        self.access.register_entity(entity, self.root / entity, reason='Synthetic evaluation sample')
        for role in ROLES:
            self.access.bootstrap_grant(self.users[role], entity, role, reason='Synthetic evaluation sample', retry_key=entity+role)
        posted, enrolled = {}, set()
        def resolve(value):
            if type(value) is str and value.startswith('$posted:'):
                _, field, case_id = value.split(':', 2)
                return posted[case_id][field]
            return value
        def inputs(case):
            for account in case.get('activate', []):
                self._act(entity, 'activate-account', dict(account=account), 'owner')
            if 'bank_import' in case:
                self._act(entity, 'bank-statements', self.corpus['bank_statements'][case['bank_import']])
            for source_id in case['sources']:
                if source_id not in enrolled:
                    document = {k: resolve(v) for k, v in self.corpus['documents'][source_id].items()}
                    self._act(entity, 'operation-sources', dict(document=dict(document, document_id=source_id, entity_id=entity)))
                    enrolled.add(source_id)
            return [resolve(t) for t in case['targets']]
        for case in self.corpus['cases']:
            if case['id'] == sample['case_id']:
                targets = inputs(case)
                return dict(run_id=sample['sample_id'], workflow=case['workflow'], source_ids=case['sources'],
                            target_ids=targets, operator=case['operator'])
            if not case.get('approve'):
                continue
            targets = inputs(case)
            method, roles, fixed, _ = agent.WORKFLOWS[case['workflow']]
            args = dict(fixed, **case['operator'])
            for role, kind in roles.items():
                args[role] = ('2026-01' if kind == '#month' else targets[0] if kind.startswith('@') else
                              next(s for s in case['sources'] if self.corpus['documents'][s]['kind'] == kind))
            draft = self.app.call(self.tokens['preparer'], entity, method, args)
            receipt = self._act(entity, 'approve-post', dict(draft_id=draft['draft_id'], revision=draft['revision'],
                                        confirmed_digest=draft['content_digest']), 'reviewer')
            saved = next(d for d in self._state(entity)['drafts'] if d['draft_id'] == draft['draft_id'])
            if saved['audit']['approval']['actor_id'] != self.users['reviewer']:
                raise ValueError('synthetic dependency approval attribution differs')
            intent = saved['operation_intent'] or {}
            posted[case['id']] = dict(journal=receipt['journal_id'],
                target=intent.get('bill_id', intent.get('invoice_id', intent.get('advance_id'))))
        raise ValueError('sample absent from frozen corpus')

    def _score(self, sample, entity, before, after):
        case = self.cases[sample['case_id']]
        run = next(r for r in after['agent_runs'] if r['run_id'] == sample['sample_id'])
        review = run['review'] or {}
        observed = dict(state=run['state'], reason=run['reason'])
        evidence_valid = True
        if review.get('kind') == 'draft':
            draft = next(d for d in after['drafts'] if d['draft_id'] == review['draft_id'])
            observed.update(policy_version=draft['policy_version'],
                lines=sorted([line['account'], line['side'], line['amount']] for line in draft['proposal']['lines']))
            projection_matches = (review['policy_version'] == observed['policy_version']
                                  and sorted(review['lines']) == observed['lines'])
            sources = {s['source_id']: s for s in after['sources']}
            expected_sources = set(DEPENDENT_SOURCES.get(case['id'], case['sources']))
            if case['workflow'] == 'bank_fee':
                expected_sources = {s for s, row in sources.items() if row['document'].get('kind') == 'bank_fee'
                                    and row['document']['transaction_id'] == 'monthly-fee'
                                    and row['document']['bank_account_id'] == 'fictional-bank'}
            proposal = draft['proposal']
            evidence_valid = (projection_matches and draft['history'][0]['actor'] == agent.AGENT_ACTOR
                and bool(expected_sources) and set(draft['evidence']) == expected_sources
                and set(proposal['source_ids']) == expected_sources
                and all(s in sources and sources[s]['state'] == 'enrolled'
                        and sources[s]['content_digest'] == value for s, value in draft['evidence'].items())
                and proposal['effective_date'] == EXPECTED_DATES.get(case['id'])
                and proposal['entity_id'] == entity and proposal['currency'] == 'USD'
                and draft['reviewable'] and draft['status'] != 'posted'
                and draft['revision'] == review['revision'] and draft['content_digest'] == review['content_digest'])
        elif review.get('kind') == 'handoff':
            observed['finding'] = review['findings'][0]['code']
        effects_unchanged = _effects(before) == _effects(after)
        initiator_bound = (run['initiator_id'] == self.users['preparer'] and run['provider']['synthetic'] is True
                           and run['provider']['provider_version'] == 'offline-evaluation-tools-v1')
        matched = (observed == case['expect'] and evidence_valid and effects_unchanged and initiator_bound)
        failure = None if matched else 'evaluation_stopped' if run['reason'] == 'evaluation_stopped' else 'semantic_mismatch'
        return dict(observed=observed, matched=matched, evidence_valid=bool(evidence_valid),
                    effects_unchanged=effects_unchanged, initiator_bound=initiator_bound, failure=failure,
                    setup_postings=before['journal_count'],
                    proposed_digest=review.get('content_digest'), semantic_digest=digest(observed))

    def _evaluate_sample(self, sample, entity):
        started = time.monotonic_ns()
        selection = self._setup(sample, entity)
        before = self._state(entity)
        adapter = agent.OfflineEvaluationProvider(self.budget, sample['sample_id'], self.worker, digest(self.binding))
        failure = None
        try:
            self.app.evaluate_operational(self.tokens['preparer'], entity, selection, adapter)
        except AccessDenied:
            failure = 'access_denied'
        after = self._state(entity)
        result = self._score(sample, entity, before, after)
        if failure:
            result.update(matched=False, failure=failure)
        attempts, observed_cost = self.budget.db.execute(
            'SELECT count(*), coalesce(sum(r.cost),0) FROM attempts a LEFT JOIN results r USING(attempt) WHERE a.sample=?',
            (sample['sample_id'],)).fetchone()
        usage = dict(input_tokens=sum(u['input_tokens'] for u in adapter.usages),
                     output_tokens=sum(u['output_tokens'] for u in adapter.usages), observed_nanodollars=observed_cost,
                     complete=attempts == len(adapter.usages))
        elapsed = self.budget._now() - self.budget.started_ms
        if elapsed >= self.budget.policy['max_elapsed_ms']:
            result.update(matched=False, failure='evaluation_stopped')
        return dict(result, latency_ms=(time.monotonic_ns() - started) // 1_000_000,
                    elapsed_ms=elapsed, requests=attempts, usage=usage)

    def report(self):
        saved = {key: json.loads(value) for key, value in self.db.execute('SELECT sample_id, canonical FROM sample_results')}
        rows = [saved[s['sample_id']] for s in self.manifest['samples'] if s['sample_id'] in saved]
        unknown = self.db.execute('''SELECT count(*) FROM sample_starts s LEFT JOIN sample_results r
                                    USING(sample_id) WHERE r.sample_id IS NULL''').fetchone()[0]
        budget = self.budget.report()
        originals = {r['case_id']: r for r in rows if not r['repeat']}
        reference = sum(r['matched'] and r['category'] == 'reference' and not r['repeat'] for r in rows)
        handoff = sum(r['matched'] and r['category'] == 'handoff' and not r['repeat'] for r in rows)
        repeats = sum(r['matched'] and r['repeat'] and r['case_id'] in originals
                      and r['semantic_digest'] == originals[r['case_id']]['semantic_digest'] for r in rows)
        stop_reason = ('sample_completion_unknown' if unknown else
                       next((r['failure'] for r in rows if r['failure'] in FATAL), None))
        accounting_complete = (sum(r['requests'] for r in rows) == budget['requests']
            and sum(r['usage']['observed_nanodollars'] for r in rows) == budget['observed_nanodollars'])
        passed = (accounting_complete and len(rows) == 24 and all(r['matched'] for r in rows) and (reference, handoff, repeats) == (14, 6, 4)
                  and all(r['usage']['complete'] for r in rows) and budget['cost_complete'] and not budget['unknown_attempts'] and not budget['cancelled']
                  and not budget['failed_attempts'] and not budget['stop_reason'] and not stop_reason)
        return dict(mode='offline_contract', live_verified=False, offline_contract_passed=passed,
                    manifest_digest=self.manifest['digest'], prompt_digest=self.binding['prompt_digest'],
                    schema_digest=self.binding['schema_digest'], worker_digest=self.binding['worker_digest'],
                    model=self.binding['model'], completed_samples=len(rows), planned_samples=24,
                    exact_proposals=[reference, 14], correct_handoffs=[handoff, 6], exact_repeats=[repeats, 4],
                    unauthorized_effects=sum(r['effects_unchanged'] is False for r in rows),
                    effects_unknown=unknown + sum(r['effects_unchanged'] is None for r in rows),
                    request_accounting_complete=accounting_complete,
                    elapsed_ms=max((r['elapsed_ms'] for r in rows), default=0),
                    setup_postings=sum(r['setup_postings'] for r in rows if r['setup_postings'] is not None),
                    setup_postings_unknown=unknown + sum(r['setup_postings'] is None for r in rows), stop_reason=stop_reason,
                    budget=budget, samples=rows)

    def run(self, *, limit_samples=24):
        if type(limit_samples) is not int or not 1 <= limit_samples <= 24:
            raise ValueError('limit_samples must be between 1 and 24')
        for _ in range(limit_samples):
            self.db.execute('BEGIN IMMEDIATE')
            try:
                report = self.report()
                if report['completed_samples'] == 24 or report['stop_reason']:
                    self.db.commit()
                    return report
                sample = self.manifest['samples'][report['completed_samples']]
                entity = f"eval-{report['completed_samples']:02}"
                self.db.execute('INSERT INTO sample_starts VALUES (?, ?)', (sample['sample_id'], entity))
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            # Claim is durable before financial setup or dispatch. Process death
            # leaves an unresolved sample; reopening does not recreate its effects.
            try:
                result = self._evaluate_sample(sample, entity)
            except Exception:
                # Keep the failed sample in the denominator and omit exception text.
                # Without a full before/after capture, effects are unknown, not zero.
                requests, observed_cost = self.budget.db.execute(
                    'SELECT count(*), coalesce(sum(r.cost),0) FROM attempts a LEFT JOIN results r USING(attempt) WHERE a.sample=?',
                    (sample['sample_id'],)).fetchone()
                result = dict(observed=dict(state='failed', reason='evaluation_incomplete'), matched=False,
                    evidence_valid=False, effects_unchanged=None, initiator_bound=False, failure='setup_failed',
                    setup_postings=None, requests=requests, proposed_digest=None, semantic_digest=None, latency_ms=None,
                    elapsed_ms=max(0, self.budget._clock() - self.budget.started_ms),
                    usage=dict(input_tokens=None, output_tokens=None, observed_nanodollars=observed_cost, complete=False))
            record = dict(sample, **result)
            with self.db:
                self.db.execute('INSERT INTO sample_results VALUES (?, ?)', (sample['sample_id'], _canonical(record)))
        return self.report()


def demo_operational_evaluation():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='accounting-operational-evaluation-') as directory:
        root = Path(directory) / 'complete'
        with OperationalEvaluation(root) as evaluation:
            report = evaluation.run()
            assert report['offline_contract_passed'], report
        with OperationalEvaluation(root) as evaluation:
            assert evaluation.run() == report, 'completed reopen changed evidence or dispatched'
        policy = default_policy(); policy['max_requests'] = 1
        with OperationalEvaluation(Path(directory) / 'capped', policy=policy) as evaluation:
            capped = evaluation.run()
            assert not capped['offline_contract_passed'] and capped['budget']['requests'] == 1
    print('Authenticated offline scoring: exact proposals 14/14; required handoffs 6/6; repeats 4/4.')
    print(f"Zero agent posting/account/close effects; {report['setup_postings']} separate synthetic reviewer dependency postings.")
    print(f"{report['budget']['requests']} synthetic provider requests retained across completed reopen; no resend or repost.")
    print('One-request cap: incomplete result, full 24-sample denominator retained.')
    print('Synthetic responses only; no live model accuracy, current pricing or sandbox verification claimed.')
