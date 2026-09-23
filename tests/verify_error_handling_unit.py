"""Checklist 5.1 verification — unit-level (no Streamlit).

Covers every error vector at the pure-function level: corrupt PDF bytes
and a real password-protected PDF both raise ocr.text_check's
PdfProcessingError (not a raw PyMuPDF exception) from both
check_pdf_text_layers and resolve_pdf_text, while a genuinely zero-page
PDF does NOT raise (confirming it stays correctly distinguished from a
real error, per checklist 2.2); run/pipeline_runner.py's per-document
isolation - a corrupt/encrypted/zero-page document mixed in with a valid
one, the valid one still fully processes and the bad one(s) produce a
warning, never a crash; single-page OCR failure (both PaddleOCR and
Tesseract mocked to fail) isolated to that one page, sibling pages in
the same document still process; and Groq resilience (missing key,
simulated network drop) in both config/synonyms.py and
verify/groq_verifier.py falling back gracefully rather than raising.

Run: python tests/verify_error_handling_unit.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


CORRUPT_PDF_BYTES = b"%PDF-1.4\ngarbage garbage garbage not real pdf structure\n%%EOF"

ZERO_PAGE_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"trailer\n<< /Size 3 /Root 1 0 R >>\n%%EOF"
)


def make_valid_pdf_bytes(text: str = "Genuine readable content for the test file.") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def make_encrypted_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Secret content", fontsize=12)
    data = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123",
        permissions=int(fitz.PDF_PERM_PRINT),
    )
    doc.close()
    return data


# ------------------------------------------------------- text_check.py --


def test_check_pdf_text_layers_error_cases() -> None:
    from ocr.text_check import PdfProcessingError, check_pdf_text_layers

    try:
        check_pdf_text_layers("corrupt.pdf", CORRUPT_PDF_BYTES)
        check("corrupt bytes -> check_pdf_text_layers raises PdfProcessingError", False)
    except PdfProcessingError as exc:
        check("corrupt bytes -> check_pdf_text_layers raises PdfProcessingError", True)
        check("...with a message naming the file and the likely cause", "corrupt.pdf" in str(exc) and "corrupted" in str(exc).lower())

    try:
        check_pdf_text_layers("secret.pdf", make_encrypted_pdf_bytes())
        check("password-protected PDF -> check_pdf_text_layers raises PdfProcessingError", False)
    except PdfProcessingError as exc:
        check("password-protected PDF -> check_pdf_text_layers raises PdfProcessingError", True)
        check("...with a message naming the file and 'password'", "secret.pdf" in str(exc) and "password" in str(exc).lower())

    # Zero-page: NOT an error - stays distinct from a real failure.
    results = check_pdf_text_layers("empty.pdf", ZERO_PAGE_PDF_BYTES)
    check("zero-page PDF -> does NOT raise (returns [], not an error)", results == [])


def test_resolve_pdf_text_error_cases() -> None:
    from ocr.pipeline import resolve_pdf_text
    from ocr.text_check import PdfProcessingError

    try:
        resolve_pdf_text("corrupt.pdf", CORRUPT_PDF_BYTES)
        check("corrupt bytes -> resolve_pdf_text raises PdfProcessingError (same type as text_check)", False)
    except PdfProcessingError:
        check("corrupt bytes -> resolve_pdf_text raises PdfProcessingError (same type as text_check)", True)

    try:
        resolve_pdf_text("secret.pdf", make_encrypted_pdf_bytes())
        check("password-protected PDF -> resolve_pdf_text raises PdfProcessingError", False)
    except PdfProcessingError:
        check("password-protected PDF -> resolve_pdf_text raises PdfProcessingError", True)

    results = resolve_pdf_text("empty.pdf", ZERO_PAGE_PDF_BYTES)
    check("zero-page PDF -> resolve_pdf_text does NOT raise (returns [])", results == [])

    valid_results = resolve_pdf_text("valid.pdf", make_valid_pdf_bytes())
    check("a genuinely valid PDF is entirely unaffected by these guards", len(valid_results) == 1 and valid_results[0].success)


# -------------------------------------------------- per-document isolation --


def test_pipeline_runner_isolates_bad_documents() -> None:
    from ingest.models import IngestedDocument
    from run.pipeline_runner import run_ocr_and_build_index

    documents = [
        IngestedDocument(name="valid1.pdf", data=make_valid_pdf_bytes("First valid document content."), source_path="valid1.pdf"),
        IngestedDocument(name="corrupt.pdf", data=CORRUPT_PDF_BYTES, source_path="corrupt.pdf"),
        IngestedDocument(name="secret.pdf", data=make_encrypted_pdf_bytes(), source_path="secret.pdf"),
        IngestedDocument(name="empty.pdf", data=ZERO_PAGE_PDF_BYTES, source_path="empty.pdf"),
        IngestedDocument(name="valid2.pdf", data=make_valid_pdf_bytes("Second valid document, different content."), source_path="valid2.pdf"),
    ]

    outcome, corpus_index, page_texts, reference_index = run_ocr_and_build_index(documents)

    check("2 of 5 documents genuinely failed (corrupt + encrypted)", outcome.skipped_document_count == 2)
    check(
        "3 of 5 documents processed successfully (2 valid + 1 zero-page, which is not an error)",
        outcome.processed_document_count == 3,
    )
    check("exactly 2 warnings recorded (one per genuinely-bad document)", len(outcome.document_warnings) == 2)
    check("the corrupt document's warning names it", any("corrupt.pdf" in w for w in outcome.document_warnings))
    check("the encrypted document's warning names it", any("secret.pdf" in w for w in outcome.document_warnings))
    check("the zero-page document did NOT produce a warning (not an error)", not any("empty.pdf" in w for w in outcome.document_warnings))

    check("both valid documents' pages made it into the OCR results", len(outcome.ocr_results) == 2)
    check("the search index only contains the 2 valid documents' pages", len(corpus_index) == 2)
    check("page_texts has exactly 2 entries", len(page_texts) == 2)
    check(
        "no corrupt/encrypted/zero-page document's name leaked into page_texts",
        not any(name in ("corrupt.pdf", "secret.pdf", "empty.pdf") for name, _page in page_texts),
    )


def test_pipeline_runner_empty_documents_list() -> None:
    from run.pipeline_runner import run_ocr_and_build_index

    outcome, corpus_index, page_texts, reference_index = run_ocr_and_build_index([])
    check("empty documents list -> no crash", outcome.processed_document_count == 0 and outcome.skipped_document_count == 0)
    check("empty documents list -> empty index, not an error", len(corpus_index) == 0 and page_texts == {})


def test_pipeline_runner_all_documents_bad() -> None:
    """Every document fails - still no crash, just an empty (but valid)
    result with warnings for all of them.
    """
    from ingest.models import IngestedDocument
    from run.pipeline_runner import run_ocr_and_build_index

    documents = [
        IngestedDocument(name="bad1.pdf", data=CORRUPT_PDF_BYTES, source_path="bad1.pdf"),
        IngestedDocument(name="bad2.pdf", data=CORRUPT_PDF_BYTES, source_path="bad2.pdf"),
    ]
    outcome, corpus_index, page_texts, reference_index = run_ocr_and_build_index(documents)
    check("all documents bad -> no crash", outcome.skipped_document_count == 2 and outcome.processed_document_count == 0)
    check("all documents bad -> 2 warnings, empty index", len(outcome.document_warnings) == 2 and len(corpus_index) == 0)


# --------------------------------------------------- single-page OCR failure --


def test_single_page_ocr_failure_does_not_abort_document() -> None:
    """Both PaddleOCR and Tesseract fail on ONE page of a 3-page scanned
    document - that page becomes engine="failed", the other two pages
    are entirely unaffected and still process. Mirrors checklist 2.3's
    own resilience contract; re-verified here under 5.1's own umbrella
    with a multi-page document specifically.
    """
    import ocr.pipeline as ocr_pipeline_mod

    doc = fitz.open()
    for i in range(3):
        w, h = 60, 60
        samples = bytes([120, 120, 120] * (w * h))
        pix = fitz.Pixmap(fitz.csRGB, w, h, samples, False)
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, page.rect.width, page.rect.height), pixmap=pix)
    pdf_bytes = doc.tobytes()
    doc.close()

    call_count = {"n": 0}
    original_paddle = ocr_pipeline_mod._ocr_with_paddle
    original_tess = ocr_pipeline_mod._ocr_with_tesseract

    def flaky_paddle(image):
        call_count["n"] += 1
        if call_count["n"] == 2:  # fail specifically on the 2nd page
            raise RuntimeError("simulated PaddleOCR failure on page 2")
        return "ok text"

    def flaky_tess(image):
        if call_count["n"] == 2:
            raise RuntimeError("simulated Tesseract failure on page 2 too")
        return "ok text"

    ocr_pipeline_mod._ocr_with_paddle = flaky_paddle
    ocr_pipeline_mod._ocr_with_tesseract = flaky_tess
    try:
        from ocr.pipeline import resolve_pdf_text

        results = resolve_pdf_text("scanned.pdf", pdf_bytes)
    finally:
        ocr_pipeline_mod._ocr_with_paddle = original_paddle
        ocr_pipeline_mod._ocr_with_tesseract = original_tess

    check("document with 1 doubly-failed page still returns all 3 page results", len(results) == 3)
    check("page 1 (unaffected) succeeded normally", results[0].success and results[0].engine == "paddleocr")
    check("page 2 (both engines failed) is marked engine='failed', success=False", results[1].engine == "failed" and results[1].success is False)
    check("page 2's text is empty, not fabricated", results[1].text == "")
    check("page 3 (after the failure) still processed normally - the failure did not abort the document", results[2].success and results[2].engine == "paddleocr")


# --------------------------------------------------------------- Groq --


def test_groq_missing_key_and_network_drop_fallback() -> None:
    """Re-confirms, under checklist 5.1's own umbrella, that both Groq
    call sites (config/synonyms.py, verify/groq_verifier.py) never raise
    and always leave the app in an interactive state - missing key and a
    simulated mid-call network drop, for both modules.
    """
    import config.synonyms as syn_mod
    import verify.groq_verifier as gv_mod
    from search.bm25_index import SearchCandidate

    saved_key = os.environ.pop("GROQ_API_KEY", None)
    try:
        syn_result = syn_mod.expand_synonyms("Column", "Some requirement text")
        check("config/synonyms.py: missing key -> success=False, does not raise", syn_result.success is False)

        candidate = SearchCandidate(pdf_name="a.pdf", page_number=1, rank=1, score=1.0, snippet="s", matched_terms=[], match_signals=["bm25"])
        verify_result = gv_mod.verify_candidate("Column", "Some requirement text", candidate, "page text")
        check("verify/groq_verifier.py: missing key -> success=False, does not raise", verify_result.success is False)
        check("verify/groq_verifier.py: missing key -> confidence is 0.0 (never a fake match)", verify_result.confidence == 0.0)
    finally:
        if saved_key is not None:
            os.environ["GROQ_API_KEY"] = saved_key

    # Simulated mid-call network drop, with a key present.
    os.environ["GROQ_API_KEY"] = "fake-key-for-this-test"
    try:
        class _DroppedConnection(RuntimeError):
            pass

        class _FailingCompletions:
            def create(self, **kwargs):
                raise _DroppedConnection("simulated connection drop mid-call")

        class _FailingClient:
            def __init__(self, *a, **k):
                self.chat = type("Chat", (), {"completions": _FailingCompletions()})()

        original_syn_groq = syn_mod.Groq
        syn_mod.Groq = _FailingClient
        try:
            syn_result2 = syn_mod.expand_synonyms("Column", "Some requirement text")
            check("config/synonyms.py: simulated network drop -> success=False, does not raise", syn_result2.success is False)
        finally:
            syn_mod.Groq = original_syn_groq

        original_gv_groq = gv_mod.Groq
        gv_mod.Groq = _FailingClient
        try:
            verify_result2 = gv_mod.verify_candidate("Column", "req", candidate, "text")
            check("verify/groq_verifier.py: simulated network drop -> success=False, does not raise", verify_result2.success is False)
            check("verify/groq_verifier.py: simulated network drop -> confidence 0.0, error explains why", verify_result2.confidence == 0.0 and bool(verify_result2.error))
        finally:
            gv_mod.Groq = original_gv_groq
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        if saved_key is not None:
            os.environ["GROQ_API_KEY"] = saved_key


def main() -> None:
    test_check_pdf_text_layers_error_cases()
    test_resolve_pdf_text_error_cases()
    test_pipeline_runner_isolates_bad_documents()
    test_pipeline_runner_empty_documents_list()
    test_pipeline_runner_all_documents_bad()
    test_single_page_ocr_failure_does_not_abort_document()
    test_groq_missing_key_and_network_drop_fallback()

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
