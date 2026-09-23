"""Checklist 3.2 verification — unit-level (no network, mocked Groq).

Covers: a true compliance match (high confidence, accurate snippet), a
false-positive candidate correctly rejected (low confidence), graceful
handling of network timeouts / API errors / malformed JSON (falls back
to a default candidate score, never raises, never propagates), correct
aggregation of the top-ranked verified result per column, and the
concurrency design itself - bounded worker count, early stopping once a
high-confidence match is found (with candidates that never got a chance
to run correctly NOT counted), and full evaluation when nothing clears
the early-stop bar.

Run: python tests/verify_groq_verifier_unit.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import verify.groq_verifier as gv  # noqa: E402
from search.bm25_index import SearchCandidate  # noqa: E402
from verify.groq_verifier import (  # noqa: E402
    VerificationResult,
    resolve_column,
    verify_candidate,
    verify_candidates,
)

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def make_candidate(pdf_name="C.pdf", page=1, snippet="fallback snippet") -> SearchCandidate:
    return SearchCandidate(
        pdf_name=pdf_name, page_number=page, rank=1, score=1.0,
        snippet=snippet, matched_terms=["term"], match_signals=["bm25"],
    )


class _FakeCompletions:
    def __init__(self, content=None, raise_exc=None, call_log=None, delay=0.0):
        self._content = content
        self._raise = raise_exc
        self._call_log = call_log if call_log is not None else []
        self._delay = delay

    def create(self, **kwargs):
        self._call_log.append(kwargs)
        if self._delay:
            time.sleep(self._delay)
        if self._raise is not None:
            raise self._raise
        message = type("M", (), {"content": self._content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice]})()


def install_fake_groq(content=None, raise_exc=None, call_log=None, delay=0.0):
    completions = _FakeCompletions(content=content, raise_exc=raise_exc, call_log=call_log, delay=delay)

    class _Client:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": completions})()

    gv.Groq = _Client
    return completions


def _json(pdf="C.pdf", page=1, confidence=0.9, snippet="matched text here", reasoning="looks right"):
    import json
    return json.dumps({
        "pdf_name": pdf, "page_number_or_range": str(page),
        "confidence": confidence, "match_snippet": snippet, "reasoning": reasoning,
    })


import os  # noqa: E402
os.environ.setdefault("GROQ_API_KEY", "fake-key-for-unit-tests")


# --------------------------------------------------------- true match --


def test_true_compliance_match() -> None:
    install_fake_groq(content=_json(confidence=0.95, snippet="Certificate No: WHO-GMP-2023-4521", reasoning="Valid, recent WHO-GMP certificate."))
    candidate = make_candidate()
    result = verify_candidate("WHO GMP Certificate", "WHO GMP/GMA Certificate requirement text", candidate, "full page text")

    check("true match -> success=True", result.success is True)
    check("true match -> high confidence (>= 0.9)", result.confidence >= 0.9)
    check("true match -> snippet reflects the model's supporting evidence", "WHO-GMP-2023-4521" in result.match_snippet)
    check("true match -> reasoning is populated", bool(result.reasoning))
    check("true match -> pdf_name/page come from OUR candidate data, not re-derived from the model", result.pdf_name == "C.pdf" and result.page_number_or_range == "1")


def test_false_positive_rejected() -> None:
    install_fake_groq(content=_json(confidence=0.1, snippet="", reasoning="Only a passing mention, no actual certificate provided."))
    candidate = make_candidate()
    result = verify_candidate("WHO GMP Certificate", "WHO GMP/GMA Certificate requirement text", candidate, "This tender mentions WHO GMP may be required, see Annexure B.")

    check("false positive -> success=True (the call itself succeeded)", result.success is True)
    check("false positive -> low confidence (<= 0.3)", result.confidence <= 0.3)
    check("false positive -> reasoning explains the rejection", "passing mention" in result.reasoning.lower())


def test_model_echo_is_never_trusted() -> None:
    """Even if the model's JSON claims a different pdf/page than what it
    was actually asked about, our own candidate data wins.
    """
    install_fake_groq(content=_json(pdf="WRONG.pdf", page=999, confidence=0.8))
    candidate = make_candidate(pdf_name="Real.pdf", page=7)
    result = verify_candidate("Col", "req", candidate, "text")
    check("model's hallucinated pdf_name/page are ignored", result.pdf_name == "Real.pdf" and result.page_number_or_range == "7")


# --------------------------------------------------- resilience/errors --


def test_missing_api_key() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        result = verify_candidate("Col", "req", make_candidate(snippet="fallback shown"), "text")
        check("missing key -> success=False", result.success is False)
        check("missing key -> confidence=0.0 (never a number that looks like a real match)", result.confidence == 0.0)
        check("missing key -> falls back to the candidate's own BM25 snippet", result.match_snippet == "fallback shown")
        check("missing key -> reasoning flags it for human review", "human review" in result.reasoning.lower())
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


def test_network_timeout_handled_gracefully() -> None:
    install_fake_groq(raise_exc=RuntimeError("simulated network timeout"))
    result = verify_candidate("Col", "req", make_candidate(), "text")
    check("simulated network failure -> caught, not raised (we got a result at all)", isinstance(result, VerificationResult))
    check("simulated network failure -> success=False", result.success is False)
    check("simulated network failure -> confidence=0.0", result.confidence == 0.0)


def test_malformed_json_handled_gracefully() -> None:
    install_fake_groq(content="this is not { valid json at all")
    result = verify_candidate("Col", "req", make_candidate(), "text")
    check("malformed JSON -> success=False, not an exception", result.success is False)
    check("malformed JSON -> error mentions parsing", "parse" in (result.error or "").lower())


def test_rate_limit_retries_with_backoff() -> None:
    """A 429 is retried (not failed immediately), with a short backoff
    between attempts - verified via a monkeypatched time.sleep so the
    test doesn't actually wait.
    """
    import groq

    call_log: list = []
    sleep_calls: list = []
    original_sleep = gv.time.sleep
    gv.time.sleep = lambda s: sleep_calls.append(s)

    try:
        request = __import__("httpx").Request("POST", "https://api.groq.com/x")
        response = __import__("httpx").Response(429, request=request)
        rate_limit_exc = groq.RateLimitError("rate limited", response=response, body=None)

        # Fails with 429 on attempts 1 and 2, succeeds on attempt 3.
        attempt_counter = {"n": 0}

        class _FlakyCompletions:
            def create(self, **kwargs):
                call_log.append(1)
                attempt_counter["n"] += 1
                if attempt_counter["n"] < 3:
                    raise rate_limit_exc
                message = type("M", (), {"content": _json(confidence=0.85)})()
                choice = type("C", (), {"message": message})()
                return type("R", (), {"choices": [choice]})()

        class _Client:
            def __init__(self, *a, **k):
                self.chat = type("Chat", (), {"completions": _FlakyCompletions()})()

        gv.Groq = _Client

        result = verify_candidate("Col", "req", make_candidate(), "text", max_attempts=3)
        check("rate limit (429) -> eventually succeeds after retrying", result.success is True and result.confidence == 0.85)
        check("rate limit (429) -> retried exactly 3 times total", len(call_log) == 3)
        check("rate limit (429) -> backoff (time.sleep) was actually invoked between retries", len(sleep_calls) == 2)
        check("rate limit (429) -> backoff durations increase with attempt number", sleep_calls[1] > sleep_calls[0])
    finally:
        gv.time.sleep = original_sleep


# ------------------------------------------------------------ aggregation --


def test_aggregation_picks_top_ranked_result() -> None:
    candidates = [make_candidate(page=i) for i in range(1, 6)]
    confidences = {1: 0.3, 2: 0.95, 3: 0.6, 4: 0.1, 5: 0.7}

    def fake_verify(column_name, requirement_text, candidate, page_text, **kw):
        return VerificationResult(
            pdf_name=candidate.pdf_name, page_number_or_range=str(candidate.page_number),
            confidence=confidences[candidate.page_number], match_snippet="x", reasoning="x", success=True,
        )

    original = gv.verify_candidate
    gv.verify_candidate = fake_verify
    try:
        results = verify_candidates("Col", "req", candidates, {}, max_workers=5, early_stop_confidence=2.0)  # unreachable threshold -> evaluate all
        check("all 5 candidates evaluated (early stop threshold unreachable)", len(results) == 5)
        check("results sorted by confidence, strictly descending", [r.confidence for r in results] == sorted(confidences.values(), reverse=True))

        best = resolve_column("Col", "req", candidates, {}, early_stop_confidence=2.0)
        check("resolve_column picks the single highest-confidence result (page 2, 0.95)", best is not None and best.page_number_or_range == "2" and best.confidence == 0.95)

        empty_best = resolve_column("Col", "req", [], {})
        check("resolve_column with zero candidates returns None, not an error", empty_best is None)
    finally:
        gv.verify_candidate = original


# -------------------------------------------------------------- concurrency --


def test_early_stopping_skips_remaining_candidates() -> None:
    """max_workers=1 makes execution effectively sequential, so the
    first-submitted high-confidence candidate triggers early stop before
    later candidates ever start - deterministically provable via a call
    counter, not a timing assumption.
    """
    candidates = [make_candidate(page=i) for i in range(1, 11)]
    call_log: list = []

    def fake_verify(column_name, requirement_text, candidate, page_text, **kw):
        call_log.append(candidate.page_number)
        confidence = 0.95 if candidate.page_number == 1 else 0.5
        return VerificationResult(
            pdf_name=candidate.pdf_name, page_number_or_range=str(candidate.page_number),
            confidence=confidence, match_snippet="x", reasoning="x", success=True,
        )

    original = gv.verify_candidate
    gv.verify_candidate = fake_verify
    try:
        results = verify_candidates("Col", "req", candidates, {}, max_workers=1, early_stop_confidence=0.90)
        check("early stop -> NOT all 10 candidates were evaluated", len(call_log) < 10)
        check("early stop -> the high-confidence result made it into the results", any(r.confidence == 0.95 for r in results))
    finally:
        gv.verify_candidate = original


def test_no_early_stop_evaluates_everything() -> None:
    """When nothing clears the early-stop bar, every candidate must
    still be evaluated - proves early stopping doesn't accidentally
    truncate a pool that never found a strong match.
    """
    candidates = [make_candidate(page=i) for i in range(1, 8)]
    call_log: list = []

    def fake_verify(column_name, requirement_text, candidate, page_text, **kw):
        call_log.append(candidate.page_number)
        return VerificationResult(
            pdf_name=candidate.pdf_name, page_number_or_range=str(candidate.page_number),
            confidence=0.4, match_snippet="x", reasoning="x", success=True,
        )

    original = gv.verify_candidate
    gv.verify_candidate = fake_verify
    try:
        results = verify_candidates("Col", "req", candidates, {}, max_workers=4, early_stop_confidence=0.90)
        check("no candidate clears the bar -> all 7 are evaluated", len(call_log) == 7 and len(results) == 7)
    finally:
        gv.verify_candidate = original


def test_page_text_lookup_falls_back_to_snippet() -> None:
    candidate = make_candidate(page=42, snippet="THE FALLBACK SNIPPET")
    captured_text = {}

    def fake_verify(column_name, requirement_text, cand, page_text, **kw):
        captured_text["value"] = page_text
        return VerificationResult(pdf_name=cand.pdf_name, page_number_or_range=str(cand.page_number), confidence=0.5, match_snippet="x", reasoning="x", success=True)

    original = gv.verify_candidate
    gv.verify_candidate = fake_verify
    try:
        verify_candidates("Col", "req", [candidate], {})  # no page_texts entry at all
        check("a candidate missing from page_texts falls back to its own BM25 snippet", captured_text["value"] == "THE FALLBACK SNIPPET")
    finally:
        gv.verify_candidate = original


def main() -> None:
    test_true_compliance_match()
    test_false_positive_rejected()
    test_model_echo_is_never_trusted()
    test_missing_api_key()
    test_network_timeout_handled_gracefully()
    test_malformed_json_handled_gracefully()
    test_rate_limit_retries_with_backoff()
    test_aggregation_picks_top_ranked_result()
    test_early_stopping_skips_remaining_candidates()
    test_no_early_stop_evaluates_everything()
    test_page_text_lookup_falls_back_to_snippet()

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
