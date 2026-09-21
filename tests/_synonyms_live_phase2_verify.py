"""Phase 2 of the live Groq synonym-expansion verification (checklist 1.4).

Reopens the DB phase 1 wrote to, in a genuinely separate OS process (real
cold reload), and confirms the live-generated synonyms actually persisted
to SQLite, byte-for-byte, alongside a pre-existing manual synonym that
must have survived the merge untouched.

Run as its own OS process by tests/verify_synonyms_live.py; never
imported directly.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import crud  # noqa: E402
from db.connection import get_connection  # noqa: E402


def main() -> None:
    db_path = sys.argv[1]
    snapshot_path = sys.argv[2]
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    checks: list[tuple[str, bool]] = []

    def check(label: str, condition: bool) -> None:
        checks.append((label, bool(condition)))
        print(f"{'OK  ' if condition else 'FAIL'} {label}")

    conn = get_connection(db_path)
    stored = crud.get_synonyms(conn, snapshot["column_id"])
    stored_texts = [s.synonym_text for s in stored]

    check("at least one live-generated synonym persisted", len(snapshot["actually_added"]) > 0)
    check(
        "every live-generated synonym is present in the reopened DB",
        all(s in stored_texts for s in snapshot["actually_added"]),
    )
    check(
        "the pre-existing manual synonym survived the merge untouched",
        snapshot["manual_synonym"] in stored_texts,
    )
    check(
        "total stored count == manual + live-added (nothing lost, nothing duplicated)",
        len(stored_texts) == 1 + len(snapshot["actually_added"]),
    )

    conn.close()

    if all(ok for _, ok in checks):
        print(f"ALL CHECKS PASSED ({len(checks)}/{len(checks)})")
        sys.exit(0)
    else:
        failed = [label for label, ok in checks if not ok]
        print(f"FAILED {len(failed)}/{len(checks)}:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
