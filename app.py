"""AIIMS Tender Compliance Mapper — Streamlit entry point.

This is the checklist-0.6 skeleton: a two-tab shell (Run / Config) with
placeholders only. No pipeline logic lives here yet — see
PROJECT_HARNESS.md for what each tab will eventually do, and
CHECKLIST.md for build order.
"""
import streamlit as st

st.set_page_config(
    page_title="AIIMS Tender Compliance Mapper",
    page_icon="\U0001f4cb",
    layout="wide",
)

st.title("AIIMS Tender Compliance Mapper")

run_tab, config_tab = st.tabs(["Run", "Config"])

with run_tab:
    st.header("Run")
    st.caption(
        "Company-in → resolve → review → “Next Company”. "
        "Reads the current persisted config; read-only here (edit via the "
        "Config tab)."
    )
    st.info(
        "Placeholder — upload handling, the resolution pipeline, the "
        "results table, and the “Next Company” reset are not built "
        "yet. See CHECKLIST.md phases 2–4."
    )

with config_tab:
    st.header("Config")
    st.caption(
        "Define tables, columns, requirement text, and stored synonyms. "
        "Persists to SQLite; independent of the Run tab; never wiped by "
        "“Next Company”."
    )
    st.info(
        "Placeholder — schema CRUD, first-run auto-seed, and synonym "
        "expansion are not built yet. See CHECKLIST.md phase 1."
    )
