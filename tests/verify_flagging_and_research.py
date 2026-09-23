"""Checklist 4.2 verification — orchestrator.

Runs, in order:
  1. verify_confidence_flagging_unit.py - pure is_flagged()/threshold logic
  2. verify_manual_research_ui.py       - AppTest: flagging UI, manual
                                          re-search isolation, DB fingerprint

Run: python tests/verify_flagging_and_research.py
"""
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent

SUITES = ["verify_confidence_flagging_unit.py", "verify_manual_research_ui.py"]


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
