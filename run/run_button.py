"""'Run Mapping' trigger (checklist 5.1).

Guards against the two "nothing to run" states explicitly - empty
upload, empty config - with a clear instructional warning rather than
an unhandled IndexError/AttributeError, then runs the ingest -> OCR ->
search-index bridge (run/pipeline_runner.py), surfacing any
per-document failures as visible warnings while every other document
still gets processed. Never touches db/crud.py for anything but a
read-only table count check.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

from db import crud
from ingest.ui import DOCUMENTS_KEY
from run.pipeline_runner import run_ocr_and_build_index
from run.results import CORPUS_INDEX_KEY, OCR_CACHE_KEY, PAGE_TEXTS_KEY, REFERENCE_INDEX_KEY


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

    progress_bar = st.progress(0.0, text="Starting...")

    def _progress(pdf_name: str, done: int, total: int) -> None:
        fraction = done / total if total else 1.0
        progress_bar.progress(fraction, text=f"{pdf_name}: page {done}/{total}")

    with st.spinner(f"Processing {len(documents)} document(s)..."):
        outcome, corpus_index, page_texts, reference_index = run_ocr_and_build_index(
            documents, ocr_cache=ocr_cache, progress_callback=_progress
        )
    progress_bar.empty()

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
