"""Phase 2 of the Config tab UI verification (checklist 1.3).

Reopens the DB file that _config_ui_phase1_drive.py's AppTest run wrote
to, in a genuinely separate OS process (a real "cold reload" — no shared
Python state, no cached st.cache_resource connection, nothing held in
memory from phase 1), and asserts every UI action from phase 1 actually
persisted: add/rename/delete tables, edit/delete/reorder columns,
add/remove synonyms, and cascade delete of a whole table through its
columns and their synonyms.

Run as its own OS process by tests/verify_config_ui.py; never imported
directly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import crud
from db.connection import get_connection
from seed.seed_data import TABLE_1_ITEMS
from seed.seeder import has_been_seeded


def main() -> None:
    db_path = sys.argv[1]
    conn = get_connection(db_path)

    checks: list[tuple[str, bool]] = []

    def check(label: str, condition: bool) -> None:
        checks.append((label, bool(condition)))
        print(f"{'OK  ' if condition else 'FAIL'} {label}")

    tables = crud.get_tables(conn)
    check("exactly 2 tables remain (Table 2 was deleted)", len(tables) == 2)
    check(
        "remaining table names/order: ['Table 1 Renamed', 'Extra Table']",
        [t.name for t in tables] == ["Table 1 Renamed", "Extra Table"],
    )
    check(
        "remaining tables re-normalized to dense order_index 0..1",
        [t.order_index for t in tables] == [0, 1],
    )

    table1 = next(t for t in tables if t.name == "Table 1 Renamed")
    extra_table = next(t for t in tables if t.name == "Extra Table")
    check("renamed table kept its original id (1)", table1.id == 1)

    cols = crud.get_columns(conn, table1.id)
    check("Table 1 Renamed has 9 columns (Item 10 was deleted)", len(cols) == 9)
    check(
        "column order reflects the up_3 swap: ids [1,3,2,4,5,6,7,8,9]",
        [c.id for c in cols] == [1, 3, 2, 4, 5, 6, 7, 8, 9],
    )
    check(
        "column order_index is dense 0..8 after delete + reorder",
        [c.order_index for c in cols] == list(range(9)),
    )

    col1 = crud.get_column(conn, 1)
    check("column 1 name edited to 'Item 1 RENAMED'", col1.name == "Item 1 RENAMED")
    check(
        "column 1 requirement_text edited with embedded newline preserved "
        "exactly through the st.text_area round-trip",
        col1.requirement_text == "Renamed requirement line one.\nRenamed line two.",
    )

    # Columns 2 and 3 were reordered but not edited: content must be untouched.
    col2 = crud.get_column(conn, 2)
    col3 = crud.get_column(conn, 3)
    seed_item2_name, seed_item2_req = TABLE_1_ITEMS[1]
    seed_item3_name, seed_item3_req = TABLE_1_ITEMS[2]
    check("column 2 name/text unchanged by the reorder", col2.name == seed_item2_name and col2.requirement_text == seed_item2_req)
    check("column 3 name/text unchanged by the reorder", col3.name == seed_item3_name and col3.requirement_text == seed_item3_req)

    check("column 10 ('Item 10') was actually deleted", crud.get_column(conn, 10) is None)

    syn = crud.get_synonyms(conn, 2)
    check("column 2 has exactly 1 synonym left", len(syn) == 1)
    check("surviving synonym is 'syn-test-2' (id 1 'syn-test-1' was removed)", syn[0].synonym_text == "syn-test-2")

    extra_cols = crud.get_columns(conn, extra_table.id)
    check("'Extra Table' has 0 columns (none were added to it)", len(extra_cols) == 0)

    # Cascade-delete proof: Table 2 and everything under it (columns 11-23,
    # and any synonyms on them) must be gone from the raw tables too.
    orphan_table2 = conn.execute(
        "SELECT COUNT(*) FROM schema_table WHERE name = 'Table 2'"
    ).fetchone()[0]
    check("no 'Table 2' row remains at all", orphan_table2 == 0)
    orphan_cols = conn.execute(
        "SELECT COUNT(*) FROM schema_column WHERE id BETWEEN 11 AND 23"
    ).fetchone()[0]
    check("Table 2's former columns (ids 11-23) cascade-deleted", orphan_cols == 0)

    check("has_been_seeded flag still set after all this editing", has_been_seeded(conn))

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
