"""Checklist 3.3 verification — real Groq calls, real seeded schema.

Runs resolve_all_columns() for real (no mocking) against the actual
seeded Table 1 schema and a small synthetic corpus built to contain a
genuine match for exactly one column (WHO-GMP, Item 4) and nothing
relevant to the others - proving the real end-to-end pipeline (BM25
retrieval -> real Groq verification, bounded workers, early-stopping)
resolves the right column correctly and leaves genuinely-unmatched ones
appropriately low-confidence/flagged, not just that the plumbing is
wired (already proven with mocks in verify_column_resolution_unit.py).

Requires a working GROQ_API_KEY in .env.
Run: python tests/verify_column_resolution_live.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def main() -> None:
    from db import crud
    from db.connection import get_connection
    from db.schema import init_db
    from run.pipeline_runner import resolve_all_columns
    from search.bm25_index import PageRecord, build_corpus_index
    from seed.seed_data import TABLE_1_ITEMS
    from verify.groq_verifier import is_flagged

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "live_resolution_test.db")
        conn = get_connection(db_path)
        init_db(conn)

        table = crud.create_table(conn, "Table 1")
        column_ids = {}
        for name, requirement_text in TABLE_1_ITEMS:
            column_ids[name] = crud.create_column(conn, table, name, requirement_text)

        # One genuine, unambiguous match for "Item 4" (WHO-GMP), and one
        # page with clearly unrelated content - nothing else in the
        # corpus for the other 9 columns to find.
        pages = [
            PageRecord(
                "CompanyA.pdf", 5,
                "CERTIFICATE OF WHO-GMP COMPLIANCE\nIssued to: ABC Pharmaceuticals Pvt Ltd\n"
                "Certificate No: WHO-GMP-2023-4521\nDate of Issue: 15 March 2023\n"
                "Valid Until: 14 March 2028\nThis is to certify that the manufacturing facility "
                "has been inspected and found compliant with World Health Organization Good "
                "Manufacturing Practice (WHO-GMP) standards, issued by the State Drug Controller.",
            ),
            PageRecord(
                "CompanyA.pdf", 6,
                "This page discusses general office administrative procedures and internal "
                "meeting schedules, entirely unrelated to any tender compliance requirement.",
            ),
        ]
        corpus_index = build_corpus_index(pages)
        page_texts = {(p.pdf_name, p.page_number): p.text for p in pages}

        print("Running resolve_all_columns() live against 10 real seeded columns...")
        progress_seen = []
        results = resolve_all_columns(
            conn, corpus_index, page_texts, reference_index=None,
            progress_callback=lambda done, total, name: progress_seen.append((done, total, name)),
        )

        check("resolution_results has an entry for all 10 real seeded columns", len(results) == 10)
        check("progress_callback fired 10 times, ending at (10, 10, ...)", len(progress_seen) == 10 and progress_seen[-1][:2] == (10, 10))

        gmp_result = results[column_ids["Item 4"]]
        print(f"Item 4 (WHO-GMP) -> confidence={gmp_result.confidence}, pdf={gmp_result.pdf_name}, page={gmp_result.page_number_or_range}")
        check("the genuinely matching column (Item 4, WHO-GMP) resolved with high confidence (>= 0.70)", gmp_result.confidence >= 0.70)
        check("...to the correct page", gmp_result.pdf_name == "CompanyA.pdf" and gmp_result.page_number_or_range == "5")
        check("...with a real, non-empty snippet", bool(gmp_result.match_snippet))
        check("...and is NOT flagged (checklist 4.2 integration)", not is_flagged(gmp_result))

        unrelated_name = "Item 1"  # "Item no. as per tender" - nothing in this corpus satisfies it
        unrelated_result = results[column_ids[unrelated_name]]
        print(f"{unrelated_name} -> confidence={unrelated_result.confidence}")
        check(
            f"a genuinely unmatched column ({unrelated_name}) resolves low-confidence and IS flagged",
            unrelated_result.confidence < 0.70 and is_flagged(unrelated_result),
        )

        conn.close()

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
