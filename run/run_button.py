"""'Run Mapping' trigger (checklists 5.1 + 3.3).

Guards against the two "nothing to run" states explicitly - empty
upload, empty config - with a clear instructional warning rather than
an unhandled IndexError/AttributeError, then runs the full pipeline
(run/pipeline_runner.py): ingest -> OCR -> search-index (checklist 5.1),
then the per-column BM25-search + Groq-verify resolution loop
(checklist 3.3), populating st.session_state["resolution_results"] for
every configured column. Surfaces per-document failures as visible
warnings while every other document still gets processed (5.1), and
shows live progress through both the page-level OCR phase and the
column-level resolution phase separately, so the user can see which
phase is running and how far through it the app is.

Overwrite semantics: every click replaces resolution_results entirely
with resolve_all_columns()'s fresh output - see run/pipeline_runner.py's
module docstring for why this is a deliberate simplicity choice rather
than trying to preserve prior manual edits across re-runs.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

from db import crud
from ingest.ui import DOCUMENTS_KEY
from run.pipeline_runner import resolve_all_columns, run_ocr_and_build_index
from run.results import CORPUS_INDEX_KEY, HAS_RUN_KEY, OCR_CACHE_KEY, PAGE_TEXTS_KEY, REFERENCE_INDEX_KEY, RESULTS_KEY


def render_run_button(conn: sqlite3.Connection) -> None:
    if st.button("▶️ Run Mapping", key="run_mapping_button", type="primary"):
        _run_mapping(conn)


def _run_mapping(conn: sqlite3.Connection) -> None:
    documents = st.session_state.get(DOCUMENTS_KEY, [])
    if not documents:
        st.warning("Upload at least one document before running the mapping.")
        return

    tables = crud.get_tables(conn)
    if not tables:
        st.warning("No compliance tables configured. Add a schema in the Config tab first.")
        return

    ocr_cache = st.session_state.setdefault(OCR_CACHE_KEY, {})

    # --- phase 1: ingest -> OCR -> search index (checklist 5.1) ---
    ocr_progress = st.progress(0.0, text="Starting...")

    def _ocr_progress(pdf_name: str, done: int, total: int) -> None:
        fraction = done / total if total else 1.0
        ocr_progress.progress(fraction, text=f"Reading documents — {pdf_name}: page {done}/{total}")

    with st.spinner(f"Processing {len(documents)} document(s)..."):
        outcome, corpus_index, page_texts, reference_index = run_ocr_and_build_index(
            documents, ocr_cache=ocr_cache, progress_callback=_ocr_progress
        )
    ocr_progress.empty()

    st.session_state[CORPUS_INDEX_KEY] = corpus_index
    st.session_state[PAGE_TEXTS_KEY] = page_texts
    st.session_state[REFERENCE_INDEX_KEY] = reference_index

    if outcome.document_warnings:
        with st.expander(
            f"⚠️ {len(outcome.document_warnings)} document(s) could not be processed", expanded=True
        ):
            for w in outcome.document_warnings:
                st.warning(w, icon="⚠️")

    if outcome.processed_document_count:
        st.success(
            f"Processed {outcome.processed_document_count} document(s), "
            f"{len(outcome.ocr_results)} page(s) indexed and searchable."
        )
    else:
        st.error("No documents could be processed.")
        return  # nothing to search against - resolving columns would only produce unresolved placeholders

    # --- phase 2: per-column BM25-search + Groq-verify (checklist 3.3) ---
    resolve_progress = st.progress(0.0, text="Starting requirement resolution...")

    def _resolve_progress(done: int, total: int, column_name: str) -> None:
        fraction = done / total if total else 1.0
        resolve_progress.progress(fraction, text=f"Resolving requirements — {done}/{total}: {column_name}")

    with st.spinner("Matching requirements against the uploaded documents..."):
        results = resolve_all_columns(
            conn, corpus_index, page_texts, reference_index, progress_callback=_resolve_progress
        )
    resolve_progress.empty()

    st.session_state[RESULTS_KEY] = results
    st.session_state[HAS_RUN_KEY] = True

    resolved_count = sum(1 for r in results.values() if r.success and r.confidence >= 0.70)
    st.success(f"Resolved {resolved_count} of {len(results)} requirement(s) with high confidence.")
