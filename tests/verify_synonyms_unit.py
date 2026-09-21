"""Checklist 1.4 verification — unit-level (no network, no Streamlit).

Covers: response parsing (backticks/whitespace/bare-array edge cases,
dedup), merge_new_synonyms's never-overwrite behavior against a real
temp DB, and expand_synonyms's non-raising failure handling for a
missing API key, a client exception, malformed JSON, and an empty
synonym list - all via a monkeypatched config.synonyms.Groq, so this
file needs no network access and no real API key.

Run: python tests/verify_synonyms_unit.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config.synonyms as syn_mod  # noqa: E402
from config.synonyms import (  # noqa: E402
    SynonymExpansionResult,
    _parse_synonyms_response,
    expand_synonyms,
    merge_new_synonyms,
)
from db import crud  # noqa: E402
from db.connection import get_connection  # noqa: E402
from db.schema import init_db  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


# ---------------------------------------------------------- parsing --


def test_parsing() -> None:
    check(
        "clean JSON object with a dup (case-insensitive) dedupes, keeps first casing",
        _parse_synonyms_response('{"synonyms": ["a", "b", "A "]}') == ["a", "b"],
    )
    check(
        "markdown code fence with 'json' language tag is stripped",
        _parse_synonyms_response('```json\n{"synonyms": ["x", "y"]}\n```') == ["x", "y"],
    )
    check(
        "plain markdown code fence (no language tag) is stripped",
        _parse_synonyms_response('```\n{"synonyms": ["x"]}\n```') == ["x"],
    )
    check(
        "leading/trailing whitespace and newlines around JSON are tolerated",
        _parse_synonyms_response('\n\n   {"synonyms": ["z"]}   \n') == ["z"],
    )
    check(
        "a bare JSON array (not the requested object) is still accepted",
        _parse_synonyms_response('["p", "q"]') == ["p", "q"],
    )
    check(
        "blank/whitespace-only entries are dropped",
        _parse_synonyms_response('{"synonyms": ["ok", "   ", ""]}') == ["ok"],
    )
    check(
        "non-string entries are silently skipped, not fatal",
        _parse_synonyms_response('{"synonyms": ["ok", 5, null, "also-ok"]}') == ["ok", "also-ok"],
    )
    try:
        _parse_synonyms_response("this is not json at all")
        check("garbage (non-JSON) input raises rather than silently returning []", False)
    except Exception:
        check("garbage (non-JSON) input raises rather than silently returning []", True)


# ------------------------------------------------------- merge logic --


def test_merge_never_overwrites() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "merge_test.db")
        conn = get_connection(db_path)
        init_db(conn)
        table_id = crud.create_table(conn, "T")
        col_id = crud.create_column(conn, table_id, "C", "requirement text")

        crud.add_synonyms(conn, col_id, ["WHO-GMP", "Schedule M"])

        added = merge_new_synonyms(
            conn, col_id, ["who-gmp", "New Term", "SCHEDULE M", "Another New"]
        )
        check(
            "merge only reports the genuinely-new candidates (case-insensitive skip)",
            added == ["New Term", "Another New"],
        )

        final = [s.synonym_text for s in crud.get_synonyms(conn, col_id)]
        check(
            "existing synonyms untouched (original casing, original two still present)",
            "WHO-GMP" in final and "Schedule M" in final,
        )
        check(
            "final list is existing + only the genuinely new ones (4 total, no dupes)",
            len(final) == 4 and set(final) == {"WHO-GMP", "Schedule M", "New Term", "Another New"},
        )

        # A second merge with the exact same candidates adds nothing further.
        added_again = merge_new_synonyms(conn, col_id, ["who-gmp", "New Term"])
        check("re-merging already-present candidates adds nothing", added_again == [])
        check(
            "synonym count unchanged after a no-op merge",
            len(crud.get_synonyms(conn, col_id)) == 4,
        )
        conn.close()


# -------------------------------------------------- expand_synonyms --


class _FakeCompletions:
    def __init__(self, content: str | None = None, raise_exc: Exception | None = None):
        self._content = content
        self._raise = raise_exc

    def create(self, **kwargs):
        if self._raise is not None:
            raise self._raise
        message = type("M", (), {"content": self._content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice]})()


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions):
        self._completions = completions
        self.chat = _FakeChat(completions)

    def __call__(self, *args, **kwargs):
        return self


def _install_fake_groq(content: str | None = None, raise_exc: Exception | None = None):
    completions = _FakeCompletions(content=content, raise_exc=raise_exc)

    class _Client:
        def __init__(self, *a, **k):
            self.chat = _FakeChat(completions)

    syn_mod.Groq = _Client


def test_expand_synonyms_missing_key() -> None:
    import os

    original = os.environ.pop("GROQ_API_KEY", None)
    try:
        result = expand_synonyms("Col", "Requirement text")
        check("missing GROQ_API_KEY -> success is False", result.success is False)
        check("missing GROQ_API_KEY -> error mentions the key", "GROQ_API_KEY" in (result.error or ""))
        check("missing GROQ_API_KEY -> synonyms list is empty", result.synonyms == [])
    finally:
        if original is not None:
            os.environ["GROQ_API_KEY"] = original


def test_expand_synonyms_client_exception_is_caught() -> None:
    os_environ_backup = __import__("os").environ.get("GROQ_API_KEY")
    __import__("os").environ["GROQ_API_KEY"] = "fake-key-for-this-test"
    try:
        _install_fake_groq(raise_exc=RuntimeError("simulated network failure"))
        result = expand_synonyms("Col", "Requirement text")
        check(
            "an exception raised by the Groq client is caught, not propagated",
            isinstance(result, SynonymExpansionResult) and result.success is False,
        )
        check("caught-exception error message is non-empty", bool(result.error))
    finally:
        if os_environ_backup is not None:
            __import__("os").environ["GROQ_API_KEY"] = os_environ_backup


def test_expand_synonyms_malformed_json_is_caught() -> None:
    import os

    os.environ["GROQ_API_KEY"] = "fake-key-for-this-test"
    _install_fake_groq(content="not valid json { at all")
    result = expand_synonyms("Col", "Requirement text")
    check("malformed JSON response -> success is False (not an exception)", result.success is False)
    check("malformed JSON response -> error mentions parsing", "parse" in (result.error or "").lower())


def test_expand_synonyms_empty_synonyms_is_a_failure() -> None:
    import os

    os.environ["GROQ_API_KEY"] = "fake-key-for-this-test"
    _install_fake_groq(content='{"synonyms": []}')
    result = expand_synonyms("Col", "Requirement text")
    check("empty synonyms array from Groq -> treated as a failed result, not a silent success", result.success is False)


def test_expand_synonyms_success_path_via_fake_client() -> None:
    import os

    os.environ["GROQ_API_KEY"] = "fake-key-for-this-test"
    _install_fake_groq(content='```json\n{"synonyms": ["Term One", "term one", "Term Two"]}\n```')
    result = expand_synonyms("Col", "Requirement text")
    check("fake successful call -> success is True", result.success is True)
    check(
        "fake successful call -> synonyms parsed, deduped, code fence stripped",
        result.synonyms == ["Term One", "Term Two"],
    )
    check("fake successful call -> error is None", result.error is None)


def main() -> None:
    test_parsing()
    test_merge_never_overwrites()
    test_expand_synonyms_missing_key()
    test_expand_synonyms_client_exception_is_caught()
    test_expand_synonyms_malformed_json_is_caught()
    test_expand_synonyms_empty_synonyms_is_a_failure()
    test_expand_synonyms_success_path_via_fake_client()

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
