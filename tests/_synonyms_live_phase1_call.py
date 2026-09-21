"""Phase 1 of the live Groq synonym-expansion verification (checklist 1.4).

Makes one real call to Groq (using the real GROQ_API_KEY from .env) for
one of the actual seeded requirement texts, merges the result into a
fresh temp DB, closes the connection, and writes a snapshot for phase 2
to check against in a genuinely separate process.

Run as its own OS process by tests/verify_synonyms_live.py; never
imported directly. Exits non-zero (with a clear message) if the live
call itself fails - a real API/network problem, not a code bug, should
be visible rather than silently skipped.
"""
import json
import sys
from pathlib import Path

# LLM-generated synonym text can contain characters (e.g. ≤, em dashes)
# that the default Windows console codepage can't encode; this is a test
# harness printing concern, not a data-correctness one.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.synonyms import expand_synonyms, merge_new_synonyms  # noqa: E402
from db import crud  # noqa: E402
from db.connection import get_connection  # noqa: E402
from db.schema import init_db  # noqa: E402
from seed.seed_data import TABLE_1_ITEMS  # noqa: E402


def main() -> None:
    db_path = sys.argv[1]
    snapshot_path = sys.argv[2]

    column_name, requirement_text = TABLE_1_ITEMS[3]  # "Item 4", WHO-GMP text
    print(f"Calling Groq live for column '{column_name}'...")
    result = expand_synonyms(column_name, requirement_text)

    if not result.success:
        print(f"LIVE CALL FAILED: {result.error}")
        sys.exit(1)

    print(f"Live call OK. Got {len(result.synonyms)} synonym(s): {result.synonyms}")

    conn = get_connection(db_path)
    init_db(conn)
    table_id = crud.create_table(conn, "Live Test Table")
    column_id = crud.create_column(conn, table_id, column_name, requirement_text)

    # Also prove the merge step (not just raw storage) via the real path
    # config/ui.py uses, including a pre-existing manual synonym that
    # must survive untouched.
    crud.add_synonym(conn, column_id, "MANUALLY ADDED BEFORE EXPANSION")
    added = merge_new_synonyms(conn, column_id, result.synonyms)
    conn.close()

    snapshot = {
        "column_id": column_id,
        "requested_synonyms": result.synonyms,
        "actually_added": added,
        "manual_synonym": "MANUALLY ADDED BEFORE EXPANSION",
    }
    Path(snapshot_path).write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    print("PHASE 1 (live call + merge + persist) COMPLETE")


if __name__ == "__main__":
    main()
