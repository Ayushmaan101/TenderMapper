"""'Run Mapping' trigger (checklists 5.1 + 3.3), with granular
per-document progress and real-time streaming results (Groq rate-limit
fix / live feedback loop refinement).

Guards against the two "nothing to run" states explicitly - empty
upload, empty config - with a clear instructional warning rather than
an unhandled IndexError/AttributeError, then runs the full pipeline
(run/pipeline_runner.py): ingest -> OCR -> search-index (checklist 5.1),
then the per-column BM25-search + Groq-verify resolution loop
(checklist 3.3, now one batched Groq call per column), populating
st.session_state["resolution_results"] for every configured column.
Surfaces per-document failures as visible warnings while every other
document still gets processed (5.1).

Phase 1 progress is now two-level: a document-counter line ("Processing
document X of Y (filename.pdf) — Extracting text...") via
document_progress_callback, plus the existing per-page progress bar
within whichever document is currently running - so a reviewer watching
a large upload can tell both which document is active and how far
through its pages the app is.

Phase 2 now streams: as run/pipeline_runner.py::resolve_all_columns()
completes each column's single batched Groq call (in completion order,
since columns run concurrently), this module immediately re-renders a
read-only preview table (run/results.py::build_live_preview_dataframe)
into an st.empty() placeholder, so rows visibly fill in live rather than
the whole grid only appearing once every column is done. That live
placeholder is emptied once the run finishes, and the script continues
on to app.py's normal render_results_section() call - the final,
editable st.data_editor - so the "swap to the interactive grid" is just
the natural next step of the same script run, not a separate rerun.

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
from run.results import (
    CORPUS_INDEX_KEY,
    HAS_RUN_KEY,
    OCR_CACHE_KEY,
    PAGE_TEXTS_KEY,
    REFERENCE_INDEX_KEY,
    RESULTS_KEY,
    build_live_preview_dataframe,
)
from verify.groq_verifier import VerificationResult


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
    doc_status = st.empty()
    ocr_progress = st.progress(0.0, text="Starting...")

    def _document_progress(doc_index: int, doc_total: int, pdf_name: str) -> None:
        doc_status.markdown(f"**Processing document {doc_index} of {doc_total} ({pdf_name}) — Extracting text...**")

    def _ocr_progress(pdf_name: str, done: int, total: int) -> None:
        fraction = done / total if total else 1.0
        ocr_progress.progress(fraction, text=f"Reading documents — {pdf_name}: page {done}/{total}")

    with st.spinner(f"Processing {len(documents)} document(s)..."):
        outcome, corpus_index, page_texts, reference_index = run_ocr_and_build_index(
            documents,
            ocr_cache=ocr_cache,
            progress_callback=_ocr_progress,
            document_progress_callback=_document_progress,
        )
    doc_status.empty()
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

    # --- phase 2: per-column BM25-search + batched Groq-verify (checklist 3.3) ---
    resolve_progress = st.progress(0.0, text="Starting requirement resolution...")
    live_table = st.empty()
    live_results: dict[int, VerificationResult] = {}

    def _on_column_resolved(done: int, total: int, column_name: str, column_id: int, result: VerificationResult) -> None:
        live_results[column_id] = result
        fraction = done / total if total else 1.0
        resolve_progress.progress(fraction, text=f"Resolving requirements — {done}/{total}: {column_name}")
        live_table.dataframe(
            build_live_preview_dataframe(conn, live_results), width="stretch", hide_index=True,
        )

    with st.spinner("Matching requirements against the uploaded documents..."):
        results = resolve_all_columns(
            conn, corpus_index, page_texts, reference_index, progress_callback=_on_column_resolved
        )
    resolve_progress.empty()
    live_table.empty()

    st.session_state[RESULTS_KEY] = results
    st.session_state[HAS_RUN_KEY] = True

    resolved_count = sum(1 for r in results.values() if r.success and r.confidence >= 0.70)
    st.success(f"Resolved {resolved_count} of {len(results)} requirement(s) with high confidence.")
