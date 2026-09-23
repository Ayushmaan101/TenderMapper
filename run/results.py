"""Results table UI (checklist 4.1) + confidence flagging and manual
re-search (checklist 4.2).

Renders one editable st.data_editor per configured table, with a row per
schema column (not per the original tender document's own visual
layout) - see "Row orientation" below for why. Reads the resolved-value
store from st.session_state, where checklist 3.3's per-column resolution
loop will write real Groq-verified results; until that's wired in, an
unresolved column just shows blank/zero placeholder values, which this
module renders identically to a real result (there is nothing 4.1-
specific about "not yet resolved" - it's just a VerificationResult
with empty fields, which flags exactly like a real low-confidence one).

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
regardless of what that column represented in the source document.

Persistence
------------
Edits are read back out of st.data_editor's return value and written
into st.session_state[RESULTS_KEY] explicitly on every render - not
left to rely solely on Streamlit's own internal per-widget cache (keyed
by the data_editor's `key=`), so the resolved-results structure stays a
plain, app-owned dict[int, VerificationResult] that checklist 3.3's
pipeline and checklist 4.4's Excel export can both read directly.

Confidence flagging (checklist 4.2)
-------------------------------------
A row is flagged for human review when verification never succeeded
(success=False - covers both "never resolved yet" and "Groq call
failed") OR its confidence is below CONFIDENCE_THRESHOLD. Never silently
blank, never silently wrong - PROJECT_HARNESS.md §2's stated safety net.

Manual re-search (checklist 4.2)
------------------------------------
Reads the session's own already-built search index rather than the
config DB - the session-state keys below are the CONTRACT checklist
3.3's resolution loop is expected to populate once it exists:

  CORPUS_INDEX_KEY     -> a search.bm25_index.CorpusIndex
  PAGE_TEXTS_KEY        -> dict[(pdf_name, page_number), str]
  REFERENCE_INDEX_KEY   -> an ocr.references.ReferenceIndex (optional)
  OCR_CACHE_KEY          -> dict[(pdf_name, page_number), OcrPageResult],
                            the cache checklist 2.3's
                            ocr.pipeline.resolve_pdf_text(cache=...)
                            parameter expects - owned here since it's
                            part of the same per-company search-index
                            lifecycle as the three keys above

Until 3.3 populates them, a manual re-search click surfaces a clear "no
documents processed yet" message instead of crashing - the same
graceful-placeholder posture as the rest of this module.

Session reset (checklist 4.3)
---------------------------------
reset_run_state() clears every key in the contract above, plus
RESULTS_KEY - called by run/session_reset.py's "Next Company" handler.
Resets to `None`/`{}` rather than deleting the keys outright, so any
code that reads them via st.session_state[...] (not .get(...)) keeps
working immediately after a reset without a KeyError.

The reviewer's custom terms drive BM25 RETRIEVAL only (query =
tokenize(custom_terms) alone, no stored synonyms mixed in - the
reviewer is overriding the search, per PROJECT_HARNESS.md §5: "type the
exact term they see in the document and re-run BM25"). Groq
VERIFICATION still judges the result against the column's real,
unmodified requirement_text - custom terms help find the page, they
don't redefine what "satisfies the requirement" means.

Strict isolation: _run_manual_research takes no db.crud import, no
sqlite3.Connection, and never calls anything that writes to the config
DB. It only reads column.id/column.name/column.requirement_text (already
fetched, read-only, by the caller) and writes into the session-scoped
results_store dict. Verified directly via a DB fingerprint before/after.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

import pandas as pd
import streamlit as st

from db import crud
from db.models import SchemaColumn
from ocr.references import ReferenceIndex
from search.bm25_index import DEFAULT_POOL_SIZE, CorpusIndex, search as bm25_search
from verify.groq_verifier import (  # noqa: F401 - CONFIDENCE_THRESHOLD/is_flagged re-exported for existing importers
    CONFIDENCE_THRESHOLD,
    VerificationResult,
    is_flagged,
    resolve_column,
)

RESULTS_KEY = "resolution_results"  # st.session_state[RESULTS_KEY]: dict[int, VerificationResult], keyed by schema_column.id
CORPUS_INDEX_KEY = "corpus_index"  # st.session_state[CORPUS_INDEX_KEY]: search.bm25_index.CorpusIndex | None
PAGE_TEXTS_KEY = "page_texts"  # st.session_state[PAGE_TEXTS_KEY]: dict[(pdf_name, page_number), str]
REFERENCE_INDEX_KEY = "reference_index"  # st.session_state[REFERENCE_INDEX_KEY]: ocr.references.ReferenceIndex | None
OCR_CACHE_KEY = "ocr_cache"  # st.session_state[OCR_CACHE_KEY]: dict[(pdf_name, page_number), OcrPageResult]

_BLANK_RESULT = VerificationResult(
    pdf_name="", page_number_or_range="", confidence=0.0, match_snippet="",
    reasoning="", success=False, error=None,
)


def reset_run_state() -> None:
    """Clears every session-state key this module's search-index
    contract owns: resolved results, the BM25 corpus index, extracted
    page texts, the reference index, and the OCR cache. Called by
    run/session_reset.py's "Next Company" handler. Touches nothing in
    db/crud.py or the SQLite connection.
    """
    st.session_state[RESULTS_KEY] = {}
    st.session_state[CORPUS_INDEX_KEY] = None
    st.session_state[PAGE_TEXTS_KEY] = {}
    st.session_state[REFERENCE_INDEX_KEY] = None
    st.session_state[OCR_CACHE_KEY] = {}


def render_results_section(conn: sqlite3.Connection) -> None:
    tables = crud.get_tables(conn)
    if not tables:
        st.info("No tables configured yet. Configure a schema in the Config tab first.")
        return

    if RESULTS_KEY not in st.session_state:
        st.session_state[RESULTS_KEY] = {}
    results_store: dict[int, VerificationResult] = st.session_state[RESULTS_KEY]

    all_columns_by_table = {table.id: crud.get_columns(conn, table.id) for table in tables}
    all_columns = [c for cols in all_columns_by_table.values() for c in cols]
    _render_overall_summary(all_columns, results_store)

    for table in tables:
        columns = all_columns_by_table[table.id]
        st.subheader(table.name)

        if not columns:
            st.caption("No columns configured for this table yet.")
            continue

        _render_table_summary(columns, results_store)

        rows = []
        for col in columns:
            result = results_store.get(col.id, _BLANK_RESULT)
            rows.append({
                "_column_id": col.id,
                "Status": "⚠️ Flagged" if is_flagged(result) else "✅ Resolved",
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
            disabled=["Status", "Column", "Requirement"],
            column_config={
                "Status": st.column_config.TextColumn("Status", width="small"),
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
            new_pdf_name = str(edited_row["PDF Name"] or "")
            new_page = str(edited_row["Page Number / Range"] or "")
            new_confidence = float(edited_row["Confidence"] or 0.0)
            new_snippet = str(edited_row["Match Snippet"] or "")

            # This read-back-and-write-back runs on EVERY rerun (checklist
            # 4.1's persistence design), not just when this specific row
            # was touched - so `success` only flips to True when a value
            # genuinely changed from what was already stored, not merely
            # because the row round-tripped through an unrelated rerun.
            # Without this, a row a reviewer corrected (e.g. confidence
            # 0.0 -> 0.95) would keep success=False from its original
            # blank placeholder and stay stuck showing "Flagged" despite
            # the now-high confidence - caught by checklist 4.4's export
            # test, which is exactly the kind of inconsistency
            # is_flagged() exists to prevent.
            changed = (
                new_pdf_name != existing.pdf_name
                or new_page != existing.page_number_or_range
                or new_confidence != existing.confidence
                or new_snippet != existing.match_snippet
            )

            results_store[col.id] = replace(
                existing,
                pdf_name=new_pdf_name,
                page_number_or_range=new_page,
                confidence=new_confidence,
                match_snippet=new_snippet,
                success=True if changed else existing.success,
            )

        _render_manual_research(table, columns, results_store)

    st.session_state[RESULTS_KEY] = results_store


# --------------------------------------------------------------- summaries --


def _render_overall_summary(all_columns: list[SchemaColumn], results_store: dict[int, VerificationResult]) -> None:
    if not all_columns:
        return
    total = len(all_columns)
    flagged = sum(1 for c in all_columns if is_flagged(results_store.get(c.id, _BLANK_RESULT)))
    col1, col2, col3 = st.columns(3)
    col1.metric("Total requirements (all tables)", total)
    col2.metric("Resolved", total - flagged)
    col3.metric("Flagged for review", flagged)
    st.divider()


def _render_table_summary(columns: list[SchemaColumn], results_store: dict[int, VerificationResult]) -> None:
    total = len(columns)
    flagged = sum(1 for c in columns if is_flagged(results_store.get(c.id, _BLANK_RESULT)))
    if flagged:
        st.warning(f"{flagged} of {total} row(s) in this table need review (confidence < {CONFIDENCE_THRESHOLD:.2f} or unresolved).")
    else:
        st.success(f"All {total} row(s) in this table meet the confidence threshold.")


# ---------------------------------------------------------- manual re-search --


def _render_manual_research(table, columns: list[SchemaColumn], results_store: dict[int, VerificationResult]) -> None:
    flagged_columns = [c for c in columns if is_flagged(results_store.get(c.id, _BLANK_RESULT))]
    if not flagged_columns:
        return

    st.markdown(f"**Search again with custom terms** ({len(flagged_columns)} flagged row(s))")
    for col in flagged_columns:
        with st.expander(f"\U0001f50d {col.name}"):
            custom_terms = st.text_input(
                "Custom search terms",
                key=f"custom_terms_{col.id}",
                placeholder="Type the exact term you see in the document, e.g. a certificate number or heading",
            )
            if st.button("Search again", key=f"research_{col.id}"):
                if not custom_terms.strip():
                    st.warning("Enter some search terms first.")
                else:
                    _run_manual_research(col, custom_terms, results_store)
                    st.rerun()


def _run_manual_research(column: SchemaColumn, custom_terms: str, results_store: dict[int, VerificationResult]) -> None:
    """Runs BM25 (over the session's already-built index) + Groq
    verification for ONE column, using the reviewer's own custom terms
    as the search query. Writes only into results_store (a plain dict
    the caller owns) - never touches db/crud.py, never opens or writes
    to the SQLite connection. See module docstring for the full isolation
    contract.
    """
    corpus_index: CorpusIndex | None = st.session_state.get(CORPUS_INDEX_KEY)
    if corpus_index is None or len(corpus_index) == 0:
        st.toast("No documents have been processed for this company yet.", icon="⚠️")
        return

    page_texts: dict[tuple[str, int], str] = st.session_state.get(PAGE_TEXTS_KEY, {})
    reference_index: ReferenceIndex | None = st.session_state.get(REFERENCE_INDEX_KEY)

    with st.spinner(f"Searching for '{custom_terms}'..."):
        candidates = bm25_search(
            corpus_index, custom_terms, synonyms=[],
            pool_size=DEFAULT_POOL_SIZE, reference_index=reference_index,
        )
        if not candidates:
            st.toast("No candidate pages found for those terms.", icon="⚠️")
            return

        best = resolve_column(column.name, column.requirement_text, candidates, page_texts)

    if best is None:
        st.toast("Re-search found no verifiable match.", icon="⚠️")
        return

    results_store[column.id] = best
    icon = "✨" if best.confidence >= CONFIDENCE_THRESHOLD else "ℹ️"
    st.toast(f"Updated '{column.name}': confidence {best.confidence:.2f}.", icon=icon)
