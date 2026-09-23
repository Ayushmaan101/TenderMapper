"""Checklist 5.1 verification (AppTest) — end-to-end, through the real UI.

Drives the actual "Run Mapping" button (run/run_button.py) through every
error vector the checklist names, via real simulated file uploads and
real button clicks - not just calling the underlying functions directly
(that's tests/verify_error_handling_unit.py's job). Confirms the app
never raises, always surfaces a clear message, and stays interactive
afterward (a further click still works) for every scenario:

  - a corrupted PDF alongside a valid one
  - a password-protected PDF alongside a valid one
  - a zero-page PDF (not an error - no warning expected for it)
  - clicking "Run Mapping" with no files uploaded
  - clicking "Run Mapping" with an empty config (all tables deleted)
  - a simulated mid-run Groq API drop / missing key, via both Groq call
    sites currently reachable from the UI (config-time synonym
    expansion, and checklist 4.2's manual re-search) - checklist 3.3's
    own per-column auto-resolution loop isn't wired in yet, so these are
    the two real UI-triggered Groq call sites that exist today

Run: python tests/verify_error_handling_ui.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


CORRUPT_PDF_BYTES = b"%PDF-1.4\ngarbage garbage garbage not real pdf structure\n%%EOF"
ZERO_PAGE_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"trailer\n<< /Size 3 /Root 1 0 R >>\n%%EOF"
)


def make_valid_pdf_bytes(text: str) -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def make_encrypted_pdf_bytes() -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Secret content", fontsize=12)
    data = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123",
        permissions=int(fitz.PDF_PERM_PRINT),
    )
    doc.close()
    return data


def make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    return buf.getvalue()


def main() -> None:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["GROQ_API_KEY"] = ""
        app_path = str(Path(__file__).resolve().parent.parent / "app.py")

        def fresh_app(db_name: str) -> AppTest:
            # app.py's DB connection is cached process-wide via
            # st.cache_resource (correct, real production behavior - one
            # connection shared across every session on a server), which
            # would otherwise make every AppTest instance in this single
            # test process silently share the FIRST instance's db_path
            # regardless of the env var. Scenario 5 below deliberately
            # empties the config, which would then corrupt every later
            # scenario if they shared state. Clearing the cache before
            # each scenario, alongside a distinct db file, gives every
            # scenario a genuinely fresh, independent app instance.
            st.cache_resource.clear()
            os.environ["TENDER_MAPPER_DB_PATH"] = str(Path(tmp) / db_name)
            at = AppTest.from_file(app_path)
            at.run()
            return at

        # ============================================================
        # 1. Corrupt PDF alongside a valid PDF
        # ============================================================
        at = fresh_app("scenario1.db")
        check("initial launch, no exception", not at.exception)

        zip_bytes = make_zip({
            "valid.pdf": make_valid_pdf_bytes("Genuine readable content for the valid PDF."),
            "corrupt.pdf": CORRUPT_PDF_BYTES,
        })
        uploader_key = [w.key for w in at.file_uploader][0]
        at.get_by_key(uploader_key).upload("docs.zip", zip_bytes, "application/zip")
        at.run()
        check("corrupt+valid zip ingested (2 documents, ingest itself doesn't open PDFs)", len(at.session_state["ingested_documents"]) == 2)

        at.get_by_key("run_mapping_button").click()
        at.run()
        check("Run Mapping with a corrupt document present -> no exception", not at.exception)
        check(
            "a warning names the corrupt file specifically",
            any("corrupt.pdf" in w.value for w in at.warning),
        )
        check(
            "a success message confirms the valid document was still processed",
            any("Processed 1 document" in s.value for s in at.success),
        )
        check("the search index contains only the valid document's page", len(at.session_state["corpus_index"]) == 1)

        # App stays interactive: a further click still works cleanly.
        at.get_by_key("run_mapping_button").click()
        at.run()
        check("clicking Run Mapping again afterward still works, no exception", not at.exception)

        # ============================================================
        # 2. Password-protected PDF alongside a valid PDF
        # ============================================================
        at2 = fresh_app("scenario2.db")
        zip_bytes2 = make_zip({
            "valid.pdf": make_valid_pdf_bytes("Another genuine valid document."),
            "locked.pdf": make_encrypted_pdf_bytes(),
        })
        uploader_key2 = [w.key for w in at2.file_uploader][0]
        at2.get_by_key(uploader_key2).upload("docs2.zip", zip_bytes2, "application/zip")
        at2.run()
        at2.get_by_key("run_mapping_button").click()
        at2.run()
        check("Run Mapping with a password-protected document -> no exception", not at2.exception)
        check("a warning names the locked file and mentions it's password-protected", any("locked.pdf" in w.value and "password" in w.value.lower() for w in at2.warning))
        check("the valid sibling document still processed successfully", any("Processed 1 document" in s.value for s in at2.success))

        # ============================================================
        # 3. Zero-page PDF - NOT an error, no warning expected for it
        # ============================================================
        at3 = fresh_app("scenario3.db")
        uploader_key3 = [w.key for w in at3.file_uploader][0]
        at3.get_by_key(uploader_key3).upload("empty.pdf", ZERO_PAGE_PDF_BYTES, "application/pdf")
        at3.run()
        at3.get_by_key("run_mapping_button").click()
        at3.run()
        check("Run Mapping with only a zero-page PDF -> no exception", not at3.exception)
        check("a zero-page PDF produces NO warning (it's not an error)", not any("empty.pdf" in w.value for w in at3.warning))
        check(
            "it still counts as 'processed' (0 pages contributed, not skipped as bad)",
            any("Processed 1 document" in s.value for s in at3.success),
        )

        # ============================================================
        # 4. Empty upload - click Run Mapping with nothing uploaded
        # ============================================================
        at4 = fresh_app("scenario4.db")
        at4.get_by_key("run_mapping_button").click()
        at4.run()
        check("Run Mapping with NO upload at all -> no exception (no IndexError/AttributeError)", not at4.exception)
        check("a clear instructional warning is shown", any("Upload at least one document" in w.value for w in at4.warning))

        # ============================================================
        # 5. Empty config - delete all tables, then click Run Mapping
        # ============================================================
        at5 = fresh_app("scenario5.db")
        for key in [b.key for b in at5.button if b.key and b.key.startswith("tdel_")]:
            at5.get_by_key(key).click()
            at5.run()
        uploader_key5 = [w.key for w in at5.file_uploader][0]
        at5.get_by_key(uploader_key5).upload("a.pdf", make_valid_pdf_bytes("content"), "application/pdf")
        at5.run()
        at5.get_by_key("run_mapping_button").click()
        at5.run()
        check("Run Mapping with an empty config -> no exception", not at5.exception)
        check("a clear 'no tables configured' warning is shown", any("No compliance tables configured" in w.value for w in at5.warning))
        check(
            "the Results section separately shows its own informative empty-config message",
            any("No tables configured yet" in i.value for i in at5.info),
        )

        # ============================================================
        # 6. Simulated mid-run Groq API drop / missing key, via the two
        # real UI-triggered Groq call sites (checklist 3.3's own
        # auto-resolution loop isn't wired in yet)
        # ============================================================
        at6 = fresh_app("scenario6.db")  # GROQ_API_KEY is blank in this whole suite's environment

        # 6a. Config-time synonym expansion with a missing key.
        at6.get_by_key("newcol_name_1").set_value("Resilience Test Col")
        at6.get_by_key("newcol_req_1").set_value("A requirement added to test Groq failure resilience.")
        at6.get_by_key("FormSubmitter:add_col_form_1-Add Column").click()
        at6.run()
        check("adding a column with GROQ_API_KEY missing -> no exception (app stays interactive)", not at6.exception)
        table1_grid = next(df for df in at6.dataframe if "Resilience Test Col" in list(df.value.get("Column", [])))
        check("the column was still created despite the missing-key synonym-generation failure", table1_grid is not None)

        # 6b. Manual re-search (checklist 4.2) with a missing key - inject
        # a minimal real search index so the flow actually reaches Groq.
        from search.bm25_index import PageRecord, build_corpus_index

        pages = [PageRecord("a.pdf", 1, "some content for the manual re-search resilience test")]
        at6.session_state["corpus_index"] = build_corpus_index(pages)
        at6.session_state["page_texts"] = {("a.pdf", 1): pages[0].text}
        at6.run()

        flagged_expanders = [e for e in at6.expander if e.label and e.label.startswith("\U0001f50d")]
        check("at least one flagged column's re-search expander is available to test against", len(flagged_expanders) > 0)
        if flagged_expanders:
            # Extract the column id from an expander we know the key pattern for.
            first_col_id = 1
            at6.get_by_key(f"custom_terms_{first_col_id}").set_value("some content")
            at6.get_by_key(f"research_{first_col_id}").click()
            at6.run()
            check("manual re-search with GROQ_API_KEY missing -> no exception", not at6.exception)
            result = at6.session_state["resolution_results"].get(first_col_id)
            check(
                "the column's result reflects the failure gracefully (confidence 0.0, not a crash)",
                result is not None and result.confidence == 0.0,
            )

        # App still fully interactive after both Groq failures.
        at6.get_by_key("company_name").set_value("Still Works After Groq Failures")
        at6.run()
        check("the app remains fully interactive after two Groq failures (company name field still works)", not at6.exception and at6.session_state["company_name"] == "Still Works After Groq Failures")

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
