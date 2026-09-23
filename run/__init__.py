"""Run package.

Owns the Run tab's own concerns beyond upload (which lives in ingest/ui.py):
the resolved-results table (checklist 4.1) and, later, the "Next Company"
session reset (checklist 4.3). Purely session-scoped — never touches
db/crud.py or the SQLite connection for anything except reading the
current schema (read-only, same as the rest of the Run tab per
PROJECT_HARNESS.md §5 step 1).
"""
