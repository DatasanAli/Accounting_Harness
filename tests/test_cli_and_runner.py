import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_tests.py"


class CLITests(unittest.TestCase):
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
