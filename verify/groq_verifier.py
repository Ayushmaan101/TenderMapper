"""Groq verification / rerank (checklist 3.2).

Reads each BM25 candidate page's text against a schema column's
requirement text and returns structured JSON:
{pdf_name, page_number_or_range, confidence, match_snippet, reasoning}.
This is where BM25's "wide candidate pool, not top-5" pays off
(PROJECT_HARNESS.md §3 step 6-7): BM25 finds pages that plausibly share
vocabulary with the requirement; this step reads each one and judges
whether it's ACTUALLY the right document, penalizing a page that merely
mentions a related term in passing.

Model: openai/gpt-oss-120b. The harness originally specified Llama 3.3
70B here too (same as checklist 1.4's synonym expansion); that model
does not exist on this Groq account (checklist 1.4 finding), so the same
substitution is used here for consistency, per explicit approval.

pdf_name / page_number_or_range are NOT trusted from the model's JSON
echo - they're always taken from the candidate we already know we asked
about, never from what the model reports back. The model's response
schema still asks for them (matching the checklist's literal schema
requirement, and because it seems to measurably help the model reason
about which page it's looking at), but nothing downstream reads them
from the parsed JSON. This closes off a whole class of "model echoed a
different filename/page than the one it was actually shown" bugs for
information we already hold with certainty.

Resilience contract: verify_candidate() never raises. Every failure mode
(missing key, any Groq SDK exception, malformed/unparseable JSON) falls
back to a VerificationResult with success=False, confidence=0.0 (never a
number that could masquerade as a real match), the candidate's own BM25
snippet kept as the visible context, and a reasoning string that says
plainly this needs human review - exactly the checklist's "fall back to
a default candidate score with a note for human review."

Concurrency: verify_candidates() evaluates the candidate pool through a
bounded ThreadPoolExecutor (default 5 workers - conservative against
Groq's per-account rate limits) AND stops early the moment a result
clears early_stop_confidence (default 0.90): once found, any
not-yet-started candidate calls are cancelled. Already-in-flight calls
(at most max_workers-1) are still awaited before returning, rather than
left running as orphaned background threads after the function returns -
a deliberate, documented tradeoff of a few extra seconds of wall-clock
for predictable, leak-free shutdown.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

from search.bm25_index import SearchCandidate

load_dotenv()

MODEL = "openai/gpt-oss-120b"

MAX_PAGE_TEXT_CHARS = 4000
DEFAULT_MAX_WORKERS = 5
DEFAULT_EARLY_STOP_CONFIDENCE = 0.90
RATE_LIMIT_BACKOFF_SECONDS = 1.5

SYSTEM_PROMPT = (
    "You are verifying whether a specific page from a company's tender-compliance "
    "document submission genuinely satisfies a stated requirement.\n\n"
    "You will be given the requirement's short column name and its full requirement "
    "text (what must be proven), plus one candidate page's extracted text, source PDF "
    "filename, and page number.\n\n"
    "Read the page text carefully and judge whether it ACTUALLY satisfies the "
    "requirement - not just whether it superficially mentions related words.\n\n"
    "Penalize:\n"
    "- Pages that merely mention a related term in passing without being the actual "
    "document/certificate/proof the requirement calls for.\n"
    "- Generic boilerplate, section headers, or table-of-contents entries that "
    "reference the requirement's subject without providing the actual evidence.\n"
    "- OCR noise or unrelated content that happens to share vocabulary.\n\n"
    "Reward:\n"
    "- Pages that are clearly the actual certificate/license/document/undertaking the "
    "requirement describes, with matching specifics (dates, numbers, issuing "
    "authority, etc.) where visible.\n\n"
    "Respond with a JSON object of EXACTLY this form:\n"
    "{\n"
    '  "pdf_name": "<the exact pdf_name given to you>",\n'
    '  "page_number_or_range": "<the exact page number given to you, as a string>",\n'
    '  "confidence": <float between 0.0 and 1.0>,\n'
    '  "match_snippet": "<a short verbatim excerpt (<=200 chars) from the page text '
    "that best supports your judgment, or an empty string if the page does not match "
    'at all>",\n'
    '  "reasoning": "<one or two sentences explaining your judgment>"\n'
    "}\n\n"
    "Confidence guide: 0.9-1.0 = clearly and specifically satisfies the requirement; "
    "0.5-0.8 = plausible but uncertain or only partial; 0.0-0.4 = does not satisfy it "
    "(wrong document, passing mention only, or irrelevant).\n"
    "Valid JSON only. No markdown, no extra text."
)


@dataclass(frozen=True)
class VerificationResult:
    pdf_name: str
    page_number_or_range: str
    confidence: float
    match_snippet: str
    reasoning: str
    success: bool
    error: Optional[str] = None


def _describe_groq_error(exc: Exception) -> str:
    from groq import (
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )

    if isinstance(exc, AuthenticationError):
        return "Groq rejected the API key (authentication failed). Check GROQ_API_KEY in .env."
    if isinstance(exc, RateLimitError):
        return "Groq rate limit hit (HTTP 429)."
    if isinstance(exc, APITimeoutError):
        return "Groq request timed out."
    if isinstance(exc, APIConnectionError):
        return f"Could not reach Groq (connection error): {exc}"
    return f"Groq verification call failed: {exc}"


def _is_retryable(exc: Exception) -> bool:
    from groq import (
        APIConnectionError,
        APITimeoutError,
        BadRequestError,
        InternalServerError,
        RateLimitError,
    )

    return isinstance(
        exc,
        (APIConnectionError, APITimeoutError, BadRequestError, InternalServerError, RateLimitError),
    )


def _is_rate_limit(exc: Exception) -> bool:
    from groq import RateLimitError

    return isinstance(exc, RateLimitError)


def _fallback_result(candidate: SearchCandidate, error: str) -> VerificationResult:
    return VerificationResult(
        pdf_name=candidate.pdf_name,
        page_number_or_range=str(candidate.page_number),
        confidence=0.0,
        match_snippet=candidate.snippet,
        reasoning=f"Verification unavailable - flagged for human review. {error}",
        success=False,
        error=error,
    )


def _parse_verification_response(raw_text: str, candidate: SearchCandidate) -> VerificationResult:
    """Tolerates a markdown code fence and surrounding whitespace, same
    as config/synonyms.py's response parsing. pdf_name and
    page_number_or_range are taken from `candidate`, never from the
    model's own echoed values - see module docstring.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    snippet = data.get("match_snippet")
    snippet = str(snippet) if snippet is not None else ""
    reasoning = data.get("reasoning")
    reasoning = str(reasoning) if reasoning is not None else ""

    return VerificationResult(
        pdf_name=candidate.pdf_name,
        page_number_or_range=str(candidate.page_number),
        confidence=confidence,
        match_snippet=snippet,
        reasoning=reasoning,
        success=True,
        error=None,
    )


