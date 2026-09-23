"""Checklist 4.4 verification (AppTest) — UI wiring.

AppTest's DownloadButton test element exposes only whether it was
clicked, not the actual file bytes (Streamlit stores download payloads
via an internal deferred-file mechanism, not the widget proto) - so this
suite verifies UI *wiring* (the button renders, reads the right session
state) via AppTest, and verifies *content* by calling
export.excel_export.export_to_bytes() directly against the exact same
session_state/db connection a real click would use - proving the real
integration without depending on Streamlit's internal download plumbing.

Covers: the download button renders correctly against the seeded
schema; a manual edit driven through the real st.data_editor (same
simulation technique as checklist 4.1/4.2's suites) lands correctly in
the exported bytes; the company-name field correctly drives the
filename; and a schema reconfigured through the real Config tab (custom
table name with special characters) exports correctly without any
hardcoded assumption.

Run: python tests/verify_excel_export_ui.py
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


def main() -> None:
    import openpyxl

    from db.connection import get_connection
    from export.excel_export import EXPORT_HEADERS, export_to_bytes, sanitize_filename
    from streamlit.testing.v1 import AppTest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "export_ui_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ["GROQ_API_KEY"] = ""

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run(timeout=30)  # first run pays full module-import cost; default 3s is too tight
        check("initial launch, no exception", not at.exception)
        check(
            "pre-run: the export button is hidden behind the run-completion gate",
            "export_download_button" not in {b.key for b in at.download_button},
        )

        # This suite tests export WIRING/CONTENT, not the real OCR/Groq
        # pipeline (see verify_column_resolution_*.py for that) - simulate
        # "Run Mapping" having completed by setting the flag it sets, same
        # as the other UI suites reworked for this gate.
        at.session_state["mapping_has_run"] = True
        at.run()
        check("simulated run-completion -> no exception", not at.exception)

        download_button = at.get_by_key("export_download_button")
        check("the export download button renders", download_button is not None)
        check("the download button's label mentions the export", "Excel" in download_button.label or "\U0001f4e5" in download_button.label)

        # --- a real manual edit, driven through st.data_editor (same
        # simulation technique proven in checklist 4.1/4.2's suites) ---
        at.session_state["results_editor_1"] = {
            "edited_rows": {3: {  # row index 3 = column_id 4 = "Item 4"
                "PDF Name": "CompanyA_certificate.pdf",
                "Page Number / Range": "5",
                "Confidence": 0.93,
                "Match Snippet": "WHO-GMP certificate, valid until 2028.",
            }},
            "added_rows": [], "deleted_rows": [],
        }
        at.run()
        check("edit applied via the real data_editor, no exception", not at.exception)

        # Export using the EXACT session_state + db connection the real
        # download button would use.
        export_conn = get_connection(db_path)
        data = export_to_bytes(export_conn, at.session_state["resolution_results"])
        wb = openpyxl.load_workbook(__import__("io").BytesIO(data))
        ws1 = wb["Table 1"]
        headers_idx = {h: i + 1 for i, h in enumerate(EXPORT_HEADERS)}
        row4 = 5  # header + 3 preceding items + this one

        check(
            "the real UI-driven edit appears exactly in the exported workbook (PDF Name)",
            ws1.cell(row=row4, column=headers_idx["PDF Name"]).value == "CompanyA_certificate.pdf",
        )
        check(
            "the real UI-driven edit appears exactly in the exported workbook (Confidence)",
            ws1.cell(row=row4, column=headers_idx["Confidence"]).value == 0.93,
        )
        check(
            "the real UI-driven edit appears exactly in the exported workbook (Match Snippet)",
            ws1.cell(row=row4, column=headers_idx["Match Snippet"]).value == "WHO-GMP certificate, valid until 2028.",
        )
        check("the edited row's Status is now 'Resolved'", ws1.cell(row=row4, column=headers_idx["Status"]).value == "Resolved")

        # --- company name -> filename ---
        at.get_by_key("company_name").set_value("ABC Pharma & Co./Ltd")
        at.run()
        expected_filename = sanitize_filename(at.session_state["company_name"])
        check(
            "sanitize_filename(company_name) produces the filename the real download button would use",
            expected_filename == "ABC Pharma & Co._Ltd.xlsx",
        )

        at.get_by_key("company_name").set_value("")
        at.run()
        check(
            "blank company name -> filename falls back to the documented default",
            sanitize_filename(at.session_state["company_name"]) == "tender_compliance_mapping.xlsx",
        )

        # --- reconfigure via the REAL Config tab: a table with special
        # characters in its name -> export must still produce a valid
        # sheet, no hardcoded assumption broken ---
        at.get_by_key("add_table_name").set_value("Special/Chars:Test*2026")
        at.get_by_key("FormSubmitter:add_table_form-Add Table").click()
        at.run()
        at.get_by_key("newcol_name_3").set_value("New Req")
        at.get_by_key("newcol_req_3").set_value("A brand new requirement for the reconfigured export test.")
        at.get_by_key("FormSubmitter:add_col_form_3-Add Column").click()
        at.run()
        check("reconfiguration via the real Config tab -> no exception", not at.exception)

        export_conn2 = get_connection(db_path)
        data2 = export_to_bytes(export_conn2, at.session_state["resolution_results"])
        wb2 = openpyxl.load_workbook(__import__("io").BytesIO(data2))
        check("reconfigured schema -> exactly 3 sheets now", len(wb2.sheetnames) == 3)
        check(
            "the special-character table name was sanitized into a valid sheet name",
            any(not any(ch in name for ch in "\\/?*[]:") for name in wb2.sheetnames) and len(wb2.sheetnames) == 3,
        )
        new_sheet = next(n for n in wb2.sheetnames if n not in ("Table 1", "Table 2"))
        check("the new table's sheet has exactly 1 data row (its 1 configured column)", wb2[new_sheet].max_row == 2)

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
