"""Results table UI (checklist 4.1).

Renders one editable st.data_editor per configured table, with a row per
schema column (not per the original tender document's own visual
layout) - see "Row orientation" below for why. Reads the resolved-value
store from st.session_state, where checklist 3.3's per-column resolution
loop will write real Groq-verified results; until that's wired in, an
unresolved column just shows blank/zero placeholder values, which this
module renders identically to a real result (there is nothing 4.1-
specific about "not yet resolved" - it's just a VerificationResult
with empty fields).

Row orientation
-----------------
The config schema is uniform regardless of how a table "looks" in the
original tender document: schema_table -> N schema_column rows, each
carrying one requirement to resolve (checklist 1.1/1.2). Table 1's 10
items read as ten columns across a single row in the original tender
document; Table 2's 13 items read as thirteen rows in a two-column
table. Rendering the RESULTS UI to mimic either original layout would
require hardcoding per-table structure - exactly what this checklist
explicitly forbids ("never hardcode for the 10-column/13-row seeded
counts... must gracefully render any arbitrary number of tables,
columns, or rows").

The only representation that stays correct for an arbitrary, freely
reconfigured schema is: one results-grid ROW per schema_column,
regardless of what that column represented in the source document. This
is a deliberate reading of "arbitrary number of columns" in the
checklist - a fixed set of resolved-field columns doesn't change count
with configuration, but the number of ROWS does, which is exactly what
"gracefully render any arbitrary number of ... columns" requires an
open-ended answer for.

Persistence
------------
Edits are read back out of st.data_editor's return value and written
into st.session_state[RESULTS_KEY] explicitly on every render - not
left to rely solely on Streamlit's own internal per-widget cache (keyed
by the data_editor's `key=`), so the resolved-results structure stays a
plain, app-owned dict[int, VerificationResult] that checklist 3.3's
pipeline and checklist 4.4's Excel export can both read directly.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

import pandas as pd
import streamlit as st

from db import crud
from verify.groq_verifier import VerificationResult

RESULTS_KEY = "resolution_results"  # st.session_state[RESULTS_KEY]: dict[int, VerificationResult], keyed by schema_column.id

_BLANK_RESULT = VerificationResult(
    pdf_name="", page_number_or_range="", confidence=0.0, match_snippet="",
    reasoning="", success=False, error=None,
)


def render_results_section(conn: sqlite3.Connection) -> None:
    tables = crud.get_tables(conn)
    if not tables:
        st.info("No tables configured yet. Configure a schema in the Config tab first.")
        return

    if RESULTS_KEY not in st.session_state:
        st.session_state[RESULTS_KEY] = {}
    results_store: dict[int, VerificationResult] = st.session_state[RESULTS_KEY]

    for table in tables:
        columns = crud.get_columns(conn, table.id)
        st.subheader(table.name)

        if not columns:
            st.caption("No columns configured for this table yet.")
            continue

        rows = []
        for col in columns:
            result = results_store.get(col.id, _BLANK_RESULT)
            rows.append({
                "_column_id": col.id,
                "Column": col.name,
                "Requirement": col.requirement_text,
                "PDF Name": result.pdf_name,
                "Page Number / Range": result.page_number_or_range,
                "Confidence": result.confidence,
                "Match Snippet": result.match_snippet,
            })

        df = pd.DataFrame(rows).set_index("_column_id")

        edited_df = st.data_editor(
            df,
            key=f"results_editor_{table.id}",
            hide_index=True,
            num_rows="fixed",  # rows correspond 1:1 to configured columns; add/remove happens via the Config tab, not here
            width="stretch",
            disabled=["Column", "Requirement"],
            column_config={
                "Column": st.column_config.TextColumn("Column", width="small"),
                "Requirement": st.column_config.TextColumn("Requirement", width="large"),
                "PDF Name": st.column_config.TextColumn("PDF Name", width="medium"),
                "Page Number / Range": st.column_config.TextColumn("Page Number / Range", width="small"),
                "Confidence": st.column_config.NumberColumn(
                    "Confidence", min_value=0.0, max_value=1.0, step=0.01, format="%.2f", width="small"
                ),
                "Match Snippet": st.column_config.TextColumn("Match Snippet", width="large"),
            },
        )

        for col in columns:
            edited_row = edited_df.loc[col.id]
            existing = results_store.get(col.id, _BLANK_RESULT)
            results_store[col.id] = replace(
                existing,
                pdf_name=str(edited_row["PDF Name"] or ""),
                page_number_or_range=str(edited_row["Page Number / Range"] or ""),
                confidence=float(edited_row["Confidence"] or 0.0),
                match_snippet=str(edited_row["Match Snippet"] or ""),
            )

    st.session_state[RESULTS_KEY] = results_store
