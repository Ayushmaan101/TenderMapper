"""Search package.

BM25 index (rank_bm25) over extracted/OCR'd page text, queried with a
schema column's requirement terms + stored synonyms, with rapidfuzz for
term-variant/OCR-noise matching. Returns a wide candidate pool (top 15-20
pages) per schema row — not top-5. See PROJECT_HARNESS.md §3 step 6 and
CHECKLIST.md item 3.1.
"""
