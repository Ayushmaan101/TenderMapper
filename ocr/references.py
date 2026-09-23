"""Section/clause reference extraction (checklist 2.4).

A lightweight secondary lookup, per PROJECT_HARNESS.md §3 step 5: catches
pages that reference a requirement by section/clause/schedule/form number
only, with none of the requirement's own vocabulary present on that page
(e.g. a page that says nothing but "Section VIII Clause 11" as a header,
with the actual certificate content on the following page).

Reference kinds and canonical form
-----------------------------------
  - "section_clause": "Section VIII Clause 11" / "Section-VIII, Clause 11"
    / "Sec. 8 Cl. 11" -> canonical "section 8 clause 11"
  - "section": a standalone section/performa reference - "Section-XVII",
    "Performa Section-XIX", "Section-XVI" -> canonical "section 17" etc.
    ("Performa" is a document-type qualifier, not part of the section's
    identity, so it's stripped; a section_clause match also emits its
    own bare "section N" entry, so a query for just "Section VIII" finds
    pages that only ever mention "Section VIII Clause 11")
  - "schedule": "Schedule 'M'" -> canonical "schedule m" (also accepts a
    short alphanumeric suffix, e.g. "Schedule H1", for other real Indian
    regulatory schedule names beyond the one in this project's seed data)
  - "form": "Form-45" -> canonical "form 45"

Section numbers may be written as Roman numerals (VIII) or Arabic digits
(8) - both canonicalize to the same Arabic-digit token, via a validated
Roman-numeral converter (round-tripped through int_to_roman to reject
malformed sequences like "IIII" or "VX"), so "Section VIII Clause 11"
and "Sec. 8 Cl. 11" are recognized as the same reference regardless of
which form a given document happens to use. Leading zeros are also
normalized away ("Form-045" -> "form 45").

Every pattern is keyword-anchored (the literal word Section/Sec/Clause/
Cl/Schedule/Form must actually be present, at a word boundary) rather
than a bare number/date heuristic - this is what keeps it from
false-positiving on financial years ("2021-22"), money ("Rs.10/-"),
durations ("45 days", "3-years"), or the word "Form" embedded inside
"performance"/"format"/"information" (all three appear in this
project's own seed schema text).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

_SECTION_WORD = r"(?:Section|Sec\.?)"
_CLAUSE_WORD = r"(?:Clause|Cl\.?)"
_ROMAN = r"[IVXLCDM]+"
_ARABIC = r"\d+"
_NUM = rf"(?:{_ROMAN}|{_ARABIC})"

# "Section VIII Clause 11" / "Section-VIII, Clause 11" / "Sec. 8 Cl. 11"
_SECTION_CLAUSE_RE = re.compile(
    rf"\b{_SECTION_WORD}[\s\-]*({_NUM})\b[\s,]*{_CLAUSE_WORD}[\s\-.:]*({_ARABIC})\b",
    re.IGNORECASE,
)

# "Section-XVII" / "Performa Section-XIX" / "Section-XVI" / "Sec. 8"
_STANDALONE_SECTION_RE = re.compile(
    rf"\b{_SECTION_WORD}[\s\-]*({_NUM})\b",
    re.IGNORECASE,
)

# "Schedule 'M'" / "Schedule M" / "Schedule H1"
_SCHEDULE_RE = re.compile(
    r"\bSchedule\s*['\"‘’]?\s*([A-Za-z][A-Za-z0-9]?)\b['\"‘’]?",
    re.IGNORECASE,
)

# "Form-45" / "Form 45" / "Form45" - deliberately requires a trailing
# number, so "Tender Acceptance Form" (no number) never matches.
_FORM_RE = re.compile(r"\bForm[\s\-]*(\d+)\b", re.IGNORECASE)

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAN_TABLE = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]  # fmt: skip


def _int_to_roman(n: int) -> str:
    parts = []
    for value, symbol in _ROMAN_TABLE:
        while n >= value:
            parts.append(symbol)
            n -= value
    return "".join(parts)


def _roman_to_int(s: str) -> Optional[int]:
    """None for anything that isn't a well-formed Roman numeral - a
    malformed sequence like "IIII" or "VX" is rejected via round-trip
    (recomputing the canonical Roman spelling and checking it matches),
    not accepted with a wrong/guessed value.
    """
    s = s.upper()
    total = 0
    prev = 0
    for ch in reversed(s):
        value = _ROMAN_VALUES.get(ch)
        if value is None:
            return None
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    if total <= 0 or _int_to_roman(total) != s:
        return None
    return total


def _normalize_number(raw: str) -> Optional[int]:
    """Arabic digits (leading zeros stripped) or a validated Roman
    numeral -> a plain int, or None if neither parses cleanly.
    """
    if raw.isdigit():
        return int(raw)
    return _roman_to_int(raw)


@dataclass(frozen=True)
class ExtractedReference:
    """One canonicalized reference found in a block of text.

    canonical is the normalized, lowercase, punctuation-free lookup key
    ("section 8 clause 11"); raw_text is the original matched substring,
    kept for display/debugging, never used for matching.
    """

    kind: str  # "section" | "section_clause" | "schedule" | "form"
    canonical: str
    raw_text: str


def extract_references(text: str) -> list[ExtractedReference]:
    """Find every section/clause/schedule/form reference in `text`,
    deduplicated by (kind, canonical) - a reference mentioned twice in
    the same text (e.g. "Section-XIX" appearing on both the first and
    last line of a requirement) produces one entry, keeping the first
    raw_text seen.
    """
    found: dict[tuple[str, str], ExtractedReference] = {}

    def add(kind: str, canonical: str, raw: str) -> None:
        key = (kind, canonical)
        if key not in found:
            found[key] = ExtractedReference(kind=kind, canonical=canonical, raw_text=raw)

    for m in _SECTION_CLAUSE_RE.finditer(text):
        section_num = _normalize_number(m.group(1))
        if section_num is None:
            continue
        clause_num = int(m.group(2))
        add("section_clause", f"section {section_num} clause {clause_num}", m.group(0))
        add("section", f"section {section_num}", m.group(0))

    for m in _STANDALONE_SECTION_RE.finditer(text):
        section_num = _normalize_number(m.group(1))
        if section_num is None:
            continue
        add("section", f"section {section_num}", m.group(0))

    for m in _SCHEDULE_RE.finditer(text):
        add("schedule", f"schedule {m.group(1).lower()}", m.group(0))

    for m in _FORM_RE.finditer(text):
        add("form", f"form {int(m.group(1))}", m.group(0))

    return list(found.values())


# ------------------------------------------------------------------ index --


@dataclass(frozen=True)
class ReferenceHit:
    pdf_name: str
    page_number: int


class ReferenceIndex:
    """Reverse index: canonical reference token -> pages that mention it.

    Deliberately has no Streamlit/db dependency, mirroring the rest of
    this package - the caller owns where the index itself lives
    (e.g. built fresh per company session, alongside the OCR results it
    was built from).
    """

    def __init__(self) -> None:
        self._index: dict[str, list[ReferenceHit]] = {}

    def add_page(self, pdf_name: str, page_number: int, text: str) -> list[ExtractedReference]:
        """Extract and index every reference on one page. Returns what
        was found, for callers that want to display/log it.
        """
        refs = extract_references(text)
        hit = ReferenceHit(pdf_name, page_number)
        for ref in refs:
            bucket = self._index.setdefault(ref.canonical, [])
            if hit not in bucket:
                bucket.append(hit)
        return refs

    def lookup(self, query_text: str) -> list[ReferenceHit]:
        """Extract references from a query/requirement string and return
        the union of every page that mentions any of them - first-seen
        order, deduplicated. Empty list if the query has no recognizable
        references at all (this index has nothing to offer in that case;
        that's the normal case for most requirement rows, which is
        exactly why this is a *secondary* lookup, not the main path).
        """
        results: list[ReferenceHit] = []
        seen: set[ReferenceHit] = set()
        for ref in extract_references(query_text):
            for hit in self._index.get(ref.canonical, []):
                if hit not in seen:
                    seen.add(hit)
                    results.append(hit)
        return results

    def __len__(self) -> int:
        return len(self._index)


def build_index(pages: Iterable[tuple[str, int, str]]) -> ReferenceIndex:
    """Convenience constructor: pages is an iterable of
    (pdf_name, page_number, text), e.g. derived from
    ocr.pipeline.OcrPageResult records.
    """
    index = ReferenceIndex()
    for pdf_name, page_number, text in pages:
        index.add_page(pdf_name, page_number, text)
    return index
