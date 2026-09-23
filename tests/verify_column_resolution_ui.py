"""Checklist 3.3 verification (AppTest) — through the real "Run Mapping" button.

Drives the real UI end-to-end: uploads a synthetic scanned document with
a KNOWN match for exactly one seeded column, clicks "Run Mapping" once
(mocked Groq, content-aware so only the genuinely relevant candidate
scores high), and confirms:

  - resolution_results auto-populates for all 23 seeded columns
  - the genuinely matching column gets a clean snippet and confidence
    >= 0.70, and its Status cell in the real st.data_editor grid reads
    "Resolved"
  - every other (unmatched) column resolves low/zero confidence and its
    Status cell reads "Flagged" (checklist 4.2 integration, through the
    real rendered grid, not just the underlying data)
  - the populated results flow into the Excel export correctly
    (checklist 4.4 integration) - the matched column's row in the
    exported workbook carries the real pdf_name/confidence/snippet

Run: python tests/verify_column_resolution_ui.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def install_fake_groq(call_log: list, high_confidence_column: str, marker: str, low_confidence=0.1, high_confidence=0.93):
    """Content-aware, matching the discrimination bug fix from
    verify_column_resolution_unit.py: the marker is checked ONLY within
    a single [Candidate N] block's own text, never the whole prompt
    (which also carries the requirement text and could otherwise
    trivially self-match). Batched design (Groq rate-limit fix): the
    response schema is now {best_candidate, confidence, ...} - the fake
    reports whichever candidate NUMBER actually contains the marker,
    rather than echoing a pdf_name/page string (which the real code
    never trusts anyway).
    """
    import verify.groq_verifier as gv

    class _Completions:
        def create(self, **kwargs):
            call_log.append(kwargs)
            user_content = kwargs["messages"][1]["content"]
            is_target_column = f"Requirement column: {high_confidence_column}" in user_content

            best_candidate = 0
            confidence = low_confidence
            if is_target_column:
                blocks = re.split(r"\[Candidate (\d+)\]", user_content)
                for i in range(1, len(blocks), 2):
                    if marker in blocks[i + 1]:
                        best_candidate = int(blocks[i])
                        confidence = high_confidence
                        break

            content = json.dumps({
                "best_candidate": best_candidate,
                "confidence": confidence, "match_snippet": "WHO-GMP certificate content matched here", "reasoning": "evaluated",
            })
            message = type("M", (), {"content": content})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice]})()

    class _Client:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    gv.Groq = _Client


def main() -> None:
    import pymupdf as fitz
    from streamlit.testing.v1 import AppTest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "column_resolution_ui_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ["GROQ_API_KEY"] = "fake-key-for-this-suite"

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run()
        check("initial launch, no exception", not at.exception)

        # A genuinely "scanned" page (image, no text layer) containing
        # real WHO-GMP content - matches Item 4's real seed requirement.
        scratch = fitz.open()
        sp = scratch.new_page()
        sp.insert_text((50, 80), "WHO GMP CERTIFICATE valid manufacturing authority approved", fontsize=16)
        pix = sp.get_pixmap(matrix=fitz.Matrix(200 / 72.0, 200 / 72.0))
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, page.rect.width, page.rect.height), pixmap=pix)
        pdf_bytes = doc.tobytes()
        doc.close()
        scratch.close()

        call_log: list = []
        install_fake_groq(call_log, high_confidence_column="Item 4", marker="WHO GMP CERTIFICATE")

        uploader_key = [w.key for w in at.file_uploader][0]
        at.get_by_key(uploader_key).upload("CompanyA_certs.pdf", pdf_bytes, "application/pdf")
        at.run(timeout=120)

        at.get_by_key("run_mapping_button").click()
        # Groq is mocked, but OCR is real (PaddleOCR/Tesseract on the
        # synthetic scanned page) - AppTest's default 3s timeout is far
        # too short for real OCR (checklist 0.5 measured ~50s just for
        # PaddleOCR's own first-use initialization). Also real now:
        # resolve_all_columns()'s ~1s-per-column submission stagger
        # (Groq rate-limit fix) across 23 seeded columns adds ~22s more -
        # left at its real default here deliberately (this is the one
        # suite that drives the actual production button end-to-end), so
        # the timeout is bumped further to give it comfortable room.
        at.run(timeout=180)
        check("Run Mapping (full pipeline, mocked Groq) -> no exception", not at.exception)

        results = at.session_state["resolution_results"]
        check("resolution_results auto-populates for all 23 seeded columns", len(results) == 23)
        check(
            "a 23-column run makes EXACTLY 23 Groq API calls total (one batched call per column, not one per candidate)",
            len(call_log) == 23,
        )
        print(f"Terminal log: {len(call_log)} Groq API call(s) made resolving {len(results)} column(s).")

        # --- real-time streaming (Groq rate-limit fix): once the run
        # completes, the live preview placeholders (document counter,
        # OCR page progress, live results table) must have been cleared
        # via st.empty() - only the FINAL interactive grid (checklist
        # 4.1's st.data_editor-backed dataframes, one per table) should
        # remain in the rendered tree. AppTest can only inspect the tree
        # AFTER the whole script finishes (it can't observe the
        # mid-script incremental renders themselves), so this confirms
        # the placeholders were correctly torn down rather than leaking
        # stale progress text into the final page. ---
        check(
            "no leftover 'Processing document' counter text after the run completes",
            not any("Processing document" in str(el.value) for el in at.markdown),
        )
        check(
            "no lingering combined 'Table' + 'Status' live-preview dataframe remains (only the upload list + the 2 final per-table grids)",
            not any("Table" in df.value.columns and "Status" in df.value.columns for df in at.dataframe),
        )

        # --- find the "Item 4" column's id via the Config tab's real data ---
        from db import crud
        from db.connection import get_connection

        check_conn = get_connection(db_path)
        table1 = next(t for t in crud.get_tables(check_conn) if t.name == "Table 1")
        item4 = next(c for c in crud.get_columns(check_conn, table1.id) if c.name == "Item 4")

        matched = results[item4.id]
        check("the genuinely matching column resolved with confidence >= 0.70", matched.confidence >= 0.70)
        check("...with a clean, non-empty snippet", bool(matched.match_snippet))
        check("...to the real uploaded document (not the model's echoed filename)", matched.pdf_name == "CompanyA_certs.pdf")

        other_columns = [c for c in crud.get_columns(check_conn, table1.id) if c.name != "Item 4"]
        check(
            "every OTHER column resolved low/zero confidence (nothing else in this corpus matches them)",
            all(results[c.id].confidence < 0.70 for c in other_columns),
        )

        # --- Status cells in the REAL rendered grid reflect this correctly ---
        table1_grid = next(df for df in at.dataframe if len(df.value) == 10)
        status_by_column = dict(zip(table1_grid.value["Column"], table1_grid.value["Status"]))
        check("Item 4's Status cell in the real grid reads 'Resolved'", "Resolved" in status_by_column["Item 4"])
        check(
            "every other column's Status cell in the real grid reads 'Flagged'",
            all("Flagged" in status_by_column[c.name] for c in other_columns),
        )

        # --- Excel export integration (checklist 4.4) ---
        from export.excel_export import EXPORT_HEADERS, export_to_bytes
        import openpyxl
        import io

        export_conn = get_connection(db_path)
        export_data = export_to_bytes(export_conn, results)
        wb = openpyxl.load_workbook(io.BytesIO(export_data))
        ws1 = wb["Table 1"]
        headers_idx = {h: i + 1 for i, h in enumerate(EXPORT_HEADERS)}
        item4_row = 2 + list(status_by_column.keys()).index("Item 4")  # 1-indexed data row matching grid order
        check(
            "the auto-resolved match flows through to the Excel export (PDF Name)",
            ws1.cell(row=item4_row, column=headers_idx["PDF Name"]).value == "CompanyA_certs.pdf",
        )
        check(
            "the auto-resolved match flows through to the Excel export (Status = Resolved)",
            ws1.cell(row=item4_row, column=headers_idx["Status"]).value == "Resolved",
        )

        # --- progress/status messaging was shown during the run ---
        check(
            "a resolution-progress success message was shown after the run",
            any("Resolved" in s.value and "requirement" in s.value for s in at.success),
        )

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
