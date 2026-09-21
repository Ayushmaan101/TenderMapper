"""Checklist 1.4 verification — one real Groq call, cross-process persistence.

Makes one real live call to Groq (using the real GROQ_API_KEY from .env)
in phase 1, merges the result into a temp DB, then reopens that same DB
file in a genuinely separate OS process in phase 2 to confirm it actually
persisted to SQLite - satisfying "test a live call verifying synonyms are
stored and persisted to SQLite" with real network + real cold reload.

Requires a working GROQ_API_KEY in .env. If it fails due to a network/API
problem rather than a code bug, that is reported clearly rather than
silently passed.

Run: python tests/verify_synonyms_live.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "synonyms_live_test.db")
        snapshot_path = str(Path(tmp) / "snapshot.json")

        print(f"Phase 1 (live Groq call + merge + persist), db: {db_path}")
        r1 = subprocess.run(
            [PY, str(HERE / "_synonyms_live_phase1_call.py"), db_path, snapshot_path],
            capture_output=True,
            text=True,
        )
        print(r1.stdout, end="")
        if r1.returncode != 0:
            print(r1.stderr)
            print("PHASE 1 (live call) FAILED")
            sys.exit(1)

        print(f"Phase 2 (cold reload, separate process), db: {db_path}")
        r2 = subprocess.run(
            [PY, str(HERE / "_synonyms_live_phase2_verify.py"), db_path, snapshot_path],
            capture_output=True,
            text=True,
        )
        print(r2.stdout, end="")
        if r2.returncode != 0:
            print(r2.stderr)
            print("PHASE 2 (cold-reload verify) FAILED")
            sys.exit(1)

        print("LIVE SYNONYM VERIFICATION PASSED")


if __name__ == "__main__":
    main()
