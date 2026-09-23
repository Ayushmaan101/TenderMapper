"""Session reset - "Next Company" (checklist 4.3).

The core company-in -> resolve -> review -> "Next Company" loop
(PROJECT_HARNESS.md §5 step 6). Clicking the button flushes every
session-scoped piece of state this app has accumulated for the current
company - company name, uploaded documents, resolved results, and the
whole search index (BM25 corpus, page texts, reference index, OCR
cache) - while leaving the persisted SQLite config completely untouched.
PROJECT_HARNESS.md §4's persistence table: schema config is user-scoped
and is never wiped by "Next Company"; everything this module touches is
session-scoped and always is. Nothing here imports db.crud or opens a
SQLite connection - it can't accidentally touch the config DB.

Uses Streamlit's on_click callback rather than an inline
`if st.button(...): ...`, specifically because it needs to reset a live
widget's displayed value via its own session_state key (company_name).
Streamlit only allows mutating a widget-backing session_state key from
within a callback that runs BEFORE the widget re-renders on the next
script pass - not from the main script body after that widget has
already been instantiated earlier in the same run (which app.py's
company-name text_input always has been, since it renders above the
results section this button sits beneath).
"""
from __future__ import annotations

import streamlit as st

from ingest.ui import reset_upload_state
from run.results import reset_run_state

COMPANY_NAME_KEY = "company_name"


def render_next_company_button() -> None:
    st.divider()
    st.button(
        "➡️ Next Company",
        key="next_company_button",
        type="primary",
        help=(
            "Clears this company's name, uploaded documents, and resolved results, "
            "ready for the next company. The configured schema (tables, columns, "
            "requirement text, synonyms) is never touched."
        ),
        on_click=_reset_for_next_company,
    )


def _reset_for_next_company() -> None:
    st.session_state[COMPANY_NAME_KEY] = ""
    reset_upload_state()
    reset_run_state()
