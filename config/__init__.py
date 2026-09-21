"""Config package.

Owns everything on the Config tab: schema CRUD (tables/columns/requirement
text/synonyms) on top of the SQLite models in `db/`, and the config-time
Groq synonym-expansion call (one-time, per column, not per search run).
See PROJECT_HARNESS.md §4.
"""
