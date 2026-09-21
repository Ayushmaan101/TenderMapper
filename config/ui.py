"""Config tab UI.

Renders the full schema editor: add/rename/delete tables; add/edit
(name + requirement text)/reorder/delete columns within each table;
view/add/remove synonyms per column. Every mutation commits straight
through db/crud.py (no local/session-state copy of the schema is ever
kept across a mutation) and is immediately followed by st.rerun(), so the
next render always re-reads the fresh DB state — there is no separate
"refresh" step and no way for the UI to show stale data after an edit.

Text is never stripped before being stored: only the *emptiness check*
that gates whether a submit is accepted uses .strip(); the value actually
written to the DB is exactly what the widget returned.

Synonym expansion (Groq) is triggered from exactly three places, and
nowhere else: creating a new column, saving a column whose requirement
text was actually changed, and the explicit "Generate Synonyms" button.
Opening/closing expanders, switching tabs, or any other rerun never calls
it — see _maybe_expand_synonyms, which is the only place that does.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

from config.synonyms import expand_synonyms, merge_new_synonyms
from db import crud


def render_config_tab(conn: sqlite3.Connection) -> None:
    st.caption(
        "Define tables, columns, requirement text, and stored synonyms. "
        "Persists to SQLite immediately; independent of the Run tab; "
        "never wiped by “Next Company.”"
    )

    _render_add_table_form(conn)

    tables = crud.get_tables(conn)
    if not tables:
        st.info("No tables configured yet. Add one above to get started.")
        return

    for table in tables:
        columns = crud.get_columns(conn, table.id)
        with st.expander(f"**{table.name}**  —  {len(columns)} column(s)", expanded=False):
            _render_table_header(conn, table)
            st.divider()
            st.markdown("**Columns**")
            if not columns:
                st.caption("No columns yet. Add one below.")
            for i, column in enumerate(columns):
                _render_column(conn, table, column, i, len(columns))
            st.divider()
            _render_add_column_form(conn, table)


# -------------------------------------------------------- synonym expansion --


def _maybe_expand_synonyms(conn: sqlite3.Connection, column_id: int, name: str, requirement_text: str) -> None:
    """The one and only call site for expand_synonyms(). Always non-fatal:
    a Groq failure only produces a toast, never an exception, never
    blocks or reverts the column save that already happened before this
    is called. Only ever *adds* synonyms (merge_new_synonyms) - never
    touches an existing entry, manual or generated.
    """
    with st.spinner("Generating synonym suggestions..."):
        result = expand_synonyms(name, requirement_text)

    if not result.success:
        st.toast(f"Synonym suggestion failed: {result.error}", icon="⚠️")
        return

    added = merge_new_synonyms(conn, column_id, result.synonyms)
    if added:
        st.toast(f"Added {len(added)} suggested synonym(s).", icon="✨")
    else:
        st.toast("Groq suggested synonyms, but all were already stored.", icon="ℹ️")


# --------------------------------------------------------------- tables --


def _render_add_table_form(conn: sqlite3.Connection) -> None:
    with st.form("add_table_form", clear_on_submit=True):
        st.markdown("**Add a table**")
        new_name = st.text_input("Table name", key="add_table_name")
        submitted = st.form_submit_button("Add Table")
        if submitted:
            if new_name.strip():
                crud.create_table(conn, new_name)
                st.rerun()
            else:
                st.warning("Table name can't be blank.")


def _render_table_header(conn: sqlite3.Connection, table) -> None:
    name_col, rename_col, delete_col = st.columns([4, 1, 1])
    with name_col:
        new_name = st.text_input(
            "Table name", value=table.name, key=f"tname_{table.id}", label_visibility="collapsed"
        )
    with rename_col:
        if st.button("Rename", key=f"tname_save_{table.id}", use_container_width=True):
            if new_name.strip():
                crud.update_table_name(conn, table.id, new_name)
                st.rerun()
            else:
                st.warning("Table name can't be blank.")
    with delete_col:
        if st.button("Delete table", key=f"tdel_{table.id}", use_container_width=True):
            crud.delete_table(conn, table.id)
            st.rerun()


# -------------------------------------------------------------- columns --


def _render_column(conn: sqlite3.Connection, table, column, index: int, total: int) -> None:
    with st.container(border=True):
        order_col, body_col = st.columns([1, 8])

        with order_col:
            if st.button("▲", key=f"up_{column.id}", disabled=(index == 0), help="Move up"):
                cols = crud.get_columns(conn, table.id)
                ids = [c.id for c in cols]
                ids[index - 1], ids[index] = ids[index], ids[index - 1]
                crud.reorder_columns(conn, table.id, ids)
                st.rerun()
            if st.button(
                "▼", key=f"down_{column.id}", disabled=(index == total - 1), help="Move down"
            ):
                cols = crud.get_columns(conn, table.id)
                ids = [c.id for c in cols]
                ids[index + 1], ids[index] = ids[index], ids[index + 1]
                crud.reorder_columns(conn, table.id, ids)
                st.rerun()

        with body_col:
            new_col_name = st.text_input(
                "Column name", value=column.name, key=f"cname_{column.id}"
            )
            new_req_text = st.text_area(
                "Requirement text",
                value=column.requirement_text,
                key=f"creq_{column.id}",
                height=120,
            )

            save_col, delete_col = st.columns([1, 1])
            with save_col:
                if st.button("Save column", key=f"csave_{column.id}", use_container_width=True):
                    if new_col_name.strip():
                        # Capture before update_column overwrites it - this is
                        # the "explicitly modified" check that gates synonym
                        # expansion. Renaming alone (text unchanged) must NOT
                        # trigger it.
                        requirement_text_changed = new_req_text != column.requirement_text
                        crud.update_column(
                            conn, column.id, name=new_col_name, requirement_text=new_req_text
                        )
                        if requirement_text_changed:
                            _maybe_expand_synonyms(conn, column.id, new_col_name, new_req_text)
                        st.rerun()
                    else:
                        st.warning("Column name can't be blank.")
            with delete_col:
                if st.button("Delete column", key=f"cdel_{column.id}", use_container_width=True):
                    crud.delete_column(conn, column.id)
                    st.rerun()

            _render_synonyms(conn, column)


# ------------------------------------------------------------- synonyms --


def _render_synonyms(conn: sqlite3.Connection, column) -> None:
    synonyms = crud.get_synonyms(conn, column.id)
    with st.expander(f"Synonyms ({len(synonyms)})"):
        if st.button(
            "✨ Generate / Suggest Synonyms", key=f"gensyn_{column.id}", use_container_width=True
        ):
            # Uses the currently *saved* name/requirement_text, not any
            # unsaved edit sitting in the widgets above - regenerating
            # against an uncommitted, possibly-discarded edit would be
            # misleading.
            _maybe_expand_synonyms(conn, column.id, column.name, column.requirement_text)
            st.rerun()

        if not synonyms:
            st.caption("No synonyms stored yet.")
        for syn in synonyms:
            text_col, remove_col = st.columns([5, 1])
            with text_col:
                st.markdown(f"• {syn.synonym_text}")
            with remove_col:
                if st.button("Remove", key=f"sdel_{syn.id}", use_container_width=True):
                    crud.delete_synonym(conn, syn.id)
                    st.rerun()

        with st.form(f"add_syn_form_{column.id}", clear_on_submit=True):
            new_syn = st.text_input(
                "Add synonym", key=f"newsyn_{column.id}", label_visibility="collapsed",
                placeholder="Type an alternate phrasing and press Add",
            )
            add_submitted = st.form_submit_button("Add")
            if add_submitted:
                if new_syn.strip():
                    crud.add_synonym(conn, column.id, new_syn)
                    st.rerun()
                else:
                    st.warning("Synonym can't be blank.")


# ----------------------------------------------------------- add column --


def _render_add_column_form(conn: sqlite3.Connection, table) -> None:
    st.markdown("**Add a column**")
    with st.form(f"add_col_form_{table.id}", clear_on_submit=True):
        new_name = st.text_input("Column name", key=f"newcol_name_{table.id}")
        new_req = st.text_area("Requirement text", key=f"newcol_req_{table.id}")
        submitted = st.form_submit_button("Add Column")
        if submitted:
            if new_name.strip() and new_req.strip():
                new_column_id = crud.create_column(conn, table.id, new_name, new_req)
                _maybe_expand_synonyms(conn, new_column_id, new_name, new_req)
                st.rerun()
            else:
                st.warning("Both column name and requirement text are required.")
