"""Phase 2 of the db round-trip verification (checklist 1.1).

Reopens the db created by _db_write_phase.py in a brand-new OS process
(no shared Python state with phase 1) and asserts: byte-identical text
retrieval, preserved ordering after reorder_*, and correct ON DELETE
CASCADE behavior for both schema_column and column_synonym. Run by
tests/verify_db_roundtrip.py; never imported directly.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import crud
from db.connection import get_connection


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main() -> None:
    db_path = sys.argv[1]
    snapshot_path = sys.argv[2]
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    conn = get_connection(db_path)

    checks: list[tuple[str, bool]] = []

    def check(label: str, condition: bool) -> None:
        checks.append((label, bool(condition)))
        print(f"{'OK  ' if condition else 'FAIL'} {label}")

    # --- table order, after reorder_tables in phase 1 ---
    tables = crud.get_tables(conn)
    check("table count == 3", len(tables) == 3)
    check("table order_index is dense 0..2", [t.order_index for t in tables] == [0, 1, 2])
    check(
        "table name order matches reorder_tables call",
        [t.name for t in tables] == snapshot["table_order_names"],
    )

    table_a_id = snapshot["table_a_id"]

    # --- column order, after reorder_columns in phase 1 ---
    cols = crud.get_columns(conn, table_a_id)
    check("column count == 3", len(cols) == 3)
    check("column order_index is dense 0..2", [c.order_index for c in cols] == [0, 1, 2])
    check(
        "column id order matches reorder_columns call",
        [c.id for c in cols] == snapshot["table_a_column_order_ids"],
    )
    check(
        "column name order matches reorder_columns call",
        [c.name for c in cols] == snapshot["table_a_column_order_names"],
    )

    # --- byte-identical requirement text (multi-line, tabs, trailing
    # spaces, blank line, em dash/curly quotes, no final newline) ---
    col_2 = crud.get_column(conn, snapshot["col_2_id"])
    expected_req = snapshot["col_2_requirement_text"]
    check("requirement_text length matches exactly", len(col_2.requirement_text) == len(expected_req))
    check(
        "requirement_text is byte-identical (sha256)",
        sha256(col_2.requirement_text) == sha256(expected_req),
    )
    check("requirement_text == expected (direct ==)", col_2.requirement_text == expected_req)
    check(
        "requirement_text preserves trailing spaces + tab + blank line",
        "trailing spaces   \n\n\tTabbed line two" in col_2.requirement_text,
    )
    check(
        "requirement_text has no trailing newline appended (no truncation/padding)",
        not col_2.requirement_text.endswith("\n"),
    )

    # --- synonyms, including a deliberately padded one, unstripped ---
    syn_rows = crud.get_synonyms(conn, snapshot["col_2_id"])
    syn_texts = [s.synonym_text for s in syn_rows]
    check("col_2 synonym count == 4", len(syn_texts) == 4)
    check("col_2 synonyms byte-identical incl. padding", syn_texts == snapshot["col_2_synonyms"])

    # --- cascade delete: delete_column removes its own synonyms ---
    col_3_id = snapshot["col_3_id"]
    before = conn.execute(
        "SELECT COUNT(*) FROM column_synonym WHERE column_id = ?", (col_3_id,)
    ).fetchone()[0]
    check("col_3 has its synonyms before delete", before == len(snapshot["col_3_synonyms"]))
    crud.delete_column(conn, col_3_id)
    after = conn.execute(
        "SELECT COUNT(*) FROM column_synonym WHERE column_id = ?", (col_3_id,)
    ).fetchone()[0]
    check("delete_column cascades to column_synonym", after == 0)
    remaining_cols = crud.get_columns(conn, table_a_id)
    check(
        "remaining columns re-normalized to dense 0..1 after delete",
        [c.order_index for c in remaining_cols] == [0, 1],
    )

    # --- cascade delete: delete_table removes its columns and,
    # transitively, those columns' synonyms ---
    remaining_col_ids = [c.id for c in remaining_cols]
    crud.delete_table(conn, table_a_id)
    orphan_cols = conn.execute(
        "SELECT COUNT(*) FROM schema_column WHERE table_id = ?", (table_a_id,)
    ).fetchone()[0]
    check("delete_table cascades to schema_column", orphan_cols == 0)
    if remaining_col_ids:
        placeholders = ",".join("?" * len(remaining_col_ids))
        orphan_syns = conn.execute(
            f"SELECT COUNT(*) FROM column_synonym WHERE column_id IN ({placeholders})",
            remaining_col_ids,
        ).fetchone()[0]
    else:
        orphan_syns = 0
    check("delete_table cascades transitively to column_synonym", orphan_syns == 0)
    remaining_tables = crud.get_tables(conn)
    check(
        "remaining tables re-normalized to dense 0..1 after delete",
        [t.order_index for t in remaining_tables] == [0, 1],
    )

    conn.close()

    if all(ok for _, ok in checks):
        print(f"ALL CHECKS PASSED ({len(checks)}/{len(checks)})")
        sys.exit(0)
    else:
        failed = [label for label, ok in checks if not ok]
        print(f"FAILED {len(failed)}/{len(checks)}: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
