"""BM25 + synonym-aware search (checklist 3.1). PROJECT_HARNESS.md §3
step 6: query = a schema column's requirement terms + its stored
synonyms, rapidfuzz handles OCR-noise term variants, returns a wide
candidate pool (15-20 pages), not top-5 - verification (Groq, checklist
3.2) happens downstream.

Two-phase design, deliberately: CorpusIndex is built ONCE per company
session from every resolved page's text (rank_bm25 tokenizes hundreds of
pages once); search() is called ONCE PER SCHEMA COLUMN against that same
prebuilt index (checklist 3.3 will call this once per column, for every
column in every configured table - rebuilding the BM25 index per column
would be wasteful).

Fuzzy term-variant matching
----------------------------
Before scoring, every query token not already present in the corpus
vocabulary is checked against that vocabulary with rapidfuzz, using
*absolute* Levenshtein edit distance (rapidfuzz.distance.Levenshtein),
not a percentage ratio. A percentage-ratio cutoff (e.g. "80% similar")
badly under-serves short tokens: "who" vs "wh0" is only a single
substituted character but scores just ~67% similarity by ratio, well
below a typical 75-80% cutoff, while "certificate" vs "cert1ficate" - the
exact same single substitution - scores ~91%. Absolute edit distance
treats both as what they are: one character wrong.

The distance budget still scales with token length, the other direction
a flat threshold gets wrong: at distance<=2, short unrelated acronyms
can collide by accident ("gst" and "gmp" are edit-distance 2 apart, but
mean completely different things). Tokens under 5 characters get a
budget of 1; 5+ characters get 2. This resolves BOTH of the checklist's
example cases (wh0-gmp, cert1ficate) while keeping short-acronym
collisions out.

Candidate merging
------------------
The reference index (checklist 2.4) is a second, independent signal: a
page whose only content is "Section VIII Clause 11" can score ~0 on
BM25 (it shares none of the requirement's descriptive vocabulary) but
should still surface, since the section citation alone is exactly the
kind of evidence a human reviewer would trust. Reference hits are
therefore guaranteed a slot in the pool (ahead of merely BM25-ranked,
non-reference pages), sorted by their own BM25 score as a tiebreak; BM25
top-ranked pages fill whatever's left, up to pool_size. A corpus smaller
than pool_size naturally returns everything - no special-casing needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rank_bm25 import BM25Okapi
from rapidfuzz import process
from rapidfuzz.distance import Levenshtein

from ocr.references import ReferenceHit, ReferenceIndex, extract_references
from search.tokenize import tokenize

DEFAULT_POOL_SIZE = 20
SNIPPET_RADIUS = 100  # characters of context on each side of the first match


@dataclass(frozen=True)
class PageRecord:
    """One page's resolved text, ready to index - the shape
    ocr.pipeline.OcrPageResult already provides (pdf_name, page_number,
    text); kept separate here so this module has no OCR-pipeline import
    dependency.
    """

    pdf_name: str
    page_number: int
    text: str


@dataclass(frozen=True)
class SearchCandidate:
    pdf_name: str
    page_number: int
    rank: int  # 1-indexed position in the final pool
    score: float  # raw BM25 score against the expanded query (0.0 for a page that only qualified via reference)
    snippet: str
    matched_terms: list[str] = field(default_factory=list)
    match_signals: list[str] = field(default_factory=list)  # "bm25" and/or "reference"


def _fuzzy_expand_tokens(query_tokens: list[str], vocabulary: set[str]) -> list[str]:
    """For every query token, add the closest vocabulary token(s) within
    the length-scaled edit distance budget - even when the token already
    has an exact vocabulary match elsewhere. A clean spelling on one page
    and a noisy OCR variant on another are both real corpus tokens; an
    exact match on page A must not short-circuit finding page B's
    "wh0"-style variant. Returns the original tokens plus whatever fuzzy
    matches were found - duplicates are fine, BM25 just weighs them.
    """
    if not vocabulary:
        return list(query_tokens)

    vocab_list = list(vocabulary)
    expanded = list(query_tokens)
    for token in query_tokens:
        max_distance = 1 if len(token) < 5 else 2
        matches = process.extract(
            token, vocab_list, scorer=Levenshtein.distance, limit=5, score_cutoff=max_distance
        )
        expanded.extend(match for match, _dist, _idx in matches if match != token)
    return expanded


def _make_snippet(text: str, matched_terms: list[str]) -> str:
    lowered = text.lower()
    best_pos = None
    for term in matched_terms:
        pos = lowered.find(term.lower())
        if pos != -1 and (best_pos is None or pos < best_pos):
            best_pos = pos
    if best_pos is None:
        excerpt = text.strip()[: SNIPPET_RADIUS * 2]
        return excerpt
    start = max(0, best_pos - SNIPPET_RADIUS)
    end = min(len(text), best_pos + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


class CorpusIndex:
    """A BM25 index over every page's resolved text for one company
    session, built once and reused across every schema column's search().
    """

    def __init__(self, pages: list[PageRecord]):
        self.pages = pages
        self._tokenized: list[list[str]] = [tokenize(p.text) for p in pages]
        self._vocabulary: set[str] = {tok for doc in self._tokenized for tok in doc}
        # rank_bm25's constructor divides by average document frequency
        # and blows up (ZeroDivisionError) if every document is empty
        # (e.g. an all-blank/all-failed-OCR upload) - guard explicitly
        # rather than let that propagate as a crash.
        self._bm25: Optional[BM25Okapi] = BM25Okapi(self._tokenized) if self._vocabulary else None

    def __len__(self) -> int:
        return len(self.pages)

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        """BM25 score for every page, in self.pages order. All zeros if
        the corpus has no vocabulary at all (nothing to score against).
        """
        if self._bm25 is None:
            return [0.0] * len(self.pages)
        return list(self._bm25.get_scores(query_tokens))


def build_corpus_index(pages: list[PageRecord]) -> CorpusIndex:
    return CorpusIndex(pages)


def search(
    index: CorpusIndex,
    requirement_text: str,
    synonyms: Optional[list[str]] = None,
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    reference_index: Optional[ReferenceIndex] = None,
) -> list[SearchCandidate]:
    """Run one schema column's query against a prebuilt CorpusIndex.

    Query tokens = tokenize(requirement_text) + tokenize(each synonym).
    Fuzzy-expanded against the corpus vocabulary before BM25 scoring.
    Reference-index hits (if a reference_index is supplied) are merged
    in, guaranteed a slot ahead of plain BM25-ranked non-reference pages.
    """
    synonyms = synonyms or []
    query_tokens = tokenize(requirement_text)
    for syn in synonyms:
        query_tokens.extend(tokenize(syn))

    if not index.pages:
        return []

    expanded_tokens = _fuzzy_expand_tokens(query_tokens, index._vocabulary)
    scores = index.get_scores(expanded_tokens)

    page_scores = list(zip(index.pages, scores))
    page_scores.sort(key=lambda ps: ps[1], reverse=True)
    score_by_key = {(p.pdf_name, p.page_number): s for p, s in page_scores}

    reference_hits: list[ReferenceHit] = []
    if reference_index is not None:
        reference_hits = reference_index.lookup(requirement_text)
        for syn in synonyms:
            for hit in reference_index.lookup(syn):
                if hit not in reference_hits:
                    reference_hits.append(hit)
    reference_hits.sort(key=lambda h: score_by_key.get((h.pdf_name, h.page_number), 0.0), reverse=True)

    selected: list[tuple[str, int]] = []
    signals: dict[tuple[str, int], set[str]] = {}
    seen: set[tuple[str, int]] = set()

    for hit in reference_hits[:pool_size]:
        key = (hit.pdf_name, hit.page_number)
        if key not in seen:
            seen.add(key)
            selected.append(key)
        signals.setdefault(key, set()).add("reference")

    for page, score in page_scores:
        if len(selected) >= pool_size:
            break
        key = (page.pdf_name, page.page_number)
        if key in seen:
            continue
        seen.add(key)
        selected.append(key)

    pages_by_key = {(p.pdf_name, p.page_number): p for p in index.pages}
    tokenized_by_key = {
        (p.pdf_name, p.page_number): toks for p, toks in zip(index.pages, index._tokenized)
    }
    expanded_token_set = set(expanded_tokens)

    candidates: list[SearchCandidate] = []
    for rank, key in enumerate(selected, start=1):
        page = pages_by_key[key]
        score = score_by_key.get(key, 0.0)
        page_tokens = set(tokenized_by_key.get(key, []))
        matched = sorted(expanded_token_set & page_tokens)

        sig = signals.get(key, set())
        if score > 0:
            sig.add("bm25")

        candidates.append(
            SearchCandidate(
                pdf_name=key[0],
                page_number=key[1],
                rank=rank,
                score=float(score),
                snippet=_make_snippet(page.text, matched or query_tokens),
                matched_terms=matched,
                match_signals=sorted(sig) or ["reference"],
            )
        )

    return candidates
