"""Checklist 1.4 verification — orchestrator.

Runs, in order:
  1. verify_synonyms_unit.py       - parsing/merge/failure logic, no network
  2. verify_synonyms_live.py       - one real Groq call, cross-process persistence
  3. verify_synonyms_ui_triggers.py - AppTest-driven trigger-scope + resilience

Run: python tests/verify_synonyms.py
"""
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent

SUITES = [
    "verify_synonyms_unit.py",
    "verify_synonyms_live.py",
    "verify_synonyms_ui_triggers.py",
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
