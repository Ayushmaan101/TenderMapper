"""Checklist 2.3 verification.

Two dedicated tests use the REAL PaddleOCR and Tesseract engines against
a genuinely "scanned" synthetic PDF (real text rendered once, then
re-embedded as a plain image with no extractable text layer - so the
pipeline has no choice but to actually OCR it) - the strongest possible
proof both engines really work in this environment. Everything else
(routing between native/OCR, caching, progress, mixed-PDF per-page
correctness, both-engines-fail handling) uses fast monkeypatched engine
functions, since those tests are about the pipeline's logic, not OCR
accuracy, and real PaddleOCR inference takes real wall-clock seconds per
call.

Run: python tests/verify_ocr_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz  # noqa: E402

import ocr.pipeline as ocr_pipeline  # noqa: E402
from ocr.pipeline import DEFAULT_DPI, OcrPageResult, ocr_page, rasterize_page, resolve_pdf_text  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


# ------------------------------------------------------- fixture helpers --


def _make_digital_page(doc: fitz.Document, text: str) -> fitz.Page:
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=14)
    return page


def _make_scanned_page(doc: fitz.Document, text: str, fontsize: int = 24) -> fitz.Page:
    """A page whose ONLY content is a raster image containing real
    rendered text - no text objects at all. Simulates a genuinely
    scanned page: get_text() == "" and get_images() is non-empty, exactly
    what ocr/text_check.py's needs_ocr requires, and what the OCR engines
    then actually have something legible to read from.
    """
    scratch = fitz.open()
    scratch_page = scratch.new_page()
    scratch_page.insert_text((50, 80), text, fontsize=fontsize)
    zoom = DEFAULT_DPI / 72.0
    pix = scratch_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))

    page = doc.new_page()
    page.insert_image(fitz.Rect(0, 0, page.rect.width, page.rect.height), pixmap=pix)
    scratch.close()
    return page


def pdf_bytes_from(doc: fitz.Document) -> bytes:
    data = doc.tobytes()
    doc.close()
    return data


class _FakeOcrEngines:
    """Swaps in deterministic, instant stand-ins for
    ocr.pipeline._ocr_with_paddle / _ocr_with_tesseract, with a call
    counter, so routing/caching/mixed-PDF tests don't depend on (or pay
    the wall-clock cost of) real inference.
    """

    def __init__(self, *, paddle_text="PADDLE-RESULT", paddle_raises=None, tesseract_text="TESS-RESULT", tesseract_raises=None):
        self.paddle_calls = 0
        self.tesseract_calls = 0
        self._paddle_text = paddle_text
        self._paddle_raises = paddle_raises
        self._tesseract_text = tesseract_text
        self._tesseract_raises = tesseract_raises
        self._orig_paddle = ocr_pipeline._ocr_with_paddle
        self._orig_tesseract = ocr_pipeline._ocr_with_tesseract

    def __enter__(self):
        def fake_paddle(image):
            self.paddle_calls += 1
            if self._paddle_raises:
                raise self._paddle_raises
            return self._paddle_text

        def fake_tesseract(image):
            self.tesseract_calls += 1
            if self._tesseract_raises:
                raise self._tesseract_raises
            return self._tesseract_text

        ocr_pipeline._ocr_with_paddle = fake_paddle
        ocr_pipeline._ocr_with_tesseract = fake_tesseract
        return self

    def __exit__(self, *exc):
        ocr_pipeline._ocr_with_paddle = self._orig_paddle
        ocr_pipeline._ocr_with_tesseract = self._orig_tesseract


# --------------------------------------------------- real-engine tests --


def test_real_paddleocr_success() -> None:
    doc = fitz.open()
    # Short enough at this fontsize to comfortably fit a standard page
    # width without running off the edge (which would just make PaddleOCR
    # correctly read a truncated string - a fixture bug, not an OCR one).
    page = _make_scanned_page(doc, "GST CERTIFICATE 27AAA", fontsize=20)
    result = ocr_page("scanned.pdf", page, 1)
    doc.close()

    check("real PaddleOCR call -> engine='paddleocr'", result.engine == "paddleocr")
    check("real PaddleOCR call -> success=True", result.success is True)
    check("real PaddleOCR call -> error is None", result.error is None)
    check(
        "real PaddleOCR call -> extracted text matches the rendered content",
        "GST CERTIFICATE" in result.text and "27AAA" in result.text,
    )
    check("real PaddleOCR call -> pdf_name/page_number carried through", result.pdf_name == "scanned.pdf" and result.page_number == 1)


def test_real_tesseract_fallback() -> None:
    """Forces PaddleOCR to fail (by monkeypatching just that one function
    to a real exception, not mocking success away) and confirms the REAL
    Tesseract binary engages and actually extracts the correct text.
    """
    doc = fitz.open()
    page = _make_scanned_page(doc, "NARCOTIC LICENSE VALID UNTIL MARCH 2027")

    original_paddle = ocr_pipeline._ocr_with_paddle
    ocr_pipeline._ocr_with_paddle = lambda image: (_ for _ in ()).throw(RuntimeError("forced PaddleOCR failure for test"))
    try:
        result = ocr_page("scanned2.pdf", page, 1)
    finally:
        ocr_pipeline._ocr_with_paddle = original_paddle
    doc.close()

    check("forced PaddleOCR failure -> falls back to engine='tesseract'", result.engine == "tesseract")
    check("forced PaddleOCR failure -> tesseract fallback succeeds", result.success is True)
    check(
        "forced PaddleOCR failure -> Tesseract's real extracted text is correct",
        "NARCOTIC LICENSE" in result.text.upper() and "2027" in result.text,
    )


# ----------------------------------------------------- rasterization --


def test_rasterize_page_resolution() -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    image = rasterize_page(page, dpi=DEFAULT_DPI)
    expected_w = round(595 * DEFAULT_DPI / 72.0)
    expected_h = round(842 * DEFAULT_DPI / 72.0)
    doc.close()

    check(
        f"rasterize_page at {DEFAULT_DPI} dpi produces the expected pixel size",
        abs(image.width - expected_w) <= 1 and abs(image.height - expected_h) <= 1,
    )
    check("rasterize_page returns a PIL Image", hasattr(image, "size") and hasattr(image, "mode"))


# ---------------------------------------------- both engines fail (mocked) --


def test_both_engines_fail() -> None:
    doc = fitz.open()
    page = _make_scanned_page(doc, "irrelevant, both engines are mocked to fail")

    with _FakeOcrEngines(paddle_raises=RuntimeError("paddle down"), tesseract_raises=RuntimeError("tesseract down")):
        result = ocr_page("both_fail.pdf", page, 1)
    doc.close()

    check("both engines failing -> engine='failed'", result.engine == "failed")
    check("both engines failing -> success=False", result.success is False)
    check("both engines failing -> text is empty, not fabricated", result.text == "")
    check(
        "both engines failing -> error mentions both failures",
        "paddle down" in result.error and "tesseract down" in result.error,
    )


# --------------------------------------------------- resolve_pdf_text --


def test_native_pages_never_invoke_ocr() -> None:
    doc = fitz.open()
    _make_digital_page(doc, "This is a real digital paragraph with plenty of words in it to be usable.")
    _make_digital_page(doc, "A second real digital paragraph, also comfortably above the usable-text bar.")
    pdf_bytes = pdf_bytes_from(doc)

    with _FakeOcrEngines() as engines:
        results = resolve_pdf_text("digital.pdf", pdf_bytes)

    check("all-digital PDF -> every page resolved engine='native'", all(r.engine == "native" for r in results))
    check("all-digital PDF -> every page success=True", all(r.success for r in results))
    check("all-digital PDF -> OCR engines never invoked", engines.paddle_calls == 0 and engines.tesseract_calls == 0)


def test_blank_page_resolves_native_empty() -> None:
    doc = fitz.open()
    doc.new_page()
    pdf_bytes = pdf_bytes_from(doc)

    with _FakeOcrEngines() as engines:
        results = resolve_pdf_text("blank.pdf", pdf_bytes)

    check("blank page -> engine='native'", results[0].engine == "native")
    check("blank page -> success=True, text empty", results[0].success is True and results[0].text.strip() == "")
    check("blank page -> OCR never invoked", engines.paddle_calls == 0)


def test_mixed_pdf_resolves_correct_engine_per_page() -> None:
    doc = fitz.open()
    _make_digital_page(doc, "A comfortably long real paragraph of digital text for page one right here.")
    _make_scanned_page(doc, "scan A")
    _make_digital_page(doc, "Another comfortably long real paragraph of digital text, this time page three.")
    _make_scanned_page(doc, "scan B")
    _make_scanned_page(doc, "scan C")
    pdf_bytes = pdf_bytes_from(doc)

    with _FakeOcrEngines(paddle_text="MOCKED-OCR-TEXT") as engines:
        results = resolve_pdf_text("mixed.pdf", pdf_bytes)

    check("mixed PDF -> 5 pages resolved", len(results) == 5)
    expected_engines = ["native", "paddleocr", "native", "paddleocr", "paddleocr"]
    check(
        "mixed PDF -> engine assigned per page matches the exact construction",
        [r.engine for r in results] == expected_engines,
    )
    check("mixed PDF -> OCR invoked exactly 3 times (the 3 scanned pages)", engines.paddle_calls == 3)
    check("mixed PDF -> OCR'd pages carry the (mocked) OCR text", all(r.text == "MOCKED-OCR-TEXT" for r in results if r.engine == "paddleocr"))


def test_progress_callback_fires_once_per_page_in_order() -> None:
    doc = fitz.open()
    for i in range(4):
        _make_digital_page(doc, f"Digital page number {i} with enough real words to be usable text here.")
    pdf_bytes = pdf_bytes_from(doc)

    calls: list[tuple[int, int]] = []
    with _FakeOcrEngines():
        resolve_pdf_text("progress.pdf", pdf_bytes, progress_callback=lambda done, total: calls.append((done, total)))

    check("progress callback fires once per page", len(calls) == 4)
    check("progress callback reports (done, total) in strict increasing order", calls == [(1, 4), (2, 4), (3, 4), (4, 4)])


# --------------------------------------------------------------- caching --


def test_cache_hit_avoids_reinvoking_ocr() -> None:
    doc = fitz.open()
    _make_scanned_page(doc, "cached page content")
    pdf_bytes = pdf_bytes_from(doc)

    cache: dict = {}
    with _FakeOcrEngines(paddle_text="FIRST-CALL-RESULT") as engines:
        first = resolve_pdf_text("cache_test.pdf", pdf_bytes, cache=cache)
        check("first call (empty cache) -> OCR invoked once", engines.paddle_calls == 1)

        second = resolve_pdf_text("cache_test.pdf", pdf_bytes, cache=cache)
        check("second call with the SAME cache -> OCR invoked zero additional times", engines.paddle_calls == 1)
        check(
            "second call returns the identical cached result object",
            second[0] is cache[("cache_test.pdf", 1)] and second[0] is first[0],
        )
        check("cached result content matches the original OCR output", second[0].text == "FIRST-CALL-RESULT")


def test_no_cache_reinvokes_ocr_every_time() -> None:
    """Contrast case: proves the speedup above is genuinely the cache's
    doing, not some other reason OCR would be skipped - without a cache,
    the same page is OCR'd again on every call.
    """
    doc = fitz.open()
    _make_scanned_page(doc, "no cache page content")
    pdf_bytes = pdf_bytes_from(doc)

    with _FakeOcrEngines() as engines:
        resolve_pdf_text("no_cache_test.pdf", pdf_bytes, cache=None)
        resolve_pdf_text("no_cache_test.pdf", pdf_bytes, cache=None)
        check("no cache passed -> OCR invoked twice (once per call)", engines.paddle_calls == 2)


def test_cache_keyed_per_page_not_per_pdf() -> None:
    """A different page number for the same pdf_name must be a distinct
    cache entry - proves the key is genuinely (pdf_name, page_number),
    not just pdf_name.
    """
    doc = fitz.open()
    _make_scanned_page(doc, "page one scan")
    _make_scanned_page(doc, "page two scan")
    pdf_bytes = pdf_bytes_from(doc)

    cache: dict = {}
    with _FakeOcrEngines() as engines:
        resolve_pdf_text("two_pages.pdf", pdf_bytes, cache=cache)
        check("2-scanned-page PDF, empty cache -> OCR invoked twice (once per page)", engines.paddle_calls == 2)
        check("cache now holds 2 distinct entries, one per page", set(cache.keys()) == {("two_pages.pdf", 1), ("two_pages.pdf", 2)})

        resolve_pdf_text("two_pages.pdf", pdf_bytes, cache=cache)
        check("re-run with the warmed cache -> zero additional OCR calls", engines.paddle_calls == 2)


def main() -> None:
    test_real_paddleocr_success()
    test_real_tesseract_fallback()
    test_rasterize_page_resolution()
    test_both_engines_fail()
    test_native_pages_never_invoke_ocr()
    test_blank_page_resolves_native_empty()
    test_mixed_pdf_resolves_correct_engine_per_page()
    test_progress_callback_fires_once_per_page_in_order()
    test_cache_hit_avoids_reinvoking_ocr()
    test_no_cache_reinvokes_ocr_every_time()
    test_cache_keyed_per_page_not_per_pdf()

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
