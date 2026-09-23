"""Excel export UI wiring (checklist 4.4).

Thin Streamlit sliver over export/excel_export.py's pure workbook-
building logic, matching the established split in this codebase (the
domain logic stays testable without AppTest; this file is the one place
that actually calls st.download_button). Placed in the Run tab beneath
the results grid and the "Next Company" control, per the checklist -
with a caption calling out that "Next Company" wipes the very state
this export reads, so a reviewer exports before moving on, not after.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

from export.excel_export import export_to_bytes, sanitize_filename
from run.results import RESULTS_KEY
from run.session_reset import COMPANY_NAME_KEY


def render_export_section(conn: sqlite3.Connection) -> None:
    st.divider()
    st.subheader("Export")
    st.caption(
        "Exports the current review state (including any manual corrections) to "
        "Excel. Export before clicking “Next Company” — that clears this data."
    )

    company_name = st.session_state.get(COMPANY_NAME_KEY, "")
    results_store = st.session_state.get(RESULTS_KEY, {})

    data = export_to_bytes(conn, results_store)
    filename = sanitize_filename(company_name)

    st.download_button(
        "\U0001f4e5 Download Excel export",
        data=data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="export_download_button",
    )
