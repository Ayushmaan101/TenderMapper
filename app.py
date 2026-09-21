"""AIIMS Tender Compliance Mapper — Streamlit entry point.

Checklist 1.3: the Config tab is live, backed by db/crud.py. Checklist
2.1: the Run tab's upload section is live, backed by ingest/pipeline.py -
purely session-scoped, touches no SQLite state. The rest of the Run tab
(resolution pipeline, results table, "Next Company" reset) is still a
placeholder — see CHECKLIST.md phases 2-4.
"""
import os

import streamlit as st

from config.ui import render_config_tab
from db.connection import DEFAULT_DB_PATH, get_connection
from db.schema import init_db
from ingest.ui import render_upload_section
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
    st.info(
        "Placeholder — the resolution pipeline, results table, and "
        "“Next Company” reset are not built yet. See CHECKLIST.md phases 2–4."
    )

with config_tab:
    st.header("Config")
    render_config_tab(conn)
