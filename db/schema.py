"""DDL for the config schema: schema_table -> schema_column -> column_synonym.

Hierarchy and cascade behavior (requires PRAGMA foreign_keys = ON on the
connection — see connection.py):

    schema_table
        |-- ON DELETE CASCADE --> schema_column
                                        |-- ON DELETE CASCADE --> column_synonym

Deleting a table cleanly removes its columns and, transitively, their
synonyms. Deleting a column removes its synonyms. Neither requires the
application to manually clean up children.

name / requirement_text / synonym_text are TEXT columns, stored and
returned exactly as given by the caller. This module makes no attempt to
strip, truncate, or normalize them — that would corrupt requirement text
whose line breaks and whitespace are the user's actual data (see
PROJECT_HARNESS.md §4.1: "preserve line breaks/formatting within each cell
as given").
"""
from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS schema_table (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS schema_column (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id          INTEGER NOT NULL,
    name              TEXT NOT NULL,
    requirement_text  TEXT NOT NULL,
    order_index       INTEGER NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (table_id) REFERENCES schema_table (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS column_synonym (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    column_id     INTEGER NOT NULL,
    synonym_text  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (column_id) REFERENCES schema_column (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_schema_column_table_id ON schema_column (table_id);
CREATE INDEX IF NOT EXISTS idx_column_synonym_column_id ON column_synonym (column_id);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables/indexes if they don't already exist. Idempotent —
    safe to call on every app startup, including against an existing DB
    with data already in it.
    """
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(DDL)
    conn.commit()