def verify_candidate(
    column_name: str,
    requirement_text: str,
    candidate: SearchCandidate,
    page_text: str,
    *,
    timeout: float = 20.0,
    max_attempts: int = 3,
) -> VerificationResult:
    """Verify one candidate page against one requirement. Never raises -
    see module docstring's resilience contract.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return _fallback_result(candidate, "GROQ_API_KEY is not set. Check your .env file.")

    truncated = page_text[:MAX_PAGE_TEXT_CHARS]
    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        truncated += "… [truncated]"

    user_content = (
        f"Requirement column: {column_name}\n\n"
        f"Requirement text: {requirement_text}\n\n"
        "---\n\n"
        f"Candidate page:\nPDF: {candidate.pdf_name}\nPage: {candidate.page_number}\n\n"
        f"Page text:\n{truncated}"
    )

    last_error = "Unknown error."
    for attempt in range(max_attempts):
        is_last_attempt = attempt == max_attempts - 1

        try:
            client = Groq(api_key=api_key, timeout=timeout)
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=800,
            )
        except Exception as exc:  # noqa: BLE001 - see module docstring
            last_error = _describe_groq_error(exc)
            if _is_retryable(exc) and not is_last_attempt:
                if _is_rate_limit(exc):
                    time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
                continue
            return _fallback_result(candidate, last_error)

        try:
            raw = response.choices[0].message.content
            return _parse_verification_response(raw, candidate)
        except Exception as exc:  # noqa: BLE001 - malformed/unexpected model output
            last_error = f"Could not parse Groq's response: {exc}"
            if not is_last_attempt:
                continue
            return _fallback_result(candidate, last_error)

    return _fallback_result(candidate, last_error)


def verify_candidates(
    column_name: str,
    requirement_text: str,
    candidates: list[SearchCandidate],
    page_texts: dict[tuple[str, int], str],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    early_stop_confidence: float = DEFAULT_EARLY_STOP_CONFIDENCE,
) -> list[VerificationResult]:
    """Evaluate a candidate pool concurrently, sorted by confidence
    descending. Stops submitting new work once a result clears
    early_stop_confidence; already-in-flight calls are still awaited
    (see module docstring).

    page_texts maps (pdf_name, page_number) -> full resolved page text.
    A candidate missing from page_texts falls back to its own BM25
    snippet as the text sent to Groq (better than skipping it outright).
    """
    if not candidates:
        return []

    results: list[VerificationResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_candidate = {}
        for candidate in candidates:
            page_text = page_texts.get((candidate.pdf_name, candidate.page_number), candidate.snippet)
            future = executor.submit(verify_candidate, column_name, requirement_text, candidate, page_text)
            future_to_candidate[future] = candidate

        pending = set(future_to_candidate)
        for future in as_completed(future_to_candidate):
            pending.discard(future)
            result = future.result()  # verify_candidate never raises
            results.append(result)
            if result.success and result.confidence >= early_stop_confidence:
                for other in pending:
                    other.cancel()  # best-effort: only cancels not-yet-started futures
                break

    return sorted(results, key=lambda r: r.confidence, reverse=True)


def resolve_column(
    column_name: str,
    requirement_text: str,
    candidates: list[SearchCandidate],
    page_texts: dict[tuple[str, int], str],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    early_stop_confidence: float = DEFAULT_EARLY_STOP_CONFIDENCE,
) -> Optional[VerificationResult]:
    """The top-ranked verified result for one schema column, or None if
    there were no candidates to evaluate at all.
    """
    results = verify_candidates(
        column_name, requirement_text, candidates, page_texts,
        max_workers=max_workers, early_stop_confidence=early_stop_confidence,
    )
    return results[0] if results else None
