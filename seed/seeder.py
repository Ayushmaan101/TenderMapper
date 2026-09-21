"""First-run auto-seeding: populate the DB with SEED_SCHEMA, but only when
it is currently empty. See PROJECT_HARNESS.md §4.1.

Definition of "empty": zero rows in schema_table. This is checked fresh
on every call — there is no separate "has been seeded before" flag. That
means seed_if_empty is naturally idempotent (a populated DB is never
empty, so a second call is a no-op) without needing extra state, and it
also means that if a user were to delete every table via the Config tab,
the DB would look empty again and a subsequent call would re-seed. That
edge case is out of scope for checklist 1.2 (which only requires "empty"
vs. "already seeded" behavior) — flagged here in case stricter
"only ever once, even after the user empties it" semantics are wanted
later, which would need a small persisted flag instead of a live count.
"""
from __future__ import annotations

import sqlite3

from db import crud
from seed.seed_data import SEED_SCHEMA


def is_empty(conn: sqlite3.Connection) -> bool:
    """True iff there are no schema_table rows at all."""
    count = conn.execute("SELECT COUNT(*) FROM schema_table").fetchone()[0]
    return count == 0


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    """Populate SEED_SCHEMA into the DB if and only if it is empty right now.

    Returns True if seeding happened, False if the DB already had data
    (nothing is touched in that case — existing tables/columns/synonyms,
    including any user edits, are left exactly as they were).
    """
    if not is_empty(conn):
        return False

    for table_name, items in SEED_SCHEMA:
        table_id = crud.create_table(conn, table_name)
        for column_name, requirement_text in items:
            crud.create_column(conn, table_id, column_name, requirement_text)

    return True
