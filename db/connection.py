"""SQLite connection helper.

Every connection must turn foreign key enforcement on explicitly — SQLite
disables it by default per-connection, and without it ON DELETE CASCADE in
the schema (see schema.py) is silently a no-op instead of actually
cascading.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# The persistent, user-scoped config DB. Lives inside db/ so the code that
# owns it and the file it owns stay together; gitignored (*.db) so a
# developer's local schema edits never get committed.
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "tender_mapper.db"


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection configured the way every part of this app
    needs: foreign keys enforced, rows addressable by column name.

    check_same_thread=False: the Streamlit app caches one connection per
    server process (st.cache_resource in app.py) and reuses it across
    script reruns, which Streamlit may execute on different internal
    threads. This app never touches one connection from two threads at
    once (Streamlit runs one script per session at a time), so relaxing
    sqlite3's same-thread check here is safe and just avoids a spurious
    ProgrammingError.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
