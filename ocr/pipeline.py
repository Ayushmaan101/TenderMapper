"""OCR pipeline (checklist 2.3): resolve final text for every page of a
PDF, using the checklist-2.2 text-layer pre-check to skip OCR wherever a
real text layer already exists, and PaddleOCR (falling back to
Tesseract) for the pages that don't.

Environment quirks found and worked around, both required for PaddleOCR
to run at all in this project's dev environment (paddlepaddle 3.3.1,
CPU, Windows) - not just test-time conveniences:

  - enable_mkldnn=False: with oneDNN acceleration on, the PP-OCRv6
    detection model crashes on every call with a Paddle-internal error
    ("ConvertPirAttribute2RuntimeAttribute not support
    [pir::ArrayAttribute<pir::DoubleAttribute>]"), a PIR/oneDNN
    incompatibility in this paddlepaddle build, not anything in this
    project's code. Disabling oneDNN avoids the broken code path
    entirely; CPU inference still works, just without that acceleration.
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
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, MutableMapping, Optional

import pymupdf as fitz
from PIL import Image

from ocr.text_check import PdfProcessingError, check_pdf_text_layers

DEFAULT_DPI = 200  # PyMuPDF's baseline is 72 dpi; zoom = dpi / 72.0.
# 200 dpi is the well-known OCR sweet spot: comfortably legible for
# small/dense certificate text without the multi-second-per-page cost
# of going much higher.

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
            enable_mkldnn=False,
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


# ------------------------------------------------------------- per-page --


def ocr_page(pdf_name: str, page: fitz.Page, page_number: int, *, dpi: int = DEFAULT_DPI) -> OcrPageResult:
    """Actually run OCR on one page: PaddleOCR first, Tesseract if that
    raises anything at all. Never raises itself - a failure of both
    engines becomes engine="failed", success=False with both errors
    recorded, not an exception the caller has to handle.
    """
    image = rasterize_page(page, dpi=dpi)

    try:
        text = _ocr_with_paddle(image)
        return OcrPageResult(pdf_name, page_number, text, "paddleocr", True)
    except Exception as paddle_exc:  # noqa: BLE001 - PaddleOCR/PaddleX has no stable exception hierarchy to narrow to
        try:
            text = _ocr_with_tesseract(image)
            return OcrPageResult(pdf_name, page_number, text, "tesseract", True)
        except Exception as tess_exc:  # noqa: BLE001 - genuinely last resort
            return OcrPageResult(
                pdf_name,
                page_number,
                "",
                "failed",
                False,
                error=f"PaddleOCR failed ({paddle_exc}); Tesseract fallback also failed ({tess_exc})",
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
                    result = ocr_page(pdf_name, page, page_number, dpi=dpi)
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
