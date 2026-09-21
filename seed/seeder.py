"""First-run auto-seeding: populate the DB with SEED_SCHEMA exactly once
ever. See PROJECT_HARNESS.md §4.1.

Superseded design note: checklist 1.2's first version of this module keyed
seeding off a *live* schema_table row count ("empty" = zero rows). That
had a real gap — if a user later deleted every table via the Config tab,
the DB would look empty again and the next app startup would silently
re-seed the defaults right back in, undoing a deliberate action. This
version fixes that with an explicit, persisted has_been_seeded flag in
app_meta (db/meta.py), set once, right after the one and only real seed,
and never unset by anything in this codebase. Emptying the schema by hand
now stays empty.

is_empty() is kept as a small standalone utility (handy in tests / the
Config tab for an "add your first table" empty-state message) but no
longer drives seed_if_empty's decision.
"""
from __future__ import annotations

import sqlite3

from db import crud, meta
from seed.seed_data import SEED_SCHEMA

HAS_BEEN_SEEDED_KEY = "has_been_seeded"


def is_empty(conn: sqlite3.Connection) -> bool:
    """True iff there are no schema_table rows at all right now. Does NOT
    by itself mean "never seeded" — see module docstring.
    """
    count = conn.execute("SELECT COUNT(*) FROM schema_table").fetchone()[0]
    return count == 0


def has_been_seeded(conn: sqlite3.Connection) -> bool:
    """True iff the one-time seed has already run, ever — persisted, so
    this stays True even if the user later deletes every table.
    """
    return meta.get_meta(conn, HAS_BEEN_SEEDED_KEY) == "1"


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    """Populate SEED_SCHEMA into the DB iff it has never been seeded
    before (has_been_seeded flag absent). Name kept as seed_if_empty for
    continuity with how it's wired into app startup; the actual gate is
    the persisted flag, not a live emptiness check — see module docstring.

    Returns True if seeding happened, False otherwise (already seeded at
    some point in the past — nothing is touched in that case, including
    a DB a user has deliberately emptied out since).
    """
    if has_been_seeded(conn):
        return False

    for table_name, items in SEED_SCHEMA:
        table_id = crud.create_table(conn, table_name)
        for column_name, requirement_text in items:
            crud.create_column(conn, table_id, column_name, requirement_text)

    meta.set_meta(conn, HAS_BEEN_SEEDED_KEY, "1")
    return True
