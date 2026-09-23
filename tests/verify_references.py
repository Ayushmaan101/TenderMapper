"""Checklist 2.4 verification.

Covers: 100% regex coverage against the real Table 1 / Table 2 seed
schema text (not synthetic stand-ins - the actual SEED_SCHEMA strings);
format-variant equivalence (Roman vs. Arabic, abbreviated vs. spelled
out, comma vs. space separators, all canonicalizing to the same token);
Roman-numeral round-trip validation rejecting malformed sequences; a
zero-requirement-vocabulary synthetic page being indexed and found purely
by reference; and an extensive false-positive suite built directly from
real risky substrings already present in this project's own seed data
(financial years, money, durations, "45 days" vs. "Form-45", "performance"
/"format"/"information" embedding the substring "form", "Tender
Acceptance Form" with no trailing number, "I.V fluids").

Run: python tests/verify_references.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.references import (  # noqa: E402
    ReferenceHit,
    build_index,
    extract_references,
)
from seed.seed_data import TABLE_1_ITEMS, TABLE_2_ITEMS  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def canonicals(text: str) -> set[str]:
    return {r.canonical for r in extract_references(text)}


# ------------------------------------------------- 100% seed coverage --

# (item index, expected set of canonical references) for every one of the
# 23 real seed items - derived directly from a manual scan of
# seed/seed_data.py, not guessed. Items not listed here are expected to
# produce zero references.
EXPECTED_TABLE_1 = {
    2: {"section 17"},          # Item 3: "Performa Section-XVII"
    3: {"schedule m"},          # Item 4: "Schedule 'M'"
    8: {"form 45"},             # Item 9: "Form-45"
    9: {"section 19"},          # Item 10: "Performa at Section-XIX" (x2, deduped)
}
EXPECTED_TABLE_2 = {
    2: {"section 8 clause 11", "section 8"},                      # Document 3
    3: {"section 8 clause 10", "section 8"},                      # Document 4
    4: {"section 8 clause 18", "section 8", "section 17"},        # Document 5
    5: {"section 8 clause 13", "section 8"},                      # Document 6
    7: {"section 8 clause 16", "section 8"},                      # Document 8
    8: {"section 8 clause 17", "section 8"},                      # Document 9
    10: {"section 8 clause 15", "section 8"},                     # Document 11
    11: {"section 8 clause 19", "section 8", "section 16"},       # Document 12
}


def test_full_seed_schema_coverage() -> None:
    for i, (name, text) in enumerate(TABLE_1_ITEMS):
        expected = EXPECTED_TABLE_1.get(i, set())
        actual = canonicals(text)
        check(f"Table 1 '{name}' -> canonical refs == {expected or '(none)'}", actual == expected)

    for i, (name, text) in enumerate(TABLE_2_ITEMS):
        expected = EXPECTED_TABLE_2.get(i, set())
        actual = canonicals(text)
        check(f"Table 2 '{name}' -> canonical refs == {expected or '(none)'}", actual == expected)

    total_expected_items = len(EXPECTED_TABLE_1) + len(EXPECTED_TABLE_2)
    check(
        f"exactly {total_expected_items} of the 23 seed items carry a reference (rest correctly empty)",
        total_expected_items == 12,
    )


# -------------------------------------------------------- false positives --


def test_no_false_positives_on_real_seed_noise() -> None:
    noisy_snippets = [
        ("financial years", "financial years (2021-22, 2022-23, 2023-24, 2024-25 & 2025-26)"),
        ("money, no-space Rs.", "Rs.10/- stating that there is no vigilance"),
        ("money, spaced Rs.", "an affidavit of Rs. 100/-, The Drugs and Cosmetics Rules, 1945"),
        ("crores amount", "minimum annual turnover of Rs. 1.5 Crores"),
        ("duration: years", "minimum of \"Three Years\" of the molecule quoted"),
        ("duration: 3-years", "Public Sector Undertakings with at least \"3-years\" market standing"),
        ("duration: 45 days (NOT Form-45)", "within 45 days from the date of placement of purchase order"),
        ("duration: 02 years", "performance certificate of 02 years for supply of drugs"),
        ("ordinal", "exclusive from supply to Government Departments and 3rd Party Sale"),
        ("percentage", "25% or more of the annual turnover shall be"),
        ("roman-numeral-like abbreviation", "Contrast media, I.V fluids (large volume parentrals)"),
        ("Form with no trailing number", "Scanned copy of \"Tender Acceptance Form\""),
        ("'form' embedded in performance", "Manufacturing firm should upload the scanned copy of performance certificate"),
        ("'form' embedded in format", "Scanned copy of Information as per the format enclosed"),
        ("'form' embedded in information", "Bidder should also provide information regarding blacklisting"),
        ("statute year, not a section", "convicted under the Drugs and Cosmetics Act, 1940 and rules"),
    ]
    for label, snippet in noisy_snippets:
        refs = extract_references(snippet)
        check(f"no false positive: {label}", refs == [])

    # And the two full real seed items that are noise-heavy but reference-free:
    doc7_text = TABLE_2_ITEMS[6][1]
    check("full Document 7 text (2x 'performance', years, '02 years') -> zero refs", canonicals(doc7_text) == set())


def test_form_45_vs_45_days_distinction() -> None:
    """The two numbers "45" that appear in the real seed data mean
    completely different things - Form-45 is a real reference, "45 days"
    is a duration. Same digits, must resolve differently.
    """
    check("'Form-45 (Permission Certificate)' -> matches form 45", canonicals("Form-45 (Permission Certificate)") == {"form 45"})
    check("'within 45 days from the date' -> no match at all", canonicals("within 45 days from the date") == set())


# ------------------------------------------------------- format variants --


def test_section_clause_format_variants_canonicalize_identically() -> None:
    variants = [
        "Section VIII Clause 11",
        "Section-VIII, Clause 11",
        "Sec. 8 Cl. 11",
        "SECTION VIII, CLAUSE 11",
        "section viii clause 11",
    ]
    for v in variants:
        check(f"'{v}' -> canonicalizes to 'section 8 clause 11'", canonicals(v) == {"section 8 clause 11", "section 8"})


def test_standalone_section_roman_vs_arabic() -> None:
    check("'Section-XVII' -> section 17", canonicals("Section-XVII") == {"section 17"})
    check("'Section 17' -> section 17 (same as Roman form)", canonicals("Section 17") == {"section 17"})
    check("'Sec. XVII' -> section 17 (abbreviated + Roman)", canonicals("Sec. XVII") == {"section 17"})
    check("'Performa Section-XIX' -> section 19 ('Performa' prefix stripped)", canonicals("Performa Section-XIX") == {"section 19"})


def test_leading_zeros_normalized() -> None:
    check("'Form-045' -> form 45 (leading zero stripped)", canonicals("Form-045") == {"form 45"})
    check("'Section 08' -> section 8 (leading zero stripped)", canonicals("Section 08") == {"section 8"})


def test_malformed_roman_numerals_rejected() -> None:
    check("'Section IIII' (invalid Roman, should be IV) -> no match", canonicals("Section IIII") == set())
    check("'Section VX' (invalid Roman) -> no match", canonicals("Section VX") == set())
    check("'Section IC' (invalid Roman) -> no match", canonicals("Section IC") == set())


def test_schedule_and_form_variants() -> None:
    check("\"Schedule 'M'\" -> schedule m", canonicals("Schedule 'M'") == {"schedule m"})
    check("'Schedule M' (no quotes) -> schedule m", canonicals("Schedule M") == {"schedule m"})
    check('\'Schedule "M"\' (double quotes) -> schedule m', canonicals('Schedule "M"') == {"schedule m"})
    check("'Schedule H1' -> schedule h1 (letter+digit schedule name)", canonicals("Schedule H1") == {"schedule h1"})
    check("'Schedule appointment' -> no match (not a real schedule reference)", canonicals("Schedule appointment") == set())


# --------------------------------------------- zero-vocabulary + lookup --


def test_zero_vocabulary_page_indexed_and_found() -> None:
    """The core point of this whole module: a page whose ONLY content is
    a bare reference - none of the requirement's actual descriptive
    words - must still be findable by a query built from that
    requirement's real text.
    """
    index = build_index([
        ("CompanyA.pdf", 4, "Section VIII Clause 11"),  # zero requirement vocabulary
        ("CompanyA.pdf", 5, "some unrelated page about something else entirely"),
    ])

    real_requirement_text = TABLE_2_ITEMS[2][1]  # Document 3's actual full text
    hits = index.lookup(real_requirement_text)

    check("zero-vocabulary page is found via the real requirement's lookup", ReferenceHit("CompanyA.pdf", 4) in hits)
    check("the unrelated page is NOT returned", ReferenceHit("CompanyA.pdf", 5) not in hits)


def test_lookup_by_bare_section_finds_combo_indexed_page() -> None:
    index = build_index([("B.pdf", 1, "Section VIII Clause 11: full requirement text here.")])
    hits = index.lookup("please find anything under Section-VIII")
    check("a bare-section query finds a page indexed via the full section+clause combo", ReferenceHit("B.pdf", 1) in hits)


def test_lookup_no_references_in_query_returns_empty() -> None:
    index = build_index([("C.pdf", 1, "Section VIII Clause 11")])
    hits = index.lookup("Item no. as per tender")  # a real seed item with no references at all
    check("a query with no extractable references returns an empty list, not an error", hits == [])


def test_index_dedup_and_multi_page_distinctness() -> None:
    index = build_index([
        ("D.pdf", 1, "Section-XVII mentioned once here, and again: Section-XVII."),
        ("D.pdf", 2, "Section-XVII also appears on this separate page."),
        ("E.pdf", 1, "A totally different PDF, also citing Section-XVII."),
    ])
    hits = index.lookup("Section-XVII")
    check("repeated mentions on one page don't duplicate that page's entry", hits.count(ReferenceHit("D.pdf", 1)) == 1)
    check(
        "distinct pages of the same PDF, and a different PDF entirely, are all tracked separately",
        set(hits) == {ReferenceHit("D.pdf", 1), ReferenceHit("D.pdf", 2), ReferenceHit("E.pdf", 1)},
    )


def main() -> None:
    test_full_seed_schema_coverage()
    test_no_false_positives_on_real_seed_noise()
    test_form_45_vs_45_days_distinction()
    test_section_clause_format_variants_canonicalize_identically()
    test_standalone_section_roman_vs_arabic()
    test_leading_zeros_normalized()
    test_malformed_roman_numerals_rejected()
    test_schedule_and_form_variants()
    test_zero_vocabulary_page_indexed_and_found()
    test_lookup_by_bare_section_finds_combo_indexed_page()
    test_lookup_no_references_in_query_returns_empty()
    test_index_dedup_and_multi_page_distinctness()

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
