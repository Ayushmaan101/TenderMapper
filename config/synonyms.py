"""Config-time synonym expansion (Groq, one-time per trigger).

Called only when: (a) a new schema column is created, (b) an existing
column's requirement_text is explicitly changed and saved, or (c) the
user clicks "Generate / Suggest Synonyms" on a column. Never called just
from rendering/navigating the Config tab — see config/ui.py, where every
call site is gated behind a specific button press.

Resilience contract: expand_synonyms() never raises. Every failure mode
(missing API key, network error, timeout, rate limit, malformed model
output) is caught and returned as a failed SynonymExpansionResult, so a
Groq failure can never block or corrupt a column create/update — the
column save always happens through db/crud.py independently, and this
module's result is used only to (maybe) add synonyms on top of it.

Merge, never replace: results from this module are only ever *added* to
a column's existing synonym list (see merge_new_synonyms), skipping
anything that already exists case-insensitively. A manually typed or
previously generated synonym is never removed by anything in this
module — the only way a synonym is deleted is the explicit "Remove"
button in config/ui.py.

Text-cleaning scope: unlike db/crud.py (which never strips user-typed
text), the parsing in this module DOES strip whitespace from each
LLM-returned candidate and dedupes case-insensitively before storage.
That's deliberate — this is machine-generated list content being
"cleaned" per the spec, not a human's typed input being altered.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

from db import crud

load_dotenv()

# PROJECT_HARNESS.md specifies Groq Llama 3.3 70B (llama-3.3-70b-versatile).
# As of 2026-09-21 that model does not exist on this Groq account's live
# /models list at all (not renamed - absent), confirmed by querying the API
# directly. Swapped to openai/gpt-oss-120b (closest available capability
# tier) with the user's explicit go-ahead. See PROJECT_HARNESS.md §8 Change
# Log and §2 Tech Stack for the full note; revisit if Groq restores Llama
# access on this account.
MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = (
    "You generate search-retrieval synonyms for a tender-compliance document "
    "matching system. Given a compliance requirement's short column name and "
    "its full requirement text, return alternate phrasings, abbreviations, "
    "and domain-specific synonyms that a scanned tender/compliance document "
    "might use instead of the exact wording in the requirement text - e.g. "
    "standard abbreviations, alternate certificate/license names, regulatory "
    "synonyms, and common short forms actually used in Indian pharmaceutical "
    "tender documents. Do not include generic filler words or restate the "
    "requirement text itself as an entry.\n\n"
    "Respond with a JSON object of the exact form "
    '{"synonyms": ["term1", "term2", ...]}. '
    "Return 5-15 distinct entries, no duplicates, no explanations, no "
    "markdown formatting, valid JSON only."
)


@dataclass
class SynonymExpansionResult:
    success: bool
    synonyms: list[str] = field(default_factory=list)
    error: Optional[str] = None


def expand_synonyms(
    column_name: str, requirement_text: str, *, timeout: float = 20.0, max_attempts: int = 3
) -> SynonymExpansionResult:
    """Call Groq to generate candidate synonyms for one schema column.

    Never raises. Returns a failed result (success=False, error set) for
    every failure mode instead: missing/blank GROQ_API_KEY, any network
    or API error Groq's SDK can raise, or a response that can't be parsed
    into a non-empty synonym list.

    Retries on failures observed to be transient in practice
    (max_attempts=3 by default): rate limits, connection/timeout errors,
    and server errors. A live check during checklist 1.4 also hit Groq's
    JSON-mode on openai/gpt-oss-120b returning HTTP 400 json_validate_failed
    with "max completion tokens reached before generating a valid
    document" - that was a real max_tokens-too-small bug (this model
    spends some of its budget on internal reasoning before the JSON
    itself), fixed by raising max_tokens, not something retrying alone
    would reliably paper over. The retry loop stays as defense-in-depth
    for genuine transients on top of that fix. Non-retryable failures
    (bad/missing key, no permission, model not found) fail immediately -
    retrying can't fix those.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return SynonymExpansionResult(
            False, [], "GROQ_API_KEY is not set. Check your .env file."
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
                    {
                        "role": "user",
                        "content": f"Column name: {column_name}\n\nRequirement text: {requirement_text}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1536,
            )
        except Exception as exc:  # noqa: BLE001 - deliberately broad; see module docstring
            last_error = _describe_groq_error(exc)
            if _is_retryable(exc) and not is_last_attempt:
                continue
            return SynonymExpansionResult(False, [], last_error)

        try:
            raw = response.choices[0].message.content
            synonyms = _parse_synonyms_response(raw)
        except Exception as exc:  # noqa: BLE001 - malformed/unexpected model output
            last_error = f"Could not parse Groq's response: {exc}"
            if not is_last_attempt:
                continue
            return SynonymExpansionResult(False, [], last_error)

        if not synonyms:
            last_error = "Groq returned no usable synonyms."
            if not is_last_attempt:
                continue
            return SynonymExpansionResult(False, [], last_error)

        return SynonymExpansionResult(True, synonyms, None)

    return SynonymExpansionResult(False, [], last_error)


def _is_retryable(exc: Exception) -> bool:
    """Failures worth one immediate retry: transient/server-side issues
    where the same request might just succeed the second time. Auth,
    permission, and not-found failures are excluded - retrying changes
    nothing for those.
    """
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


def _parse_synonyms_response(raw_text: str) -> list[str]:
    """Parse a Groq JSON-mode response into a clean, deduplicated list of
    strings. Tolerates the model wrapping its JSON in a markdown code
    fence (```json ... ``` or plain ``` ... ```), leading/trailing
    whitespace, a bare JSON array instead of the requested
    {"synonyms": [...]} object, and non-string/blank entries.
    """
    text = raw_text.strip()

    if text.startswith("```"):
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()

    data = json.loads(text)

    if isinstance(data, dict):
        items = data.get("synonyms", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned


def _describe_groq_error(exc: Exception) -> str:
    """Best-effort human-readable message for the UI. Falls through to
    str(exc) for anything not specifically recognized — still caught,
    still non-fatal, just a plainer message.
    """
    from groq import (
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )

    if isinstance(exc, AuthenticationError):
        return "Groq rejected the API key (authentication failed). Check GROQ_API_KEY in .env."
    if isinstance(exc, RateLimitError):
        return "Groq rate limit hit. Try again shortly, or use “Generate Synonyms” later."
    if isinstance(exc, APITimeoutError):
        return "Groq request timed out."
    if isinstance(exc, APIConnectionError):
        return f"Could not reach Groq (connection error): {exc}"
    return f"Groq synonym generation failed: {exc}"


def merge_new_synonyms(conn, column_id: int, candidates: list[str]) -> list[str]:
    """Add only the candidates not already present for this column
    (case-insensitive match against existing synonym_text). Every
    existing synonym - manually typed or previously generated - is left
    exactly as it is; this function only ever adds rows, never deletes
    or replaces one.

    Returns the synonym texts that were actually newly added (may be
    fewer than len(candidates), or empty if everything was already
    present).
    """
    existing_keys = {s.synonym_text.strip().lower() for s in crud.get_synonyms(conn, column_id)}
    to_add = [c for c in candidates if c.strip().lower() not in existing_keys]
    if to_add:
        crud.add_synonyms(conn, column_id, to_add)
    return to_add
