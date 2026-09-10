#!/usr/bin/env python3
"""Run application tests and fail when discovery unexpectedly finds no tests."""

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-directory", type=Path, default=ROOT / "tests")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    try:
        suite = unittest.TestLoader().discover(str(args.start_directory.resolve()), pattern="test_*.py")
    except (ImportError, OSError) as error:
        print(f"FAIL: could not discover tests: {error}", file=sys.stderr)
        return 1
    if suite.countTestCases() == 0:
        print("FAIL: no application tests discovered", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
