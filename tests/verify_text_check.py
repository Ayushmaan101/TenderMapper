"""Checklist 2.2 verification.

Generates synthetic PDFs entirely in memory with PyMuPDF itself (no
external files, no Pillow) covering: an all-digital PDF, an all-scanned
(image-only) PDF, a mixed PDF, and edge cases specifically chosen to
prove the threshold is doing real work and not just `len(text) > 0`:
a truly blank page, a page with only stray/noise text and no image
(nothing for OCR to recover), a page with stray watermark text ON TOP OF
a scanned image (needs_ocr must still be True), a page with substantial
real text that ALSO happens to carry an embedded image (usable text
wins), and a punctuation-only "noise" page that racks up character count
without being real words.

Run: python tests/verify_text_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz  # noqa: E402

from ocr.text_check import (  # noqa: E402
    MIN_USABLE_CHAR_COUNT,
    MIN_USABLE_WORD_COUNT,
    check_pdf_text_layers,
)

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


REAL_PARAGRAPH = (
    "This is a real paragraph of digital compliance text, describing a "
    "certificate issued by the concerned authority, valid for the "
    "stated period and covering the items quoted in this tender."
)


def _add_text_page(doc: fitz.Document, text: str) -> fitz.Page:
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    return page


def _add_image_page(doc: fitz.Document, watermark_text: str = "") -> fitz.Page:
    page = doc.new_page()
    w, h = 200, 200
    samples = bytes([100, 100, 100] * (w * h))  # solid gray "scanned page"
    pix = fitz.Pixmap(fitz.csRGB, w, h, samples, False)
    rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
    page.insert_image(rect, pixmap=pix)
    if watermark_text:
        page.insert_text((36, 36), watermark_text, fontsize=8)
    return page


def _add_blank_page(doc: fitz.Document) -> fitz.Page:
    return doc.new_page()


def pdf_bytes_from(doc: fitz.Document) -> bytes:
    data = doc.tobytes()
    doc.close()
    return data


# --------------------------------------------------------------- suites --


def test_born_digital_pdf() -> None:
    doc = fitz.open()
    for _ in range(3):
        _add_text_page(doc, REAL_PARAGRAPH)
    results = check_pdf_text_layers("digital.pdf", pdf_bytes_from(doc))

    check("born-digital PDF -> 3 pages evaluated", len(results) == 3)
    check("born-digital PDF -> every page has_usable_text=True", all(r.has_usable_text for r in results))
    check("born-digital PDF -> every page needs_ocr=False", all(not r.needs_ocr for r in results))
    check("born-digital PDF -> every page has_images=False", all(not r.has_images for r in results))
    check("born-digital PDF -> page_number is 1-indexed in order", [r.page_number for r in results] == [1, 2, 3])
    check("born-digital PDF -> pdf_name carried through", all(r.pdf_name == "digital.pdf" for r in results))
    check("born-digital PDF -> extracted text actually contains the real paragraph", all("certificate" in r.text for r in results))


def test_scanned_image_only_pdf() -> None:
    doc = fitz.open()
    for _ in range(3):
        _add_image_page(doc)
    results = check_pdf_text_layers("scanned.pdf", pdf_bytes_from(doc))

    check("scanned PDF -> 3 pages evaluated", len(results) == 3)
    check("scanned PDF -> every page has_usable_text=False", all(not r.has_usable_text for r in results))
    check("scanned PDF -> every page needs_ocr=True", all(r.needs_ocr for r in results))
    check("scanned PDF -> every page has_images=True", all(r.has_images for r in results))
    check("scanned PDF -> extracted text is empty (nothing to read)", all(r.text.strip() == "" for r in results))


def test_mixed_pdf_per_page_split() -> None:
    doc = fitz.open()
    _add_text_page(doc, REAL_PARAGRAPH)     # page 1: digital
    _add_image_page(doc)                    # page 2: scanned
    _add_text_page(doc, REAL_PARAGRAPH)     # page 3: digital
    _add_image_page(doc)                    # page 4: scanned
    _add_image_page(doc)                    # page 5: scanned
    results = check_pdf_text_layers("mixed.pdf", pdf_bytes_from(doc))

    check("mixed PDF -> 5 pages evaluated", len(results) == 5)
    expected_needs_ocr = [False, True, False, True, True]
    check(
        "mixed PDF -> needs_ocr matches the exact page-by-page construction",
        [r.needs_ocr for r in results] == expected_needs_ocr,
    )
    expected_usable = [True, False, True, False, False]
    check(
        "mixed PDF -> has_usable_text matches the exact page-by-page construction",
        [r.has_usable_text for r in results] == expected_usable,
    )


def test_blank_page() -> None:
    doc = fitz.open()
    _add_blank_page(doc)
    results = check_pdf_text_layers("blank.pdf", pdf_bytes_from(doc))

    r = results[0]
    check("truly blank page -> has_usable_text=False", not r.has_usable_text)
    check(
        "truly blank page -> needs_ocr=False (nothing there for OCR to recover)",
        not r.needs_ocr,
    )
    check("truly blank page -> has_images=False", not r.has_images)
    check("truly blank page -> word_count == 0", r.word_count == 0)


def test_stray_noise_no_image_not_worth_ocr() -> None:
    """A short, real, but sparse text-only page (no embedded image) -
    e.g. a page that legitimately just says 'ANNEXURE A' or a bare page
    number. Below the usable-text bar, but with nothing rasterized on
    the page, there's nothing for OCR to recover - must NOT be flagged
    needs_ocr. This is the case a naive `len(text) > 0` check gets wrong
    in the "waste an OCR pass for nothing" direction.
    """
    doc = fitz.open()
    _add_text_page(doc, "ANNEXURE A")
    results = check_pdf_text_layers("annexure.pdf", pdf_bytes_from(doc))

    r = results[0]
    check("sparse real text, no image -> has_usable_text=False (below word/char bar)", not r.has_usable_text)
    check("sparse real text, no image -> needs_ocr=False (no image to OCR against)", not r.needs_ocr)
    check("sparse real text, no image -> has_images=False", not r.has_images)
    check("sparse real text, no image -> some text was still captured for what it's worth", "ANNEXURE" in r.text)


def test_watermark_over_scanned_image_needs_ocr() -> None:
    """The classic failure mode a naive check gets wrong in the OTHER
    direction: a scanned certificate (embedded image) with a little
    stray extractable text riding along (a watermark/stamp). The sparse
    text alone would fail the usable-text bar either way, but the
    embedded image must still force needs_ocr=True - this is exactly
    what has_images is for.
    """
    doc = fitz.open()
    _add_image_page(doc, watermark_text="CONFIDENTIAL DRAFT")
    results = check_pdf_text_layers("watermarked_scan.pdf", pdf_bytes_from(doc))

    r = results[0]
    check("watermark + scanned image -> has_usable_text=False (watermark alone is too sparse)", not r.has_usable_text)
    check("watermark + scanned image -> needs_ocr=True (image present, don't trust the sparse text)", r.needs_ocr)
    check("watermark + scanned image -> has_images=True", r.has_images)
    check("watermark + scanned image -> the watermark text is still captured/available", "CONFIDENTIAL" in r.text)


def test_real_text_with_incidental_image_stays_usable() -> None:
    """A normal digital page that also happens to embed an image (e.g. a
    letterhead logo) alongside substantial real text: usable text must
    win regardless of the image's presence.
    """
    doc = fitz.open()
    page = _add_text_page(doc, REAL_PARAGRAPH)
    w, h = 40, 40
    samples = bytes([200, 200, 200] * (w * h))
    pix = fitz.Pixmap(fitz.csRGB, w, h, samples, False)
    page.insert_image(fitz.Rect(400, 20, 440, 60), pixmap=pix)
    results = check_pdf_text_layers("letterhead.pdf", pdf_bytes_from(doc))

    r = results[0]
    check("real text + incidental logo image -> has_usable_text=True", r.has_usable_text)
    check("real text + incidental logo image -> needs_ocr=False (usable text wins)", not r.needs_ocr)
    check("real text + incidental logo image -> has_images=True (the logo is still detected)", r.has_images)


def test_punctuation_noise_is_not_usable_text() -> None:
    """Demonstrates the core 'not naive len(text) > 0' claim directly: a
    page whose raw text is long (plenty of characters) but is entirely
    punctuation/divider noise, no real words - must NOT count as usable.
    """
    noise = "---------- ********** ........................ ============"
    doc = fitz.open()
    _add_text_page(doc, noise)
    results = check_pdf_text_layers("noise.pdf", pdf_bytes_from(doc))

    r = results[0]
    check(f"punctuation noise (len={len(noise)} chars, naive check would pass) -> has_usable_text=False", not r.has_usable_text)
    check("punctuation noise -> word_count == 0 (no alphanumeric tokens at all)", r.word_count == 0)
    check("punctuation noise, no image -> needs_ocr=False", not r.needs_ocr)


def test_threshold_boundary() -> None:
    """Constructs text landing exactly at, and just under, the documented
    threshold constants, to prove the boundary is where it's documented
    to be rather than some other accidental value. Uses real 5-letter
    words (not "w0", "w1", ...) so the word count AND char count bars
    are cleared together, the way real short text would.
    """
    words = ["alpha", "bravo", "charlie", "delta", "echo"][:MIN_USABLE_WORD_COUNT]
    exactly_at_threshold = " ".join(words)
    alnum_count = sum(ch.isalnum() for ch in exactly_at_threshold)
    check(
        f"exactly-at-threshold fixture has {MIN_USABLE_WORD_COUNT} words and "
        f">= {MIN_USABLE_CHAR_COUNT} alnum chars ({alnum_count})",
        len(words) == MIN_USABLE_WORD_COUNT and alnum_count >= MIN_USABLE_CHAR_COUNT,
    )

    doc = fitz.open()
    _add_text_page(doc, exactly_at_threshold)
    r_at = check_pdf_text_layers("at_threshold.pdf", pdf_bytes_from(doc))[0]
    check(
        f"exactly {MIN_USABLE_WORD_COUNT} words at/above char bar -> has_usable_text=True",
        r_at.has_usable_text,
    )

    just_under = " ".join(words[:-1])
    doc2 = fitz.open()
    _add_text_page(doc2, just_under)
    r_under = check_pdf_text_layers("under_threshold.pdf", pdf_bytes_from(doc2))[0]
    check(
        f"{MIN_USABLE_WORD_COUNT - 1} words (one under the word bar) -> has_usable_text=False",
        not r_under.has_usable_text,
    )


def test_empty_pdf_zero_pages() -> None:
    """PyMuPDF's own writer refuses to save a zero-page document
    (`doc.tobytes()` raises "cannot save with zero pages"), so this
    fixture is a minimal hand-crafted PDF byte string instead - proving
    check_pdf_text_layers handles genuinely zero-page *input* bytes
    gracefully, which is exactly the "zero-page PDFs" scenario
    CHECKLIST.md 5.1 calls out for later, broader error handling.
    """
    minimal_zero_page_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
        b"trailer\n<< /Size 3 /Root 1 0 R >>\n"
        b"%%EOF"
    )
    results = check_pdf_text_layers("empty.pdf", minimal_zero_page_pdf)
    check("zero-page PDF -> returns an empty list, no crash", results == [])


def main() -> None:
    test_born_digital_pdf()
    test_scanned_image_only_pdf()
    test_mixed_pdf_per_page_split()
    test_blank_page()
    test_stray_noise_no_image_not_worth_ocr()
    test_watermark_over_scanned_image_needs_ocr()
    test_real_text_with_incidental_image_stays_usable()
    test_punctuation_noise_is_not_usable_text()
    test_threshold_boundary()
    test_empty_pdf_zero_pages()

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
