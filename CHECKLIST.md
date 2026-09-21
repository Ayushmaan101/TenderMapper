# BUILD CHECKLIST — AIIMS Tender Compliance Mapper

**Working rules:**
- Re-read [PROJECT_HARNESS.md](PROJECT_HARNESS.md) before starting **any** item below.
- Work through items **one at a time, in order**.
- After completing an item: check it off, **stop**, and report (a) what was built/verified,
  (b) what's next. Do not start the next item without the user confirming.
- If the plan or stack needs to change, propose it and wait for a go-ahead. Do not edit
  PROJECT_HARNESS.md or change the stack unilaterally.

Legend: `[ ]` not started · `[x]` done · each item ends in a **Verify** line that must
actually pass before the item is checked off.

---

## Phase 0 — Foundations

### [x] 0.1 — Conda environment
Create conda env `tender-mapper` on Python 3.11. Confirm it exists and is activatable.
**Verify:** env activates; `python --version` reports 3.11.x. ✅ *Done 2026-09-21 — Python 3.11.16 at `C:\Users\Abhinav\anaconda3\envs\tender-mapper`.*

### [x] 0.2 — Project harness document
Write `PROJECT_HARNESS.md`: Overview, Tech Stack, Pipeline Steps, Data Model / Schema Config,
Main Workflow, Explicit Non-Goals, Environment.
**Verify:** file exists at project root and covers all six sections. ✅ *Done 2026-09-21.*

### [x] 0.3 — Build checklist
Write this file.
**Verify:** file exists at project root, every item unchecked except completed ones. ✅ *Done 2026-09-21.*

### [x] 0.4 — requirements.txt
Pin versions for streamlit, pymupdf, paddleocr (+ paddlepaddle), pytesseract, rank_bm25,
rapidfuzz, groq, openpyxl, python-dotenv. Flag platform install friction in PROJECT_HARNESS.md.
**Verify:** file exists; every pin is a version that actually resolves on PyPI for cp311/win-64;
friction documented in harness §7. ✅ *Done 2026-09-21 — versions resolved against live PyPI.*

### [x] 0.5 — Install dependencies & smoke-test imports
Install `requirements.txt` into `tender-mapper`. Install `paddlepaddle` first and alone, then
the rest. Install the Tesseract system binary separately (it is not a pip package).
**Verify:** `import streamlit, fitz, paddleocr, pytesseract, rank_bm25, rapidfuzz, groq,
openpyxl, dotenv` all succeed; `paddle.utils.run_check()` passes; `pytesseract.get_tesseract_version()`
returns a version. ✅ *Done 2026-09-21 — paddlepaddle 3.3.1 installed & verified alone first
(`paddle.utils.run_check()` → "PaddlePaddle is installed successfully"); remaining 9 packages
installed clean (exit 0); PaddleOCR warmed up (5 model bundles downloaded to
`~/.paddlex/official_models`, init in 50.1s); Tesseract 5.4.0 binary at
`C:\Program Files\Tesseract-OCR\tesseract.exe` confirmed via `pytesseract.get_tesseract_version()`;
full 10/10 smoke test passed.*

### [x] 0.6 — Project structure & skeleton
Create the package layout (app entry, `config/`, `ingest/`, `ocr/`, `search/`, `verify/`,
`export/`, `db/`, `seed/`), `.env.example`, `.gitignore`, and a `README.md` stub. Initialize git.
**Verify:** `streamlit run app.py` launches a two-tab shell (Run / Config) with no errors.
✅ *Done 2026-09-21 — `.gitignore` written first (excludes `.env`, `__pycache__/`,
`.pytest_cache/`, `*.db`/`*.sqlite`, model weight files, `uploads/`/`*.pdf`/`*.zip`, and
`.claude/`); 8 package dirs created each with a docstring `__init__.py` describing its
future role; `.env.example` mirrors the real `.env`'s key name only; `README.md` added;
`app.py` two-tab (Run/Config) shell launched headless on port 8765 — HTTP 200, clean
server log, no errors/warnings; server stopped after verification. `git init` +
initial commit (15 files) — confirmed `.env` and `.claude/` excluded from the diff
before committing.*

