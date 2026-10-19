"""Offline QuickBooks JournalEntry read contract: staging mirror only, never the local books."""
import copy
import hashlib
import http.client
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

from accounting_harness import qbo_read as q
from accounting_harness.access import AccessStore, AccessDenied, provision_synthetic_workspace
from accounting_harness.workspace import Workspace, AuthenticatedWorkspace

CODES = {'1000', '1100', '1200', '1500', '1590', '2000', '2100', '3000', '3100', '4000', '5000', '5100', '5200'}
REFERENCE_ACCOUNTS = [
    dict(local_account='1000', remote_account_id='35', debit_cents=20000, credit_cents=40000, debit_amount='200.00', credit_amount='400.00'),
    dict(local_account='4000', remote_account_id='79', debit_cents=0, credit_cents=20000, debit_amount='0.00', credit_amount='200.00'),
    dict(local_account='5000', remote_account_id='57', debit_cents=10000, credit_cents=0, debit_amount='100.00', credit_amount='0.00'),
    dict(local_account='5100', remote_account_id='61', debit_cents=30000, credit_cents=0, debit_amount='300.00', credit_amount='0.00')]


def book_files(root):
    # The authoritative books plus evidence/run state; the staging mirror is deliberately excluded.
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('ledger.sqlite3', 'sources.sqlite3', 'runs.sqlite3')}


def deterministic(report):
    return {k: report[k] for k in ('status', 'complete', 'reconciled', 'accepted', 'accounts', 'total_debits', 'total_credits', 'pages', 'checkpoint_digest')}


def position(request):
    return int(parse_qs(urlsplit(request['url']).query)['query'][0].split('STARTPOSITION ')[1].split()[0])


class StagingContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root / q.FILE
        self.now = datetime(2026, 2, 1, tzinfo=timezone.utc)
        self.config = dict(q.CONNECTOR, page_size=2)  # Injected test page size; production stays 100 x 100.

    def read(self, transport, batch_id='january', config=None, path=None, **options):
        return q.read_batch(path or self.path, entity_id='fictional-entity', account_codes=CODES, batch_id=batch_id,
            actor_id='synthetic-preparer', transport=transport, config=config or self.config, clock=lambda: self.now, **options)

    def count(self, table, path=None):
        with sqlite3.connect(path or self.path) as db:
            return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def journals(self, change=None):
        rows = q.reference_journals()
        if change: change(rows)
        return rows

    def test_reference_two_pages_reconcile_without_touching_local_books(self):
        workspace = Workspace(self.root / 'books')
        # The first state() lazily creates empty subsidiary schemas; baseline the bytes after it.
        package, state = workspace.report_package('2026-01-31'), workspace.state()
        files = book_files(workspace.root)
        simulator = q.SimulatedQBO()
        report = q.read_batch(workspace.root / q.FILE, entity_id=workspace.catalog.entity_id, account_codes={a.code for a in workspace.catalog.list_accounts()},
            batch_id='january', actor_id='synthetic-preparer', transport=simulator, config=self.config, clock=lambda: self.now)
        self.assertEqual(report['label'], 'Offline contract simulation')
        self.assertIn('authoritative', report['ownership'])
        self.assertEqual((report['status'], report['complete'], report['reconciled']), ('complete', True, True))
        self.assertEqual([(r['remote_id'], r['sync_token'], r['total_amount']) for r in report['accepted']],
                         [('101', '0', '100.00'), ('102', '0', '200.00'), ('103', '0', '300.00')])
        self.assertEqual((report['total_debit_cents'], report['total_credit_cents'], report['total_debits'], report['total_credits']), (60000, 60000, '600.00', '600.00'))
        self.assertEqual(report['accounts'], REFERENCE_ACCOUNTS)
        self.assertEqual([(p['position'], p['row_count'], p['next_position']) for p in report['pages']], [(1, 2, 3), (3, 1, 4)])
        self.assertEqual(report['totals_basis'], 'Reconciled full batch total')
        self.assertEqual(book_files(workspace.root), files)
        self.assertEqual(workspace.report_package('2026-01-31'), package)
        self.assertEqual(workspace.state(), state)
        # Exact retry after completion reuses the mirror and makes no request.
        again = q.read_batch(workspace.root / q.FILE, entity_id=workspace.catalog.entity_id, account_codes=CODES, batch_id='january',
            actor_id='synthetic-owner', transport=simulator, config=self.config, clock=lambda: self.now)
        self.assertEqual(again, report); self.assertEqual(len(simulator.requests), 2)
        self.assertEqual(workspace.external_reads()['batches'], [report])
        self.assertEqual(self.count('qbo_observations', workspace.root / q.FILE), 3)

    def test_request_contract_targets_only_the_bounded_sandbox_query(self):
        simulator = q.SimulatedQBO(); self.read(simulator)
        first, second = simulator.requests
        url = urlsplit(first['url'])
        self.assertEqual((first['method'], url.scheme, url.netloc, url.path),
                         ('GET', 'https', 'sandbox-quickbooks.api.intuit.com', '/v3/company/9341450000000001/query'))
        self.assertEqual(parse_qs(url.query), {'query': ["SELECT * FROM JournalEntry WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-01-31' "
                                                         "ORDERBY Id STARTPOSITION 1 MAXRESULTS 2"], 'minorversion': ['75']})
        self.assertEqual(first['headers'], {'Accept': 'application/json'})
        self.assertEqual((position(first), position(second)), (1, 3))
        self.assertEqual(position(q.build_request(q.CONNECTOR, 101)), 101)
        self.assertIn('MAXRESULTS 100', unquote(q.build_request(q.CONNECTOR, 1)['url']))

    def test_strict_mapping_and_page_errors_stop_without_advancing(self):
        def amount(value):
            def change(rows):
                for line in rows[0]['Line']: line['Amount'] = value
            return change
        def account(rows):
            rows[0]['Line'][0]['JournalEntryLineDetail']['AccountRef'] = {'value': '999', 'name': 'Cash'}  # A matching name never maps.
        cases = [('currency', lambda r: r[0]['CurrencyRef'].update(value='EUR'), 'not USD'), ('account', account, 'unmapped'),
            ('window', lambda r: r[0].update(TxnDate='2026-02-01'), 'window'), ('date', lambda r: r[0].update(TxnDate='2026-02-30'), 'TxnDate'),
            ('precision', amount(Decimal('100.001')), 'Amount'), ('exponent', amount(Decimal('1E+2')), 'Amount'),
            ('negative', amount(Decimal('-100.00')), 'Amount'), ('zero', amount(Decimal('0.00')), 'Amount'), ('boolean', amount(True), 'Amount'),
            ('string', amount('100.00'), 'Amount'), ('nonfinite', amount(float('nan')), 'nonfinite'),
            ('unbalanced', lambda r: r[0]['Line'][1].update(Amount=Decimal('99.99')), 'balance'),
            ('one line', lambda r: r[0]['Line'].pop(), 'two positive lines'), ('line id', lambda r: r[0]['Line'][1].update(Id='0'), 'line Id'),
            ('posting', lambda r: r[0]['Line'][0]['JournalEntryLineDetail'].update(PostingType='debit'), 'PostingType'),
            ('sync token', lambda r: r[0].pop('SyncToken'), 'SyncToken'), ('page duplicate', lambda r: r[1].update(Id='101'), 'duplicate JournalEntry Id')]
        for name, change, expected in cases:
            with self.subTest(name=name):
                simulator = q.SimulatedQBO(self.journals(change))
                report = self.read(simulator, batch_id='bad-' + name.replace(' ', '-'))
                self.assertEqual((report['status'], report['pages'], report['accepted_count'], report['reconciled']), ('blocked', [], 0, False))
                self.assertIn(expected, report['exceptions'][0]['reason'])
                self.assertIn('Accepted', report['totals_basis'])
                self.assertEqual(self.read(simulator, batch_id='bad-' + name.replace(' ', '-')), report)
                self.assertEqual(len(simulator.requests), 1, 'refused pages require correction or a new batch, not blind retry')
        self.assertEqual(self.count('qbo_observations'), 0)

    def test_malformed_responses_and_statuses_are_refused(self):
        def raw(mutate, status=200, kind='application/json'):
            simulator = q.SimulatedQBO()
            def transport(request):
                _, headers, body = simulator(request)
                return status, {'Content-Type': kind}, mutate(body)
            return transport
        cases = [('duplicate field', raw(lambda b: b.replace(b'"SyncToken":"0"', b'"SyncToken":"0","SyncToken":"0"', 1)), 'duplicate JSON field'),
            ('malformed', raw(lambda b: b'{'), 'malformed JSON'), ('content type', raw(lambda b: b, kind='text/html'), 'application/json'),
            ('start', raw(lambda b: b.replace(b'"startPosition":1', b'"startPosition":2')), 'startPosition'),
            ('count', raw(lambda b: b.replace(b'"maxResults":2', b'"maxResults":3')), 'maxResults'),
            ('fault', raw(lambda b: b'{"Fault":{"Error":[]}}'), 'QueryResponse'), ('status', raw(lambda b: b, status=401), 'HTTP status 401'),
            ('size', raw(lambda b: b' ' * (q.MAX_BODY + 1)), '4 MiB')]
        for name, transport, expected in cases:
            with self.subTest(name=name):
                report = self.read(transport, batch_id='raw-' + name.replace(' ', '-'))
                self.assertEqual((report['status'], report['accepted_count']), ('blocked', 0))
                self.assertIn(expected, report['exceptions'][0]['reason'])

    def test_currency_absence_requires_captured_usd_only_knowledge(self):
        missing = self.journals(lambda r: r[0].pop('CurrencyRef'))
        report = self.read(q.SimulatedQBO(missing), batch_id='captured-usd')
        self.assertTrue(report['reconciled'])
        with q.QBOStagingStore(self.path, 'fictional-entity') as store:
            record = next(r for r in store.capture('captured-usd')['observations'] if r['remote_id'] == '101')
        self.assertEqual(record['currency_basis'], 'captured USD home currency; multicurrency disabled')
        unknown = self.read(q.SimulatedQBO(missing), batch_id='unknown-currency', config=dict(self.config, multicurrency_enabled=True))
        self.assertEqual(unknown['status'], 'blocked'); self.assertIn('lacks CurrencyRef', unknown['exceptions'][0]['reason'])

    def test_unsupported_detail_is_preserved_not_flattened(self):
        def change(rows):
            rows[0]['TxnTaxDetail'] = {'TotalTax': Decimal('0')}
            rows[2]['Line'][0]['JournalEntryLineDetail']['Entity'] = {'Type': 'Vendor', 'EntityRef': {'value': '7'}}
        report = self.read(q.SimulatedQBO(self.journals(change)))
        self.assertEqual((report['status'], report['complete'], report['reconciled']), ('complete', True, False))
        self.assertEqual([(r['remote_id'], r['status'], r['total_amount']) for r in report['accepted']],
                         [('101', 'unsupported', None), ('102', 'supported', '200.00'), ('103', 'unsupported', None)])
        self.assertEqual((report['total_debits'], report['total_credits']), ('200.00', '200.00'))
        self.assertEqual([(e['kind'], e['remote_id']) for e in report['exceptions']], [('unsupported', '101'), ('unsupported', '103')])
        self.assertIn('TxnTaxDetail', report['exceptions'][0]['reason']); self.assertIn('Entity', report['exceptions'][1]['reason'])
        self.assertIn('not a reconciled full total', report['totals_basis'])
        self.assertEqual([r['local_account'] for r in report['accounts']], ['1000', '4000'])

    def test_unsupported_records_still_refuse_bad_lines_and_detect_conflicts(self):
        def taxed(amount=Decimal('100.00'), account='57', tax=Decimal('0')):
            def change(rows):
                rows[0]['TxnTaxDetail'] = {'TotalTax': tax}
                rows[0]['Line'][0]['JournalEntryLineDetail']['AccountRef']['value'] = account
                for line in rows[0]['Line']: line['Amount'] = amount
            return change
        def note_line(amount):
            return lambda rows: rows[0]['Line'].append({'Id': '2', 'DetailType': 'DescriptionOnly', 'Description': 'Synthetic note', 'Amount': amount})
        for name, change, expected in (('precision', taxed(amount=Decimal('100.001')), 'Amount'), ('unmapped', taxed(account='999'), 'unmapped'),
                                       ('note exponent', note_line(Decimal('1E+999')), 'Amount'), ('note precision', note_line(Decimal('0.001')), 'Amount')):
            with self.subTest(name=name):
                report = self.read(q.SimulatedQBO(self.journals(change)), batch_id='taxed-' + name.replace(' ', '-'))
                self.assertEqual((report['status'], report['pages']), ('blocked', []))
                self.assertIn(expected, report['exceptions'][0]['reason'])
        self.assertEqual(self.read(q.SimulatedQBO(self.journals(taxed())), batch_id='taxed')['exceptions'][0]['kind'], 'unsupported')
        for name, change in (('amount', taxed(amount=Decimal('999.00'))), ('tax detail', taxed(tax=Decimal('5')))):
            with self.subTest(name=name):
                report = self.read(q.SimulatedQBO(self.journals(change)), batch_id='taxed-conflict-' + name.replace(' ', '-'))
                self.assertEqual(report['status'], 'blocked'); self.assertIn('conflicts', report['exceptions'][0]['reason'])

    def test_unstorable_identifier_and_malformed_transport_returns_are_recorded(self):
        simulator = q.SimulatedQBO()
        surrogate = lambda request: (lambda s, h, b: (s, h, b.replace(b'"Id":"101"', b'"Id":"\\ud800"', 1)))(*simulator(request))
        report = self.read(surrogate, batch_id='surrogate')
        self.assertEqual(report['status'], 'blocked'); self.assertIn('JournalEntry Id', report['exceptions'][0]['reason'])
        for index, value in enumerate([(200.0, {}, b''), (200, None, b''), (200, {}, 'text'), (200, {}), 'response', True]):
            with self.subTest(value=value):
                report = self.read(lambda request, v=value: v, batch_id=f'shape-{index}')
                self.assertEqual((report['status'], report['next_position'], report['attempts'][-1]['reason']),
                                 ('resumable', 1, 'invalid transport response'))

    def test_entity_connector_scope_and_configuration_are_bound(self):
        self.read(q.SimulatedQBO())
        with self.assertRaisesRegex(ValueError, 'different entity'):
            q.QBOStagingStore(self.path, 'other-entity')
        changed_map = dict(self.config, account_map=dict(self.config['account_map'], version='synthetic-qbo-map-v2'))
        with self.assertRaisesRegex(ValueError, 'different connector scope'):
            self.read(q.SimulatedQBO(), config=changed_map)
        for change in (dict(environment='production'), dict(realm_id='realm'), dict(page_size=101), dict(max_pages=0), dict(home_currency='EUR'),
                       dict(account_map=dict(version='v', accounts={'35': '9999'})), dict(window=dict(start='2026-01-31', end='2026-01-01')),
                       dict(url='https://example.invalid')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.read(q.SimulatedQBO(), batch_id='config', config=dict(self.config, **change))
        for batch_id in ('', 'a/b', 'x' * 81, 7):
            with self.subTest(batch_id=batch_id), self.assertRaises(ValueError):
                self.read(q.SimulatedQBO(), batch_id=batch_id)
        other_realm = self.read(q.SimulatedQBO(), batch_id='other-realm', config=dict(self.config, realm_id='1111'))
        self.assertEqual(other_realm['status'], 'blocked'); self.assertIn('HTTP status 400', other_realm['exceptions'][0]['reason'])

    def test_interrupt_before_and_after_page_commit_resumes_to_the_same_mirror(self):
        clean = self.read(q.SimulatedQBO(), path=self.root / 'clean.sqlite3')
        q.QBOStagingStore(self.path, 'fictional-entity').close()
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER injected_crash BEFORE INSERT ON qbo_events WHEN NEW.kind='page' BEGIN SELECT RAISE(ABORT,'injected crash'); END")
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'injected crash'):
            self.read(q.SimulatedQBO())
        self.assertEqual((self.count('qbo_observations'), self.count('qbo_events')), (0, 0))
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER injected_crash')

        class Death(BaseException):
            pass
        simulator = q.SimulatedQBO()
        def dies_after_first_commit(request):
            if position(request) == 3: raise Death()
            return simulator(request)
        with self.assertRaises(Death):
            self.read(dies_after_first_commit)
        self.assertEqual(self.count('qbo_events'), 1)
        resumed = q.SimulatedQBO(); report = self.read(resumed)
        self.assertEqual([position(r) for r in resumed.requests], [3])
        self.assertEqual(deterministic(report), deterministic(clean))
        dump = lambda path: list(sqlite3.connect(path).execute('SELECT * FROM qbo_observations ORDER BY remote_id'))
        self.assertEqual(dump(self.path), dump(self.root / 'clean.sqlite3'))

    def test_same_version_conflict_cannot_overwrite_and_new_versions_are_immutable(self):
        original = self.read(q.SimulatedQBO())
        def amounts(token, value):
            def change(rows):
                rows[0]['SyncToken'] = token
                for line in rows[0]['Line']: line['Amount'] = value
            return change
        conflict = self.read(q.SimulatedQBO(self.journals(amounts('0', Decimal('150.00')))), batch_id='conflict')
        self.assertEqual(conflict['status'], 'blocked'); self.assertIn('conflicts', conflict['exceptions'][0]['reason'])
        self.assertEqual(self.count('qbo_observations'), 3)
        edited = self.read(q.SimulatedQBO(self.journals(amounts('1', Decimal('150.00')))), batch_id='edited')
        self.assertTrue(edited['reconciled']); self.assertEqual(edited['total_debits'], '650.00')
        self.assertEqual(self.count('qbo_observations'), 4)
        with q.QBOStagingStore(self.path, 'fictional-entity') as store:
            self.assertEqual(q.batch_report(store.capture('january')), original)
        batches = {b['batch_id']: b for b in q.staged_batches(self.path, 'fictional-entity')['batches']}
        self.assertEqual(batches['january'], original)

    def test_rate_limit_persists_cursor_and_next_attempt_without_sleeping(self):
        simulator, calls = q.SimulatedQBO(), []
        def transport(request):
            calls.append(request)
            return (429, {'Retry-After': '120'}, b'') if len(calls) == 1 else simulator(request)
        first = self.read(transport)
        self.assertEqual((first['status'], first['next_position'], first['next_attempt_at']), ('rate_limited', 1, (self.now + timedelta(seconds=120)).isoformat()))
        self.now += timedelta(seconds=60)
        self.assertEqual(self.read(transport), first); self.assertEqual(len(calls), 1)
        self.now += timedelta(seconds=60)
        done = self.read(transport)
        self.assertTrue(done['reconciled']); self.assertEqual(len(calls), 3)
        self.assertEqual([a['kind'] for a in done['attempts']], ['rate_limited'])
        minimum = self.now + timedelta(seconds=60)  # 2026-02-01T00:03:00Z
        cases = (({'Retry-After': '5'}, minimum), ({'retry-after': 'Sun, 01 Feb 2026 00:10:00 GMT'}, datetime(2026, 2, 1, 0, 10, tzinfo=timezone.utc)),
                 ({'Retry-After': 'Sun, 01 Feb 2026 00:00:30 GMT'}, minimum), ({'Retry-After': 'soon'}, minimum), ({}, minimum),
                 ({'Retry-After': '999999'}, self.now + timedelta(days=1)), ({'Retry-After': 'Fri, 31 Dec 9999 00:00:00 GMT'}, self.now + timedelta(days=1)),
                 ({'Retry-After': 'Fri, 31 Dec 9999 23:00:00 -1200'}, minimum))  # Unrepresentable in UTC: invalid, minimum wait, no crash.
        for index, (header, expected) in enumerate(cases):
            with self.subTest(header=header):
                report = self.read(lambda request, h=header: (429, h, b''), batch_id=f'limit-{index}')
                self.assertEqual(report['next_attempt_at'], expected.isoformat())

    def test_rate_limit_wait_starts_at_arrival_and_survives_a_later_failure(self):
        def slow(request):
            self.now += timedelta(seconds=30)  # The response arrives 30 seconds after the request starts.
            return 429, {}, b''
        start = self.now
        report = self.read(slow)
        self.assertEqual(report['next_attempt_at'], (start + timedelta(seconds=90)).isoformat())
        with q.QBOStagingStore(self.path, 'fictional-entity') as store:
            store.record('january', 'transport_failure', 1, dict(reason='OSError'), 'concurrent-attempt', self.now)
        after = q.staged_batches(self.path, 'fictional-entity')['batches'][0]
        self.assertEqual((after['status'], after['next_attempt_at']), ('resumable', report['next_attempt_at']))
        calls = []
        self.read(lambda request: calls.append(request))
        self.assertEqual(calls, [], 'a concurrent failure cannot erase the recorded 429 wait')

    def test_transport_failures_remain_resumable_at_the_same_cursor(self):
        simulator, failures = q.SimulatedQBO(), [TimeoutError('timed out'), q.TransportError('reset'), (503, {}, b'')]
        def transport(request):
            if failures:
                failure = failures.pop(0)
                if isinstance(failure, BaseException): raise failure
                return failure
            return simulator(request)
        for reason in ('TimeoutError', 'TransportError', 'HTTP 503'):
            report = self.read(transport)
            self.assertEqual((report['status'], report['next_position'], report['attempts'][-1]['reason']), ('resumable', 1, reason))
        done = self.read(transport)
        self.assertTrue(done['reconciled']); self.assertEqual(len(done['attempts']), 3)

    def test_repeated_changed_and_nonadvancing_pages_are_exceptions(self):
        for name, token in (('repeated', '0'), ('changed', '1')):
            with self.subTest(name=name):
                rows = self.journals()
                replay = copy.deepcopy(rows[0]); replay['SyncToken'] = token
                simulator = q.SimulatedQBO(rows[:2] + [replay])
                report = self.read(simulator, batch_id=name)
                self.assertEqual((report['status'], report['accepted_count'], report['reconciled']), ('blocked', 2, False))
                self.assertIn(name + ' during batch', report['exceptions'][0]['reason'])
                self.assertEqual(report['total_debits'], '300.00'); self.assertIn('not a reconciled', report['totals_basis'])

    def test_page_caps_are_incomplete_not_successful_totals(self):
        def extra(identifier):
            row = copy.deepcopy(q.reference_journals()[0]); row['Id'] = identifier
            return row
        capped = dict(self.config, max_pages=2)
        for count, status in ((5, 'incomplete'), (4, 'incomplete'), (3, 'complete')):
            with self.subTest(count=count):
                simulator = q.SimulatedQBO((self.journals() + [extra('104'), extra('105')])[:count])
                report = self.read(simulator, batch_id=f'cap-{count}', config=capped)
                self.assertEqual((report['status'], report['complete'], report['reconciled'], report['next_position']),
                                 (status, status == 'complete', status == 'complete', None))
                self.assertEqual(report['accepted_count'], min(count, 4))
                self.read(simulator, batch_id=f'cap-{count}', config=capped)
                self.assertEqual(len(simulator.requests), 2)

    def test_concurrent_same_page_retry_records_one_page_per_cursor(self):
        simulator, barrier, results = q.SimulatedQBO(), threading.Barrier(2), []
        def transport(request):
            if position(request) == 1: barrier.wait(timeout=5)
            return simulator(request)
        threads = [threading.Thread(target=lambda: results.append(self.read(transport))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
        self.assertEqual(len(results), 2); self.assertEqual(results[0], results[1])
        self.assertTrue(results[0]['reconciled']); self.assertEqual(self.count('qbo_observations'), 3)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT position FROM qbo_events WHERE kind='page' ORDER BY position").fetchall(), [(1,), (3,)])

    def test_captured_report_is_pure_and_records_are_append_only(self):
        report = self.read(q.SimulatedQBO())
        with q.QBOStagingStore(self.path, 'fictional-entity') as store:
            capture = store.capture('january')
        self.assertEqual(q.batch_report(copy.deepcopy(capture)), report)
        altered = copy.deepcopy(capture); altered['observations'][0]['lines'][0]['amount_cents'] += 1
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            q.batch_report(altered)
        altered['input_digest'] = q.digest({k: v for k, v in altered.items() if k != 'input_digest'})
        with self.assertRaisesRegex(ValueError, 'page receipt'):
            q.batch_report(altered)
        capped = self.read(q.SimulatedQBO(), batch_id='capped', config=dict(self.config, max_pages=1))
        self.assertEqual(capped['status'], 'incomplete')
        with q.QBOStagingStore(self.path, 'fictional-entity') as store:
            forged = store.capture('capped')
        page = forged['events'][0]['detail']; page['terminal'] = 'complete'
        page['receipt_digest'] = q.digest({k: v for k, v in page.items() if k not in ('receipt_digest', 'checkpoint_digest')})
        page['checkpoint_digest'] = q.digest([forged['batch']['scope_digest'], page['receipt_digest']])
        forged['input_digest'] = q.digest({k: v for k, v in forged.items() if k != 'input_digest'})
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            q.batch_report(forged)
        db = sqlite3.connect(self.path); self.addCleanup(db.close)
        for sql in ("INSERT OR REPLACE INTO qbo_events SELECT batch_id,99,kind,position,detail_json,actor_id,recorded_at FROM qbo_events WHERE kind='page' LIMIT 1",
                    "UPDATE qbo_observations SET record_json='{}'", 'DELETE FROM qbo_events', "UPDATE qbo_batches SET actor_id='x'",
                    'DELETE FROM staging_context', "INSERT OR REPLACE INTO qbo_observations SELECT * FROM qbo_observations LIMIT 1"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)

    def test_demo_command(self):
        demo = subprocess.run([sys.executable, '-m', 'accounting_harness', 'demo-sandbox-read'], capture_output=True, text=True)
        self.assertEqual(demo.returncode, 0, demo.stderr)
        for text in ('Offline contract simulation', '600.00 / 600.00', 'rate limited', 'unchanged'):
            self.assertIn(text, demo.stdout)


class AuthenticatedReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.access = AccessStore(self.root / 'access.sqlite3')
        for entity in ('alpha', 'beta'):
            provision_synthetic_workspace(self.root / entity, entity)
            self.access.register_entity(entity, self.root / entity, reason='fixture')
        self.users, self.tokens = {}, {}
        for role in ('preparer', 'reviewer', 'owner'):
            self.users[role] = self.access.create_user(role, 'Synthetic fixture passphrase ' + role, reason='fixture')
            self.access.bootstrap_grant(self.users[role], 'alpha', role, reason='fixture', retry_key=role)
            self.tokens[role] = self.access.login(role, 'Synthetic fixture passphrase ' + role)
        self.facade = AuthenticatedWorkspace(self.access)

    def call(self, role, method, *args, entity='alpha'):
        return self.facade.call(self.tokens[role], entity, method, *args)

    def test_start_resume_read_permissions_cross_entity_and_revocation(self):
        files = book_files(self.root / 'alpha')
        with self.assertRaises(AccessDenied):
            self.call('reviewer', 'action', 'qbo-read', dict(batch_id='january'))
        report = self.call('preparer', 'action', 'qbo-read', dict(batch_id='january'))
        self.assertEqual((report['status'], report['reconciled'], report['total_debits'], report['started_by']), ('complete', True, '600.00', self.users['preparer']))
        self.assertEqual([p['row_count'] for p in report['pages']], [3])  # Production page size 100.
        self.assertEqual(self.call('owner', 'action', 'qbo-read', dict(batch_id='january')), report)
        self.assertEqual(self.call('reviewer', 'external_reads')['batches'], [report])
        for method, args in (('action', ('qbo-read', dict(batch_id='january'))), ('external_reads', ())):
            with self.assertRaises(AccessDenied):
                self.call('preparer', method, *args, entity='beta')
        for data in (dict(batch_id='x', realm_id='1111'), dict(batch_id='x', url='https://example.invalid'), {}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.call('owner', 'action', 'qbo-read', data)
        self.assertEqual(book_files(self.root / 'alpha'), files)
        self.assertFalse((self.root / 'beta' / q.FILE).exists())
        original = q.SimulatedQBO.__call__
        def revoke_then_serve(simulator, request):
            self.access.bootstrap_revoke(self.users['preparer'], 'alpha', reason='mid-batch revocation', retry_key='revoke')
            return original(simulator, request)
        with patch.object(q.SimulatedQBO, '__call__', revoke_then_serve), self.assertRaises(AccessDenied):
            self.call('preparer', 'action', 'qbo-read', dict(batch_id='revoked'))
        revoked = next(b for b in self.call('owner', 'external_reads')['batches'] if b['batch_id'] == 'revoked')
        self.assertEqual((revoked['status'], revoked['pages'], revoked['accepted_count']), ('resumable', [], 0))

    def test_http_route_status_view_and_strict_fields(self):
        from auth_fixture import make_server
        directory = self.root / 'http'
        server = make_server(directory, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        def request(method, path, data=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = dict(server.test_headers)
            if method == 'POST':
                headers.update({'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{server.server_port}', 'X-CSRF-Token': server.csrf_token})
            connection.request(method, path, json.dumps(data) if data is not None else None, headers)
            response = connection.getresponse(); result = (response.status, json.loads(response.read())); connection.close()
            return result
        status, state = request('GET', '/api/state')
        self.assertIn('qbo-read', state['allowed_actions'])
        self.assertEqual(request('GET', '/api/external-reads')[1]['batches'], [])
        self.assertFalse((directory / q.FILE).exists(), 'reading never creates the staging mirror')
        status, report = request('POST', '/api/qbo-read', dict(batch_id='http-january'))
        self.assertEqual((status, report['label'], report['total_credits']), (200, 'Offline contract simulation', '600.00'))
        self.assertEqual(request('POST', '/api/qbo-read', dict(batch_id='x', realm_id='1111'))[0], 409)
        self.assertEqual(request('GET', '/api/external-reads?realm_id=1111')[0], 409)
        self.assertEqual(request('GET', '/api/external-reads')[1]['batches'], [report])
        self.assertEqual(request('GET', '/api/state')[1]['journal_count'], state['journal_count'])

    def test_static_status_view_is_labeled_offline(self):
        static = Path(q.__file__).with_name('static')
        html, script = (static / 'index.html').read_text(), (static / 'app.js').read_text()
        for text in ('data-view="integrations"', 'id="view-integrations"', 'action="/api/qbo-read"', 'Offline contract simulation'):
            self.assertIn(text, html)
        self.assertIn("'/api/external-reads'", script)


if __name__ == '__main__':
    unittest.main()
