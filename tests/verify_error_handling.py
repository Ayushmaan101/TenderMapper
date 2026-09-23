"""Checklist 5.1 verification — orchestrator.

Runs, in order:
  1. verify_error_handling_unit.py - pure functions, no Streamlit
  2. verify_error_handling_ui.py   - AppTest, through the real "Run Mapping" button

Run: python tests/verify_error_handling.py
"""
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent

SUITES = ["verify_error_handling_unit.py", "verify_error_handling_ui.py"]


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
