"""Checklist 3.2 verification — one real Groq call (no mocking), rewritten
for the batched single-call-per-column design (Groq rate-limit fix).

Confirms the batched JSON schema actually parses from a genuine model
response (not just from hand-crafted mock JSON) and that the batched
verification prompt does what it's for: discriminating a genuine
compliance match from a page that only mentions the requirement's
subject in passing, WHEN BOTH ARE SENT IN THE SAME SINGLE CALL - on real
page content built from the actual seed schema's WHO-GMP requirement
text (seed/seed_data.py Item 4).

Requires a working GROQ_API_KEY in .env. Run: python tests/verify_groq_verifier_live.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from search.bm25_index import SearchCandidate  # noqa: E402
from seed.seed_data import TABLE_1_ITEMS  # noqa: E402
from verify.groq_verifier import verify_candidates_batch  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def main() -> None:
    column_name, requirement_text = TABLE_1_ITEMS[3]  # "Item 4", the real WHO-GMP requirement

    genuine_page = (
        "CERTIFICATE OF WHO-GMP COMPLIANCE\n"
        "Issued to: ABC Pharmaceuticals Pvt Ltd\n"
        "Certificate No: WHO-GMP-2023-4521\n"
        "Date of Issue: 15 March 2023\n"
        "Valid Until: 14 March 2028\n"
        "This is to certify that the manufacturing facility located at Plot 45, "
        "Industrial Area, has been inspected and found compliant with World Health "
        "Organization Good Manufacturing Practice (WHO-GMP) standards, issued by the "
        "State Drug Controller."
    )
    irrelevant_page = (
        "This tender document mentions that WHO GMP certification may be required "
        "for some categories of bidders. Please refer to Annexure B for details on "
        "general eligibility criteria and submission timelines."
    )

    candidate_genuine = SearchCandidate(
        pdf_name="CompanyA.pdf", page_number=5, rank=1, score=3.2,
        snippet="WHO GMP certificate excerpt", matched_terms=["who", "gmp"], match_signals=["bm25"],
    )
    candidate_irrelevant = SearchCandidate(
        pdf_name="CompanyA.pdf", page_number=9, rank=2, score=1.1,
        snippet="passing mention of WHO GMP", matched_terms=["who", "gmp"], match_signals=["bm25"],
    )

    page_texts = {
        ("CompanyA.pdf", 5): genuine_page,
        ("CompanyA.pdf", 9): irrelevant_page,
    }

    print("Calling Groq live: ONE batched call with both the genuine match and the passing-mention false positive...")
    result = verify_candidates_batch(column_name, requirement_text, [candidate_genuine, candidate_irrelevant], page_texts)

    check("live batched call succeeds (JSON schema parses)", result.success is True)
    check(f"the genuine candidate is correctly picked as the winner (got page {result.page_number_or_range})", result.page_number_or_range == "5")
    check(f"the winning result scores high confidence (got {result.confidence})", result.confidence >= 0.7)
    check("the winning result's snippet/reasoning are non-empty", bool(result.match_snippet) and bool(result.reasoning))
    check(
        "the winning result's pdf_name/page are exactly the genuine candidate's, not re-derived from the model",
        result.pdf_name == "CompanyA.pdf" and result.page_number_or_range == "5",
    )
    print(f"  confidence={result.confidence}  reasoning={result.reasoning}")

    print("\nCalling Groq live: ONE batched call with ONLY the passing-mention false positive...")
    fp_only_result = verify_candidates_batch(column_name, requirement_text, [candidate_irrelevant], {("CompanyA.pdf", 9): irrelevant_page})
    check("live batched call (single false-positive candidate) succeeds (JSON schema parses)", fp_only_result.success is True)
    check(f"a passing-mention-only pool scores low confidence (got {fp_only_result.confidence})", fp_only_result.confidence <= 0.4)
    print(f"  confidence={fp_only_result.confidence}  reasoning={fp_only_result.reasoning}")

    check(
        "the prompt discriminates correctly even within one batched call: genuine match clearly outscores the passing-mention-only pool",
        result.confidence > fp_only_result.confidence,
    )

    if all(ok for _, ok in checks):
        print(f"\nALL CHECKS PASSED ({len(checks)}/{len(checks)})")
        sys.exit(0)
    else:
        failed = [label for label, ok in checks if not ok]
        print(f"\nFAILED {len(failed)}/{len(checks)}:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
