"""Checklist 4.1 verification (AppTest).

Covers: results rendering cleanly for the seeded schema (Table 1: 10
rows, Table 2: 13 rows, matching st.data_editor shapes); a
reconfigured schema (different table count, row counts, column names -
added/deleted via the real Config tab, not hand-constructed) rendering
without layout collapse or index errors; edits made directly in
st.data_editor being captured and retained in st.session_state across
reruns, including reruns where nothing new is edited; and the edge
cases of zero tables and a table with zero columns.

st.data_editor has no dedicated AppTest interaction helper (unlike
st.button/.text_input/.file_uploader) - edits are simulated the way
Streamlit's own widget mechanism represents them internally: writing a
DataEditorState-shaped dict ({'edited_rows': {...}, 'added_rows': [],
'deleted_rows': []}, row keys are 0-indexed DISPLAY position, not the
underlying column_id) directly into st.session_state[<data_editor key>]
before the next at.run() - confirmed empirically to correctly drive the
real st.data_editor() call in app.py before writing this suite.

Run: python tests/verify_results_ui.py
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


EXPECTED_RESULT_COLUMNS = ["Column", "Requirement", "PDF Name", "Page Number / Range", "Confidence", "Match Snippet"]


def main() -> None:
    from streamlit.testing.v1 import AppTest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "results_ui_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ["GROQ_API_KEY"] = ""  # keep this suite scoped to the results UI, not synonym expansion

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run()
        check("initial launch (seeded schema), no exception", not at.exception)

        # --- seeded schema: 2 data_editor grids, shapes matching 10 and 13 rows ---
        dataframes = list(at.dataframe)
        check("seeded schema -> exactly 2 results grids rendered (Table 1, Table 2)", len(dataframes) == 2)
        shapes = sorted(df.value.shape for df in dataframes)
        check("seeded schema -> grid row counts are exactly 10 and 13 (Table 1 / Table 2)", shapes == [(10, 6), (13, 6)])
        check(
            "each grid has exactly the 6 expected resolved-field + label columns",
            all(list(df.value.columns) == EXPECTED_RESULT_COLUMNS for df in dataframes),
        )
        check(
            "requirement text is shown verbatim (not truncated/altered) for review context",
            any("WHO-GMP" in "".join(df.value["Requirement"].astype(str)) for df in dataframes),
        )

        # --- edits captured and retained in session_state ---
        at.session_state["results_editor_1"] = {
            "edited_rows": {0: {"PDF Name": "invoice.pdf", "Page Number / Range": "3", "Confidence": 0.87, "Match Snippet": "proof text here"}},
            "added_rows": [], "deleted_rows": [],
        }
        at.run()
        check("edit applied -> no exception", not at.exception)

        results = at.session_state["resolution_results"]
        edited = results.get(1)  # column_id 1 = Table 1's first configured column
        check("edited cell values landed in st.session_state['resolution_results']", edited is not None)
        if edited:
            check(
                "all 4 edited fields persisted correctly (pdf/page/confidence/snippet)",
                edited.pdf_name == "invoice.pdf" and edited.page_number_or_range == "3"
                and edited.confidence == 0.87 and edited.match_snippet == "proof text here",
            )

        # --- persists across a FURTHER rerun where nothing new is edited ---
        at.run()
        check("no exception on a subsequent no-op rerun", not at.exception)
        still_there = at.session_state["resolution_results"].get(1)
        check(
            "edit survives an additional rerun with no new edits (not silently reset)",
            still_there is not None and still_there.pdf_name == "invoice.pdf",
        )

        # --- reconfigure the schema via the REAL Config tab: add a table,
        # delete Table 2 entirely, add a column with a custom name ---
        at.get_by_key("add_table_name").set_value("Extra Results Table")
        at.get_by_key("FormSubmitter:add_table_form-Add Table").click()
        at.run()
        at.get_by_key("tdel_2").click()  # delete Table 2 (13 rows) entirely
        at.run()
        at.get_by_key("newcol_name_1").set_value("Custom Reviewer Column")
        at.get_by_key("newcol_req_1").set_value("A brand-new ad hoc requirement added for this test.")
        at.get_by_key("FormSubmitter:add_col_form_1-Add Column").click()
        at.run()
        check("reconfiguration via the Config tab -> no exception", not at.exception)

        dataframes_after = list(at.dataframe)
        check(
            "reconfigured schema -> exactly 1 results grid (Table 1; Table 2 deleted; "
            "the still-columnless 'Extra Results Table' correctly renders no grid at all)",
            len(dataframes_after) == 1,
        )
        table1_df = dataframes_after[0]
        check("Table 1's grid grew to 11 rows after adding one column (10 -> 11), no hardcoded assumption broke", len(table1_df.value) == 11)
        check(
            "the new column's custom name appears as its own row label, not a placeholder",
            "Custom Reviewer Column" in list(table1_df.value["Column"]),
        )
        check(
            "the newly added, still-columnless 'Extra Results Table' shows its caption instead of an empty/broken grid",
            any("No columns configured for this table yet" in str(el.value) for el in at.caption),
        )

        # --- zero tables: delete everything, confirm graceful empty state ---
        at.get_by_key("tdel_1").click()
        at.run()
        # "Extra Results Table" is now the only table; find and delete it too.
        remaining_tdel_keys = [b.key for b in at.button if b.key and b.key.startswith("tdel_")]
        for key in remaining_tdel_keys:
            at.get_by_key(key).click()
            at.run()

        check("all tables deleted -> no exception", not at.exception)
        check("zero tables -> zero results grids rendered", len(list(at.dataframe)) == 0)
        check(
            "zero tables -> the empty-state message is shown",
            any("No tables configured yet" in str(el.value) for el in at.info),
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
