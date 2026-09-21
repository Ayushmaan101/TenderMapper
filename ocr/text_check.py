"""Per-page text-layer pre-check (checklist 2.2).

Decides, for each page of an uploaded PDF, whether PyMuPDF's own
get_text() extraction is good enough to search directly ("usable text
layer") or whether the page needs to go through OCR instead (checklist
2.3). Getting this right matters for cost: OCR is the slow, expensive
step in the pipeline - this pre-check exists specifically to skip it
wherever a real text layer already exists (PROJECT_HARNESS.md §3 step 2).

THRESHOLD, and why it's not `len(text) > 0`
--------------------------------------------
A naive "any text at all" check is wrong in both directions:

  - False positive: a scanned page can still carry a *little* extractable
    text - a diagonal "CONFIDENTIAL" watermark, a stamped date, a page
    number baked in as its own text object - while the actual certificate
    body is a raster image PyMuPDF can't read as text at all.
    `len(text) > 0` would call this page "usable" and skip OCR, silently
    losing almost all of the page's real content.
  - False negative: a genuinely short but complete digital page (a cover
    sheet reading just "ANNEXURE A") has very little text, but what's
    there IS the real, complete content - there is nothing more for OCR
    to recover. Flagging every short page as "needs OCR" wastes the slow
    OCR step for zero benefit.

This module resolves both by combining two independent signals per page,
not just raw text length:

  1. Word/character density of the extracted text (-> has_usable_text):
     the text must clear MIN_USABLE_WORD_COUNT distinct word-like tokens
     AND MIN_USABLE_CHAR_COUNT alphanumeric characters. A watermark or a
     lone page number almost never clears both bars; a real sentence or
     paragraph comfortably does. Word tokens are whitespace-separated and
     must contain at least one alphanumeric character, so a run of pure
     punctuation/divider characters ("---", "***") doesn't inflate the
     count.
  2. Whether the page carries an embedded raster image (-> has_images),
     via PyMuPDF's own page.get_images() - the reliable signature of a
     scanned page, independent of how much or how little extractable
     text happens to ride along with it (a watermark, a stamp).

A page needs OCR only when BOTH its text layer falls short of "usable"
AND it actually has an image for OCR to work against:

    needs_ocr = (not has_usable_text) and has_images

This is deliberately not a plain negation of has_usable_text. A
short-but-real text-only page (no embedded image) ends up
has_usable_text=False, needs_ocr=False: not dense enough to trust
outright, but nothing rasterized exists to re-extract anything better
from, so there's no point sending it to OCR. The same is true, more
simply, for a truly blank page (no text, no image). Corrupt/unreadable
PDF bytes are out of scope here - see checklist 5.1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf as fitz

MIN_USABLE_WORD_COUNT = 5
MIN_USABLE_CHAR_COUNT = 20

_TOKEN_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class PageTextResult:
    """The text-layer pre-check's verdict for one page.

    has_usable_text and needs_ocr are two independent booleans, not a
    negation of each other - see module docstring for the third,
    "neither" case (short/blank page, nothing for OCR to recover).
    """

    pdf_name: str
    page_number: int  # 1-indexed, matching how a human refers to "page N"
    text: str
    has_usable_text: bool
    needs_ocr: bool
    word_count: int
    alnum_char_count: int
    has_images: bool


def check_page_text_layer(pdf_name: str, page: fitz.Page, page_number: int) -> PageTextResult:
    """Evaluate a single already-open PyMuPDF page against the threshold."""
    text = page.get_text() or ""
    stripped = text.strip()

    tokens = _TOKEN_RE.findall(stripped)
    word_tokens = [t for t in tokens if any(ch.isalnum() for ch in t)]
    word_count = len(word_tokens)
    alnum_char_count = sum(1 for ch in stripped if ch.isalnum())

    has_usable_text = word_count >= MIN_USABLE_WORD_COUNT and alnum_char_count >= MIN_USABLE_CHAR_COUNT
    has_images = bool(page.get_images(full=False))
    needs_ocr = (not has_usable_text) and has_images

    return PageTextResult(
        pdf_name=pdf_name,
        page_number=page_number,
        text=text,
        has_usable_text=has_usable_text,
        needs_ocr=needs_ocr,
        word_count=word_count,
        alnum_char_count=alnum_char_count,
        has_images=has_images,
    )


def check_pdf_text_layers(pdf_name: str, pdf_bytes: bytes) -> list[PageTextResult]:
    """Open pdf_bytes fully in memory (no temp files) and evaluate every
    page. Empty-list result for a zero-page PDF; not a crash.
    """
    results: list[PageTextResult] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index, page in enumerate(doc):
            results.append(check_page_text_layer(pdf_name, page, page_number=index + 1))
    return results
