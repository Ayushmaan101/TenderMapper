"""Ingest -> OCR/text-layer resolution bridge (checklist 5.1).

Builds a real, tested slice of checklist 3.3's still-pending per-column
resolution loop: turns the session's ingested documents into resolved
per-page OCR/text records and the search-index session-state contract
checklist 4.2 defined (corpus_index, page_texts, reference_index) - by
wiring together already-built, already-tested pieces
(ocr.pipeline.resolve_pdf_text, search.bm25_index.build_corpus_index,
ocr.references.build_index). Deliberately does NOT run BM25 candidate
search or Groq verification per schema column - that is the remaining,
still-deferred substance of checklist 3.3 (for every column in every
configured table, search + verify): see CHECKLIST.md.

Error isolation is the actual point of this module for checklist 5.1: a
single corrupt/encrypted/unopenable document must never abort processing
for its siblings. Each document is processed independently inside its
own try/except; a failure produces one warning and that document is
skipped, while every other document still gets processed. Within a
document, per-page OCR failures are already handled by
ocr.pipeline.resolve_pdf_text/ocr_page (checklist 2.3) - a page where
both PaddleOCR and Tesseract fail becomes engine="failed",
success=False, text="", and the next page still gets processed; nothing
here needs to duplicate that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ocr.pipeline import OcrPageResult, resolve_pdf_text
from ocr.references import ReferenceIndex, build_index
from ocr.text_check import PdfProcessingError
from search.bm25_index import CorpusIndex, PageRecord, build_corpus_index


@dataclass
class RunOutcome:
    ocr_results: list[OcrPageResult] = field(default_factory=list)
    document_warnings: list[str] = field(default_factory=list)
    processed_document_count: int = 0
    skipped_document_count: int = 0


def run_ocr_and_build_index(
    documents,
    *,
    ocr_cache: Optional[dict] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> tuple[RunOutcome, CorpusIndex, dict[tuple[str, int], str], ReferenceIndex]:
    """documents: list[ingest.models.IngestedDocument]. Returns
    (outcome, corpus_index, page_texts, reference_index) - the last
    three are exactly the shapes checklist 4.2's session-state contract
    expects (CORPUS_INDEX_KEY/PAGE_TEXTS_KEY/REFERENCE_INDEX_KEY in
    run/results.py).

    progress_callback, if given, is called as (pdf_name, pages_done,
    pages_total) once per page within the CURRENT document - it does not
    track progress across documents, since document count/order can
    change based on what fails.
    """
    outcome = RunOutcome()

    for doc in documents:
        per_doc_progress = (
            (lambda done, total, name=doc.name: progress_callback(name, done, total))
            if progress_callback is not None
            else None
        )
        try:
            page_results = resolve_pdf_text(doc.name, doc.data, cache=ocr_cache, progress_callback=per_doc_progress)
        except PdfProcessingError as exc:
            outcome.document_warnings.append(str(exc))
            outcome.skipped_document_count += 1
            continue
        except Exception as exc:  # noqa: BLE001 - a single document must never take down the whole run
            outcome.document_warnings.append(f"'{doc.name}' could not be processed: {exc}")
            outcome.skipped_document_count += 1
            continue

        outcome.ocr_results.extend(page_results)
        outcome.processed_document_count += 1

    page_records = [PageRecord(r.pdf_name, r.page_number, r.text) for r in outcome.ocr_results]
    corpus_index = build_corpus_index(page_records)
    page_texts = {(r.pdf_name, r.page_number): r.text for r in outcome.ocr_results}
    reference_index = build_index((r.pdf_name, r.page_number, r.text) for r in outcome.ocr_results)

    return outcome, corpus_index, page_texts, reference_index
