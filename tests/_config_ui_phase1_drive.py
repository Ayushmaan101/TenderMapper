"""Phase 1 of the Config tab UI verification (checklist 1.3).

Actually launches the real Streamlit app (via Streamlit's own
streamlit.testing.v1.AppTest — no browser, no extra dependency) against a
disposable temp DB, and drives it through add/edit/delete/reorder actions
on tables, columns, and synonyms by clicking the same buttons and setting
the same widgets a person would in the browser. Every mutation goes
through the real button callbacks in config/ui.py, which call the real
db/crud.py functions against the real SQLite file.

Run as its own OS process by tests/verify_config_ui.py; never imported
directly. Exits non-zero with a message if anything raises.

Deliberately blanks GROQ_API_KEY for this process (checklist 1.4 added
automatic synonym expansion on column create/edit - see config/synonyms.py
and config/ui.py). This test is scoped to Config CRUD, not synonym
expansion (that has its own suite: verify_synonyms_ui_triggers.py), and a
real live Groq call here would insert extra column_synonym rows and shift
the ids this script's hardcoded assertions rely on. Set to "" rather than
popped/deleted: config.synonyms calls load_dotenv() on import, and
load_dotenv() only fills in keys that are entirely ABSENT from os.environ
- a popped key gets silently refilled from .env on the next import, an
explicitly blank one does not. With a blank key, expand_synonyms fails
fast and cleanly (per its own resilience contract) instead of calling out.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = sys.argv[1]
os.environ["TENDER_MAPPER_DB_PATH"] = DB_PATH
os.environ["GROQ_API_KEY"] = ""

from streamlit.testing.v1 import AppTest  # noqa: E402


def run_ok(at: AppTest, label: str) -> None:
    at.run(timeout=15)  # default 3s is occasionally too tight for this app's now-larger startup/import cost
    if at.exception:
        print(f"FAIL {label}: exception during run: {at.exception}")
        sys.exit(1)
    print(f"OK   {label}")


def main() -> None:
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"))
    run_ok(at, "initial launch (DB created + seeded at startup)")

    # Fresh temp DB -> deterministic autoincrement ids from seeding:
    # Table 1 = table id 1, columns id 1..10; Table 2 = table id 2, columns id 11..23.

    # --- ADD a table ---
    at.get_by_key("add_table_name").set_value("Extra Table")
    at.get_by_key("FormSubmitter:add_table_form-Add Table").click()
    run_ok(at, "add table 'Extra Table'")

    # --- EDIT (rename) an existing table ---
    at.get_by_key("tname_1").set_value("Table 1 Renamed")
    at.get_by_key("tname_save_1").click()
    run_ok(at, "rename table 1 -> 'Table 1 Renamed'")

    # --- EDIT a column's name + requirement text (multi-line, to also
    # confirm the st.text_area round-trip preserves embedded newlines) ---
    at.get_by_key("cname_1").set_value("Item 1 RENAMED")
    at.get_by_key("creq_1").set_value("Renamed requirement line one.\nRenamed line two.")
    at.get_by_key("csave_1").click()
    run_ok(at, "edit column 1 (name + multi-line requirement_text)")

    # --- DELETE a column ---
    at.get_by_key("cdel_10").click()
    run_ok(at, "delete column 10 ('Item 10')")

    # --- REORDER: move column 3 up, swapping with column 2 ---
    at.get_by_key("up_3").click()
    run_ok(at, "move column 3 up (swap with column 2)")

    # --- ADD two synonyms to column 2, then REMOVE the first ---
    at.get_by_key("newsyn_2").set_value("syn-test-1")
    at.get_by_key("FormSubmitter:add_syn_form_2-Add").click()
    run_ok(at, "add synonym 'syn-test-1' to column 2")

    at.get_by_key("newsyn_2").set_value("syn-test-2")
    at.get_by_key("FormSubmitter:add_syn_form_2-Add").click()
    run_ok(at, "add synonym 'syn-test-2' to column 2")

    # First synonym inserted ever -> id 1. Remove it, keep the second (id 2).
    at.get_by_key("sdel_1").click()
    run_ok(at, "remove synonym id 1 ('syn-test-1'), keep 'syn-test-2'")

    # --- DELETE an entire table (cascade: its columns + their synonyms) ---
    at.get_by_key("tdel_2").click()
    run_ok(at, "delete table 2 ('Table 2') entirely")

    print("PHASE 1 (drive UI) COMPLETE")


if __name__ == "__main__":
    main()
