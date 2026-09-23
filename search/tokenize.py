"""Tokenizer shared by the BM25 index and every query built against it
(checklist 3.1). rank_bm25 ships no tokenizer of its own - this is it.

Design:
  - lowercase, then split on any run of non-alphanumeric characters (so
    "WHO-GMP" -> ["who", "gmp"], "Section-XVII" -> ["section", "xvii"],
    "non-conviction" -> ["non", "conviction"]) - standard, predictable,
    and it's what lets a hyphenated compound match a query that only
    uses one half of it.
  - drop tokens shorter than MIN_TOKEN_LENGTH (2) - kills stray single
    letters/digits left over from punctuation splitting; no real
    acronym in this project's vocabulary is that short (GST, GMP, IV,
    PSU are all >= 2 chars).
  - filter a small, deliberately conservative stopword list.

The stopword list is the part worth being careful with: a generic
English stopword list would drop "who" - but "WHO" (World Health
Organization) is load-bearing domain vocabulary here (WHO-GMP
certificate, checklist seed Item 4), not the pronoun. It is deliberately
NOT in STOPWORDS, and tokenize() is tested against exactly that case.
"""
from __future__ import annotations

import re

MIN_TOKEN_LENGTH = 2

# Deliberately conservative: common function words with no retrieval
# value in this domain, and nothing that could plausibly double as a
# domain acronym/keyword. When in doubt, a word is left OUT of this list
# (better to keep a low-value token than silently drop something real).
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those",
    "with", "as", "by", "from", "it", "its",
    "has", "have", "had",
    "not", "do", "does", "did",
    "will", "would", "should", "shall", "can", "could", "may", "might",
    "than", "then", "so", "such", "if", "but",
    "which", "whom", "each", "any", "all", "also", "into", "per",
    "their", "they", "them", "there", "here",
})  # fmt: skip

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """text -> a flat list of lowercase alphanumeric tokens, punctuation
    stripped, stopwords and single-character noise removed. Empty/None
    input returns an empty list, never raises.
    """
    if not text:
        return []
    return [
        tok
        for tok in _TOKEN_RE.findall(text.lower())
        if len(tok) >= MIN_TOKEN_LENGTH and tok not in STOPWORDS
    ]
