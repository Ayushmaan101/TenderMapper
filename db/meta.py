"""Key-value app metadata (app_meta table).

Used for flags that must persist independently of any other table's row
count — right now, just has_been_seeded (see seed/seeder.py). Deliberately
tiny and generic rather than a one-off "seeded" column somewhere, so any
future single-flag/single-value need (a schema version, a last-run
timestamp) has somewhere to live without a new migration.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
