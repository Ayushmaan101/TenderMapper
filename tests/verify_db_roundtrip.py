"""Checklist 1.1 verification.

Creates schema/column/synonym data in one OS process, closes the
connection, reopens the same db file in a genuinely separate OS process
(via subprocess — different PID, no shared Python state), and asserts
byte-identical retrieval, preserved ordering, and correct cascade-delete
behavior.

Run: python tests/verify_db_roundtrip.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "roundtrip_test.db")
        snapshot_path = str(Path(tmp) / "snapshot.json")

        print(f"Phase 1 (write), db: {db_path}")
        r1 = subprocess.run(
            [PY, str(HERE / "_db_write_phase.py"), db_path, snapshot_path],
            capture_output=True,
            text=True,
        )
        print(r1.stdout, end="")
        if r1.returncode != 0:
            print(r1.stderr)
            print("WRITE PHASE FAILED")
            sys.exit(1)

        print(f"Phase 2 (read, separate process), db: {db_path}")
        r2 = subprocess.run(
            [PY, str(HERE / "_db_read_phase.py"), db_path, snapshot_path],
            capture_output=True,
            text=True,
        )
        print(r2.stdout, end="")
        if r2.returncode != 0:
            print(r2.stderr)
            print("READ PHASE FAILED")
            sys.exit(1)

        print("ROUND-TRIP VERIFICATION PASSED")


if __name__ == "__main__":
    main()
