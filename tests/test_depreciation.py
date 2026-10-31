"""Independent schedule expectations; projections never record depreciation."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.persistence import SQLiteLedger

ROOT = Path(__file__).resolve().parents[1]


class DepreciationTests(unittest.TestCase):
    def schedule(self, **changes):
        self.assertIsNotNone(importlib.util.find_spec('accounting_harness.depreciation'),
                             'straight-line schedule must be implemented')
        from accounting_harness.depreciation import depreciation_schedule
        inputs = dict(entity_id='demo-service-001', asset_id='synthetic-laptop',
                      cost='1200.00', residual='0.00', months=12, in_service='2026-01-15')
        inputs.update(changes)
        return depreciation_schedule(**inputs)

    def test_reference_full_months_and_carrying_values(self):
        result = self.schedule()
        self.assertEqual(result['basis'], 'supplied_inputs_projection')
        self.assertEqual(result['total_depreciation'], '1200.00')
        self.assertEqual(result['ending_carrying_value'], '0.00')
        self.assertEqual(len(result['rows']), 12)
        self.assertEqual([r['depreciation'] for r in result['rows']], ['100.00'] * 12)
        self.assertEqual(result['rows'][0], dict(month='2026-01', effective_date='2026-01-31',
            depreciation='100.00', accumulated_depreciation='100.00', carrying_value='1100.00'))
        self.assertEqual(result['rows'][-1], dict(month='2026-12', effective_date='2026-12-31',
            depreciation='100.00', accumulated_depreciation='1200.00', carrying_value='0.00'))

    def test_residual_final_remainder_and_leap_year(self):
        result = self.schedule(cost='100.00', residual='10.00', months=7, in_service='2027-11-30')
        self.assertEqual([r['depreciation'] for r in result['rows']], ['12.85'] * 6 + ['12.90'])
        self.assertEqual([r['effective_date'] for r in result['rows']],
            ['2027-11-30', '2027-12-31', '2028-01-31', '2028-02-29', '2028-03-31', '2028-04-30', '2028-05-31'])
        self.assertEqual(result['rows'][-1]['accumulated_depreciation'], '90.00')
        self.assertEqual(result['ending_carrying_value'], '10.00')

    def test_zero_allocations_and_single_month(self):
        tiny = self.schedule(cost='0.02', months=3)
        self.assertEqual([r['depreciation'] for r in tiny['rows']], ['0.00', '0.00', '0.02'])
        equal = self.schedule(cost='12.34', residual='12.34', months=2)
        self.assertEqual([r['carrying_value'] for r in equal['rows']], ['12.34', '12.34'])
        self.assertEqual(equal['total_depreciation'], '0.00')
        one = self.schedule(cost='12.34', residual='2.00', months=1, in_service='2026-02-28')
        self.assertEqual(one['rows'], [dict(month='2026-02', effective_date='2026-02-28',
            depreciation='10.34', accumulated_depreciation='10.34', carrying_value='2.00')])

    def test_large_cents_are_exact(self):
        result = self.schedule(cost='92233720368547758.07', residual='0.01', months=2)
        self.assertEqual([r['depreciation'] for r in result['rows']],
                         ['46116860184273879.03', '46116860184273879.03'])
        self.assertEqual(result['total_depreciation'], '92233720368547758.06')
        self.assertEqual(result['ending_carrying_value'], '0.01')

    def test_invalid_money_and_policy_refused(self):
        for changes in [dict(cost=x) for x in (0, 1.2, True, '0.00', '-1.00', '1.001', '1e2',
                'NaN', '92233720368547758.08', '1' * 65 + '.00')]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.schedule(**changes)
        for changes in [dict(residual='1200.01'), dict(residual=-1), dict(residual='-0.01'),
                        dict(currency='EUR'), dict(policy='daily-prorated')]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.schedule(**changes)

    def test_invalid_identity_life_and_dates_refused(self):
        for key, values in [('months', [True, 1.0, '12', 0, -1, 1201]),
                ('in_service', ['2026-02-29', '2026-1-1', '2026-01-01T00:00:00', None]),
                ('entity_id', ['', ' spaced ', 'bad\nname', 1, 'x' * 201]),
                ('asset_id', ['', 'bad\x00name', '\ud800', False])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises((ValueError, TypeError)):
                    self.schedule(**{key: value})
        with self.assertRaises(ValueError):
            self.schedule(in_service='9999-12-01', months=2)
        self.assertEqual(self.schedule(in_service='9999-12-31', months=1)['rows'][0]['effective_date'], '9999-12-31')
        self.assertEqual(self.schedule(in_service='0001-01-01', months=1200)['rows'][-1]['month'], '0100-12')

    def test_repeat_normalization_and_changed_inputs(self):
        original = self.schedule()
        frozen = copy.deepcopy(original)
        self.assertEqual(self.schedule(cost='01200.00'), original)
        for change in [dict(cost='1200.01'), dict(residual='1.00'), dict(months=11),
                dict(in_service='2026-01-16'), dict(entity_id='another'), dict(asset_id='another')]:
            with self.subTest(change=change):
                self.assertNotEqual(self.schedule(**change)['schedule_digest'], original['schedule_digest'])
        repeated = self.schedule()
        repeated['rows'][0]['depreciation'] = '999.00'
        self.assertEqual(original, frozen)
        self.assertEqual(self.schedule(), frozen)

    def cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, '-m', 'accounting_harness', *args],
                              cwd=cwd or ROOT, text=True, capture_output=True)

    def test_cli_json_and_invalid_request(self):
        args = ['depreciation-schedule', '--entity', 'demo-service-001', '--asset', 'synthetic-laptop',
                '--cost', '1200.00', '--residual', '0.00', '--months', '12', '--in-service', '2026-01-15']
        run = self.cli(*args)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), self.schedule())
        self.assertEqual(self.cli(*args).stdout, run.stdout)
        invalid = self.cli(*args, '--cost', '1.001')
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stdout, '')
        self.assertNotIn('Traceback', invalid.stderr)

    def test_demo_and_existing_ledger_unchanged(self):
        catalog = load_account_catalog(ROOT / 'data/fixtures/service-business-month.json')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.sqlite3'
            with SQLiteLedger(path, catalog=catalog, period_start='2026-01-01',
                    period_end='2026-01-31', known_source_ids={'synthetic-source'}) as ledger:
                ledger.admit(dict(id='owner', entity_id=catalog.entity_id, currency='USD',
                    effective_date='2026-01-01', description='Synthetic contribution',
                    source_ids=['synthetic-source'], lines=[
                        dict(account='1000', side='debit', amount='1200.00'),
                        dict(account='3000', side='credit', amount='1200.00')]),
                    idempotency_key='owner', actor_id='synthetic-human')
                before = (ledger.counts(), ledger.trial_balance('2026-01-31'), ledger.receipt('owner'))
                self.schedule()
                self.schedule()
                run = self.cli('demo-depreciation')
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn('100.00', run.stdout)
                self.assertIn('12.90', run.stdout)
                self.assertEqual((ledger.counts(), ledger.trial_balance('2026-01-31'), ledger.receipt('owner')), before)


if __name__ == '__main__':
    unittest.main()
