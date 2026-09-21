"""Lightweight typed views over sqlite3.Row for the config schema.

These are read-model dataclasses, not an ORM — crud.py builds them
straight from query rows. Immutable (frozen) because a caller mutating
its local copy should never be mistaken for a DB write.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaTable:
    id: int
    name: str
    order_index: int


@dataclass(frozen=True)
class SchemaColumn:
    id: int
    table_id: int
    name: str
    requirement_text: str
    order_index: int


@dataclass(frozen=True)
class ColumnSynonym:
    id: int
    column_id: int
    synonym_text: str
