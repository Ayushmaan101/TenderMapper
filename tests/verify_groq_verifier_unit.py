"""Checklist 3.2 verification — unit-level (no network, mocked Groq),
rewritten for the batched single-call-per-column design (Groq
rate-limit fix / live feedback loop refinement).

Covers: a true compliance match among several candidates (high
confidence, correct candidate picked, accurate snippet), a
false-positive-only pool correctly rejected (low confidence), graceful
handling of network timeouts / API errors / malformed JSON (falls back
to a default candidate score anchored to the top-ranked BM25 candidate,
never raises, never propagates), the "never trust the model's echo"
guarantee generalized to batching (an out-of-range/hallucinated
best_candidate index still can't point outside the real candidate list),
resolve_column's empty-pool guard, and — the whole point of this
rewrite — that evaluating N candidates costs exactly ONE Groq API call,
not N.

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
    verify_candidates_batch,
)

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def make_candidates(n: int, *, pdf_name="C.pdf") -> list[SearchCandidate]:
    return [
        SearchCandidate(
            pdf_name=pdf_name, page_number=i, rank=i, score=1.0,
            snippet=f"fallback snippet {i}", matched_terms=["term"], match_signals=["bm25"],
        )
        for i in range(1, n + 1)
    ]


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


def _json(best_candidate=1, confidence=0.9, snippet="matched text here", reasoning="looks right"):
    import json
    return json.dumps({
        "best_candidate": best_candidate, "confidence": confidence,
        "match_snippet": snippet, "reasoning": reasoning,
    })


import os  # noqa: E402
os.environ.setdefault("GROQ_API_KEY", "fake-key-for-unit-tests")


# --------------------------------------------------------- true match --


def test_true_compliance_match_picked_from_batch() -> None:
    """5 candidates in the pool, the model picks candidate #3 - exactly
    ONE Groq call is made for all 5, and the result is anchored to
    candidate #3's real pdf_name/page, not re-derived from the model.
    """
    call_log: list = []
    install_fake_groq(
        content=_json(best_candidate=3, confidence=0.95, snippet="Certificate No: WHO-GMP-2023-4521", reasoning="Valid, recent WHO-GMP certificate."),
        call_log=call_log,
    )
    candidates = make_candidates(5)
    page_texts = {(c.pdf_name, c.page_number): f"page text {i}" for i, c in enumerate(candidates, start=1)}
    result = verify_candidates_batch("WHO GMP Certificate", "WHO GMP/GMA Certificate requirement text", candidates, page_texts)

    check("true match -> success=True", result.success is True)
    check("true match -> high confidence (>= 0.9)", result.confidence >= 0.9)
    check("true match -> snippet reflects the model's supporting evidence", "WHO-GMP-2023-4521" in result.match_snippet)
    check("true match -> reasoning is populated", bool(result.reasoning))
    check(
        "true match -> pdf_name/page come from candidate #3 (the model's chosen index), not re-derived from any model echo",
        result.pdf_name == candidates[2].pdf_name and result.page_number_or_range == str(candidates[2].page_number),
    )
    check("evaluating a 5-candidate pool costs exactly ONE Groq API call", len(call_log) == 1)
    check(
        "the single prompt actually contains all 5 candidates, numbered",
        all(f"[Candidate {i}]" in call_log[0]["messages"][1]["content"] for i in range(1, 6)),
    )


def test_false_positive_pool_rejected() -> None:
    install_fake_groq(content=_json(best_candidate=0, confidence=0.1, snippet="", reasoning="Only a passing mention, no actual certificate provided anywhere in these candidates."))
    candidates = make_candidates(3)
    result = verify_candidates_batch("WHO GMP Certificate", "WHO GMP/GMA Certificate requirement text", candidates, {})

    check("false positive pool -> success=True (the call itself succeeded)", result.success is True)
    check("false positive pool -> low confidence (<= 0.3)", result.confidence <= 0.3)
    check("false positive pool -> reasoning explains the rejection", "passing mention" in result.reasoning.lower())
    check(
        "best_candidate=0 ('none match') anchors to the top-ranked (rank 1) candidate, not left undefined",
        result.pdf_name == candidates[0].pdf_name and result.page_number_or_range == str(candidates[0].page_number),
    )


def test_out_of_range_index_never_escapes_the_real_candidate_list() -> None:
    """Even if the model returns a best_candidate index that doesn't
    correspond to any real candidate (hallucinated/out of range), the
    result is still anchored to a REAL candidate from our own list - the
    model can only ever select among what we actually sent it.
    """
    candidates = make_candidates(3)
    install_fake_groq(content=_json(best_candidate=999, confidence=0.8))
    result = verify_candidates_batch("Col", "req", candidates, {})
    check(
        "an out-of-range best_candidate index anchors to the top-ranked candidate, not a fabricated identity",
        result.pdf_name == candidates[0].pdf_name and result.page_number_or_range == str(candidates[0].page_number),
    )


# --------------------------------------------------- resilience/errors --


def test_missing_api_key() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        candidates = make_candidates(1)
        result = verify_candidates_batch("Col", "req", candidates, {})
        check("missing key -> success=False", result.success is False)
        check("missing key -> confidence=0.0 (never a number that looks like a real match)", result.confidence == 0.0)
        check("missing key -> falls back to the top candidate's own BM25 snippet", result.match_snippet == candidates[0].snippet)
        check("missing key -> reasoning flags it for human review", "human review" in result.reasoning.lower())
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


def test_network_timeout_handled_gracefully() -> None:
    install_fake_groq(raise_exc=RuntimeError("simulated network timeout"))
    result = verify_candidates_batch("Col", "req", make_candidates(2), {})
    check("simulated network failure -> caught, not raised (we got a result at all)", isinstance(result, VerificationResult))
    check("simulated network failure -> success=False", result.success is False)
    check("simulated network failure -> confidence=0.0", result.confidence == 0.0)


def test_malformed_json_handled_gracefully() -> None:
    install_fake_groq(content="this is not { valid json at all")
    result = verify_candidates_batch("Col", "req", make_candidates(2), {})
    check("malformed JSON -> success=False, not an exception", result.success is False)
    check("malformed JSON -> error mentions parsing", "parse" in (result.error or "").lower())


def test_rate_limit_retries_with_backoff() -> None:
    """A 429 is retried (not failed immediately), with a short backoff
    between attempts - verified via a monkeypatched time.sleep so the
    test doesn't actually wait. Still exactly one LOGICAL call per
    column (retries of the same call, not additional per-candidate
    calls).
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
                message = type("M", (), {"content": _json(best_candidate=1, confidence=0.85)})()
                choice = type("C", (), {"message": message})()
                return type("R", (), {"choices": [choice]})()

        class _Client:
            def __init__(self, *a, **k):
                self.chat = type("Chat", (), {"completions": _FlakyCompletions()})()

        gv.Groq = _Client

        result = verify_candidates_batch("Col", "req", make_candidates(4), {}, max_attempts=3)
        check("rate limit (429) -> eventually succeeds after retrying", result.success is True and result.confidence == 0.85)
        check("rate limit (429) -> retried exactly 3 times total (still one column's worth of calls)", len(call_log) == 3)
        check("rate limit (429) -> backoff (time.sleep) was actually invoked between retries", len(sleep_calls) == 2)
        check("rate limit (429) -> backoff durations increase with attempt number", sleep_calls[1] > sleep_calls[0])
    finally:
        gv.time.sleep = original_sleep


