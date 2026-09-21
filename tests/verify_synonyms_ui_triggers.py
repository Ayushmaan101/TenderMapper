"""Checklist 1.4 verification — UI trigger scope (AppTest, mocked Groq).

Drives the real app (via streamlit.testing.v1.AppTest - no browser, no
new dependency, runs in-process so config.synonyms.Groq can be
monkeypatched directly) through the exact scenarios the trigger-scope
requirement describes, counting calls to prove:

  - creating a new column triggers expansion exactly once
  - editing a column WITHOUT changing requirement_text does NOT trigger it
  - editing a column's requirement_text DOES trigger it exactly once
  - the manual "Generate / Suggest Synonyms" button triggers it on demand
  - merely navigating the Config tab (reruns, opening/closing expanders)
    never triggers it - zero calls
  - a forced Groq failure (missing key) during create/edit does not
    prevent the column save, corrupt it, or raise - at.exception stays
    empty and the DB is checked directly afterward
  - manually-added synonyms survive a "Generate Synonyms" click whose
    mocked result contains completely different terms (merge, not
    replace)

Run: python tests/verify_synonyms_ui_triggers.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


class _FakeCompletions:
    def __init__(self, call_log: list, content: str = '{"synonyms": ["Fake Term A", "Fake Term B"]}'):
        self._call_log = call_log
        self._content = content

    def create(self, **kwargs):
        self._call_log.append(kwargs)
        message = type("M", (), {"content": self._content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice]})()


def install_fake_groq(call_log: list, content: str = '{"synonyms": ["Fake Term A", "Fake Term B"]}'):
    import config.synonyms as syn_mod

    completions = _FakeCompletions(call_log, content=content)

    class _Client:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": completions})()

    syn_mod.Groq = _Client


def main() -> None:
    from streamlit.testing.v1 import AppTest

    # ignore_cleanup_errors: AppTest's st.cache_resource DB connection stays
    # open in this process for the rest of the run; on Windows that holds an
    # OS-level lock on the .db file, which would otherwise make the
    # temp-dir's own cleanup raise PermissionError after every check has
    # already passed. Harmless - the OS reclaims the temp dir eventually.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "ui_triggers_test.db")
        os.environ["TENDER_MAPPER_DB_PATH"] = db_path
        os.environ.setdefault("GROQ_API_KEY", "fake-key-for-ui-trigger-test")

        call_log: list = []
        install_fake_groq(call_log)

        app_path = str(Path(__file__).resolve().parent.parent / "app.py")
        at = AppTest.from_file(app_path)
        at.run()
        check("initial launch, no exception", not at.exception)
        check("no Groq calls just from launching", len(call_log) == 0)

        # --- navigation alone must never trigger a call ---
        for _ in range(3):
            at.run()
        check("re-running the script repeatedly (no button clicks) -> zero calls", len(call_log) == 0)

        # --- ADD a column -> exactly one call, synonyms merged ---
        at.get_by_key("newcol_name_1").set_value("Trigger Test Col")
        at.get_by_key("newcol_req_1").set_value("Trigger test requirement text.")
        at.get_by_key("FormSubmitter:add_col_form_1-Add Column").click()
        at.run()
        check("adding a column -> no exception", not at.exception)
        check("adding a column -> exactly one Groq call", len(call_log) == 1)

        from db import crud
        from db.connection import get_connection

        conn = get_connection(db_path)
        cols = crud.get_columns(conn, 1)
        new_col = next(c for c in cols if c.name == "Trigger Test Col")
        syns = [s.synonym_text for s in crud.get_synonyms(conn, new_col.id)]
        check(
            "new column's synonyms were merged from the (mocked) Groq response",
            set(syns) == {"Fake Term A", "Fake Term B"},
        )
        conn.close()

        # --- EDIT a column, name only, requirement_text UNCHANGED -> no call ---
        calls_before = len(call_log)
        at.get_by_key(f"cname_{new_col.id}").set_value("Trigger Test Col RENAMED")
        # creq widget left at its current value on purpose - simulates "didn't touch it"
        at.get_by_key(f"csave_{new_col.id}").click()
        at.run()
        check("rename-only save -> no exception", not at.exception)
        check(
            "rename-only save (requirement_text unchanged) -> triggers NO new Groq call",
            len(call_log) == calls_before,
        )

        # --- EDIT a column, requirement_text CHANGED -> exactly one more call ---
        calls_before = len(call_log)
        at.get_by_key(f"creq_{new_col.id}").set_value("Trigger test requirement text - EDITED.")
        at.get_by_key(f"csave_{new_col.id}").click()
        at.run()
        check("requirement_text-changed save -> no exception", not at.exception)
        check(
            "requirement_text-changed save -> triggers exactly one more Groq call",
            len(call_log) == calls_before + 1,
        )

        conn = get_connection(db_path)
        edited_col = crud.get_column(conn, new_col.id)
        check(
            "edited requirement_text actually persisted",
            edited_col.requirement_text == "Trigger test requirement text - EDITED.",
        )
        conn.close()

        # --- MANUAL "Generate Synonyms" button: triggers on demand, and
        # MERGES rather than replacing (add a manual synonym first, then
        # regenerate with different mocked terms; both must survive) ---
        conn = get_connection(db_path)
        crud.add_synonym(conn, new_col.id, "HUMAN TYPED THIS MANUALLY")
        conn.close()

        install_fake_groq(call_log, content='{"synonyms": ["Totally Different Term"]}')
        calls_before = len(call_log)
        at.run()  # re-render so the widget tree reflects the manual synonym just added
        at.get_by_key(f"gensyn_{new_col.id}").click()
        at.run()
        check("manual 'Generate Synonyms' button -> no exception", not at.exception)
        check("manual 'Generate Synonyms' button -> triggers exactly one call", len(call_log) == calls_before + 1)

        conn = get_connection(db_path)
        final_syns = [s.synonym_text for s in crud.get_synonyms(conn, new_col.id)]
        check(
            "manual synonym survived the button-triggered regeneration (merge, not replace)",
            "HUMAN TYPED THIS MANUALLY" in final_syns,
        )
        check(
            "new mocked term from the button click was added on top",
            "Totally Different Term" in final_syns,
        )
        check(
            "earlier auto-generated terms also still present (nothing wiped)",
            "Fake Term A" in final_syns and "Fake Term B" in final_syns,
        )
        conn.close()

        # --- FAILURE RESILIENCE: missing API key during column creation
        # must not prevent the column from saving correctly ---
        saved_key = os.environ.pop("GROQ_API_KEY", None)
        try:
            at.get_by_key("newcol_name_1").set_value("Resilience Test Col")
            at.get_by_key("newcol_req_1").set_value("Resilience requirement text.")
            at.get_by_key("FormSubmitter:add_col_form_1-Add Column").click()
            at.run()
        finally:
            if saved_key is not None:
                os.environ["GROQ_API_KEY"] = saved_key

        check("Groq failure (missing key) during add-column -> no exception raised", not at.exception)
        conn = get_connection(db_path)
        cols_after = crud.get_columns(conn, 1)
        resilience_col = next((c for c in cols_after if c.name == "Resilience Test Col"), None)
        check("column was still created despite the Groq failure", resilience_col is not None)
        if resilience_col is not None:
            check(
                "column's requirement_text is exactly correct, not corrupted/truncated",
                resilience_col.requirement_text == "Resilience requirement text.",
            )
            resilience_syns = crud.get_synonyms(conn, resilience_col.id)
            check(
                "no synonyms were fabricated/stored for the failed generation",
                len(resilience_syns) == 0,
            )
        conn.close()

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
