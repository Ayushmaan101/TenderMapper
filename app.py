"""AIIMS Tender Compliance Mapper — Streamlit entry point.

Checklist 1.3: the Config tab is live, backed by db/crud.py. Checklist
2.1: the Run tab's upload section is live, backed by ingest/pipeline.py -
purely session-scoped, touches no SQLite state. Checklist 4.1: the
results table is live, backed by run/results.py. Checklist 4.3: the
"Next Company" reset is live, backed by run/session_reset.py. Checklist
4.4: the Excel export is live, backed by export/excel_export.py +
run/export_ui.py. Checklist 5.1: the "Run Mapping" button
(run/run_button.py) turns uploaded documents into a searchable OCR/text
index (run/pipeline_runner.py) - a real slice of checklist 3.3, with
robust per-document error isolation. Still deferred from 3.3: the actual
per-column BM25-search + Groq-verify loop that would populate
resolution_results automatically - see CHECKLIST.md phase 3.
"""
import os

import streamlit as st

from config.ui import render_config_tab
from db.connection import DEFAULT_DB_PATH, get_connection
from db.schema import init_db
from ingest.ui import render_upload_section
from run.export_ui import render_export_section
from run.results import render_results_section
from run.run_button import render_run_button
from run.session_reset import render_next_company_button
from seed.seeder import seed_if_empty

st.set_page_config(
    page_title="AIIMS Tender Compliance Mapper",
    page_icon="\U0001f4cb",
    layout="wide",
)


@st.cache_resource
def get_db_connection():
    """One SQLite connection per server process, reused across every
    script rerun and every session. init_db() is idempotent (CREATE TABLE
    IF NOT EXISTS); seed_if_empty() is a one-time no-op after the first
    successful seed (see seed/seeder.py) — both are safe to call here,
    on every process start, without risk of duplicating anything.

    TENDER_MAPPER_DB_PATH overrides the DB file path when set — used by
    tests/verify_config_ui.py to point a real run of this app at a
    disposable temp DB instead of the real one. Unset in normal use.
    """
    db_path = os.environ.get("TENDER_MAPPER_DB_PATH", str(DEFAULT_DB_PATH))
    conn = get_connection(db_path)
    init_db(conn)
    seed_if_empty(conn)
    return conn


conn = get_db_connection()

st.title("AIIMS Tender Compliance Mapper")

run_tab, config_tab = st.tabs(["Run", "Config"])

with run_tab:
    st.header("Run")
    st.caption(
        "Company-in → resolve → review → “Next Company”. "
        "Reads the current persisted config; read-only here (edit via the "
        "Config tab)."
    )
    st.text_input("Company name", key="company_name")
    render_upload_section()
    st.divider()
    render_run_button(conn)
    st.divider()
    st.subheader("Results")
    st.caption(
        "Populated per-document by “Run Mapping” (OCR/text-layer resolution); the "
        "per-column BM25-search + Groq-verify loop that would auto-fill these cells "
        "(checklist 3.3) is still not wired in — correct any flagged or wrong cell "
        "directly, edits persist for this session."
    )
    render_results_section(conn)
    render_next_company_button()
    render_export_section(conn)

with config_tab:
    st.header("Config")
    render_config_tab(conn)
