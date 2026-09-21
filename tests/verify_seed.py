"""Checklist 1.2 verification.

Checks, against a fresh temp DB:
  1. Empty DB -> seed_if_empty populates both tables and all 23 items.
  2. Already-seeded DB -> a second call does nothing (idempotent): no
     duplicate tables/columns are created.
  3. Every stored requirement_text matches SEED_SCHEMA character-for-
     character (direct == and sha256, on every one of the 23 items, not
     just a couple of samples).
  4. A user edit made after seeding survives a further seed_if_empty call
     (proves idempotency isn't achieved by blindly re-applying the seed).

Run: python tests/verify_seed.py
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import crud
from db.connection import get_connection
from db.schema import init_db
from seed.seed_data import SEED_SCHEMA
from seed.seeder import has_been_seeded, is_empty, seed_if_empty


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main() -> None:
    checks: list[tuple[str, bool]] = []

    def check(label: str, condition: bool) -> None:
        checks.append((label, bool(condition)))
        print(f"{'OK  ' if condition else 'FAIL'} {label}")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "seed_test.db")
        conn = get_connection(db_path)
        init_db(conn)

        # --- 1. empty DB -> seeding populates everything ---
        check("DB starts empty (is_empty)", is_empty(conn))
        seeded = seed_if_empty(conn)
        check("seed_if_empty returns True on an empty DB", seeded is True)

        tables = crud.get_tables(conn)
        check("exactly 2 tables after seeding", len(tables) == 2)
        check(
            "table names match SEED_SCHEMA order",
            [t.name for t in tables] == [name for name, _ in SEED_SCHEMA],
        )

        total_columns = 0
        expected_by_table_id: dict[int, list[tuple[str, str]]] = {}
        for table, (expected_name, expected_items) in zip(tables, SEED_SCHEMA):
            cols = crud.get_columns(conn, table.id)
            total_columns += len(cols)
            check(
                f"'{table.name}' has {len(expected_items)} columns",
                len(cols) == len(expected_items),
            )
            expected_by_table_id[table.id] = expected_items

            # --- 3. every requirement_text byte-identical to SEED_SCHEMA,
            # checked for all items, in stored order ---
            for col, (expected_col_name, expected_req) in zip(cols, expected_items):
                check(
                    f"'{table.name}'/'{col.name}' name matches seed data",
                    col.name == expected_col_name,
                )
                exact = col.requirement_text == expected_req
                hash_match = sha256(col.requirement_text) == sha256(expected_req)
                check(
                    f"'{table.name}'/'{col.name}' requirement_text is "
                    f"character-for-character identical to SEED_SCHEMA",
                    exact and hash_match,
                )

        check("23 total columns across both tables (10 + 13)", total_columns == 23)

        # --- 2. idempotency: seeding again on a non-empty DB is a no-op ---
        check("DB no longer empty after seeding", not is_empty(conn))
        seeded_again = seed_if_empty(conn)
        check("seed_if_empty returns False on an already-seeded DB", seeded_again is False)

        tables_after = crud.get_tables(conn)
        check(
            "table count unchanged after redundant seed_if_empty call (no duplicates)",
            len(tables_after) == 2,
        )
        total_columns_after = sum(
            len(crud.get_columns(conn, t.id)) for t in tables_after
        )
        check(
            "column count unchanged after redundant seed_if_empty call (no duplicates)",
            total_columns_after == 23,
        )

        # --- 4. a user edit survives a further (no-op) seed_if_empty call ---
        first_col = crud.get_columns(conn, tables_after[0].id)[0]
        edited_text = "USER-EDITED: this text must survive re-seeding attempts."
        crud.update_column(conn, first_col.id, requirement_text=edited_text)
        seed_if_empty(conn)  # must be a no-op; already seeded
        reread = crud.get_column(conn, first_col.id)
        check(
            "user edit to a seeded column survives a subsequent seed_if_empty call",
            reread.requirement_text == edited_text,
        )

        # --- 5. user deliberately deletes every table -> a later "restart"
        # (another seed_if_empty call, as app startup would make) must NOT
        # silently re-seed the defaults back in. This is the scenario the
        # live-emptiness-check design (checklist 1.2 v1) got wrong, and the
        # has_been_seeded flag (checklist 1.3) exists specifically to fix. ---
        for t in crud.get_tables(conn):
            crud.delete_table(conn, t.id)
        check("DB is empty again after user deletes every table", is_empty(conn))
        check("has_been_seeded flag still true after user empties the DB", has_been_seeded(conn))
        reseeded = seed_if_empty(conn)
        check(
            "seed_if_empty does NOT re-seed a DB the user deliberately emptied",
            reseeded is False,
        )
        check(
            "DB is still empty after the no-op seed_if_empty call (defaults not silently restored)",
            is_empty(conn),
        )

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
