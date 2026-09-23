"""Checklist 2.1 verification — Streamlit session-state integration (AppTest).

Drives the real Run tab's upload widget (via streamlit.testing.v1.AppTest
with real simulated file uploads - AppTest.file_uploader.upload/set_value
producing genuine UploadedFile objects) and confirms:

  - uploading populates st.session_state cleanly (documents + warnings)
  - a zip with mixed valid/invalid content renders correctly
  - the persistent SQLite config DB is completely untouched by any of
    this - same table/column/synonym counts before and after
  - re-running the script without changing the upload selection does NOT
    re-run normalize_uploads (call-counter, mirrors the checklist 1.4
    pattern for "no unnecessary calls")
  - clearing the upload clears session state back to empty

Run: python tests/verify_ingest_ui.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def pdf_bytes(marker: str = "") -> bytes:
    return f"%PDF-1.4\n%fake pdf content {marker}\n%%EOF".encode()


def make_zip(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    return buf.getvalue()


def db_fingerprint(db_path: str) -> tuple:
    """A cheap snapshot of everything in the config DB, for before/after
    comparison - proves the ingest flow touched none of it."""
    from db import crud
    from db.connection import get_connection

    conn = get_connection(db_path)
    tables = crud.get_tables(conn)
    fingerprint = []
    for t in tables:
        cols = crud.get_columns(conn, t.id)
        col_snapshot = []
        for c in cols:
            syns = tuple(s.synonym_text for s in crud.get_synonyms(conn, c.id))
            col_snapshot.append((c.name, c.requirement_text, syns))
        fingerprint.append((t.name, tuple(col_snapshot)))
    conn.close()
    return tuple(fingerprint)


def main() -> None:
    from streamlit.testing.v1 import AppTest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "ingest_ui_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ["GROQ_API_KEY"] = ""  # keep this test scoped to ingest, not synonym expansion

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run()
        check("initial launch, no exception", not at.exception)

        fingerprint_before_any_upload = db_fingerprint(db_path)

        # --- install a call-counter around normalize_uploads, patched
        # into ingest.ui's own reference (the module app.py actually
        # calls through) ---
        import ingest.ui as ingest_ui_mod

        call_log: list = []
        original_normalize = ingest_ui_mod.normalize_uploads

        def counting_normalize(*args, **kwargs):
            call_log.append(1)
            return original_normalize(*args, **kwargs)

        ingest_ui_mod.normalize_uploads = counting_normalize

        # --- upload a zip with a mix of valid PDFs and unsupported files ---
        zip_bytes = make_zip({
            "invoice.pdf": pdf_bytes("inv"),
            "logo.png": b"\x89PNG fake bytes",
            "certificate.pdf": pdf_bytes("cert"),
        })
        at.get_by_key("company_file_uploader_0").upload("CompanyDocs.zip", zip_bytes, "application/zip")
        at.run()
        check("upload a mixed zip -> no exception", not at.exception)
        check("upload a mixed zip -> normalize_uploads called exactly once", len(call_log) == 1)

        docs = at.session_state.get("ingested_documents")
        warnings = at.session_state.get("ingest_warnings")
        check("session_state has 2 ingested documents (the 2 valid PDFs)", docs is not None and len(docs) == 2)
        check(
            "session_state documents have correct names",
            {d.name for d in docs} == {"invoice.pdf", "certificate.pdf"} if docs else False,
        )
        check("session_state has 1 warning (for logo.png)", warnings is not None and len(warnings) == 1 and "logo.png" in warnings[0])

        # --- re-run WITHOUT touching the upload -> must not reprocess ---
        for _ in range(3):
            at.run()
        check("re-running without changing the upload -> zero additional calls", len(call_log) == 1)
        check("session_state documents unchanged after idle reruns", len(at.session_state.get("ingested_documents")) == 2)

        # --- the persistent config DB must be completely untouched ---
        fingerprint_after_upload = db_fingerprint(db_path)
        check(
            "config DB fingerprint identical before/after upload (schema untouched by ingest)",
            fingerprint_before_any_upload == fingerprint_after_upload,
        )
        check("config DB still has the seeded 2 tables (ingest didn't wipe or add anything)", len(fingerprint_after_upload) == 2)

        # --- clearing the upload clears session state ---
        at.get_by_key("company_file_uploader_0").clear()
        at.run()
        check("clearing the upload -> normalize_uploads called again (selection changed)", len(call_log) == 2)
        check("clearing the upload -> session_state documents empty", at.session_state.get("ingested_documents") == [])
        check("clearing the upload -> session_state warnings empty", at.session_state.get("ingest_warnings") == [])

        ingest_ui_mod.normalize_uploads = original_normalize

    if all(ok for _, ok in checks):
        print(f"ALL CHECKS PASSED ({len(checks)}/{len(checks)})")
        sys.exit(0)
    else:
        failed = [label for label, ok in checks if not ok]
        print(f"FAILED {len(failed)}/{len(checks)}:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