# ------------------------------------------------------------ resolve_column --


def test_resolve_column_empty_pool_returns_none() -> None:
    empty_best = resolve_column("Col", "req", [], {})
    check("resolve_column with zero candidates returns None, not an error", empty_best is None)


def test_resolve_column_delegates_to_batch() -> None:
    install_fake_groq(content=_json(best_candidate=2, confidence=0.77))
    candidates = make_candidates(4)
    best = resolve_column("Col", "req", candidates, {})
    check(
        "resolve_column returns the batch result, anchored to the chosen candidate (#2)",
        best is not None and best.pdf_name == candidates[1].pdf_name and best.confidence == 0.77,
    )


def test_page_text_lookup_falls_back_to_snippet() -> None:
    """A candidate missing from page_texts sends its own BM25 snippet in
    the batched prompt instead - proven by checking the actual prompt
    content sent to Groq.
    """
    candidate = make_candidates(1, pdf_name="X.pdf")[0]
    call_log: list = []
    install_fake_groq(content=_json(best_candidate=1, confidence=0.5), call_log=call_log)

    verify_candidates_batch("Col", "req", [candidate], {})  # no page_texts entry at all
    prompt = call_log[0]["messages"][1]["content"]
    check("a candidate missing from page_texts falls back to its own BM25 snippet in the prompt", candidate.snippet in prompt)


def main() -> None:
    test_true_compliance_match_picked_from_batch()
    test_false_positive_pool_rejected()
    test_out_of_range_index_never_escapes_the_real_candidate_list()
    test_missing_api_key()
    test_network_timeout_handled_gracefully()
    test_malformed_json_handled_gracefully()
    test_rate_limit_retries_with_backoff()
    test_resolve_column_empty_pool_returns_none()
    test_resolve_column_delegates_to_batch()
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
