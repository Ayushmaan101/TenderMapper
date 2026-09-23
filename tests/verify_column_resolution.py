"""Checklist 3.3 verification — orchestrator.

Runs, in order:
  1. verify_column_resolution_unit.py - mocked Groq, real BM25 index, no AppTest
  2. verify_column_resolution_live.py - real Groq calls, real seeded schema
  3. verify_column_resolution_ui.py   - AppTest, through the real "Run Mapping" button

Run: python tests/verify_column_resolution.py
"""
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent

SUITES = [
    "verify_column_resolution_unit.py",
    "verify_column_resolution_live.py",
    "verify_column_resolution_ui.py",
]


def main() -> None:
    failures = []
    for suite in SUITES:
        print(f"\n{'=' * 70}\nRunning {suite}\n{'=' * 70}")
        r = subprocess.run([PY, str(HERE / suite)], capture_output=True, text=True)
        print(r.stdout, end="")
        if r.returncode != 0:
            print(r.stderr)
            failures.append(suite)

    print(f"\n{'=' * 70}")
    if failures:
        print(f"FAILED SUITES: {failures}")
        sys.exit(1)
    else:
        print(f"ALL {len(SUITES)} SUITES PASSED")


if __name__ == "__main__":
    main()
