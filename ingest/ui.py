"""Run-tab upload widget.

Wires ingest/pipeline.py's normalize_uploads() to st.file_uploader and
st.session_state. Deliberately touches nothing in db/ - the ingested
document list is pure session state, wiped by "Next Company" (checklist
4.3) and never persisted anywhere. See PROJECT_HARNESS.md §4 persistence
table: uploaded PDFs/zip are session-scoped, config is not, and the two
must never cross.

Re-normalizes only when the actual upload selection changes (tracked via
a lightweight signature of names+sizes in session_state), not on every
unrelated script rerun elsewhere in the app - unzipping a large archive
on every keystroke in the Config tab would be wasteful.
"""
from __future__ import annotations

import streamlit as st

from ingest.pipeline import normalize_uploads

DOCUMENTS_KEY = "ingested_documents"
WARNINGS_KEY = "ingest_warnings"
_SIGNATURE_KEY = "_ingest_upload_signature"


def _signature(uploaded_files) -> tuple:
    if not uploaded_files:
        return ()
    return tuple((f.name, f.size) for f in uploaded_files)


def render_upload_section() -> None:
    uploaded_files = st.file_uploader(
        "Upload this company's documents",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        key="company_file_uploader",
        help=(
            "Accepts individual PDF files, one or more .zip archives, or a "
            "folder's worth of files selected/dropped at once. Zips are "
            "unpacked automatically (including zips nested inside zips)."
        ),
    )

    signature = _signature(uploaded_files)
    if st.session_state.get(_SIGNATURE_KEY) != signature:
        result = normalize_uploads(uploaded_files)
        st.session_state[DOCUMENTS_KEY] = result.documents
        st.session_state[WARNINGS_KEY] = result.warnings
        st.session_state[_SIGNATURE_KEY] = signature

    documents = st.session_state.get(DOCUMENTS_KEY, [])
    warnings = st.session_state.get(WARNINGS_KEY, [])

    if warnings:
        with st.expander(f"⚠️ {len(warnings)} file(s) skipped or renamed", expanded=False):
            for w in warnings:
                st.warning(w, icon="⚠️")

    if documents:
        st.success(f"{len(documents)} PDF document(s) ready.")
        st.dataframe(
            [
                {
                    "PDF name": d.name,
                    "Source": d.source_path,
                    "Size (KB)": round(len(d.data) / 1024, 1),
                }
                for d in documents
            ],
            width="stretch",
            hide_index=True,
        )
    elif uploaded_files:
        st.warning("No valid PDF documents were found in this upload.")
    else:
        st.caption("No documents uploaded yet.")
