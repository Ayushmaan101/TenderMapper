"""Groq verification / rerank (checklist 3.2), batched (checklist
"Groq API rate-limit fix").

Originally one Groq call per BM25 candidate (checklist 3.2), evaluated
through a bounded thread pool with early-stopping. Against a real
Streamlit Community Cloud deployment, hundreds of per-candidate calls
per run both felt slow (the UI blocked until every call finished) and
burned through Groq's free-tier rate limits fast. Rewritten so ONE Groq
call evaluates every candidate for a column at once: all of the
column's BM25 candidates' page text goes into a single prompt, labeled
[Candidate 1], [Candidate 2], ... , and the model picks the single best
match by number. This guarantees exactly 1 API call per column,
regardless of how many candidates that column has - run/pipeline_runner.py
additionally caps candidates to TOP_K_CANDIDATES (5) per column before
they ever reach here, both to keep each prompt a reasonable size and to
keep the model's job (picking the best of a handful of already-strong
BM25 matches) tractable.

This is where BM25's "wide-ish candidate pool" pays off (PROJECT_HARNESS.md
§3 step 6-7): BM25 finds pages that plausibly share vocabulary with the
requirement; this step reads all of them at once and judges which one, if
any, is ACTUALLY the right document - penalizing a page that merely
mentions a related term in passing.

Model: openai/gpt-oss-120b. The harness originally specified Llama 3.3
70B here too (same as checklist 1.4's synonym expansion); that model
does not exist on this Groq account (checklist 1.4 finding), so the same
substitution is used here for consistency, per explicit approval.

pdf_name / page_number_or_range are NOT trusted from the model's JSON
echo - the model is only ever asked to return a 1-based CANDIDATE NUMBER
(best_candidate), which is then used to index back into the candidate
list we already hold with certainty. A number outside 1..len(candidates)
(including the documented 0, meaning "none of them match") anchors the
result to the top-ranked (rank 1) BM25 candidate instead of guessing -
the model can steer WHICH known candidate wins, and how confident we are
in it, but it can never fabricate a pdf_name/page_number_or_range that
isn't one of the candidates we actually sent it. This is the same
"never trust the model's identity echo" principle checklist 3.2
established, adapted from a single implicit candidate to an explicit
numbered set.

Resilience contract: verify_candidates_batch() never raises. Every
failure mode (missing key, any Groq SDK exception, malformed/unparseable
JSON) falls back to a VerificationResult anchored to candidates[0] (the
top-ranked BM25 candidate), success=False, confidence=0.0 (never a
number that could masquerade as a real match), that candidate's own BM25
snippet kept as the visible context, and a reasoning string that says
plainly this needs human review.

Concurrency now lives one level up, in run/pipeline_runner.py: since
each column costs exactly one Groq call, that module runs a small bounded
thread pool ACROSS COLUMNS (2-3 workers) with a staggered submission
delay, rather than this module running a thread pool across candidates
WITHIN one column (there's nothing left to parallelize within a column -
one call, one column).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

from search.bm25_index import SearchCandidate

load_dotenv()

MODEL = "openai/gpt-oss-120b"

MAX_PAGE_TEXT_CHARS_PER_CANDIDATE = 1000  # per candidate, not per prompt - keeps a 5-candidate batch a reasonable total size
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_ATTEMPTS = 3
RATE_LIMIT_BACKOFF_SECONDS = 1.5

BATCH_SYSTEM_PROMPT = (
    "You are verifying which ONE of several candidate pages from a company's "
    "tender-compliance document submission genuinely satisfies a stated requirement.\n\n"
    "You will be given the requirement's short column name and its full requirement "
    "text (what must be proven), plus several numbered candidate pages, each with its "
    "source PDF filename, page number, and extracted text.\n\n"
    "Read each candidate carefully and judge whether it ACTUALLY satisfies the "
    "requirement - not just whether it superficially mentions related words. Then pick "
    "the SINGLE best candidate (or none, if none of them genuinely satisfy it).\n\n"
    "Penalize:\n"
    "- Candidates that merely mention a related term in passing without being the "
    "actual document/certificate/proof the requirement calls for.\n"
    "- Generic boilerplate, section headers, or table-of-contents entries that "
    "reference the requirement's subject without providing the actual evidence.\n"
    "- OCR noise or unrelated content that happens to share vocabulary.\n\n"
    "Reward:\n"
    "- Candidates that are clearly the actual certificate/license/document/undertaking "
    "the requirement describes, with matching specifics (dates, numbers, issuing "
    "authority, etc.) where visible.\n\n"
    "Respond with a JSON object of EXACTLY this form:\n"
    "{\n"
    '  "best_candidate": <integer 1-N, the number of the best-matching candidate, or 0 '
    "if NONE of the candidates genuinely satisfy the requirement>,\n"
    '  "confidence": <float between 0.0 and 1.0 - how strongly the EVIDENCE shows the '
    "requirement is satisfied. This is NOT how sure you are about your own reasoning - "
    "it reflects the strength of the match itself. If best_candidate is 0 (no candidate "
    "satisfies the requirement), confidence MUST be low (0.0-0.4): being certain that "
    "nothing matches is still a LOW-confidence match, never a high number that could be "
    "mistaken for a genuine one>,\n"
    '  "match_snippet": "<a short verbatim excerpt (<=200 chars) from the chosen '
    "candidate's text that best supports your judgment, or an empty string if no "
    'candidate matches>",\n'
    '  "reasoning": "<one or two sentences explaining your judgment, comparing '
    'candidates if it helps>"\n'
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


# Confidence flagging (checklist 4.2) lives here, alongside VerificationResult
# itself, rather than in run/results.py (a UI-layer package) - both
# run/results.py and export/excel_export.py need this rule and neither
# should depend on the other; verify/ is the natural shared, lower-level
# home for anything about interpreting a VerificationResult.
CONFIDENCE_THRESHOLD = 0.70


def is_flagged(result: VerificationResult) -> bool:
    """True if this result needs human review: verification never
    succeeded (covers both "never resolved yet" and "the Groq call
    itself failed"), or it succeeded but scored below
    CONFIDENCE_THRESHOLD. Never silently blank, never silently wrong -
    PROJECT_HARNESS.md §2's stated safety net.
    """
    return (not result.success) or result.confidence < CONFIDENCE_THRESHOLD


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


def _fallback_result(anchor: SearchCandidate, error: str) -> VerificationResult:
    return VerificationResult(
        pdf_name=anchor.pdf_name,
        page_number_or_range=str(anchor.page_number),
        confidence=0.0,
        match_snippet=anchor.snippet,
        reasoning=f"Verification unavailable - flagged for human review. {error}",
        success=False,
        error=error,
    )


def _build_batch_prompt(
    column_name: str,
    requirement_text: str,
    candidates: list[SearchCandidate],
    page_texts: dict[tuple[str, int], str],
) -> str:
    parts = [
        f"Requirement column: {column_name}\n\n"
        f"Requirement text: {requirement_text}\n\n"
        "---\n\n"
        f"You are given {len(candidates)} candidate page(s). Evaluate each one and "
        "identify the single best match by its number.\n"
    ]
    for i, candidate in enumerate(candidates, start=1):
        page_text = page_texts.get((candidate.pdf_name, candidate.page_number), candidate.snippet)
        truncated = page_text[:MAX_PAGE_TEXT_CHARS_PER_CANDIDATE]
        if len(page_text) > MAX_PAGE_TEXT_CHARS_PER_CANDIDATE:
            truncated += "… [truncated]"
        parts.append(
            f"\n[Candidate {i}]\n"
            f"PDF: {candidate.pdf_name}\n"
            f"Page: {candidate.page_number}\n"
            f"Text:\n{truncated}\n"
        )
    return "".join(parts)


def _parse_batch_response(raw_text: str, candidates: list[SearchCandidate]) -> VerificationResult:
    """Tolerates a markdown code fence and surrounding whitespace, same
    as config/synonyms.py's response parsing. The model's best_candidate
    is only ever used to INDEX into `candidates` - see module docstring's
    "never trust the model's JSON echo" note.
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
        best_index = int(data.get("best_candidate", 0))
    except (TypeError, ValueError):
        best_index = 0

    if 1 <= best_index <= len(candidates):
        anchor = candidates[best_index - 1]
    else:
        # 0 ("none match") or an out-of-range/invalid index - anchor to
        # the top-ranked (rank 1) BM25 candidate rather than guessing.
        anchor = candidates[0]

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    snippet = data.get("match_snippet")
    snippet = str(snippet) if snippet else anchor.snippet
    reasoning = data.get("reasoning")
    reasoning = str(reasoning) if reasoning is not None else ""

    return VerificationResult(
        pdf_name=anchor.pdf_name,
        page_number_or_range=str(anchor.page_number),
        confidence=confidence,
        match_snippet=snippet,
        reasoning=reasoning,
        success=True,
        error=None,
    )


def verify_candidates_batch(
    column_name: str,
    requirement_text: str,
    candidates: list[SearchCandidate],
    page_texts: dict[tuple[str, int], str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> VerificationResult:
    """Evaluate every candidate for one column in ONE Groq call. Never
    raises - see module docstring's resilience contract. `candidates`
    must be non-empty; resolve_column() below is the production entry
    point that guards the empty-pool case.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return _fallback_result(candidates[0], "GROQ_API_KEY is not set. Check your .env file.")

    user_content = _build_batch_prompt(column_name, requirement_text, candidates, page_texts)

    last_error = "Unknown error."
    for attempt in range(max_attempts):
        is_last_attempt = attempt == max_attempts - 1

        try:
            client = Groq(api_key=api_key, timeout=timeout)
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": BATCH_SYSTEM_PROMPT},
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
            return _fallback_result(candidates[0], last_error)

        try:
            raw = response.choices[0].message.content
            return _parse_batch_response(raw, candidates)
        except Exception as exc:  # noqa: BLE001 - malformed/unexpected model output
            last_error = f"Could not parse Groq's response: {exc}"
            if not is_last_attempt:
                continue
            return _fallback_result(candidates[0], last_error)

    return _fallback_result(candidates[0], last_error)


def resolve_column(
    column_name: str,
    requirement_text: str,
    candidates: list[SearchCandidate],
    page_texts: dict[tuple[str, int], str],
) -> Optional[VerificationResult]:
    """The verified result for one schema column, from a single batched
    Groq call over its candidate pool - or None if there were no
    candidates to evaluate at all (nothing for BM25 to find).
    """
    if not candidates:
        return None
    return verify_candidates_batch(column_name, requirement_text, candidates, page_texts)
