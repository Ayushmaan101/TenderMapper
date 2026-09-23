"""Checklist 3.1 verification.

Covers, against synthetic multi-page/multi-PDF corpora: exact matches
ranking top; a synonym-only page (zero overlap with the requirement's
own wording) still ranking top because of the synonym; OCR-noise
fuzzy-expansion matches (the checklist's own wh0-gmp / cert1ficate
examples) being captured, with the length-scaled edit-distance design
proven directly against the classic short-acronym false-positive risk
(gst vs. gmp); a reference-only page (checklist 2.4) bubbling into the
pool despite a near-zero BM25 score; and the 15-20 candidate pool
holding across corpus sizes both smaller and larger than the cap.

Run: python tests/verify_bm25_search.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.references import ReferenceIndex  # noqa: E402
from search.bm25_index import (  # noqa: E402
    DEFAULT_POOL_SIZE,
    PageRecord,
    _fuzzy_expand_tokens,
    build_corpus_index,
    search,
)
from search.tokenize import STOPWORDS, tokenize  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


# ------------------------------------------------------------- tokenizer --


def test_tokenizer_keeps_domain_keywords() -> None:
    check("'who' is NOT filtered as a stopword (WHO-GMP is domain-critical)", "who" not in STOPWORDS)
    tokens = tokenize("WHO-GMP certificate issued by the State Drug Controller")
    check("tokenize('WHO-GMP ...') keeps 'who' as its own token", "who" in tokens)
    check("tokenize splits the hyphenated compound into both halves", "who" in tokens and "gmp" in tokens)
    check("common stopwords ('the', 'by') are filtered", "the" not in tokens and "by" not in tokens)
    check("tokenize('') -> []", tokenize("") == [])
    check("tokenize(None) -> [] (never raises)", tokenize(None) == [])


# ---------------------------------------------------------------- fixture --

CORPUS = [
    PageRecord("CompanyA.pdf", 1, "This is the WHO GMP certificate for manufacturing, valid and duly approved by the authority."),
    PageRecord("CompanyA.pdf", 2, "This page discusses GST registration and tax filing matters entirely unrelated to certificates."),
    PageRecord("CompanyA.pdf", 3, "wh0 gmp cert1ficate scan n0isy OCR text with character substitutions present throughout"),
    PageRecord("CompanyA.pdf", 4, "Section VIII Clause 11"),
    PageRecord("CompanyA.pdf", 5, "Schedule M approval document filed for the manufacturer license renewal process"),
    PageRecord("CompanyB.pdf", 1, "Narcotic license issued by the Central Excise Commissioner for the bidder firm"),
    PageRecord("CompanyB.pdf", 2, "A completely irrelevant page about office furniture procurement and delivery schedules"),
]


def build_index_and_refs():
    index = build_corpus_index(CORPUS)
    ref_index = ReferenceIndex()
    for p in CORPUS:
        ref_index.add_page(p.pdf_name, p.page_number, p.text)
    return index, ref_index


# --------------------------------------------------------------- exact --


def test_exact_match_ranks_top() -> None:
    index, refs = build_index_and_refs()
    results = search(index, "WHO GMP certificate manufacturing", reference_index=refs)
    check("exact-wording query -> top result is the clean WHO GMP page", results[0].pdf_name == "CompanyA.pdf" and results[0].page_number == 1)
    check("exact match has a strictly positive BM25 score", results[0].score > 0)
    check("exact match carries the 'bm25' signal", "bm25" in results[0].match_signals)
    check("results are sorted by score, strictly descending among bm25-scored pages", all(results[i].score >= results[i + 1].score for i in range(len(results) - 1)))


# ------------------------------------------------------------- synonym --


def test_synonym_only_match_ranks_top() -> None:
    """The target page shares ZERO tokens with the requirement's own
    wording - it is only findable through the stored synonym.
    """
    requirement = "valid manufacturing authorization paperwork required for the bidder"
    target_tokens = set(tokenize(requirement))
    page5_tokens = set(tokenize(CORPUS[4].text))  # "Schedule M approval document..."
    check(
        "sanity: the requirement and the target page share zero tokens before adding the synonym",
        target_tokens & page5_tokens == set(),
    )

    index, refs = build_index_and_refs()

    without_synonym = search(index, requirement, synonyms=[], reference_index=refs)
    page5_rank_without = next((r.rank for r in without_synonym if r.pdf_name == "CompanyA.pdf" and r.page_number == 5), None)

    with_synonym = search(index, requirement, synonyms=["Schedule M"], reference_index=refs)
    page5_result = next(r for r in with_synonym if r.pdf_name == "CompanyA.pdf" and r.page_number == 5)

    check("without the synonym, the target page scores zero (unreachable by wording alone)", page5_rank_without is None or index.get_scores(tokenize(requirement))[4] == 0)
    check("WITH the synonym, the target page is found and scores > 0", page5_result.score > 0)
    check("WITH the synonym, the target page ranks #1 (nothing else in the corpus mentions 'schedule m')", page5_result.rank == 1)
    check("the synonym term itself shows up in matched_terms", "schedule" in page5_result.matched_terms or "m" in " ".join(page5_result.matched_terms))


# --------------------------------------------------------- fuzzy / OCR --


def test_ocr_noise_variants_captured_via_fuzzy_expansion() -> None:
    index, refs = build_index_and_refs()
    results = search(index, "WHO GMP certificate", reference_index=refs)

    noisy = next((r for r in results if r.pdf_name == "CompanyA.pdf" and r.page_number == 3), None)
    check("the OCR-noisy page (wh0/cert1ficate) is present in the result set at all", noisy is not None)
    if noisy:
        check("noisy page score > 0 (fuzzy-expanded tokens actually scored)", noisy.score > 0)
        check("'wh0' appears in matched_terms (fuzzy match for 'who')", "wh0" in noisy.matched_terms)
        check("'cert1ficate' appears in matched_terms (fuzzy match for 'certificate')", "cert1ficate" in noisy.matched_terms)
        clean = next(r for r in results if r.pdf_name == "CompanyA.pdf" and r.page_number == 1)
        check("the clean exact-wording page still outranks the noisy fuzzy-matched one", clean.rank < noisy.rank)


def test_fuzzy_expansion_does_not_cross_match_unrelated_short_acronyms() -> None:
    """The false-positive risk a naive percentage-ratio cutoff misses:
    'gst' and 'gmp' are only edit-distance 2 apart but mean completely
    different things. The length-scaled budget (distance<=1 for tokens
    under 5 chars) must keep them apart.
    """
    expanded = _fuzzy_expand_tokens(["gst"], {"gmp", "gst", "certificate"})
    check("fuzzy expansion of 'gst' does NOT pull in the unrelated 'gmp'", "gmp" not in expanded)

    index, refs = build_index_and_refs()
    results = search(index, "GST registration", reference_index=refs)
    gmp_page = next((r for r in results if r.pdf_name == "CompanyA.pdf" and r.page_number == 1), None)
    check(
        "a GST query does not spuriously score the unrelated WHO-GMP page via fuzzy cross-match",
        gmp_page is None or gmp_page.score == 0,
    )


# ----------------------------------------------------------- reference --


def test_reference_only_page_bubbles_into_pool() -> None:
    """CompanyA.pdf page 4's entire content is 'Section VIII Clause 11' -
    zero requirement vocabulary. A requirement whose own text cites that
    same section/clause must still surface it, via the reference index.
    (Its raw BM25 score need not be exactly zero here - the requirement
    text itself starts with the same section/clause words, matching how
    the real seed schema is written, so some incidental word overlap is
    realistic. See test_reference_merge_is_not_just_small_corpus_luck
    below for the case where the reference index is the ONLY reason the
    page is included at all.)
    """
    requirement = "Section VIII Clause 11: submission of annual turnover documents audited by a Chartered Accountant"
    index, refs = build_index_and_refs()

    results_with_refs = search(index, requirement, reference_index=refs)
    ref_page = next((r for r in results_with_refs if r.pdf_name == "CompanyA.pdf" and r.page_number == 4), None)
    check("reference-only page is present in the pool when reference_index is supplied", ref_page is not None)
    if ref_page:
        check("its match_signals include 'reference'", "reference" in ref_page.match_signals)


def test_reference_merge_is_not_just_small_corpus_luck() -> None:
    """Isolates the reference merge's actual effect from (a) the
    separately-tested "small corpus returns everything" behavior and
    (b) BM25 rewarding a literal word-for-word match on rare terms so
    strongly that a bare reference phrase can rank #1 on wording alone
    even without any merge - not something the merge should get credit
    for, and something a query that repeats the page's exact wording
    ("Section VIII Clause 11...") can't avoid triggering.

    Fix: the query cites the SAME reference in a DIFFERENT surface form
    ("Sec. 8 Cl. 11") than the page ("Section VIII Clause 11"). The two
    canonicalize identically (checklist 2.4's Roman/abbreviation
    normalization - proven separately in tests/verify_references.py),
    so the reference index still finds the page; but at the raw-token
    BM25 level the query and page now share almost nothing, so the page
    scores low on wording alone and decoys with real substantive overlap
    naturally outrank it - a clean, realistic separation of the two
    signals instead of hand-fighting BM25's IDF math.
    """
    requirement = "Sec. 8 Cl. 11: submission of annual turnover documents audited by a Chartered Accountant"

    decoys = [
        PageRecord(
            "Decoy.pdf", i,
            f"Annual turnover documents audited by a Chartered Accountant, submission record {i} filed.",
        )
        for i in range(1, 21)
    ]
    ref_only_page = PageRecord("RefOnly.pdf", 1, "Section VIII Clause 11")
    corpus = decoys + [ref_only_page]

    index = build_corpus_index(corpus)
    refs = ReferenceIndex()
    for p in corpus:
        refs.add_page(p.pdf_name, p.page_number, p.text)

    # Uncapped query -> discover RefOnly's real natural rank empirically,
    # rather than assuming it.
    full_ranking = search(index, requirement, reference_index=None, pool_size=len(corpus))
    ref_only_rank = next(r.rank for r in full_ranking if r.pdf_name == "RefOnly.pdf")
    check("sanity: the reference-only page does not naturally rank first in this corpus", ref_only_rank > 1)

    cutoff = ref_only_rank - 1  # exactly excludes it on raw BM25 alone, by construction

    without_refs = search(index, requirement, reference_index=None, pool_size=cutoff)
    check(
        f"pool_size set exactly below the reference-only page's natural rank ({ref_only_rank}) "
        f"-> it is excluded on BM25 alone",
        not any(r.pdf_name == "RefOnly.pdf" for r in without_refs),
    )
    check("...and the pool is still exactly that size", len(without_refs) == cutoff)

    with_refs = search(index, requirement, reference_index=refs, pool_size=cutoff)
    ref_hit = next((r for r in with_refs if r.pdf_name == "RefOnly.pdf"), None)
    check(
        "same cutoff, WITH the reference index -> found despite the query using a "
        "different surface form ('Sec. 8 Cl. 11' vs. the page's 'Section VIII Clause 11')",
        ref_hit is not None,
    )
    check("...pool size still respects that same cap (a decoy was displaced to make room)", len(with_refs) == cutoff)


# --------------------------------------------------------------- pool --


def test_pool_size_small_corpus_returns_everything() -> None:
    index, refs = build_index_and_refs()  # 7 pages total, well under the default pool size
    results = search(index, "certificate license section", reference_index=refs, pool_size=DEFAULT_POOL_SIZE)
    check(
        f"corpus of {len(CORPUS)} pages (< pool_size={DEFAULT_POOL_SIZE}) returns ALL of them",
        len(results) == len(CORPUS),
    )
    check("ranks are a contiguous 1..N sequence with no gaps", [r.rank for r in results] == list(range(1, len(CORPUS) + 1)))


def test_pool_size_large_corpus_caps_at_limit() -> None:
    filler = [
        PageRecord("Big.pdf", i, f"generic filler certificate page number {i} with some certificate wording repeated")
        for i in range(1, 31)
    ]
    index = build_corpus_index(filler)
    results = search(index, "certificate wording", pool_size=DEFAULT_POOL_SIZE)
    check(
        f"corpus of {len(filler)} pages (> pool_size={DEFAULT_POOL_SIZE}) returns exactly {DEFAULT_POOL_SIZE}",
        len(results) == DEFAULT_POOL_SIZE,
    )

    results_custom = search(index, "certificate wording", pool_size=15)
    check("a custom pool_size=15 is honored exactly", len(results_custom) == 15)


def test_reference_hits_dont_blow_past_pool_size() -> None:
    """Even if reference hits alone would exceed pool_size, the final
    pool still respects the cap.
    """
    many_ref_pages = [
        PageRecord("Refs.pdf", i, "Section VIII Clause 11") for i in range(1, 26)
    ]  # 25 pages, all pure reference hits, no other content
    index = build_corpus_index(many_ref_pages)
    refs = ReferenceIndex()
    for p in many_ref_pages:
        refs.add_page(p.pdf_name, p.page_number, p.text)

    results = search(index, "Section VIII Clause 11: irrelevant requirement wording", reference_index=refs, pool_size=DEFAULT_POOL_SIZE)
    check(
        f"25 reference-hit pages still cap the returned pool at pool_size={DEFAULT_POOL_SIZE}",
        len(results) == DEFAULT_POOL_SIZE,
    )
    check("every returned candidate carries the 'reference' signal in this all-reference corpus", all("reference" in r.match_signals for r in results))


# ------------------------------------------------------------- robustness --


def test_empty_corpus_and_all_empty_pages_do_not_crash() -> None:
    empty_index = build_corpus_index([])
    check("search() against an empty corpus returns [] without raising", search(empty_index, "anything at all") == [])

    blank_pages = [PageRecord("Blank.pdf", 1, ""), PageRecord("Blank.pdf", 2, "   ")]
    blank_index = build_corpus_index(blank_pages)
    results = search(blank_index, "certificate license")
    check("an all-blank corpus (no vocabulary at all) doesn't crash BM25Okapi's construction", True)
    check("an all-blank corpus returns pages with score 0, not an error", all(r.score == 0 for r in results))


def main() -> None:
    test_tokenizer_keeps_domain_keywords()
    test_exact_match_ranks_top()
    test_synonym_only_match_ranks_top()
    test_ocr_noise_variants_captured_via_fuzzy_expansion()
    test_fuzzy_expansion_does_not_cross_match_unrelated_short_acronyms()
    test_reference_only_page_bubbles_into_pool()
    test_reference_merge_is_not_just_small_corpus_luck()
    test_pool_size_small_corpus_returns_everything()
    test_pool_size_large_corpus_caps_at_limit()
    test_reference_hits_dont_blow_past_pool_size()
    test_empty_corpus_and_all_empty_pages_do_not_crash()

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
