"""CRUD operations for schema_table / schema_column / column_synonym.

Ordering rules
--------------
- order_index is dense and zero-based within its scope: global for
  schema_table, per table_id for schema_column.
- create_table / create_column always append at the end of their scope.
- delete_table / delete_column re-normalize the remaining siblings' back
  to a dense 0..n-1 range immediately after the delete, so gaps never
  accumulate from repeated add/remove.
- reorder_tables / reorder_columns are the only other way order_index
  changes. Each requires the *complete* set of ids in the target scope,
  exactly once, so a partial or stale list fails loudly (ValueError)
  instead of silently corrupting order for the ids left out.

Text rules
----------
name / requirement_text / synonym_text are stored and returned exactly as
given. No .strip(), no truncation, no line-ending normalization anywhere
in this module. Whitespace and line breaks inside a requirement cell are
the user's data, not formatting noise, and must round-trip unchanged.

Every write function commits before returning (SQLite's per-connection
default isolation is fine for this single-process Streamlit app; there is
no long-lived open transaction spanning function calls).
"""
from __future__ import annotations

import sqlite3
from typing import Optional, Sequence

from db.models import ColumnSynonym, SchemaColumn, SchemaTable

# ============================================================== tables ==


def create_table(conn: sqlite3.Connection, name: str) -> int:
    """Insert a new schema_table, appended at the end of the global order."""
    next_index = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) + 1 FROM schema_table"
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO schema_table (name, order_index) VALUES (?, ?)",
        (name, next_index),
    )
    conn.commit()
    return cur.lastrowid


def get_tables(conn: sqlite3.Connection) -> list[SchemaTable]:
    rows = conn.execute(
        "SELECT id, name, order_index FROM schema_table ORDER BY order_index ASC"
    ).fetchall()
    return [
        SchemaTable(id=r["id"], name=r["name"], order_index=r["order_index"])
        for r in rows
    ]


def get_table(conn: sqlite3.Connection, table_id: int) -> Optional[SchemaTable]:
    row = conn.execute(
        "SELECT id, name, order_index FROM schema_table WHERE id = ?", (table_id,)
    ).fetchone()
    if row is None:
        return None
    return SchemaTable(id=row["id"], name=row["name"], order_index=row["order_index"])


def update_table_name(conn: sqlite3.Connection, table_id: int, name: str) -> None:
    conn.execute(
        "UPDATE schema_table SET name = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (name, table_id),
    )
    conn.commit()


def reorder_tables(conn: sqlite3.Connection, ordered_table_ids: Sequence[int]) -> None:
    """Reassign order_index 0..n-1 to exactly match the given id sequence.

    ordered_table_ids must contain every existing table id exactly once.
    """
    existing_ids = {t.id for t in get_tables(conn)}
    given_ids = list(ordered_table_ids)
    if set(given_ids) != existing_ids or len(given_ids) != len(existing_ids):
        raise ValueError(
            "reorder_tables requires every existing table id exactly once "
            f"(got {given_ids}, existing {sorted(existing_ids)})"
        )
    try:
        conn.execute("BEGIN")
        for i, table_id in enumerate(given_ids):
            conn.execute(
                "UPDATE schema_table SET order_index = ? WHERE id = ?", (i, table_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def delete_table(conn: sqlite3.Connection, table_id: int) -> None:
    """Delete a table. ON DELETE CASCADE removes its columns and, through
    schema_column's own cascade, their synonyms — no manual cleanup needed.
    """
    conn.execute("DELETE FROM schema_table WHERE id = ?", (table_id,))
    _renormalize_table_order(conn)
    conn.commit()


def _renormalize_table_order(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM schema_table ORDER BY order_index ASC"
    ).fetchall()
    for i, row in enumerate(rows):
        conn.execute(
            "UPDATE schema_table SET order_index = ? WHERE id = ?", (i, row["id"])
        )


# ============================================================= columns ==


def create_column(
    conn: sqlite3.Connection, table_id: int, name: str, requirement_text: str
) -> int:
    """Insert a new schema_column, appended at the end of its table's order."""
    next_index = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) + 1 FROM schema_column WHERE table_id = ?",
        (table_id,),
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO schema_column (table_id, name, requirement_text, order_index) "
        "VALUES (?, ?, ?, ?)",
        (table_id, name, requirement_text, next_index),
    )
    conn.commit()
    return cur.lastrowid


def get_columns(conn: sqlite3.Connection, table_id: int) -> list[SchemaColumn]:
    rows = conn.execute(
        "SELECT id, table_id, name, requirement_text, order_index FROM schema_column "
        "WHERE table_id = ? ORDER BY order_index ASC",
        (table_id,),
    ).fetchall()
    return [
        SchemaColumn(
            id=r["id"],
            table_id=r["table_id"],
            name=r["name"],
            requirement_text=r["requirement_text"],
            order_index=r["order_index"],
        )
        for r in rows
    ]