---

## Phase 1 — Config & persistence

### [x] 1.1 — SQLite schema + data models
Tables for `schema_table`, `schema_column` (name, requirement text, ordering), and
`column_synonym`. Connection helper, migrations/`CREATE TABLE IF NOT EXISTS`, CRUD functions.
User-scoped; survives restart.
**Verify:** unit-level script creates a DB, writes a table + columns + synonyms, reopens the DB
in a new process, reads them back identical — including preserved line breaks in requirement text.
✅ *Done 2026-09-21 — `db/connection.py` (foreign_keys=ON per connection), `db/schema.py`
(DDL with `ON DELETE CASCADE` schema_table→schema_column→column_synonym), `db/models.py`
(frozen dataclasses), `db/crud.py` (create/get/update/delete + `reorder_tables`/
`reorder_columns` with dense 0-based `order_index`, re-normalized on delete; no `.strip()`
anywhere). Verified via `tests/verify_db_roundtrip.py`, which spawns two genuinely separate
OS processes (subprocess, distinct PIDs) — 20/20 checks passed: table/column order survives
`reorder_*`, a multi-line requirement string (trailing spaces, blank line, tab, em dash/curly
quotes, no final newline) round-trips sha256-identical, a padded synonym round-trips
unstripped, and `delete_column`/`delete_table` cascade correctly (verified as real DB-level
`ON DELETE CASCADE`, since the CRUD code never manually deletes child rows).*

### [ ] 1.2 — Seed data module + first-run auto-seed
Encode the exact Table 1 (10 columns) and Table 2 (13 rows) requirement text verbatim,
line breaks preserved. Auto-seed **only** when the DB is empty.
**Verify:** fresh DB → both tables present with exactly 10 and 13 entries, text byte-identical to
spec; second startup does **not** re-seed or duplicate; edits made by the user survive a restart.

### [ ] 1.3 — Config tab UI
Dedicated Config tab: add/remove tables, add/remove/reorder columns, edit column names and
requirement text, view/edit stored synonyms per column. Persists to SQLite on save.
**Verify:** add a table, edit a requirement, delete a column, restart the app — all changes
persist; seeded baseline is editable, not read-only.

### [ ] 1.4 — Config-time synonym expansion (Groq, one-time)
On configuring/saving a column, make **one** Groq call to generate alternate phrasings and
abbreviations for its key terms; store them with the row in the DB. Not per-search-run.
Manually editable afterwards. Handle API failure without losing the user's config edit.
**Verify:** saving a new column populates synonyms once; re-opening the Config tab makes **no**
further API call; manual edits to the synonym list stick; a forced API failure still saves the
column text.

---

## Phase 2 — Ingest & text extraction

### [ ] 2.1 — Upload + zip/folder handling
Accept all three input modes: a zip, a folder, and multiple separate PDF files. Normalize to a
session-scoped list of `(pdf_name, bytes/path)`. Reject non-PDFs with a clear message.
**Verify:** all three modes produce the same normalized PDF list; a nested zip of folders works;
a zip containing non-PDFs skips them with a visible warning.

### [ ] 2.2 — Text-layer pre-check (PyMuPDF)
Per page, `get_text()`; decide "usable text layer" vs "needs OCR" with a documented threshold.
**Verify:** on a born-digital PDF every page is marked text-layer; on a scanned PDF every page is
marked needs-OCR; on a mixed PDF the split is correct per page.

### [ ] 2.3 — OCR pipeline (PaddleOCR primary, Tesseract fallback)
Rasterize needs-OCR pages via PyMuPDF and OCR them. PaddleOCR primary; fall back to Tesseract on
failure/unavailability. Cache per (pdf, page) so re-runs within a session don't re-OCR. Surface
progress in the UI — this is the slow step.
**Verify:** a scanned PDF yields non-empty text per page; forcing PaddleOCR to fail routes to
Tesseract and still returns text; a second run within the session hits cache, not OCR.

