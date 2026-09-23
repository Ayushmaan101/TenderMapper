"""Checklist 4.3 verification (AppTest).

Full-cycle simulation: ingest Company A's data (name, an uploaded PDF,
mock resolved results, a manual re-search injected result, and a full
search-index session-state contract - corpus_index/page_texts/
reference_index/ocr_cache), click "Next Company", then assert all four
clear conditions plus a DB fingerprint, then confirm Company B can load
cleanly with zero residual state from Company A.

Note on "resolution_results cleared": reset_run_state() sets it to {} AND
clears mapping_has_run, which puts the Results section back behind the
pre-run gate - app.py's next render no longer even calls
render_results_section() (it shows the pre-run placeholder instead), so
resolution_results genuinely stays an empty dict post-reset, not merely
a dict of blank placeholder entries. The "every entry is functionally
blank" assertions below hold either way (vacuously true over an empty
dict), kept as a stricter check in case that ever changes.

Also covers: the pre-run gate (checklist "Run tab UI lifecycle") hiding
the Results grid and re-search controls both on a fresh cold start and
immediately after a "Next Company" reset.

Run: python tests/verify_next_company_reset.py
"""
from __future__ import annotations

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


def main() -> None:
    from streamlit.testing.v1 import AppTest

    from run.results import _BLANK_RESULT
    from search.bm25_index import PageRecord, build_corpus_index

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "next_company_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ["GROQ_API_KEY"] = ""  # keep this suite scoped to reset behavior

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run(timeout=30)  # first run pays full module-import cost; default 3s is too tight
        check("initial launch, no exception", not at.exception)

        # --- fresh cold start: Results grid + re-search controls completely hidden ---
        check("cold start: zero results grids rendered", len(list(at.dataframe)) == 0)
        check(
            "cold start: zero re-search expanders rendered",
            not any("Manual Re-Search" in (e.label or "") for e in at.expander),
        )
        check(
            "cold start: the pre-run placeholder callout is shown instead",
            any("Run Mapping" in str(el.value) for el in at.info),
        )

        fingerprint_before_anything = db_fingerprint(db_path)

        # ============================================================
        # Ingest Company A: name, an uploaded PDF, mock resolved
        # results, a manual-re-search-style edit, and a full search
        # index (the checklist-3.3 session-state contract).
        # ============================================================
        at.get_by_key("company_name").set_value("Company A Pvt Ltd")

        uploader_key_gen0 = [w.key for w in at.file_uploader][0]
        check("uploader starts at generation 0", uploader_key_gen0 == "company_file_uploader_0")
        pdf_bytes = b"%PDF-1.4\n%company A fake pdf\n%%EOF"
        at.get_by_key(uploader_key_gen0).upload("CompanyA_certificate.pdf", pdf_bytes, "application/pdf")
        at.run()
        check("Company A upload registered", len(at.session_state["ingested_documents"]) == 1)
        check(
            "Company A's uploaded document has the right name",
            at.session_state["ingested_documents"][0].name == "CompanyA_certificate.pdf",
        )

        # This suite tests reset behavior, not the real OCR/Groq pipeline
        # (see verify_column_resolution_*.py for that) - simulate "Run
        # Mapping" having completed by setting the flag it sets, so the
        # gated results/re-search UI renders and resolution_results exists
        # to inject mock values into below.
        at.session_state["mapping_has_run"] = True
        at.run()
        check("simulated run-completion -> no exception", not at.exception)

        # Mock resolved results: a couple of high-confidence, a couple flagged.
        for cid, conf in [(1, 0.95), (2, 0.88), (3, 0.3), (4, 0.0)]:
            at.session_state["resolution_results"][cid] = replace(
                at.session_state["resolution_results"].get(cid, _BLANK_RESULT),
                pdf_name="CompanyA_certificate.pdf", page_number_or_range=str(cid),
                confidence=conf, match_snippet=f"Company A evidence for column {cid}", success=True,
            )

        # A full search-index session state (the 3.3 contract, populated by hand for this test).
        pages = [
            PageRecord("CompanyA_certificate.pdf", 1, "Company A WHO GMP certificate content here."),
            PageRecord("CompanyA_certificate.pdf", 2, "Company A narcotic license page content."),
        ]
        at.session_state["corpus_index"] = build_corpus_index(pages)
        at.session_state["page_texts"] = {(p.pdf_name, p.page_number): p.text for p in pages}
        from ocr.references import ReferenceIndex
        ref_index = ReferenceIndex()
        ref_index.add_page("CompanyA_certificate.pdf", 1, pages[0].text)
        at.session_state["reference_index"] = ref_index
        at.session_state["ocr_cache"] = {("CompanyA_certificate.pdf", 1): "some cached OCR result object"}

        at.run()
        check("Company A state fully populated, no exception", not at.exception)
        check("corpus_index is populated (non-empty)", len(at.session_state["corpus_index"]) == 2)
        check("ocr_cache is populated", len(at.session_state["ocr_cache"]) == 1)

        # ============================================================
        # Click "Next Company"
        # ============================================================
        at.get_by_key("next_company_button").click()
        at.run()
        check("Next Company click -> no exception", not at.exception)

        # --- immediately after reset: back behind the pre-run gate ---
        check("post-reset: zero results grids rendered", len(list(at.dataframe)) == 0)
        check(
            "post-reset: zero re-search expanders rendered",
            not any("Manual Re-Search" in (e.label or "") for e in at.expander),
        )
        check(
            "post-reset: the pre-run placeholder callout is shown again",
            any("Run Mapping" in str(el.value) for el in at.info),
        )
        check("post-reset: mapping_has_run flag cleared", at.session_state["mapping_has_run"] is False)

        # --- 1. company name reset to empty ---
        check("company name field is empty after reset", at.session_state["company_name"] == "")
        name_widget = at.get_by_key("company_name")
        check("company name WIDGET itself displays empty (not just the underlying key)", name_widget.value == "")

        # --- 2. uploaded file caches, bytes, and the uploader WIDGET cleared ---
        check("ingested_documents is empty after reset", at.session_state["ingested_documents"] == [])
        check("ingest_warnings is empty after reset", at.session_state["ingest_warnings"] == [])
        uploader_key_gen1 = [w.key for w in at.file_uploader][0]
        check("file_uploader's widget key was CYCLED (generation 0 -> 1), not just its value cleared", uploader_key_gen1 == "company_file_uploader_1")
        check("the NEW generation's uploader widget shows no files", at.get_by_key(uploader_key_gen1).value in (None, []))

        # --- 3. resolution_results cleared (every entry functionally blank - see module docstring) ---
        results_after = at.session_state["resolution_results"]
        check(
            "every resolution_results entry is functionally blank after reset (no Company A data survives)",
            all(v == _BLANK_RESULT for v in results_after.values()),
        )
        check(
            "specifically, none of Company A's actual confidences/snippets/pdf names remain anywhere",
            not any(v.pdf_name == "CompanyA_certificate.pdf" or v.confidence in (0.95, 0.88, 0.3) for v in results_after.values()),
        )

        # --- 4. in-memory OCR caches, page texts, corpus_index, reference_index cleared ---
        check("corpus_index reset to None", at.session_state["corpus_index"] is None)
        check("page_texts reset to empty", at.session_state["page_texts"] == {})
        check("reference_index reset to None", at.session_state["reference_index"] is None)
        check("ocr_cache reset to empty", at.session_state["ocr_cache"] == {})

        # --- DB fingerprint byte-identical across the whole cycle ---
        fingerprint_after_reset = db_fingerprint(db_path)
        check(
            "config DB fingerprint is byte-identical: before Company A ever touched it, and after Company A's full reset",
            fingerprint_before_anything == fingerprint_after_reset,
        )

        # ============================================================
        # Company B loads cleanly, zero residual Company A state
        # ============================================================
        at.get_by_key("company_name").set_value("Company B Ltd")
        pdf_bytes_b = b"%PDF-1.4\n%company B fake pdf\n%%EOF"
        at.get_by_key(uploader_key_gen1).upload("CompanyB_license.pdf", pdf_bytes_b, "application/pdf")
        at.run()
        check("Company B: no exception", not at.exception)
        check("Company B's name is set correctly", at.session_state["company_name"] == "Company B Ltd")
        check("Company B's upload is the ONLY document present (no Company A leakage)", len(at.session_state["ingested_documents"]) == 1)
        check(
            "Company B's document is genuinely Company B's, not a stale Company A entry",
            at.session_state["ingested_documents"][0].name == "CompanyB_license.pdf",
        )
        check(
            "no trace of 'CompanyA_certificate.pdf' remains anywhere in ingested_documents",
            not any("CompanyA" in d.name for d in at.session_state["ingested_documents"]),
        )
        check(
            "resolution_results is still clean for Company B (no Company A values reappeared)",
            all(v.pdf_name != "CompanyA_certificate.pdf" for v in at.session_state["resolution_results"].values()),
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
