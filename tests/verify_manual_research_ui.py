"""Checklist 4.2 verification (AppTest), updated for the Run tab
lifecycle/consolidated re-search refinement.

Covers: confidence flagging surfacing correctly in the UI (status text
per row, summary metrics) both for the all-unresolved starting state and
after some rows are resolved above/below the threshold; manual re-search
updating ONLY the target column's result while every other column's
result is provably untouched; a database fingerprint (every
table/column/synonym in the real config DB) staying byte-identical
across a manual re-search, confirming zero SQLite side effects; graceful
handling when no corpus index has been built yet (checklist 3.3 not
wired in); a row that clears the threshold via re-search flipping from
Flagged to Resolved and dropping out of the dropdown's options; and the
single consolidated "Manual Re-Search" expander (not one per flagged
row) whose selectbox drives which column's search box/button render.

Run: python tests/verify_manual_research_ui.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def db_fingerprint(db_path: str) -> tuple:
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


def install_fake_groq(confidence: float, pdf_name="ignored-echo.pdf", page="ignored-echo"):
    import verify.groq_verifier as gv

    content = json.dumps({
        "pdf_name": pdf_name, "page_number_or_range": page,
        "confidence": confidence, "match_snippet": "matched snippet text", "reasoning": "reasoning text",
    })

    class _Completions:
        def create(self, **kwargs):
            message = type("M", (), {"content": content})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice]})()

    class _Client:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    gv.Groq = _Client


def main() -> None:
    from streamlit.testing.v1 import AppTest

    from search.bm25_index import PageRecord, build_corpus_index

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "manual_research_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ["GROQ_API_KEY"] = "fake-key-for-this-suite"

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run(timeout=30)  # first run pays full module-import cost; default 3s is too tight
        check("initial launch, no exception", not at.exception)

        # --- pre-run gate: nothing results-related renders before "Run Mapping" ---
        check("pre-run: zero metrics rendered", len(list(at.get("metric"))) == 0)
        check("pre-run: zero results grids rendered", len(list(at.dataframe)) == 0)
        check(
            "pre-run: zero re-search expanders rendered",
            not any("Manual Re-Search" in (e.label or "") for e in at.expander),
        )
        check(
            "pre-run: the placeholder callout is shown instead",
            any("Run Mapping" in str(el.value) for el in at.info),
        )

        # This suite intentionally bypasses the real OCR/Groq pipeline for
        # phase 1 (see verify_column_resolution_*.py for that end-to-end
        # coverage) and injects resolution_results directly - simulate
        # "Run Mapping" having completed the same way, by setting the flag
        # it sets, so the gated UI below renders.
        at.session_state["mapping_has_run"] = True
        at.run()
        check("simulated run-completion -> no exception", not at.exception)

        # --- flagging: fresh/all-unresolved state ---
        metrics = {m.label: m.value for m in at.get("metric")}
        check("fresh state -> 23 total requirements", metrics.get("Total requirements (all tables)") == "23")
        check("fresh state -> 0 resolved", metrics.get("Resolved") == "0")
        check("fresh state -> all 23 flagged", metrics.get("Flagged for review") == "23")

        table1_grid = next(df for df in at.dataframe if len(df.value) == 10)
        check("every row in the fresh grid shows the Flagged status", all("Flagged" in s for s in table1_grid.value["Status"]))

        research_expanders = [e for e in at.expander if "Manual Re-Search" in (e.label or "")]
        check("exactly ONE consolidated re-search expander (not one per flagged row)", len(research_expanders) == 1)
        check("consolidated expander's title shows the correct flagged count (23)", "(23 flagged)" in research_expanders[0].label)

        select = at.get_by_key("manual_research_column_select")
        check("dropdown lists all 23 flagged columns", len(select.options) == 23)
        check(
            "dropdown entries are prefixed with an exclamation mark and show name + confidence",
            all(opt.startswith("❗") and "Confidence: 0.00" in opt for opt in select.options),
        )

        # --- inject some results: one high-confidence, one low-confidence ---
        at.session_state["resolution_results"][1] = replace(
            at.session_state["resolution_results"].get(1),
            pdf_name="cert.pdf", page_number_or_range="4", confidence=0.95,
            match_snippet="genuine match", success=True,
        )
        at.session_state["resolution_results"][2] = replace(
            at.session_state["resolution_results"].get(2),
            pdf_name="weak.pdf", page_number_or_range="9", confidence=0.4,
            match_snippet="weak match", success=True,
        )
        at.run()
        metrics = {m.label: m.value for m in at.get("metric")}
        check("after injecting 1 high + 1 low confidence result -> Resolved=1", metrics.get("Resolved") == "1")
        check("after injecting 1 high + 1 low confidence result -> Flagged=22", metrics.get("Flagged for review") == "22")

        table1_grid = next(df for df in at.dataframe if len(df.value) == 10)
        status_by_column = dict(zip(table1_grid.value["Column"], table1_grid.value["Status"]))
        check("the 0.95-confidence row shows Resolved", "Resolved" in status_by_column["Item 1"])
        check("the 0.4-confidence row still shows Flagged", "Flagged" in status_by_column["Item 2"])
        check("an untouched (still-blank) row also shows Flagged", "Flagged" in status_by_column["Item 3"])

        research_expanders = [e for e in at.expander if "Manual Re-Search" in (e.label or "")]
        check("still exactly ONE consolidated expander", len(research_expanders) == 1)
        check("expander's title now shows the reduced flagged count (22)", "(22 flagged)" in research_expanders[0].label)

        select = at.get_by_key("manual_research_column_select")
        check(
            "column 1 (now resolved) no longer appears in the dropdown's options",
            not any(opt.startswith("❗ Item 1:") for opt in select.options),
        )
        check(
            "column 2 (still flagged) still appears in the dropdown's options",
            any(opt.startswith("❗ Item 2:") for opt in select.options),
        )

        # --- manual re-search: no corpus index yet -> graceful message, no crash ---
        # (select column 3 first - a fresh selectbox defaults to its first
        # option, which is no longer necessarily column 3 now that column 1
        # dropped out of the flagged list)
        at.get_by_key("manual_research_column_select").select(3)
        at.run()
        at.get_by_key("custom_terms_3").set_value("some custom term")
        at.get_by_key("research_3").click()
        at.run()
        check("re-search attempted with no corpus index built -> no exception", not at.exception)
        check(
            "re-search with no corpus index -> that column's result is untouched (still blank)",
            at.session_state["resolution_results"].get(3) is None or at.session_state["resolution_results"][3].confidence == 0.0,
        )

        # --- inject a real corpus index + page texts (the checklist-3.3 contract) ---
        pages = [
            PageRecord("CompanyA.pdf", 7, "Narcotic license issued by Central Excise Commissioner, valid registration certificate for the bidder firm."),
            PageRecord("CompanyA.pdf", 8, "Completely unrelated page about office furniture procurement."),
        ]
        at.session_state["corpus_index"] = build_corpus_index(pages)
        at.session_state["page_texts"] = {(p.pdf_name, p.page_number): p.text for p in pages}

        fingerprint_before = db_fingerprint(db_path)

        install_fake_groq(confidence=0.88, pdf_name="MODEL-HALLUCINATED-NAME.pdf", page="999")
        at.run()
        at.get_by_key("custom_terms_3").set_value("narcotic license excise commissioner")
        at.get_by_key("research_3").click()
        at.run()
        check("manual re-search with a real corpus index -> no exception", not at.exception)

        result3 = at.session_state["resolution_results"][3]
        check("re-searched column's result updated (success=True)", result3.success is True)
        check("re-searched column's confidence updated to the mocked value", result3.confidence == 0.88)
        check(
            "re-searched column's pdf_name/page are the REAL candidate's, not the model's hallucinated echo",
            result3.pdf_name == "CompanyA.pdf" and result3.page_number_or_range == "7",
        )

        # --- isolation: every OTHER column's result is untouched ---
        col1_after = at.session_state["resolution_results"][1]
        col2_after = at.session_state["resolution_results"][2]
        check("column 1's result (0.95, cert.pdf) is completely unchanged by column 3's re-search", col1_after.confidence == 0.95 and col1_after.pdf_name == "cert.pdf")
        check("column 2's result (0.4, weak.pdf) is completely unchanged by column 3's re-search", col2_after.confidence == 0.4 and col2_after.pdf_name == "weak.pdf")

        other_untouched = all(
            at.session_state["resolution_results"].get(cid) is None or at.session_state["resolution_results"][cid].confidence in (0.0, 0.95, 0.4)
            for cid in range(4, 24)
        )
        check("no other (never-touched) column was accidentally populated", other_untouched)

        # --- the re-searched row flips from Flagged to Resolved ---
        table1_grid_after = next(df for df in at.dataframe if len(df.value) == 10)
        status_by_column_after = dict(zip(table1_grid_after.value["Column"], table1_grid_after.value["Status"]))
        check("re-searched column (0.88 >= 0.70) now shows Resolved", "Resolved" in status_by_column_after["Item 3"])

        select_after = at.get_by_key("manual_research_column_select")
        check(
            "the now-resolved column no longer appears in the dropdown's options",
            not any(opt.startswith("❗ Item 3:") for opt in select_after.options),
        )
        research_expanders_after = [e for e in at.expander if "Manual Re-Search" in (e.label or "")]
        check("still exactly ONE consolidated expander after the re-search", len(research_expanders_after) == 1)
        check("expander's title reflects the further-reduced flagged count (21)", "(21 flagged)" in research_expanders_after[0].label)

        # --- DB fingerprint: zero SQLite side effects from the manual re-search ---
        fingerprint_after = db_fingerprint(db_path)
        check("config DB fingerprint is byte-identical before/after the manual re-search", fingerprint_before == fingerprint_after)

        # --- empty custom terms -> warning shown, no re-search executed ---
        install_fake_groq(confidence=0.5)  # would be a NEW distinguishable value if wrongly invoked
        at.run()
        at.get_by_key("manual_research_column_select").select(4)
        at.run()
        result4_before = at.session_state["resolution_results"].get(4)
        at.get_by_key("custom_terms_4").set_value("   ")  # whitespace only
        at.get_by_key("research_4").click()
        at.run()
        check("empty/whitespace-only custom terms -> a warning is shown", len(at.warning) > 0)
        result4_after = at.session_state["resolution_results"].get(4)
        check(
            "empty custom terms -> column 4's result is unchanged (no re-search actually ran)",
            (result4_before is None and result4_after is None) or result4_before == result4_after,
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
