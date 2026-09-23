"""Ingest -> OCR -> search-index -> per-column resolution pipeline
(checklists 5.1 and 3.3).

Two stages, wiring together already-built, already-tested pieces:

  1. run_ocr_and_build_index() (checklist 5.1) - turns the session's
     ingested documents into resolved per-page OCR/text records and the
     search-index session-state contract checklist 4.2 defined
     (corpus_index, page_texts, reference_index), via
     ocr.pipeline.resolve_pdf_text, search.bm25_index.build_corpus_index,
     ocr.references.build_index. document_progress_callback, if given,
     fires once per document (before that document's own pages start
     processing) with (doc_index, doc_total, pdf_name) - the "Processing
     document X of Y" counter (Run tab UI lifecycle refinement); separate
     from the existing per-page progress_callback, which reports
     progress WITHIN whichever document is currently running.

  2. resolve_all_columns() (checklist 3.3, rewritten for the Groq
     rate-limit fix) - for every schema_column in every schema_table
     currently configured, queries that same index with the column's
     requirement text + stored synonyms (search.bm25_index.search, top
     TOP_K_CANDIDATES candidates, merged with reference-index hits), then
     verifies that small candidate pool via ONE batched Groq call
     (verify.groq_verifier.resolve_column - checklist 3.2, rewritten to
     evaluate every candidate in a single call rather than one call per
     candidate). BM25 search itself runs sequentially, up front, on the
     main thread for every column BEFORE any Groq call starts - it's
     fast, in-memory, and reads the shared sqlite3 connection (`conn`)
     via crud.get_synonyms(), which is not safe to call concurrently from
     multiple threads even with check_same_thread=False (see
     db/connection.py). Only the actual Groq calls - the slow,
     rate-limited step, and the only step that no longer touches `conn`
     at all once candidates are in hand - run through a small bounded
     ThreadPoolExecutor across columns (COLUMN_MAX_WORKERS, default 3),
     with a short delay between each submission (COLUMN_SUBMIT_DELAY_SECONDS)
     so ~20+ columns don't all fire through the pool at once. Results are
     collected via as_completed(), so progress_callback fires in
     COMPLETION order (not configured order) as each column's single call
     actually finishes - this is what lets run/run_button.py stream rows
     into a live preview table as they arrive, rather than only after
     every column is done.

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

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from db import crud
from ocr.pipeline import OcrPageResult, resolve_pdf_text
from ocr.references import ReferenceIndex, build_index
from ocr.text_check import PdfProcessingError
from search.bm25_index import CorpusIndex, PageRecord, build_corpus_index
from search.bm25_index import search as bm25_search
from verify.groq_verifier import VerificationResult, resolve_column

TOP_K_CANDIDATES = 5  # BM25 candidates handed to Groq per column, all in ONE batched call (see verify/groq_verifier.py)
COLUMN_MAX_WORKERS = 3  # bounded concurrency ACROSS columns - each column now costs exactly 1 Groq call
COLUMN_SUBMIT_DELAY_SECONDS = 1.0  # staggers submissions into the pool to respect Groq's per-account RPM limits


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
    document_progress_callback: Optional[Callable[[int, int, str], None]] = None,
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

    document_progress_callback, if given, is called as (doc_index,
    doc_total, pdf_name) once per document, BEFORE that document's pages
    start processing (doc_index is 1-based) - the "Processing document X
    of Y (name)" counter (Run tab UI lifecycle refinement). doc_total is
    simply len(documents); a document that later fails still counted
    toward "processing", matching what the user actually watched happen.
    """
    outcome = RunOutcome()
    doc_total = len(documents)

    for doc_index, doc in enumerate(documents, start=1):
        if document_progress_callback is not None:
            document_progress_callback(doc_index, doc_total, doc.name)

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
    progress_callback: Optional[Callable[[int, int, str, int, VerificationResult], None]] = None,
    max_workers: Optional[int] = None,
    submit_delay: Optional[float] = None,
) -> dict[int, VerificationResult]:
    """For every schema_column in every schema_table currently
    configured (read fresh from conn - never cached across calls), run
    the full search+verify pipeline and return the single best verified
    result per column, keyed by column.id - the exact shape
    st.session_state["resolution_results"] expects.

    max_workers/submit_delay default to the COLUMN_MAX_WORKERS/
    COLUMN_SUBMIT_DELAY_SECONDS module constants, resolved fresh on every
    call (not bound as literal parameter defaults) specifically so tests
    can monkeypatch those module-level names - e.g. setting
    COLUMN_SUBMIT_DELAY_SECONDS to 0 to drive the real "Run Mapping"
    button through many AppTest suites without paying ~1s per column in
    wall-clock time - the same pattern ocr/pipeline.py's _engine_func()
    uses for the same reason.

    A column whose BM25 search returns zero candidates at all (only
    possible when corpus_index itself has zero pages - see
    search.bm25_index.search's own guard) resolves to a clear
    "unresolved" placeholder rather than None, so every configured
    column always gets an entry - never silently missing.

    BM25 search (which reads `conn` via crud.get_synonyms) runs
    sequentially first, for every column, on the calling thread - see
    module docstring for why this must not move into the worker pool.
    Only the Groq calls run concurrently, through a small bounded pool.

    progress_callback, if given, is called as (columns_done,
    columns_total, column_name, column_id, result) once per column, as
    each column's Groq call actually completes - in COMPLETION order,
    not configured order, since columns run concurrently. This is what
    lets a caller stream results into a live preview table as they
    arrive (run/run_button.py).
    """
    if max_workers is None:
        max_workers = COLUMN_MAX_WORKERS
    if submit_delay is None:
        submit_delay = COLUMN_SUBMIT_DELAY_SECONDS

    tables = crud.get_tables(conn)
    all_columns = [(table, column) for table in tables for column in crud.get_columns(conn, table.id)]
    total = len(all_columns)
    if total == 0:
        return {}

    column_candidates = []
    for _table, column in all_columns:
        synonyms = [s.synonym_text for s in crud.get_synonyms(conn, column.id)]
        candidates = bm25_search(
            corpus_index, column.requirement_text, synonyms,
            pool_size=TOP_K_CANDIDATES, reference_index=reference_index,
        )
        column_candidates.append((column, candidates))

    def _verify_one(column, candidates) -> VerificationResult:
        if candidates:
            best = resolve_column(column.name, column.requirement_text, candidates, page_texts)
        else:
            best = None
        return best if best is not None else _UNRESOLVED_RESULT

    results: dict[int, VerificationResult] = {}
    done_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_column = {}
        for i, (column, candidates) in enumerate(column_candidates):
            future = executor.submit(_verify_one, column, candidates)
            future_to_column[future] = column
            if submit_delay and i < len(column_candidates) - 1:
                time.sleep(submit_delay)

        for future in as_completed(future_to_column):
            column = future_to_column[future]
            result = future.result()  # _verify_one/resolve_column never raise (see verify/groq_verifier.py)
            results[column.id] = result
            done_count += 1
            if progress_callback is not None:
                progress_callback(done_count, total, column.name, column.id, result)

    return results
