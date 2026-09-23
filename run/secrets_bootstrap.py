"""Bridges Streamlit Community Cloud's native secrets store into
os.environ (checklist 5.2).

config/synonyms.py and verify/groq_verifier.py are deliberately
Streamlit-free (see PROJECT_HARNESS.md §2) so they stay unit-testable
without a running Streamlit app, and both already read GROQ_API_KEY via a
plain os.environ.get(...) (local dev fills that in from .env via
python-dotenv). Community Cloud has no .env file at all — secrets are
set through its dashboard and surfaced to the app only via st.secrets.
Rather than importing streamlit into those two Streamlit-free modules,
app.py calls bootstrap_groq_api_key() once at startup to copy the value
across, so the two pipeline modules never need to change.
"""
from __future__ import annotations

import os

import streamlit as st


def bootstrap_groq_api_key() -> None:
    """No-op if GROQ_API_KEY is already set (the local-dev/.env case, and
    every test in this project that sets it directly). Otherwise, try
    st.secrets - swallowing any exception, since st.secrets raises when no
    secrets.toml exists at all, which is the normal case for local dev.
    """
    if os.environ.get("GROQ_API_KEY", "").strip():
        return
    try:
        key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        key = None
    if key:
        os.environ["GROQ_API_KEY"] = key
