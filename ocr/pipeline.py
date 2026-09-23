"""OCR pipeline (checklist 2.3): resolve final text for every page of a
PDF, using the checklist-2.2 text-layer pre-check to skip OCR wherever a
real text layer already exists, and PaddleOCR (falling back to
Tesseract) for the pages that don't.

Environment quirks found and worked around, both required for PaddleOCR
to run at all in this project's dev environment (paddlepaddle 3.3.1,
CPU, Windows) - not just test-time conveniences:

  - enable_mkldnn: on Windows, oneDNN acceleration crashes the PP-OCRv6
    detection model on every call with a Paddle-internal error
    ("ConvertPirAttribute2RuntimeAttribute not support
    [pir::ArrayAttribute<pir::DoubleAttribute>]"), a PIR/oneDNN
    incompatibility in this paddlepaddle build on this platform, not
    anything in this project's code - so it stays off there. On Linux
    (Streamlit Community Cloud's `packages.txt` container - checklist
    5.2), oneDNN is enabled instead, to take advantage of CPU
    vectorization for faster inference under the platform's resource
    ceiling. This is a directed, platform-gated change
    (`sys.platform == "linux"`) that has not been verified against a
    real Linux box in this environment - if the same crash turns out to
    reproduce on Linux too, this needs to flip back to unconditionally
    off, not silently left as-is.
  - use_doc_orientation_classify=False, use_doc_unwarping=False: these
    two preprocessing models are meant to correct real photographed-
    document distortion (skew, page warp) - genuinely useful for a
    phone-camera capture, much less relevant for this project's actual
    input (office-scanned/flatbed tender PDFs, per PROJECT_HARNESS.md,
    not phone photos). Investigating checklist 2.3 found the unwarping
    model can degrade a page badly enough that the detector finds zero
    text on it. Given the marginal value for this project's real input
    and the demonstrated risk, both are off by default; still
    configurable per-call if a future need for photographed-document
    correction shows up.

use_textline_orientation=True (per-line rotation correction - the user's
explicit spec) stays on: lighter-weight, lower-risk, and directly useful
for a page scanned slightly rotated or with upside-down text lines.

Caching contract: resolve_pdf_text takes an optional `cache` dict from
the caller (e.g. st.session_state in the Streamlit app - this module has
no Streamlit dependency of its own) keyed by (pdf_name, page_number),
written to only for pages that actually went through OCR. A page already
in the cache is never re-OCR'd.

Load-based engine routing (cloud memory ceiling)
--------------------------------------------------
PaddleOCR is the more accurate engine but also the heavier one - a large
model held in memory, more RAM/CPU per page. Tesseract is lighter and
faster but less accurate. Against Streamlit Community Cloud's ~1GB
memory ceiling (checklist 5.2's flagged, unverified risk), running
PaddleOCR as primary across a PDF with a large number of pages needing
OCR (a bulk scan) risks compounding that cost across the whole document.
choose_engine_order() decides PER PDF, once, based on how many of its
pages actually need OCR (checklist 2.2's needs_ocr, counted before any
OCR runs): at or under HEAVY_LOAD_THRESHOLD pages, PaddleOCR stays
primary (its accuracy is worth it at that volume); above the threshold,
Tesseract becomes primary and PaddleOCR becomes the fallback for
whichever pages Tesseract can't read - trading a little per-page
accuracy for staying inside the resource budget across a heavy document.
This is a per-document decision, not a per-page one - so it can't ping-
pong mid-document.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable, MutableMapping, Optional

import pymupdf as fitz
from PIL import Image

from ocr.text_check import PdfProcessingError, check_pdf_text_layers

DEFAULT_DPI = 200  # PyMuPDF's baseline is 72 dpi; zoom = dpi / 72.0.
# 200 dpi is the well-known OCR sweet spot: comfortably legible for
# small/dense certificate text without the multi-second-per-page cost
# of going much higher.

HEAVY_LOAD_THRESHOLD = 15  # pages needing OCR in one PDF - see "Load-based engine routing" above

ProgressCallback = Callable[[int, int], None]  # (pages_done, pages_total)


@dataclass(frozen=True)
class OcrPageResult:
    """The resolved outcome for one page - whichever path produced it."""

    pdf_name: str
    page_number: int  # 1-indexed
    text: str
    engine: str  # "native" | "paddleocr" | "tesseract" | "failed"
    success: bool
    error: Optional[str] = None


# ------------------------------------------------------------ rasterize --


def rasterize_page(page: fitz.Page, *, dpi: int = DEFAULT_DPI) -> Image.Image:
    """Render a page to a PIL Image at the given resolution. No temp
    files - the pixmap's raw samples are wrapped directly into memory.
    """
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


# ---------------------------------------------------------------- paddle --

_paddle_ocr_singleton = None  # lazy: model load is expensive, do it once


def _get_paddle_ocr():
    global _paddle_ocr_singleton
    if _paddle_ocr_singleton is None:
        from paddleocr import PaddleOCR

        _paddle_ocr_singleton = PaddleOCR(
            use_textline_orientation=True,
            lang="en",
            enable_mkldnn=(sys.platform == "linux"),  # off on Windows (this dev machine's crash), on for cloud CPU vectorization
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )
    return _paddle_ocr_singleton


def _ocr_with_paddle(image: Image.Image) -> str:
    import numpy as np

    ocr = _get_paddle_ocr()
    result = ocr.predict(np.array(image))
    if not result:
        return ""
    texts = result[0].get("rec_texts", [])
    return "\n".join(texts)


# ------------------------------------------------------------ tesseract --


def _resolve_tesseract_cmd() -> str:
    """Locate the Tesseract binary without assuming any one OS.

    Priority: an explicit TESSERACT_CMD env var always wins (works on any
    platform); then shutil.which("tesseract") (resolves the standard
    /usr/bin/tesseract that `packages.txt`'s `tesseract-ocr` apt package
    installs on Streamlit Community Cloud, or any other Linux/Mac box with
    Tesseract on PATH); only as a last resort, the Windows UB-Mannheim
    build's default install location, since that's this project's own
    local dev environment (checklist 0.5) and a reasonable final guess.
    """
    import shutil

    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd:
        return env_cmd
    which_cmd = shutil.which("tesseract")
    if which_cmd:
        return which_cmd
    return r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _ocr_with_tesseract(image: Image.Image) -> str:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _resolve_tesseract_cmd()
    return pytesseract.image_to_string(image)


# -------------------------------------------------------- engine routing --


def _engine_func(name: str) -> Callable[[Image.Image], str]:
    """Resolves _ocr_with_paddle/_ocr_with_tesseract by name, looked up
    fresh on every call (not a dict of function references captured
    once) specifically so tests that monkeypatch
    ocr_pipeline._ocr_with_paddle/_ocr_with_tesseract directly - the
    established pattern in this project's test suite - keep working
    exactly as before.
    """
    if name == "paddleocr":
        return _ocr_with_paddle
    if name == "tesseract":
        return _ocr_with_tesseract
    raise ValueError(f"unknown OCR engine: {name!r}")


def choose_engine_order(needs_ocr_count: int) -> tuple[str, str]:
    """Per-PDF primary/fallback engine choice from how many of its pages
    need OCR - see module docstring's "Load-based engine routing".
    Returns (primary_engine, fallback_engine).
    """
    if needs_ocr_count > HEAVY_LOAD_THRESHOLD:
        return "tesseract", "paddleocr"
    return "paddleocr", "tesseract"


# ------------------------------------------------------------- per-page --


def ocr_page(
    pdf_name: str,
    page: fitz.Page,
    page_number: int,
    *,
    dpi: int = DEFAULT_DPI,
    primary_engine: str = "paddleocr",
    fallback_engine: str = "tesseract",
) -> OcrPageResult:
    """Actually run OCR on one page: primary_engine first, fallback_engine
    if that raises anything at all (which engine is primary is decided
    per-PDF by choose_engine_order(), defaulting to PaddleOCR-primary for
    any caller - e.g. direct tests - that doesn't pass the pair
    explicitly). Never raises itself - a failure of both engines becomes
    engine="failed", success=False with both errors recorded, not an
    exception the caller has to handle.
    """
    image = rasterize_page(page, dpi=dpi)
    primary_func = _engine_func(primary_engine)
    fallback_func = _engine_func(fallback_engine)

    try:
        text = primary_func(image)
        return OcrPageResult(pdf_name, page_number, text, primary_engine, True)
    except Exception as primary_exc:  # noqa: BLE001 - PaddleOCR/PaddleX has no stable exception hierarchy to narrow to
        try:
            text = fallback_func(image)
            return OcrPageResult(pdf_name, page_number, text, fallback_engine, True)
        except Exception as fallback_exc:  # noqa: BLE001 - genuinely last resort
            return OcrPageResult(
                pdf_name,
                page_number,
                "",
                "failed",
                False,
                error=(
                    f"{primary_engine} failed ({primary_exc}); "
                    f"{fallback_engine} fallback also failed ({fallback_exc})"
                ),
            )


# -------------------------------------------------------------- pdf-wide --


def resolve_pdf_text(
    pdf_name: str,
    pdf_bytes: bytes,
    *,
    dpi: int = DEFAULT_DPI,
    cache: Optional[MutableMapping[tuple[str, int], OcrPageResult]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> list[OcrPageResult]:
    """Resolve every page of a PDF: reuse the existing text layer where
    checklist 2.2's pre-check says it's usable (engine="native", no OCR
    engine invoked at all), OCR the rest, and pass a genuinely
    blank/uncertain page through as engine="native" too (empty text -
    nothing to gain from OCR without an image, per ocr/text_check.py).

    Raises PdfProcessingError for corrupt/password-protected bytes
    (checklist 5.1) - propagated from check_pdf_text_layers() below, so
    the caller only ever has one exception type to catch regardless of
    which stage detects the problem. Callers processing multiple
    documents (checklist 5.1's per-document orchestration) must catch
    this per document so one bad PDF never aborts its siblings.
    """
    pre_checks = check_pdf_text_layers(pdf_name, pdf_bytes)  # raises PdfProcessingError, uncaught here on purpose
    results: list[OcrPageResult] = []
    total = len(pre_checks)

    needs_ocr_count = sum(1 for pre in pre_checks if pre.needs_ocr)
    primary_engine, fallback_engine = choose_engine_order(needs_ocr_count)

    try:
        doc_cm = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - defense-in-depth; check_pdf_text_layers already opened these same bytes once
        raise PdfProcessingError(f"'{pdf_name}' could not be re-opened for OCR: {exc}") from exc

    with doc_cm as doc:
        for i, pre in enumerate(pre_checks):
            page_number = pre.page_number
            cache_key = (pdf_name, page_number)

            if pre.has_usable_text:
                result = OcrPageResult(pdf_name, page_number, pre.text, "native", True)
            elif pre.needs_ocr:
                if cache is not None and cache_key in cache:
                    result = cache[cache_key]
                else:
                    page = doc[page_number - 1]
                    result = ocr_page(
                        pdf_name, page, page_number, dpi=dpi,
                        primary_engine=primary_engine, fallback_engine=fallback_engine,
                    )
                    if cache is not None:
                        cache[cache_key] = result
            else:
                # Neither usable nor needs_ocr: blank/near-blank page
                # with no image - nothing more to extract.
                result = OcrPageResult(pdf_name, page_number, pre.text, "native", True)

            results.append(result)
            if progress_callback is not None:
                progress_callback(i + 1, total)

    return results