def get_column(conn: sqlite3.Connection, column_id: int) -> Optional[SchemaColumn]:
    row = conn.execute(
        "SELECT id, table_id, name, requirement_text, order_index "
        "FROM schema_column WHERE id = ?",
        (column_id,),
    ).fetchone()
    if row is None:
        return None
    return SchemaColumn(
        id=row["id"],
        table_id=row["table_id"],
        name=row["name"],
        requirement_text=row["requirement_text"],
        order_index=row["order_index"],
    )


def update_column(
    conn: sqlite3.Connection,
    column_id: int,
    *,
    name: Optional[str] = None,
    requirement_text: Optional[str] = None,
) -> None:
    """Partial update. Passing None for a field leaves it unchanged — this
    is NOT the same as passing an empty string, which is a real value and
    will overwrite the existing one.
    """
    current = get_column(conn, column_id)
    if current is None:
        raise ValueError(f"no schema_column with id={column_id}")
    new_name = current.name if name is None else name
    new_req = current.requirement_text if requirement_text is None else requirement_text
    conn.execute(
        "UPDATE schema_column SET name = ?, requirement_text = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (new_name, new_req, column_id),
    )
    conn.commit()


def reorder_columns(
    conn: sqlite3.Connection, table_id: int, ordered_column_ids: Sequence[int]
) -> None:
    """Reassign order_index 0..n-1, within table_id, to match the given
    id sequence exactly. ordered_column_ids must contain every existing
    column id for that table, exactly once.
    """
    existing_ids = {c.id for c in get_columns(conn, table_id)}
    given_ids = list(ordered_column_ids)
    if set(given_ids) != existing_ids or len(given_ids) != len(existing_ids):
        raise ValueError(
            "reorder_columns requires every existing column id for this "
            f"table exactly once (got {given_ids}, existing {sorted(existing_ids)})"
        )
    try:
        conn.execute("BEGIN")
        for i, column_id in enumerate(given_ids):
            conn.execute(
                "UPDATE schema_column SET order_index = ? WHERE id = ?", (i, column_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def delete_column(conn: sqlite3.Connection, column_id: int) -> None:
    """Delete a column. ON DELETE CASCADE removes its synonyms."""
    row = conn.execute(
        "SELECT table_id FROM schema_column WHERE id = ?", (column_id,)
    ).fetchone()
    if row is None:
        return
    table_id = row["table_id"]
    conn.execute("DELETE FROM schema_column WHERE id = ?", (column_id,))
    _renormalize_column_order(conn, table_id)
    conn.commit()


def _renormalize_column_order(conn: sqlite3.Connection, table_id: int) -> None:
    rows = conn.execute(
        "SELECT id FROM schema_column WHERE table_id = ? ORDER BY order_index ASC",
        (table_id,),
    ).fetchall()
    for i, row in enumerate(rows):
        conn.execute(
            "UPDATE schema_column SET order_index = ? WHERE id = ?", (i, row["id"])
        )


# ============================================================ synonyms ==


def add_synonym(conn: sqlite3.Connection, column_id: int, synonym_text: str) -> int:
    cur = conn.execute(
        "INSERT INTO column_synonym (column_id, synonym_text) VALUES (?, ?)",
        (column_id, synonym_text),
    )
    conn.commit()
    return cur.lastrowid


def add_synonyms(
    conn: sqlite3.Connection, column_id: int, synonym_texts: Sequence[str]
) -> list[int]:
    """Insert several synonyms in one commit (used by config-time Groq
    expansion, which produces a batch of alternate phrasings at once).
    """
    ids = []
    for text in synonym_texts:
        cur = conn.execute(
            "INSERT INTO column_synonym (column_id, synonym_text) VALUES (?, ?)",
            (column_id, text),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def get_synonyms(conn: sqlite3.Connection, column_id: int) -> list[ColumnSynonym]:
    rows = conn.execute(
        "SELECT id, column_id, synonym_text FROM column_synonym "
        "WHERE column_id = ? ORDER BY id ASC",
        (column_id,),
    ).fetchall()
    return [
        ColumnSynonym(id=r["id"], column_id=r["column_id"], synonym_text=r["synonym_text"])
        for r in rows
    ]


def set_synonyms(
    conn: sqlite3.Connection, column_id: int, synonym_texts: Sequence[str]
) -> list[int]:
    """Replace the full synonym list for a column. Used by the Config tab's
    editable synonym list (a human overwriting the stored list) and can
    equally be used to (re)apply a Groq-generated batch.
    """
    conn.execute("DELETE FROM column_synonym WHERE column_id = ?", (column_id,))
    return add_synonyms(conn, column_id, synonym_texts)


def delete_synonym(conn: sqlite3.Connection, synonym_id: int) -> None:
    conn.execute("DELETE FROM column_synonym WHERE id = ?", (synonym_id,))
    conn.commit()
