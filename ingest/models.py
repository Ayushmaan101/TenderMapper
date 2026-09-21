"""Data model for ingested documents.

Deliberately has zero dependency on Streamlit or db/ - this package only
turns raw uploaded bytes into a clean, normalized list. Where those bytes
came from (a widget, a test fixture) and where the result is stored
(st.session_state) are the caller's concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IngestedDocument:
    """One accepted PDF, ready for the OCR/search pipeline.

    name: the display/storage name used from here on. Deduplicated
        against every other document in the same ingest batch - if two
        source files would produce the same name, the later one is
        renamed (see pipeline._dedupe_name).
    data: raw PDF bytes, unmodified.
    source_path: where this came from, for transparency/debugging -
        e.g. "invoice.pdf" for a direct upload, or
        "CompanyA.zip/scans/invoice.pdf" for a zip entry. Never used for
        matching/dedup - only `name` is.
    """

    name: str
    data: bytes
    source_path: str


@dataclass
class IngestResult:
    """The outcome of one normalize_uploads() call."""

    documents: list[IngestedDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
