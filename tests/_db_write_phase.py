"""Phase 1 of the db round-trip verification (checklist 1.1).

Creates schema data — including a deliberately messy multi-line
requirement string and a synonym with leading/trailing padding — writes an
expected-values snapshot next to the db, then exits. Run as its own OS
process by tests/verify_db_roundtrip.py; never imported directly.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import crud
from db.connection import get_connection
from db.schema import init_db

# Deliberately exercises: trailing spaces before a newline, a blank line,
# a tab-indented line, an em dash + curly quotes (non-ASCII), a
# leading-space line, and no trailing newline at the very end.
MULTILINE_REQUIREMENT = (
    "Line one with trailing spaces   \n"
    "\n"
    "\tTabbed line two\n"
    "Line three — em dash, “curly quotes”, and 3-years\n"
    "    Leading-space line four\n"
    "Final line, no trailing newline"
)

SYNONYM_WITH_PADDING = "  WHO-GMP   "  # deliberately not stripped


def main() -> None:
    db_path = sys.argv[1]
    snapshot_path = sys.argv[2]

    conn = get_connection(db_path)
    init_db(conn)

    # Tables created out of final order on purpose, then reordered, to
    # prove reorder_tables (not just insertion order) drives what's read back.
    id_a = crud.create_table(conn, "Table A")
    id_b = crud.create_table(conn, "Table B")
    id_c = crud.create_table(conn, "Table C")
    crud.reorder_tables(conn, [id_c, id_a, id_b])

    col_1 = crud.create_column(conn, id_a, "Item no. as per tender", "Item no. as per tender")
    col_2 = crud.create_column(conn, id_a, "WHO GMP/GMA Certificate", MULTILINE_REQUIREMENT)
    col_3 = crud.create_column(conn, id_a, "Narcotic license", "Narcotic license requirement text")
    # Reorder columns within table A too, for the same reason.
    crud.reorder_columns(conn, id_a, [col_3, col_1, col_2])

    crud.add_synonyms(conn, col_2, ["WHO-GMP", "WHO GMP", SYNONYM_WITH_PADDING, "Schedule M"])
    crud.add_synonyms(conn, col_3, ["narcotics license", "excise license"])

    conn.close()

    snapshot = {
        "table_order_names": ["Table C", "Table A", "Table B"],
        "table_a_id": id_a,
        "table_a_column_order_ids": [col_3, col_1, col_2],
        "table_a_column_order_names": [
            "Narcotic license",
            "Item no. as per tender",
            "WHO GMP/GMA Certificate",
        ],
        "col_2_id": col_2,
        "col_2_requirement_text": MULTILINE_REQUIREMENT,
        "col_3_id": col_3,
        "col_2_synonyms": ["WHO-GMP", "WHO GMP", SYNONYM_WITH_PADDING, "Schedule M"],
        "col_3_synonyms": ["narcotics license", "excise license"],
    }
    Path(snapshot_path).write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    print("WRITE PHASE OK")


if __name__ == "__main__":
    main()
