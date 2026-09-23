"""Ingest -> OCR -> search-index -> per-column resolution pipeline
(checklists 5.1 and 3.3).

Two stages, wiring together already-built, already-tested pieces:

  1. run_ocr_and_build_index() (checklist 5.1) - turns the session's
     ingested documents into resolved per-page OCR/text records and the
     search-index session-state contract checklist 4.2 defined
     (corpus_index, page_texts, reference_index), via
     ocr.pipeline.resolve_pdf_text, search.bm25_index.build_corpus_index,
     ocr.references.build_index.

  2. resolve_all_columns() (checklist 3.3) - for every schema_column in
     every schema_table currently configured, queries that same index
     with the column's requirement text + stored synonyms
     (search.bm25_index.search, top DEFAULT_POOL_SIZE candidates, merged
     with reference-index hits), then verifies the candidate pool via
     Groq (verify.groq_verifier.resolve_column - already bounded-worker
     and early-stopping at 0.90 by its own defaults, checklist 3.2),
     returning the single best verified result per column. Columns are
     processed one at a time (not also parallelized across each other,
     on top of the concurrency resolve_column already does within one
     column's candidate pool) - deliberately, to keep the total
     concurrent Groq load bounded at exactly max_workers regardless of
     how many columns are configured, not max_workers times the column
     count.

Error isolation is the point of stage 1 for checklist 5.1: a single
corrupt/encrypted/unopenable document must never abort processing for
its siblings. Each document is processed independently inside its own
try/except; a failure produces one warning and that document is
skipped, while every other document still gets processed. Within a
document, per-page OCR failures are already handled by
ocr.pipeline.resolve_pdf_text/ocr_page (checklist 2.3) - a page where
both PaddleOCR and Tesseract fail becomes engine="failed",
success=False, text="", and the next page still gets processed; nothing
here needs to duplicate that.

Overwrite semantics for stage 2: resolve_all_columns() always returns a
FRESH result for every column - it does not know about, and does not
try to preserve, any prior manual edit or earlier automated result
already sitting in st.session_state["resolution_results"]. The caller
(run/run_button.py) replaces the whole dict with this fresh output. This
is a deliberate simplicity choice: "Run Mapping" is an explicit user
action, and partially merging "was this a human correction or a stale
auto-result" per column has no reliable signal to decide on (checklist
4.4 found that even VerificationResult.success alone means either
"Groq resolved it" or "a human edited it" - there's no third state to
distinguish "this should survive a re-run" from "this shouldn't").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from db import crud
from ocr.pipeline import OcrPageResult, resolve_pdf_text
from ocr.references import ReferenceIndex, build_index
from ocr.text_check import PdfProcessingError
from search.bm25_index import CorpusIndex, PageRecord, build_corpus_index
from search.bm25_index import search as bm25_search
from verify.groq_verifier import VerificationResult, resolve_column


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


_UNRESOLVED_RESULT = VerificationResult(
    pdf_name="", page_number_or_range="", confidence=0.0, match_snippet="",
    reasoning="No candidate pages were found to verify against.", success=False, error=None,
)


def resolve_all_columns(
    conn,
    corpus_index: CorpusIndex,
    page_texts: dict[tuple[str, int], str],
    reference_index: Optional[ReferenceIndex] = None,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[int, VerificationResult]:
    """For every schema_column in every schema_table currently
    configured (read fresh from conn - never cached across calls), run
    the full search+verify pipeline and return the single best verified
    result per column, keyed by column.id - the exact shape
    st.session_state["resolution_results"] expects.

    A column whose BM25 search returns zero candidates at all (only
    possible when corpus_index itself has zero pages - see
    search.bm25_index.search's own guard) resolves to a clear
    "unresolved" placeholder rather than None, so every configured
    column always gets an entry - never silently missing.

    progress_callback, if given, is called as (columns_done,
    columns_total, column_name) once per column, after that column
    finishes.
    """
    results: dict[int, VerificationResult] = {}

    tables = crud.get_tables(conn)
    all_columns = [(table, column) for table in tables for column in crud.get_columns(conn, table.id)]
    total = len(all_columns)

    for i, (_table, column) in enumerate(all_columns):
        synonyms = [s.synonym_text for s in crud.get_synonyms(conn, column.id)]
        candidates = bm25_search(
            corpus_index, column.requirement_text, synonyms,
            reference_index=reference_index,
        )

        if candidates:
            best = resolve_column(column.name, column.requirement_text, candidates, page_texts)
        else:
            best = None

        results[column.id] = best if best is not None else _UNRESOLVED_RESULT

        if progress_callback is not None:
            progress_callback(i + 1, total, column.name)

    return results