### [ ] 2.4 — Section/clause reference extraction
During extraction/OCR, separately index "Section X, Clause Y" style references per page as a
lightweight secondary lookup.
**Verify:** a page whose only signal is "Section VIII Clause 13" is retrievable by that reference
even though it contains none of the requirement's vocabulary.

---

## Phase 3 — Retrieval & verification

### [ ] 3.1 — BM25 index + synonym-aware search
Build a BM25 index over all extracted/OCR'd page text for the session. Own the tokenizer
(`rank_bm25` has none). Query = requirement terms + stored synonyms, with `rapidfuzz` for term
variants/OCR noise. Return **top 15–20 candidate pages** per schema row — wide, not top-5.
**Verify:** a known requirement returns its known page inside the candidate pool; synonyms
demonstrably change results vs. terms alone; pool size is 15–20, configurable.

### [ ] 3.2 — Groq verification / rerank
For each candidate page, send page text + requirement text to Groq (Llama 3.3 70B); get back
structured JSON `{pdf_name, page_number_or_range, confidence, match_snippet}`. Handle malformed
JSON, rate limits, and retries. Batch/parallelize sensibly — this runs per column per candidate.
**Verify:** returns well-formed JSON for every column; a deliberately wrong candidate gets low
confidence; malformed model output is caught and retried rather than crashing the run.

### [ ] 3.3 — Full per-column resolution loop
Drive the whole pipeline for **every column in every configured table**, generalizing to any
configured shape. Progress reporting across the whole run.
**Verify:** with a 3rd table added via the Config tab, the run resolves its columns too — nothing
hardcodes 2 tables / 10 / 13.

---

## Phase 4 — Review UI & output

### [ ] 4.1 — Results table UI (`st.data_editor`)
One editable table per configured table, columns matching the config. Layout holds up for any
table/column/row count.
**Verify:** renders correctly for the seeded 10-column and 13-row tables **and** for an edited
config with different counts; cell edits persist in session state.

### [ ] 4.2 — Confidence flagging + manual re-search
Flag any row without a clean high-confidence match as flagged/incomplete — never silently blank,
never silently wrong. Flagged rows get a **"search again with custom terms"** box that re-runs
BM25 with the reviewer's terms, without touching the Config panel.
**Verify:** a low-confidence row renders visibly flagged; a no-match row renders flagged, not
blank; custom-term re-search updates just that row and leaves stored config synonyms unchanged.

### [ ] 4.3 — Session reset ("Next Company")
Build session-state management explicitly around the company-in → resolve → review →
"Next Company" loop. The button clears company name, uploads, and results; leaves config
untouched; returns to a fresh upload state.
**Verify:** after clicking, all four clear conditions hold, config is byte-identical to before,
and a second company can be processed immediately in the same session with no stale state.

### [ ] 4.4 — Excel export (openpyxl)
Export the (possibly reviewer-edited) results to Excel matching the configured schema.
**Verify:** exported workbook opens cleanly; sheet/table structure matches the current config,
not the seeded default; reviewer edits from `st.data_editor` appear in the export.

---

## Phase 5 — Hardening & deployment

### [ ] 5.1 — Basic error handling
Graceful handling for: corrupt/encrypted PDFs, zero-page PDFs, OCR failures on a single page,
Groq API errors/timeouts/missing key, empty upload, and empty config. Errors surface in the UI
and never take down an entire run.
**Verify:** each failure mode produces a clear in-app message and the run continues for the
remaining pages/columns.

### [ ] 5.2 — Streamlit Community Cloud deployment config
`packages.txt` (Tesseract via apt), `requirements.txt` pinned for Linux, `.streamlit/config.toml`,
secrets handling for `GROQ_API_KEY`. Confirm whether PaddleOCR fits Community Cloud's resource
ceiling — if it does not, **report back before changing the stack**.
**Verify:** app builds and runs on Community Cloud; OCR path works there; secrets resolve.
