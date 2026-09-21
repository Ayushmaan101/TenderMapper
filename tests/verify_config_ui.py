"""Checklist 1.3 verification.

Phase 1 actually launches the real Streamlit app (via Streamlit's own
AppTest harness — no browser needed, no new dependency) against a
disposable temp DB and drives it through add/edit/delete/reorder actions
on tables, columns, and synonyms by clicking the real buttons in
config/ui.py. Phase 2 reopens that same DB file in a genuinely separate
OS process (a real cold reload) and asserts every action persisted.

Run: python tests/verify_config_ui.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "config_ui_test.db")

        print(f"Phase 1 (drive the live Streamlit app via AppTest), db: {db_path}")
        r1 = subprocess.run(
            [PY, str(HERE / "_config_ui_phase1_drive.py"), db_path],
            capture_output=True,
            text=True,
        )
        print(r1.stdout, end="")
        if r1.returncode != 0:
            print(r1.stderr)
            print("PHASE 1 (drive UI) FAILED")
            sys.exit(1)

        print(f"Phase 2 (cold reload, separate process), db: {db_path}")
        r2 = subprocess.run(
            [PY, str(HERE / "_config_ui_phase2_verify.py"), db_path],
            capture_output=True,
            text=True,
        )
        print(r2.stdout, end="")
        if r2.returncode != 0:
            print(r2.stderr)
            print("PHASE 2 (cold-reload verify) FAILED")
            sys.exit(1)

        print("CONFIG UI VERIFICATION PASSED")


if __name__ == "__main__":
    main()
