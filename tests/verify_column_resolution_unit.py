"""Checklist 3.3 verification — unit-level (mocked Groq, no AppTest).

Covers resolve_all_columns() against a real temp DB + a real
search.bm25_index.CorpusIndex built from a small synthetic multi-page
corpus with KNOWN matches for some columns and none for others:

  - resolution_results auto-populates for EVERY configured column,
    across multiple tables, never silently missing one
  - a column whose requirement text directly matches a page resolves
    with a high (mocked-Groq) confidence, a clean snippet, and the
    REAL candidate's pdf_name/page (never the model's echo)
  - a column findable ONLY via its stored synonym (zero literal overlap
    with the page otherwise) still resolves correctly - proves synonyms
    are actually wired into the query, not just accepted as a parameter
  - a column with no relevant content anywhere in the corpus resolves to
    a low/zero-confidence result, which checklist 4.2's is_flagged()
    correctly flags
  - a genuinely empty corpus_index (zero pages) -> every column still
    gets an entry (the documented "unresolved" placeholder), with ZERO
    Groq calls made at all (nothing to verify against)
  - progress_callback fires exactly once per column, in strict
    increasing order, naming each column correctly

Run: python tests/verify_column_resolution_unit.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def install_fake_groq(call_log: list, column_to_marker: dict[str, str] | None = None, low_confidence: float = 0.1, high_confidence: float = 0.92):
    """A content-aware fake: inspects BOTH which column is being
    evaluated ("Requirement column: {name}", present verbatim in the
    prompt) AND the candidate page text actually sent, returning
    high_confidence only when that SPECIFIC column's own marker phrase
    is present in that page's text - low_confidence otherwise.

    Scoping matters: a flat "does any known-good phrase appear anywhere"
    check (this test's first draft) let a page relevant to one column
    get wrongly counted as a strong match for a DIFFERENT column's query
    too, since a small corpus puts every page in every column's
    candidate pool. With confidence tied only to page content, multiple
    candidates could spuriously score high for the same column, and
    early-stopping would then pick whichever one's thread happened to
    finish first - not necessarily the genuinely correct page. Tying the
    match to (column, marker) pairs is what makes this a real,
    per-column-discriminating simulation rather than a uniform
    rubber-stamp.
    """
    import verify.groq_verifier as gv

    column_to_marker = column_to_marker or {}

    class _Completions:
        def create(self, **kwargs):
            call_log.append(kwargs)
            user_content = kwargs["messages"][1]["content"]
            # The marker must appear in the PAGE TEXT specifically, not
            # merely anywhere in the prompt - the "Requirement text:"
            # section can itself legitimately contain the same words
            # (e.g. a "WHO GMP" column's own requirement text mentions
            # "WHO GMP certificate"), which would otherwise make every
            # candidate for that column match regardless of which page
            # it actually is. This was this test's own real bug: without
            # scoping to the page-text section, ALL candidates for a
            # column scored equally high, and early-stopping then just
            # returned whichever one's thread happened to finish first -
            # non-deterministic, caught by re-running the test 3 times.
            page_text_section = user_content.split("Page text:\n", 1)[-1]
            confidence = low_confidence
            for col_name, marker in column_to_marker.items():
                if f"Requirement column: {col_name}" in user_content and marker in page_text_section:
                    confidence = high_confidence
                    break
            content = json.dumps({
                "pdf_name": "MODEL-ECHO-IGNORED.pdf", "page_number_or_range": "999",
                "confidence": confidence, "match_snippet": "matched evidence text", "reasoning": "evaluated",
            })
            message = type("M", (), {"content": content})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice]})()

    class _Client:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    gv.Groq = _Client


def main() -> None:
    os.environ["GROQ_API_KEY"] = "fake-key-for-unit-tests"

    from db import crud
    from db.connection import get_connection
    from db.schema import init_db
    from run.pipeline_runner import resolve_all_columns
    from search.bm25_index import PageRecord, build_corpus_index
    from verify.groq_verifier import is_flagged

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "resolution_test.db")
        conn = get_connection(db_path)
        init_db(conn)

        table1 = crud.create_table(conn, "Table 1")
        col_direct_match = crud.create_column(conn, table1, "WHO GMP", "WHO GMP certificate requirement text")
        col_synonym_only = crud.create_column(conn, table1, "Narcotic License", "valid narcotic license from the excise commissioner")
        crud.add_synonym(conn, col_synonym_only, "Schedule N permit")
        col_no_match = crud.create_column(conn, table1, "Irrelevant", "completely unrelated requirement about office furniture procurement")

        table2 = crud.create_table(conn, "Table 2")
        col_table2 = crud.create_column(conn, table2, "GST", "GST registration certificate for the bidder")

        pages = [
            PageRecord("CompanyA.pdf", 1, "This is the WHO GMP certificate, valid and duly issued by the authority."),
            PageRecord("CompanyA.pdf", 2, "Schedule N permit document filed for the manufacturer, approved and current."),
            PageRecord("CompanyA.pdf", 3, "GST registration certificate number 27AAA, filed with the tax department."),
            PageRecord("CompanyA.pdf", 4, "A completely unrelated page about quarterly office furniture procurement plans."),
        ]
        corpus_index = build_corpus_index(pages)
        page_texts = {(p.pdf_name, p.page_number): p.text for p in pages}

        # --- one content-aware mock for the whole run: each of the 3
        # genuinely relevant pages carries its own distinguishing marker
        # phrase and gets high confidence; the "Irrelevant" column's
        # candidates (whatever BM25 surfaces for it - none of them
        # containing any of these 3 phrases) correctly get low
        # confidence, exactly like a real verifier rejecting a weak
        # match rather than rubber-stamping it ---
        call_log: list = []
        install_fake_groq(
            call_log,
            column_to_marker={
                "WHO GMP": "WHO GMP certificate",
                "Narcotic License": "Schedule N permit",
                "GST": "GST registration certificate",
            },
        )

        progress_calls: list = []
        results = resolve_all_columns(
            conn, corpus_index, page_texts, reference_index=None,
            progress_callback=lambda done, total, name: progress_calls.append((done, total, name)),
        )

        check("resolution_results auto-populates for EVERY configured column (4 total, across 2 tables)", len(results) == 4)
        check("every configured column id is present, none missing", set(results.keys()) == {col_direct_match, col_synonym_only, col_no_match, col_table2})

        direct = results[col_direct_match]
        check("direct-match column -> high confidence (>= 0.70)", direct.confidence >= 0.70)
        check("direct-match column -> success=True", direct.success is True)
        check("direct-match column -> pdf_name/page are the REAL candidate's, not the model's echoed 'MODEL-ECHO-IGNORED.pdf'", direct.pdf_name == "CompanyA.pdf" and direct.page_number_or_range == "1")
        check("direct-match column -> a clean, non-empty match_snippet", bool(direct.match_snippet))
        check("direct-match column's result is NOT flagged by checklist 4.2's is_flagged() (integration check)", not is_flagged(direct))

        synonym_result = results[col_synonym_only]
        check(
            "synonym-only-findable column -> resolves to the RIGHT page with high confidence (proves synonyms are wired into the query, not just accepted as a no-op parameter)",
            synonym_result.confidence >= 0.70 and synonym_result.pdf_name == "CompanyA.pdf" and synonym_result.page_number_or_range == "2",
        )

        table2_result = results[col_table2]
        check("a column in a SECOND table resolves correctly too (not just table 1)", table2_result.confidence >= 0.70 and table2_result.page_number_or_range == "3")

        irrelevant_result = results[col_no_match]
        check("irrelevant column (no marker phrase in any of its candidates) -> low confidence (< 0.70)", irrelevant_result.confidence < 0.70)
        check("irrelevant column's low-confidence result IS flagged by checklist 4.2's is_flagged()", is_flagged(irrelevant_result))

        check("progress_callback fired exactly once per column (4 total)", len(progress_calls) == 4)
        check("progress_callback reports strictly increasing (done, total) pairs", [c[:2] for c in progress_calls] == [(1, 4), (2, 4), (3, 4), (4, 4)])
        check("progress_callback names are among the configured column names", {c[2] for c in progress_calls} == {"WHO GMP", "Narcotic License", "Irrelevant", "GST"})

        conn.close()

    # --- empty corpus: every column still gets an entry, zero Groq calls ---
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp2:
        db_path2 = str(Path(tmp2) / "empty_corpus_test.db")
        conn2 = get_connection(db_path2)
        init_db(conn2)
        t = crud.create_table(conn2, "T")
        c1 = crud.create_column(conn2, t, "Col1", "some requirement")
        c2 = crud.create_column(conn2, t, "Col2", "another requirement")

        empty_corpus = build_corpus_index([])
        call_log3: list = []
        install_fake_groq(call_log3)
        results3 = resolve_all_columns(conn2, empty_corpus, {}, reference_index=None)

        check("empty corpus -> every column still gets an entry (2 of 2)", len(results3) == 2)
        check("empty corpus -> both entries are the unresolved placeholder (success=False)", all(not r.success for r in results3.values()))
        check("empty corpus -> ZERO Groq calls made (nothing to verify against)", len(call_log3) == 0)
        conn2.close()

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
