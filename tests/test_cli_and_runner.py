import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_tests.py"


class CLITests(unittest.TestCase):
    def test_source_demo_preserves_repeat_and_distinct_identity(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "demo-source"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ("Registered: 1 source, 1 registration event",
                     "Reopened repeat: True; 1 unchanged source",
                     "Distinct identity: 2 sources; equal content digests: True",
                     "Rejected changed content; original evidence preserved",
                     "Registration only; ledger source context unchanged",
                     "Temporary synthetic database removed"):
            self.assertIn(text, result.stdout)

    def test_reversal_demo_cancels_expense_and_preserves_original_after_reopen(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "demo-reversal"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ("Original expense: 5100 debit 125.00; 1000 credit 125.00",
                     "Reversal correction -> expense: 5100 credit 125.00; 1000 debit 125.00",
                     "2026-01-09: debits 125.00 / credits 125.00 USD",
                     "2026-01-10: debits 0.00 / credits 0.00 USD",
                     "Pre-reversal snapshot reproduced: 125.00 / 125.00 USD",
                     "Original receipt unchanged after reversal and reopen",
                     "Retried: 2 journals, 2 events, 1 reversal",
                     "Temporary synthetic database removed"):
            self.assertIn(text, result.stdout)

    def test_persistence_demo_restarts_and_retries_without_duplicate_posting(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "demo-persistence"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for stage in ("Persisted", "Reopened", "Retried"):
            self.assertIn(f"{stage}: 9 journals, 18 lines, 9 events, 9 retry records", result.stdout)
        self.assertIn("Debits 13300.00 / credits 13300.00 USD; Cash 9400.00 USD", result.stdout)
        self.assertIn("Original receipt preserved", result.stdout)
        self.assertIn("Temporary synthetic database removed", result.stdout)

    def test_ledger_demo_displays_reference_trial_balance_and_scope(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "demo-ledger"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Unadjusted trial balance as of 2026-01-31", result.stdout)
        self.assertIn("Entity: demo-service-001 | Currency: USD", result.stdout)
        self.assertIn("Policy: unadjusted-zero-opening-v1", result.stdout)
        self.assertIn("Included entries: T01, T02, T03, T04, T05, T06, T07, T08, T09", result.stdout)
        self.assertRegex(result.stdout, r"1000\s+Cash\s+9400\.00\s+0\.00")
        self.assertRegex(result.stdout, r"TOTAL\s+13300\.00\s+13300\.00")
        self.assertIn("balances are not saved after exit", result.stdout)

    def test_journal_demo_shows_acceptance_and_rejection(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "demo-journal"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ACCEPTED: debits 1000.00 / credits 1000.00 USD", result.stdout)
        self.assertIn("REJECTED: debits 1000.00 / credits 999.00 USD", result.stdout)
        self.assertIn("Difference: 1.00 USD", result.stdout)
        self.assertIn("unbalanced at lines", result.stdout)

    def test_account_demo_displays_catalog_and_exact_addition(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "demo-accounts"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Entity: demo-service-001 | Currency: USD", result.stdout)
        self.assertIn("13 validated accounts.", result.stdout)
        self.assertIn("0.10 + 0.20 = 0.30 USD (30 cents)", result.stdout)
        self.assertIn("Rejected excess precision '1.005'", result.stdout)
        self.assertRegex(result.stdout, r"1590\s+Accumulated Depreciation\s+asset\s+credit")
        self.assertRegex(result.stdout, r"3100\s+Owner Drawings\s+equity\s+debit")

    def test_unknown_command_is_rejected(self):
        result = subprocess.run([sys.executable, "-m", "accounting_harness", "post"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


class TestRunnerTests(unittest.TestCase):
    def run_discovery(self, directory):
        return subprocess.run([sys.executable, str(RUNNER), "--start-directory", str(directory)],
                              cwd=directory, capture_output=True, text=True, timeout=10)

    def test_empty_discovery_fails_instead_of_passing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_discovery(directory)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no application tests discovered", result.stderr)

    def test_real_test_failure_sets_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "test_failure.py").write_text(
                "import unittest\nclass Failure(unittest.TestCase):\n"
                "    def test_failure(self):\n        self.fail('intentional failure')\n")
            result = self.run_discovery(directory)
        self.assertEqual(result.returncode, 1)
        self.assertIn("intentional failure", result.stderr)

    def test_passing_test_can_import_package_outside_repository_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "test_success.py").write_text(
                "import unittest\nfrom accounting_harness.domain.money import Money\n"
                "class Success(unittest.TestCase):\n"
                "    def test_success(self):\n        self.assertEqual(Money.parse('1.00').cents, 100)\n")
            result = self.run_discovery(directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ran 1 test", result.stderr)


if __name__ == "__main__":
    unittest.main()
