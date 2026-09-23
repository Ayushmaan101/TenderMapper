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

### [x] 1.2 — Seed data module + first-run auto-seed
Encode the exact Table 1 (10 columns) and Table 2 (13 rows) requirement text verbatim,
line breaks preserved. Auto-seed **only** when the DB is empty.
**Verify:** fresh DB → both tables present with exactly 10 and 13 entries, text byte-identical to
spec; second startup does **not** re-seed or duplicate; edits made by the user survive a restart.
✅ *Done 2026-09-21 — `seed/seed_data.py` (`SEED_SCHEMA`, all 23 items transcribed from the
original spec; per user's explicit choice, wrapped lines are rejoined into one continuous
paragraph per item, single-space-joined at each line break — all other text, including
original typos/inconsistencies like Item 3's "centre" vs. other items' "Centre" and the
mismatched parens in Item 7, preserved as-is) and `seed/seeder.py` (`is_empty`/`seed_if_empty`).
Verified via `tests/verify_seed.py` — 58/58 checks passed: empty DB → 2 tables / 23 columns
created; every one of the 23 `requirement_text` values individually checked
character-for-character (`==` and sha256) against `SEED_SCHEMA`; re-running `seed_if_empty` on
the now-populated DB returns `False` and creates zero duplicates; a user edit made after
seeding survives a further `seed_if_empty` call. Column names ("Item N" / "Document N") are a
documented default assumption, freely renamable via the Config tab (1.3) — not part of the
user's original spec.
**Superseded in 1.3:** the original v1 gating (live `schema_table` row count) couldn't tell
"never seeded" apart from "user deliberately emptied it" — see 1.3's `app_meta.has_been_seeded`
flag fix below.*

### [x] 1.3 — Config tab UI
Dedicated Config tab: add/remove tables, add/remove/reorder columns, edit column names and
requirement text, view/edit stored synonyms per column. Persists to SQLite on save.
**Verify:** add a table, edit a requirement, delete a column, restart the app — all changes
persist; seeded baseline is editable, not read-only.
✅ *Done 2026-09-21 — **Seeding fix (requested alongside 1.3):** added `app_meta` key-value
table (`db/schema.py`, `db/meta.py`) and switched `seed/seeder.py`'s `seed_if_empty` to gate on
a persisted `has_been_seeded` flag instead of a live row count, so a user deliberately deleting
every table no longer causes a later restart to silently re-seed the defaults back in
(`tests/verify_seed.py` extended to 62/62, covering exactly that scenario). Also switched
`db/connection.py` to `check_same_thread=False`, required for Streamlit's cached cross-thread
connection.
**Config tab:** `config/ui.py` (`render_config_tab`) — add/rename/delete tables; add/edit
(name + requirement text)/reorder (▲/▼)/delete columns; view/add/remove synonyms per column.
Every mutation calls `db/crud.py` directly, no session-state schema cache, followed by
`st.rerun()` for a guaranteed-fresh re-render. `app.py` wires `seed_if_empty()` into a
`st.cache_resource`-cached DB connection created at startup (once per server process).
**Verification — `tests/verify_config_ui.py`, 18/18 checks passed, two genuinely separate OS
processes:** phase 1 uses Streamlit's own `streamlit.testing.v1.AppTest` (no browser, no new
dependency) to actually launch `app.py` and click the real buttons — add a table, rename a
table, edit a column's name + multi-line requirement text, delete a column, reorder two
columns, add two synonyms and remove one, then delete an entire table. Phase 2 reopens the
same DB file cold, in a separate process, and confirms every action persisted exactly,
including cascade-delete of the removed table's columns and the multi-line requirement text
surviving the `st.text_area` round-trip untouched. Separately confirmed via `AppTest` against
the real default DB path (not a temp override) that the production `db/tender_mapper.db` is
created and seeded correctly on first real run, with the em dash in Item 4 verified by
codepoint (`U+2014`) and sha256 rather than trusting terminal rendering.*

### [x] 1.4 — Config-time synonym expansion (Groq, one-time)
On configuring/saving a column, make **one** Groq call to generate alternate phrasings and
abbreviations for its key terms; store them with the row in the DB. Not per-search-run.
Manually editable afterwards. Handle API failure without losing the user's config edit.
**Verify:** saving a new column populates synonyms once; re-opening the Config tab makes **no**
further API call; manual edits to the synonym list stick; a forced API failure still saves the
column text.
✅ *Done 2026-09-21 — **Model substitution (user-approved):** the harness's `llama-3.3-70b-versatile`
does not exist on this Groq account at all (confirmed live via `/models`); switched to
`openai/gpt-oss-120b`. Same risk flagged against the not-yet-built checklist 3.2 (verification/
rerank), also specced as Llama 3.3 70B. See PROJECT_HARNESS.md §2, §9.
**`config/synonyms.py`:** `expand_synonyms()` never raises — every failure (missing key, any
Groq SDK exception, malformed/empty JSON) returns a failed `SynonymExpansionResult` instead;
retries up to 3 attempts on genuinely transient failures (rate limit, connection, timeout,
server error, malformed JSON), not on auth/permission/not-found. `_parse_synonyms_response`
strips markdown code fences and surrounding whitespace, accepts either the requested
`{"synonyms": [...]}` object or a bare array, dedupes case-insensitively. `merge_new_synonyms`
only ever *adds* rows not already present (case-insensitive) — never replaces or deletes,
satisfying "manually added/edited synonyms are never overwritten."
**Trigger wiring (`config/ui.py`):** exactly three call sites — column create; column save
*only if requirement_text actually changed* (name-only edits don't trigger it); the new
"✨ Generate / Suggest Synonyms" button per column. Every other rerun (opening/closing
expanders, switching tabs) calls nothing. Feedback via `st.toast` (survives the immediate
`st.rerun()` that follows every mutation); a Groq failure never blocks or reverts the column
save, which already happened independently through `db/crud.py` first.
**Verification — three suites, orchestrated by `tests/verify_synonyms.py`, all passing:**
`verify_synonyms_unit.py` (24/24, no network) — response parsing edge cases, `merge_new_synonyms`
never-overwrite behavior against a real temp DB, and every `expand_synonyms` failure path via a
monkeypatched `config.synonyms.Groq`. `verify_synonyms_live.py` (4/4, **one real Groq call**,
two genuinely separate OS processes) — a live call against real seeded requirement text, merged
into a temp DB, then reopened cold in a separate process to confirm real SQLite persistence
alongside a pre-existing manual synonym that survived untouched; this live run is what surfaced
the `max_tokens` bug above. `verify_synonyms_ui_triggers.py` (20/20, `AppTest` with a mocked
Groq client and a call-counter) — proves, by exact call count: add-column triggers once;
rename-only save triggers zero times; requirement-text-changed save triggers exactly once;
the manual button triggers on demand and merges rather than replaces (a manual synonym added
mid-test survives a regeneration with entirely different mocked terms); repeated reruns/
navigation with no button press trigger zero calls; a forced missing-key failure during
column creation still saves the column correctly (exact name + requirement_text, zero
fabricated synonyms) and raises no exception.
**Regression fixes found along the way:** `tests/_config_ui_phase1_drive.py` (checklist 1.3)
needed `GROQ_API_KEY` explicitly blanked, since its own "edit column 1" step now triggers real
automatic expansion, which was shifting the hardcoded synonym ids that test's phase 2 asserted
on — fixed by scoping that test to Config CRUD only (blanked key → expansion fails cleanly,
per its own resilience contract). Also had to set the key to `""` rather than pop it, since
`config/synonyms.py`'s `load_dotenv()` refills a fully-absent key from `.env` on import.
Full regression suite (`verify_db_roundtrip`, `verify_seed`, `verify_config_ui`,
`verify_synonyms`) passes clean end-to-end after both fixes.*

---

## Phase 2 — Ingest & text extraction

### [x] 2.1 — Upload + zip/folder handling
Accept all three input modes: a zip, a folder, and multiple separate PDF files. Normalize to a
session-scoped list of `(pdf_name, bytes/path)`. Reject non-PDFs with a clear message.
**Verify:** all three modes produce the same normalized PDF list; a nested zip of folders works;
a zip containing non-PDFs skips them with a visible warning.
✅ *Done 2026-09-21 — **`ingest/pipeline.py`** (`normalize_uploads`, zero dependency on Streamlit
or `db/`): accepts loose PDFs and/or `.zip` archives from `st.file_uploader(accept_multiple_files=True)`
— a dropped/multi-selected folder collapses to the same "many files" path in the browser, so all
three input modes are handled by one code path. Zip handling is recursive (zip-in-zip, bounded
`MAX_ZIP_DEPTH=5`), filters macOS junk (`__MACOSX/`, `.DS_Store`, `._*` AppleDouble forks)
silently (no warning spam for noise the user didn't create), and rejects unsafe entry paths
(absolute paths, drive letters, `..` traversal, embedded NUL) as an explicit Zip Slip guard even
though this module never writes to disk today. A `.pdf`-named file whose content doesn't start
with `%PDF-` is rejected, not silently trusted. Size/count budgets
(`MAX_TOTAL_UNCOMPRESSED_BYTES=1 GiB`, `MAX_TOTAL_ENTRIES=5000`, both overridable) guard against
zip bombs, shared across an entire upload batch. Filename collisions (same name from two
sources) are resolved by auto-renaming the later one (`invoice (2).pdf`) with a warning
explaining why, never by silently dropping one.
**`ingest/ui.py`** wires this to `st.session_state` only (`ingested_documents`,
`ingest_warnings`) — zero `db/` imports, zero SQLite calls. Re-normalizes only when the upload
selection's (name, size) signature actually changes, not on every unrelated rerun elsewhere in
the app (e.g. editing something in the Config tab). Wired into `app.py`'s Run tab alongside a
company-name field (a small proactive step toward the Main Workflow's step 2 in
PROJECT_HARNESS.md §5, beyond 2.1's literal scope but low-cost and already-approved shape).
**Verification — two suites, orchestrated by `tests/verify_ingest.py`, both passing:**
`verify_ingest_unit.py` (39/39, no Streamlit) — direct single/multi PDF uploads; a zip with
PDFs nested several folders deep; a zip mixing valid PDFs with `.png`/`.docx` (each producing
its own named warning, valid PDFs still extracted cleanly); macOS junk silently filtered;
zip-in-zip recursion; four distinct Zip Slip payloads (`../../evil.pdf`, `/etc/evil.pdf`,
backslash traversal, a drive-letter path) all rejected with none reaching the output; a corrupt
zip rejected cleanly; a fake-content `.pdf` rejected; three-way and cross-source (direct upload
vs. zip entry) filename collisions resolved by sequential renaming without data loss; both
safety-budget limits proven to stop processing early rather than hang/crash.
`verify_ingest_ui.py` (13/13, real `AppTest` file-upload simulation via `.upload()`) — a mixed
zip populates `session_state` with exactly the 2 valid PDFs and 1 warning; a call-counter on
`normalize_uploads` proves it fires exactly once on upload and zero additional times across 3
idle reruns; a before/after fingerprint of every table/column/synonym in the real config DB is
byte-identical across the whole upload flow, proving session state is fully isolated from
SQLite; clearing the upload clears session state back to empty and triggers exactly one more
call. Full regression suite (`verify_db_roundtrip`, `verify_seed`, `verify_config_ui`,
`verify_synonyms`, `verify_ingest`) passes clean end-to-end.*

### [x] 2.2 — Text-layer pre-check (PyMuPDF)
Per page, `get_text()`; decide "usable text layer" vs "needs OCR" with a documented threshold.
**Verify:** on a born-digital PDF every page is marked text-layer; on a scanned PDF every page is
marked needs-OCR; on a mixed PDF the split is correct per page.
✅ *Done 2026-09-21 — **`ocr/text_check.py`**: `check_page_text_layer`/`check_pdf_text_layers`,
immutable `PageTextResult` (`pdf_name, page_number, text, has_usable_text, needs_ocr,
word_count, alnum_char_count, has_images`). **Threshold, deliberately not `len(text) > 0`:**
`has_usable_text` requires >= 5 whitespace-separated word-tokens (each containing at least one
alnum char, so `"----" "****"` divider noise doesn't count) AND >= 20 alnum characters total —
catches both a scanned page's stray watermark/stamp text (too sparse to clear the bar) and a
punctuation-only noise page (long in raw length, zero real words). `needs_ocr = (not
has_usable_text) and has_images` — deliberately not a plain negation of `has_usable_text`: a
short-but-real text-only page (e.g. "ANNEXURE A", no embedded image) ends up
`has_usable_text=False, needs_ocr=False`, since there's nothing rasterized for OCR to recover
anything better from; only when an embedded image (`page.get_images()`) is *also* present does
the sparse/absent text trigger OCR. `has_images` is PyMuPDF's own image list, a reliable
scanned-page signature independent of text density.
**Verification — `tests/verify_text_check.py`, 37/37, all synthetic PDFs generated in-memory
via PyMuPDF itself** (`page.insert_text`/`page.insert_image` with a raw `fitz.Pixmap` — no
external files, no Pillow): an all-digital 3-page PDF (every page usable, no OCR, 1-indexed
page numbers correct); an all-scanned 3-page PDF (every page needs OCR, empty text); a 5-page
mixed PDF with the exact per-page digital/scanned pattern asserted page-by-page; a truly blank
page (`has_usable_text=False, needs_ocr=False` — the "neither" case); a sparse-real-text page
with no image (proves the "don't waste OCR on a short-but-complete page" half of the design);
a watermark-over-a-scanned-image page (proves the "don't trust sparse text on a real scan"
other half — `needs_ocr=True` despite text being present); a real-text page with an
incidental logo image (usable text wins regardless of image presence); a long
punctuation-only page demonstrating directly that raw character count alone (which a naive
check would accept) is correctly rejected; an exact threshold-boundary pair (5 words passes,
4 words fails) proving the documented constants are the real boundary; and a hand-crafted
zero-page PDF (PyMuPDF's own writer can't produce one via `tobytes()`, so this fixture is a
minimal raw PDF byte string) confirming graceful handling of the "zero-page PDFs" scenario
CHECKLIST.md 5.1 flags for later. Full regression suite (`verify_db_roundtrip`, `verify_seed`,
`verify_config_ui`, `verify_synonyms`, `verify_ingest`, `verify_text_check`) passes clean.*

### [x] 2.3 — OCR pipeline (PaddleOCR primary, Tesseract fallback)
Rasterize needs-OCR pages via PyMuPDF and OCR them. PaddleOCR primary; fall back to Tesseract on
failure/unavailability. Cache per (pdf, page) so re-runs within a session don't re-OCR. Surface
progress in the UI — this is the slow step.
**Verify:** a scanned PDF yields non-empty text per page; forcing PaddleOCR to fail routes to
Tesseract and still returns text; a second run within the session hits cache, not OCR.
✅ *Done 2026-09-21 — **`ocr/pipeline.py`**: `rasterize_page` (PyMuPDF `get_pixmap` at 200 dpi,
`zoom = dpi/72`, no temp files, returns a PIL Image); `ocr_page` (PaddleOCR first, Tesseract on
any exception, `engine="failed"` with both error messages if both fail — never raises itself);
`resolve_pdf_text` (the real per-PDF orchestrator: reuses checklist 2.2's pre-check to route
each page to `engine="native"` — no OCR engine invoked at all — or to `ocr_page`, with an
optional caller-supplied cache dict keyed `(pdf_name, page_number)` and an optional
`progress_callback(pages_done, pages_total)`; Streamlit-free throughout — the caller, e.g.
`st.session_state`, owns the actual cache/progress wiring). Immutable `OcrPageResult`
(`pdf_name, page_number, text, engine, success, error`) — engine is one of `"native"`,
`"paddleocr"`, `"tesseract"`, `"failed"`.
**Two real environment issues found and fixed** (documented in PROJECT_HARNESS.md §7/§9, not
just here): (1) `PaddleOCR(...).predict()` crashed on every call on this machine with oneDNN
acceleration on (a Paddle-internal PIR/oneDNN bug in the detection model, not project code) —
fixed with `enable_mkldnn=False`, required in production, not just for tests; (2)
`use_doc_orientation_classify`/`use_doc_unwarping` (correction for photographed/warped
documents) were observed to zero out detection entirely on a clean synthetic test page —
disabled by default, since this project's real input is office-scanned PDFs, not phone
photos, and the risk outweighed the marginal value here; `use_textline_orientation=True`
(the user's spec) kept on as the lighter-weight, lower-risk correction. `Pillow`/`numpy` added
to `requirements.txt` as explicit direct dependencies (already installed transitively).
**Verification — `tests/verify_ocr_pipeline.py`, 34/34.** Two tests use the REAL engines
against a genuinely "scanned" synthetic PDF (real text rendered once, then re-embedded as a
plain image with no extractable text layer, so the pipeline has no choice but to actually OCR
it): real PaddleOCR success with correct extracted text; a forced PaddleOCR failure (a real
raised exception, not a mocked success) correctly falling back to the real Tesseract binary,
which correctly extracts the text. Routing/caching/progress logic — the parts that are about
pipeline correctness, not OCR accuracy — use fast monkeypatched engines with a call counter to
stay deterministic and quick: both-engines-fail handling; an all-digital PDF never invoking
either OCR engine; a blank page resolving to empty native text with zero OCR calls; a 5-page
mixed PDF resolving the exact per-page native/OCR pattern with OCR invoked exactly 3 times;
the progress callback firing once per page in strict increasing order; a cache hit returning
the identical cached result object with zero additional OCR calls, contrasted directly against
`cache=None` re-invoking OCR every time; and the cache key proven to be genuinely
`(pdf_name, page_number)` (two scanned pages in one PDF produce two distinct entries, each hit
independently on re-run). Full regression suite (all 7 test files) passes clean.*

### [x] 2.4 — Section/clause reference extraction
During extraction/OCR, separately index "Section X, Clause Y" style references per page as a
lightweight secondary lookup.
**Verify:** a page whose only signal is "Section VIII Clause 13" is retrievable by that reference
even though it contains none of the requirement's vocabulary.
✅ *Done 2026-09-23 — **`ocr/references.py`**: `extract_references` (4 keyword-anchored regexes —
section+clause combo, standalone section/performa, schedule, form), immutable
`ExtractedReference` (`kind, canonical, raw_text`), plus `ReferenceIndex`/`build_index`/`lookup`
for the reverse (canonical token → `(pdf_name, page_number)`) index. Every pattern requires its
literal keyword (Section/Sec./Clause/Cl./Schedule/Form) at a word boundary — never a bare
number/date heuristic — which is what keeps it from false-positiving on financial years, money,
or durations. **Canonicalization**: section numbers may be Roman (`VIII`) or Arabic (`8`) — both
normalize to the same Arabic token via a round-trip-validated Roman-numeral converter (rejects
malformed sequences like `IIII` or `VX` rather than guessing a value), so `Section VIII Clause 11`
and `Sec. 8 Cl. 11` resolve to the identical `section 8 clause 11` token; leading zeros stripped
(`Form-045` → `form 45`). A section+clause match also emits its own bare `section N` entry, so a
query for just "Section VIII" still finds a page only ever indexed via the full combo.
**Verification — `tests/verify_references.py`, 68/68**, including:
- **100% seed-schema coverage**: every one of the 23 real Table 1/Table 2 seed items checked
  against a hand-derived expected canonical-reference set (12 items carry a reference, 11
  correctly produce none) — not synthetic stand-ins, the actual `SEED_SCHEMA` strings.
- **False positives**: an extensive suite built from real risky substrings already present in
  the seed text itself — financial years, `Rs.10/-`/`Rs. 100/-` amounts, `"3-years"`/`45 days`/
  `02 years` durations, `3rd Party Sale`, `25%`, `I.V fluids`, `"Tender Acceptance Form"` (Form
  with no trailing number), and — the trickiest case — `"form"` embedded mid-word inside
  `performance`/`format`/`information`, all three of which are literal substrings of the real
  seed text. A dedicated test also confirms `Form-45` and the unrelated `45 days` (same digits,
  different meaning) resolve correctly in opposite directions.
- **Format-variant equivalence**: `Section VIII Clause 11` / `Section-VIII, Clause 11` /
  `Sec. 8 Cl. 11` / mixed case all canonicalize identically; malformed Roman numerals rejected.
- **The core point of this module**: a synthetic page whose entire text is the bare string
  `"Section VIII Clause 11"` — zero requirement vocabulary — is correctly found via `lookup()`
  when queried with the real Document 3 seed text; an unrelated page in the same index is not.
  Also verified: bare-section queries find combo-indexed pages, a no-reference query returns an
  empty list rather than erroring, repeated mentions on one page don't duplicate that page's
  index entry, and distinct pages/PDFs are tracked independently.
Full regression suite (all 8 test files) passes clean.*

---

## Phase 3 — Retrieval & verification

### [x] 3.1 — BM25 index + synonym-aware search
Build a BM25 index over all extracted/OCR'd page text for the session. Own the tokenizer
(`rank_bm25` has none). Query = requirement terms + stored synonyms, with `rapidfuzz` for term
variants/OCR noise. Return **top 15–20 candidate pages** per schema row — wide, not top-5.
**Verify:** a known requirement returns its known page inside the candidate pool; synonyms
demonstrably change results vs. terms alone; pool size is 15–20, configurable.
✅ *Done 2026-09-23 — **`search/tokenize.py`**: lowercase, split on non-alphanumeric runs,
drop tokens < 2 chars, filter a deliberately conservative stopword list — explicitly verified
`"who"` is never filtered (WHO-GMP is load-bearing domain vocabulary, and a generic stopword
list would normally drop the pronoun "who").
**`search/bm25_index.py`**: `CorpusIndex` (built once per session, reused across every schema
column's query — not rebuilt per column) wraps `rank_bm25.BM25Okapi`, guarded against the
library's `ZeroDivisionError` on an all-empty corpus. `search()` builds query tokens from
requirement text + synonyms, fuzzy-expands them against the corpus vocabulary, scores via BM25,
merges in `ocr.references.ReferenceIndex` hits (guaranteed a pool slot ahead of plain
BM25-ranked non-reference pages, tiebroken by their own score), and returns `SearchCandidate`
(`pdf_name, page_number, rank, score, snippet, matched_terms, match_signals`).
**Fuzzy matching, corrected from the first draft**: uses `rapidfuzz.distance.Levenshtein`
*absolute* edit distance, not a percentage ratio — a ratio cutoff badly under-serves short
tokens (`who`→`wh0` is only ~67% similar by ratio, below a typical 75–80% cutoff, while the
identical single-substitution `certificate`→`cert1ficate` scores ~91%; both are exactly one
wrong character). The distance budget scales with token length (1 for <5 chars, 2 for longer)
specifically to avoid the opposite risk: at distance ≤2, unrelated short acronyms like `gst`/
`gmp` are edit-distance 2 apart and would otherwise cross-match. Also fixed during verification:
the first draft skipped fuzzy expansion for any query token that had *some* exact vocabulary
match, which silently missed a noisy OCR variant on a *different* page when a clean spelling
existed elsewhere in the corpus — now every token is fuzzy-expanded regardless.
**Verification — `tests/verify_bm25_search.py`, 38/38** against synthetic multi-page/multi-PDF
corpora: exact matches rank top with a positive score; a synonym-only page (zero token overlap
with the requirement's own wording, confirmed by direct set intersection) ranks #1 once the
synonym is added and is unreachable without it; the checklist's own `wh0`/`cert1ficate` OCR-noise
examples are captured via fuzzy expansion while still ranking below the clean exact match; the
`gst`/`gmp` short-acronym collision is proven *not* to happen; a reference-only page bubbles into
the pool, with a dedicated test isolating that effect from both "small corpus returns everything"
and BM25's own IDF math (which can make a bare rare phrase score deceptively high on wording
alone) — using a query that cites the same reference in a different surface form
(`Sec. 8 Cl. 11` vs. the page's `Section VIII Clause 11`) so the two signals stay cleanly
decoupled, with the exclusion cutoff discovered empirically at runtime rather than assumed; and
pool-size limits hold across corpus sizes both smaller (returns everything) and much larger
(caps exactly, including when reference hits alone would otherwise exceed the cap). Full
regression suite (all 9 test files) passes clean.*

### [x] 3.2 — Groq verification / rerank
For each candidate page, send page text + requirement text to Groq (Llama 3.3 70B); get back
structured JSON `{pdf_name, page_number_or_range, confidence, match_snippet}`. Handle malformed
JSON, rate limits, and retries. Batch/parallelize sensibly — this runs per column per candidate.
**Verify:** returns well-formed JSON for every column; a deliberately wrong candidate gets low
confidence; malformed model output is caught and retried rather than crashing the run.
✅ *Done 2026-09-23 — Model: `openai/gpt-oss-120b` (same substitution as 1.4, kept consistent
across both Groq call sites — `llama-3.3-70b-versatile` still doesn't exist on this account;
PROJECT_HARNESS.md §2/§9 updated to drop the "unconfirmed" flag left on this row after 1.4).
**`verify/groq_verifier.py`**: `verify_candidate` (single candidate, never raises — every
failure falls back to a `VerificationResult` with `confidence=0.0`, the candidate's own BM25
snippet kept as visible context, and a reasoning string flagging it for human review),
`verify_candidates` (bounded `ThreadPoolExecutor`, default 5 workers, plus early stopping —
once a result clears `early_stop_confidence` (default 0.90), not-yet-started candidate calls
are cancelled; already-in-flight ones are still awaited rather than left as orphaned background
threads, a deliberate documented tradeoff), `resolve_column` (top-ranked result per column, or
`None` for zero candidates). Structured JSON schema exactly as specified
(`pdf_name, page_number_or_range, confidence, match_snippet, reasoning`), response parsing
tolerant of markdown code fences (same pattern as `config/synonyms.py`). **`pdf_name`/
`page_number_or_range` are never trusted from the model's JSON echo** — always taken from the
candidate we already know we asked about, closing off a class of hallucination bugs for
information already held with certainty; verified directly with a candidate whose model
response deliberately claims a different pdf/page. Retryable failures (rate limit, timeout,
connection, server error) get up to 3 attempts, with an actual backoff sleep before retrying a
429 specifically (verified via a monkeypatched `time.sleep`, using a genuinely constructed
`groq.RateLimitError` via real `httpx.Request`/`Response` objects, not a generic stand-in).
**Verification — two suites, orchestrated by `tests/verify_groq_verifier.py`, both passing:**
`verify_groq_verifier_unit.py` (30/30, mocked Groq) — a true compliance match (confidence ≥0.9,
snippet reflects real evidence); a false-positive passing-mention candidate correctly scored
low; the model's echoed pdf/page deliberately ignored; missing-API-key, simulated network
failure, and malformed-JSON all falling back gracefully with `confidence=0.0` rather than
raising; the 429-retry-with-backoff behavior; `resolve_column` correctly picking the single
highest-confidence result among 5 out-of-order candidates (and returning `None` for zero
candidates); early stopping proven to skip remaining candidates deterministically
(`max_workers=1` makes execution sequential, so a call-counter proves later candidates never
ran) while a no-strong-match pool is proven to still evaluate every candidate; and a candidate
missing from the page-text map correctly falling back to its own BM25 snippet.
`verify_groq_verifier_live.py` (7/7, **two real Groq calls**) — against the real seed schema's
WHO-GMP requirement text (not synthetic stand-ins): a genuine WHO-GMP certificate page scored
0.95 confidence with accurate reasoning citing the actual issue date and issuing authority; a
page that only mentions WHO-GMP in passing (pointing to "Annexure B") scored 0.0, with
reasoning correctly explaining why — directly proving the prompt does its one job, penalizing
passing mentions and boilerplate rather than rewarding superficial keyword overlap.
Full regression suite (all 10 test files) passes clean.*

### [x] 3.3 — Full per-column resolution loop
Drive the whole pipeline for **every column in every configured table**, generalizing to any
configured shape. Progress reporting across the whole run.
**Verify:** with a 3rd table added via the Config tab, the run resolves its columns too — nothing
hardcodes 2 tables / 10 / 13.
✅ *Done 2026-09-23 — completed on top of checklist 5.1's partial build (ingest → OCR →
search-index, with per-document error isolation). **`run/pipeline_runner.py`** gains
`resolve_all_columns(conn, corpus_index, page_texts, reference_index)`: reads every
`schema_table`/`schema_column` fresh from `conn` (never cached), for each column queries the
index with the column's requirement text + its stored synonyms
(`search.bm25_index.search`, `DEFAULT_POOL_SIZE=20` candidates merged with reference-index
hits), verifies the pool via `verify.groq_verifier.resolve_column` (already bounded-worker +
early-stopping-at-0.90 by its own checklist 3.2 defaults — no new concurrency code needed
here), and returns the single best result per column, keyed by `column.id` — never silently
missing a column, even one with zero candidates (an empty corpus resolves every column to a
clear "unresolved" placeholder with **zero Groq calls made**, not a guess). Columns are
resolved **one at a time**, deliberately not ALSO parallelized against each other on top of
`resolve_column`'s own internal concurrency — keeps total concurrent Groq load bounded at
exactly `max_workers` regardless of column count, not `max_workers × column count`.
**Overwrite semantics (a real decision, documented in the module)**: every "Run Mapping" click
replaces `resolution_results` entirely with fresh output — it does not try to distinguish "a
prior human edit" from "a stale earlier auto-result" per column, since checklist 4.4 already
found `VerificationResult.success` alone can't tell those apart. Simple and predictable:
clicking Run Mapping means start the automated resolution fresh.
**UI (`run/run_button.py`)**: a second, distinct progress bar for the column-resolution phase
(`"Resolving requirements — N/M: <column name>"`), separate from phase 1's page-level OCR
progress bar, so a reviewer can see which phase is running.
**Verification — three suites, orchestrated by `tests/verify_column_resolution.py`, all
passing**: `verify_column_resolution_unit.py` (17/17, mocked Groq, real BM25 index) — every
configured column across **two tables** gets an entry; a column findable only via a *stored
synonym* (zero literal wording overlap otherwise) still resolves correctly, proving synonyms
are genuinely wired into the query rather than accepted as a no-op parameter; a column with
nothing relevant anywhere resolves low-confidence and is correctly flagged by checklist 4.2's
`is_flagged()`; an empty corpus makes every column resolve to the unresolved placeholder with
zero Groq calls; `progress_callback` fires once per column in strict order. **A real,
non-obvious bug in the test's own mock was caught via genuine run-to-run flakiness** (3/3
re-runs varied) before being fixed: a naive "does this marker phrase appear anywhere in the
prompt" check let a column's *own requirement text* (which legitimately contains its own
marker phrase) satisfy the check for *every* candidate regardless of which page was actually
being evaluated — scoping the check to the "Page text:" section specifically (not the whole
prompt) fixed it deterministically, confirmed via 5 consecutive clean runs.
`verify_column_resolution_live.py` (7/7, **real Groq calls**, real seeded schema) — against
all 10 real Table 1 columns and a synthetic corpus with a genuine WHO-GMP match: the matching
column (Item 4) resolved 0.95 confidence to the exact right page with a real snippet and
correctly *not* flagged; a genuinely unrelated column (Item 1) resolved 0.0 confidence and
correctly flagged.
`verify_column_resolution_ui.py` (12/12, `AppTest`, through the real "Run Mapping" button,
mocked Groq but **real OCR** on a genuinely rasterized synthetic scanned page) —
`resolution_results` auto-populates for all 23 seeded columns; the matching column's Status
cell in the real rendered grid reads "Resolved", every other column's reads "Flagged"; the
resolved match flows correctly into both the `st.data_editor` grid and the Excel export
(checklist 4.4 integration, verified via the real exported workbook bytes). Needed a bumped
`AppTest` timeout (default 3s is far too short for real OCR — checklist 0.5 measured ~50s for
PaddleOCR's own first-use init). Full regression suite (all 16 top-level test files) passes
clean; also confirmed against the real production DB.*

---

## Phase 4 — Review UI & output

### [x] 4.1 — Results table UI (`st.data_editor`)
One editable table per configured table, columns matching the config. Layout holds up for any
table/column/row count.
**Verify:** renders correctly for the seeded 10-column and 13-row tables **and** for an edited
config with different counts; cell edits persist in session state.
✅ *Done 2026-09-23 — **New `run/` package** (mirroring the `config/`, `ingest/` pattern):
`run/results.py`. **Row-orientation decision** (worth flagging explicitly): the results grid
renders one ROW per schema_column, not per the original tender document's own visual layout
(Table 1's 10 items read as ten columns-in-one-row in the real document; Table 2's 13 read as
thirteen rows). Mimicking either original layout would require per-table hardcoding — exactly
what this checklist forbids. Since config storage is uniform (N schema_columns per table, each
one resolvable requirement) regardless of the source document's layout, one grid row per
schema_column is the only representation that stays correct for an arbitrary, freely
reconfigured schema — this is how "gracefully render any arbitrary number of ... columns"
resolves into a concrete, dynamically-sized design.
**Columns**: `Column` (name, read-only) and `Requirement` (full text, read-only, for reviewer
context — a small addition beyond the checklist's literal 4-field list, justified since a
reviewer needs to see the requirement to judge whether a resolved match is correct) are
disabled; `PDF Name`, `Page Number / Range`, `Confidence` (numeric, clamped 0–1), `Match
Snippet` are editable. Edits are read back out of `st.data_editor`'s return value and written
explicitly into `st.session_state["resolution_results"]: dict[int, VerificationResult]` —
reusing checklist 3.2's `VerificationResult` type directly rather than inventing a parallel
data model, so checklist 3.3's resolution loop can populate the exact same structure this UI
already reads.
**Note on build order**: checklist 3.3 (the actual per-column resolution loop) hasn't been
built yet — per the user's explicit instruction to proceed straight to 4.1. The results UI
reads/edits whatever's in `st.session_state["resolution_results"]`; until 3.3 wires in real
search+verify calls, unresolved columns just show blank placeholder values, rendered identically
to a real (but empty) result — there is nothing 4.1-specific about "not yet resolved."
**Verification — `tests/verify_results_ui.py`, 18/18 (AppTest)**: `st.data_editor` has no
dedicated AppTest interaction helper (unlike `st.button`/`.text_input`/`.file_uploader`) — edits
are simulated the way Streamlit's own widget mechanism represents them internally, by writing a
`DataEditorState`-shaped dict directly into `st.session_state[<data_editor key>]` before the
next `at.run()` (confirmed empirically against the real widget before writing the suite).
Covers: the seeded schema renders exactly 2 grids with shapes `(10, 6)` and `(13, 6)` and the 6
expected columns; a cell edit's 4 fields land correctly in `resolution_results` and **survive a
further no-op rerun** (not silently reset); a schema reconfigured through the **real Config
tab** (a table added, Table 2 deleted, a column with a custom name added to Table 1) re-renders
with zero hardcoded assumptions — Table 1's grid grows from 10 to 11 rows, the new custom
column name appears as its own row, and a still-columnless new table correctly shows its caption
instead of an empty/broken grid; and the zero-tables edge case renders the empty-state message
cleanly. One real test-design bug was caught and fixed along the way: a 0-column table correctly
renders *no* `data_editor` at all — my first draft's expected dataframe count was wrong, not the
module's behavior. Full regression suite (all 11 test files) passes clean; also confirmed
against the real production DB (still holding the untouched seeded 10/13-row schema).*

### [x] 4.2 — Confidence flagging + manual re-search
Flag any row without a clean high-confidence match as flagged/incomplete — never silently blank,
never silently wrong. Flagged rows get a **"search again with custom terms"** box that re-runs
BM25 with the reviewer's terms, without touching the Config panel.
**Verify:** a low-confidence row renders visibly flagged; a no-match row renders flagged, not
blank; custom-term re-search updates just that row and leaves stored config synonyms unchanged.
✅ *Done 2026-09-23 — **Flagging**: `CONFIDENCE_THRESHOLD = 0.70`; `is_flagged(result)` = `(not
result.success) or confidence < 0.70` — deliberately not a plain confidence check, so a never-run
column (the 4.1 blank placeholder, `success=False`) and a Groq call that outright failed both
flag identically to a real low-confidence match, never silently blank. **Surfaced** via a
read-only "Status" column (⚠️ Flagged / ✅ Resolved) prepended to each table's grid, a per-table
`st.warning`/`st.success` summary, and an overall 3-metric summary (Total / Resolved / Flagged)
across all tables at the top of the Results section.
**Manual re-search**: one expander per flagged column ("🔍 {column name}") with a text input +
"Search again" button. Defines the session-state contract checklist 3.3 will populate —
`corpus_index` (a `search.bm25_index.CorpusIndex`), `page_texts`, `reference_index` — with a
graceful "no documents processed yet" message when they're absent, same placeholder posture as
4.1. The reviewer's custom terms drive BM25 **retrieval only** (no stored synonyms mixed in —
the reviewer is overriding the search per PROJECT_HARNESS.md §5: "type the exact term they see");
Groq **verification** still judges the result against the column's real, unmodified
`requirement_text` — custom terms help find the page, they don't redefine what "satisfies the
requirement" means. As in checklist 3.2, the resolved `pdf_name`/`page_number_or_range` are taken
from the real candidate, never the model's JSON echo.
**Strict isolation**: `_run_manual_research` takes no `db.crud` import and no `sqlite3.Connection`
— it can't write to the config DB even by accident, not just by convention. Verified directly
with a full table/column/synonym DB fingerprint, byte-identical before and after a manual
re-search.
**Verification — two suites, orchestrated by `tests/verify_flagging_and_research.py`, both
passing**: `verify_confidence_flagging_unit.py` (10/10, no Streamlit) — the blank placeholder and
a `success=False` result both flag regardless of confidence; the exact threshold boundary (0.69
flagged, 0.70 and 0.71 not). `verify_manual_research_ui.py` (27/27, `AppTest`) — fresh seeded
schema shows 23/23 flagged with 23 matching re-search expanders; injecting one high- and one
low-confidence result updates the summary metrics and per-row Status correctly, and the
now-resolved column's expander disappears while the still-flagged one's stays; a re-search
attempted with no corpus index yet is handled gracefully; a real re-search (mocked Groq,
deliberately returning a hallucinated `pdf_name`/page to prove it's ignored) updates only the
target column — **every other column's result, including two pre-existing ones, is proven
byte-unchanged** — flips that row's Status from Flagged to Resolved and removes its expander;
the **DB fingerprint is byte-identical before and after**; empty/whitespace-only custom terms
show a warning and never invoke a search at all. Full regression suite (all 12 test files,
including checklist 4.1's own suite updated for the new "Status" column) passes clean; also
confirmed against the real production DB.*

### [x] 4.3 — Session reset ("Next Company")
Build session-state management explicitly around the company-in → resolve → review →
"Next Company" loop. The button clears company name, uploads, and results; leaves config
untouched; returns to a fresh upload state.
**Verify:** after clicking, all four clear conditions hold, config is byte-identical to before,
and a second company can be processed immediately in the same session with no stale state.
✅ *Done 2026-09-23 — **New `run/session_reset.py`**: `render_next_company_button()` +
`_reset_for_next_company` callback. Uses `st.button(..., on_click=...)` rather than an inline
`if st.button(...)`, specifically because resetting the `company_name` text_input's displayed
value requires mutating its widget-backing session-state key **before** that widget re-renders
on the next script pass — Streamlit only permits this from within an `on_click` callback, not
from the main script body after the widget has already been instantiated earlier in the same run
(which it always has, since it renders above the results section this button sits beneath).
**File-uploader widget reset**: Streamlit has no direct "clear" API for `st.file_uploader`.
`ingest/ui.py` now keys the uploader dynamically (`company_file_uploader_{generation}`);
`reset_upload_state()` bumps the generation counter, forcing Streamlit to instantiate a brand-new
widget with no memory of prior selections (in both `session_state` and the browser's own DOM) —
the standard, documented workaround, and literally what the checklist asked for ("widget keys...
properly cycled"). The old generation's now-orphaned session-state entry is harmless and left
alone.
**Session-state contract completed**: `run/results.py` gains `OCR_CACHE_KEY` (the cache
checklist 2.3's `ocr.pipeline.resolve_pdf_text(cache=...)` parameter expects) alongside the
`corpus_index`/`page_texts`/`reference_index` keys already defined in 4.2, plus `reset_run_state()`
clearing all four. Nothing in `run/session_reset.py` imports `db.crud` or opens a
`sqlite3.Connection` — it cannot touch the config DB even by accident, not just by convention.
**Verification — `tests/verify_next_company_reset.py`, 27/27 (AppTest), full-cycle simulation**:
ingests Company A (name, an uploaded PDF, mock resolved results spanning both high- and
low-confidence, and a hand-populated search-index session-state contract matching what checklist
3.3 will produce), clicks "Next Company", then asserts **all four clear conditions** — company
name (both the session-state key *and* the widget's own displayed value), uploaded documents/
warnings/the uploader widget itself (confirmed via the key generation cycling from `_0` to `_1`,
not merely its value), `resolution_results` (every entry verified functionally blank — see the
test's own note on why the dict isn't literally `{}` immediately: `run/results.py`'s own
read-back-and-write-back persistence cycle from 4.1 repopulates it with blank-equivalent entries
on the very next render, which is correct, not a leak), and the full search-index contract
(`corpus_index`/`page_texts`/`reference_index`/`ocr_cache`, all reset to `None`/`{}`). Also
asserts the **config DB fingerprint is byte-identical** across the whole cycle — before Company A
ever touched it and after its full reset — and that **Company B loads with zero residual state**:
its upload is the *only* document present, explicitly checked for no `"CompanyA"` trace anywhere.
One real regression surfaced and fixed: checklist 2.1's own upload test hardcoded the (now
dynamic) uploader key — updated to the generation-0 key in the same commit. Full regression suite
(all 13 test files) passes clean; also confirmed against the real production DB.*

### [x] 4.4 — Excel export (openpyxl)
Export the (possibly reviewer-edited) results to Excel matching the configured schema.
**Verify:** exported workbook opens cleanly; sheet/table structure matches the current config,
not the seeded default; reviewer edits from `st.data_editor` appear in the export.
✅ *Done 2026-09-23 — **`export/excel_export.py`** (pure openpyxl, deliberately no Streamlit
import — matching the established split throughout this codebase, and what makes the workbook
directly unit-testable): one worksheet per `schema_table`, one data row per `schema_column`
(the same row orientation `run/results.py` settled on in 4.1). Exported columns exactly as
specified — `Status, Requirement, PDF Name, Page Number / Range, Confidence, Match Snippet`
— deliberately omitting the short internal "Column" label the Run tab's grid also shows; the
full requirement text is what a reader outside this app needs. **Formatting**: bold headers,
frozen header row, per-column widths, `wrap_text` on Requirement/Match Snippet, `0.00`
number format on Confidence. **Sheet-name sanitization**: ≤31 chars, Excel-prohibited
characters (`\ / ? * [ ] :`) replaced, blank-after-cleaning falls back to `"Sheet"`, and —
not explicitly asked for but necessary for correctness — **case-insensitive de-duplication**
(Excel treats "Table A" and "TABLE A" as the same sheet name) via a numeric suffix that still
respects the 31-char limit. **Refactor along the way**: `CONFIDENCE_THRESHOLD`/`is_flagged`
moved from `run/results.py` into `verify/groq_verifier.py` (alongside `VerificationResult`
itself) before `export/excel_export.py` was written — the first draft needed them from
`run/results.py`, an inverted dependency for a UI-layer package; `run/results.py` now
re-exports both for existing importers, unchanged behavior.
**Real bug found and fixed** (via this checklist's own export test, not 4.1/4.2's): the
results grid's edit-writeback (checklist 4.1) never set `success=True` on a manually corrected
cell, so a reviewer raising a row's confidence to 0.95 by hand kept `success=False` from its
original blank placeholder and stayed stuck showing "Flagged" — exactly the inconsistency
`is_flagged()` exists to prevent. Fixed by flipping `success` to `True` only when an edited
value genuinely differs from what's stored (not on every incidental rerender, which would have
made `success` meaningless as a signal). Verified this doesn't regress 4.1/4.2's own test
suites (full regression re-run clean).
**UI — new `run/export_ui.py`**: a thin `st.download_button` wrapper, placed after the
"Next Company" button per the checklist's literal instruction, with a caption calling out
that export should happen *before* clicking Next Company (which wipes the very state being
exported). Filename: sanitized company name + `.xlsx`, falling back to
`tender_compliance_mapping.xlsx` for a blank/all-invalid name.
**Verification — two suites, orchestrated by `tests/verify_excel_export.py`, both passing**:
`verify_excel_export_unit.py` (52/52, no Streamlit) — sheet/filename sanitization including a
genuine case-insensitive collision disambiguated within the length limit; the **seeded schema
producing exactly 2 sheets** ("Table 1": 11 rows, "Table 2": 14 rows including headers) with
every Requirement cell checked **verbatim** against the real seed text, in order; a hand-built
edit landing exactly in the right cell without touching any other row; a **reconfigured schema
with custom names, special characters, and a genuine sheet-name collision** producing a valid
file; and empty-results/zero-table/zero-column edge cases. Every workbook built in the suite is
round-tripped through `openpyxl.load_workbook()` on its exported bytes — the direct proof of
"produces valid, openable Excel files."
`verify_excel_export_ui.py` (14/14, `AppTest`) — since `AppTest`'s download-button element
exposes only whether it was clicked, not the file bytes (Streamlit stores the payload via an
internal deferred-file mechanism), this suite verifies UI *wiring* via `AppTest` and verifies
*content* by calling `export_to_bytes()` directly against the exact same session state a real
click would use: a real edit driven through the actual `st.data_editor` (same simulation
technique as 4.1/4.2) lands correctly in the exported bytes and flips that row's exported
Status to "Resolved"; company-name-to-filename mapping; and a table added through the real
Config tab with special characters in its name exports correctly with zero hardcoded
assumptions. Full regression suite (all 14 test files) passes clean; also confirmed against
the real production DB.*

---

## Phase 5 — Hardening & deployment

### [x] 5.1 — Basic error handling
Graceful handling for: corrupt/encrypted PDFs, zero-page PDFs, OCR failures on a single page,
Groq API errors/timeouts/missing key, empty upload, and empty config. Errors surface in the UI
and never take down an entire run.
**Verify:** each failure mode produces a clear in-app message and the run continues for the
remaining pages/columns.
✅ *Done 2026-09-23 — **Note on scope**: checklist 3.3 (the full per-column BM25-search +
Groq-verify loop) is still deferred, but per the user's explicit direction this item builds
both the underlying pipeline guards *and* a real, tested slice of the end-to-end execution
flow to verify them against — a new "▶️ Run Mapping" button (`run/run_button.py` +
`run/pipeline_runner.py`) that turns ingested documents into a searchable OCR/text index
(`corpus_index`/`page_texts`/`reference_index`), with per-document error isolation. This is
genuine forward progress on 3.3, not throwaway scaffolding — 3.3 still needs to add the
actual per-column BM25-search + Groq-verify loop on top of this.
**Corrupt / encrypted / zero-page PDFs** — confirmed PyMuPDF's real behavior first (not
assumed): `fitz.open()` raises `FileDataError` for corrupt bytes; for an encrypted PDF, `open()`
itself succeeds but `doc.needs_pass` is truthy and iterating pages raises `ValueError` the
moment anything tries to read one; a zero-page PDF opens fine with `page_count == 0` — a real,
different case, not an error. `ocr/text_check.py` gained `PdfProcessingError` (raised for the
first two, explicitly *not* the third) so `check_pdf_text_layers`/`resolve_pdf_text` (both
`ocr/text_check.py` and `ocr/pipeline.py`) give every caller exactly one exception type to
catch regardless of which underlying failure mode occurred, rather than a raw
version-dependent PyMuPDF exception. `run/pipeline_runner.py` catches it **per document**, so
one corrupt/encrypted sibling never aborts the rest of the batch.
**Single-page OCR failures**: re-confirmed checklist 2.3's existing contract (both PaddleOCR
and Tesseract failing on one page → `engine="failed"`, empty text, sibling pages unaffected)
specifically with a multi-page document under this checklist's own test umbrella — no code
change needed here, it already worked.
**Groq errors** (`config/synonyms.py`, `verify/groq_verifier.py`): re-confirmed the existing
resilience contracts from checklists 1.4/3.2 (missing key, simulated network drop) — again no
code change needed, already handled; re-tested here as dedicated 5.1 verification.
**Empty upload / empty config**: `run/run_button.py` checks both explicitly before doing
anything else — `st.warning` and an early return, never an `IndexError`/`AttributeError`.
Empty config was already separately handled by `run/results.py` (checklist 4.1); the new
button adds its own guard on the same condition, checked independently.
**A real, useful process discovery**: this checklist's UI test needed **multiple `AppTest`
instances within one Python process** for the first time in this project (every prior UI
suite created exactly one). That exposed that `app.py`'s DB connection — cached via
`st.cache_resource`, correct and intentional for real production use — is silently **shared
across every `AppTest` instance in the same process regardless of the `TENDER_MAPPER_DB_PATH`
env var**, since the cache doesn't vary by any argument. One scenario deliberately emptying
its config would otherwise have corrupted every later scenario's state. Fixed with
`st.cache_resource.clear()` before each scenario, alongside a distinct temp DB file — now
documented in the test itself for future multi-instance AppTest suites in this project.
**Verification — two suites, orchestrated by `tests/verify_error_handling.py`, both
passing**: `verify_error_handling_unit.py` (34/34, no Streamlit) — `PdfProcessingError` raised
correctly for corrupt/encrypted bytes and NOT raised for zero-page, at both the
`text_check`/`pipeline` layer; `run/pipeline_runner.py` isolating 2 genuinely bad documents
(corrupt + encrypted) from 3 good ones (2 valid + 1 zero-page, correctly not flagged as bad)
in one 5-document batch, with the search index containing only the valid pages; empty and
all-bad document lists handled cleanly; single-page OCR failure isolated within a 3-page
document; Groq missing-key and simulated-network-drop fallback for both call sites.
`verify_error_handling_ui.py` (24/24, `AppTest`, through the real "Run Mapping" button) — a
corrupted PDF alongside a valid one (valid one processes, corrupt one gets a named warning,
search index has only the valid page, **and the app stays interactive for a further click
afterward**); a password-protected PDF alongside a valid one; a zero-page PDF producing no
warning at all; an empty-upload click; an empty-config click (plus the Results section's own
independent empty-config message); and a simulated Groq drop/missing key through both real
UI-triggered Groq call sites that exist today (config-time synonym expansion, checklist 4.2's
manual re-search) — the app remains fully interactive afterward, confirmed by a further
successful interaction. Full regression suite (all 15 test files) passes clean; also confirmed
against the real production DB.*

### [x] 5.2 — Streamlit Community Cloud deployment config
✅ *Done 2026-09-23 — new `packages.txt` (repo root): `tesseract-ocr` (the OCR-fallback system
binary — `pytesseract` is only a wrapper, see §7's `pytesseract` row) plus `libgl1`,
`libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1` — headless graphics libs
`opencv-contrib-python` (pulled in transitively by `paddleocr`/`paddlepaddle`) needs just to
**import** on a minimal Debian container. `requirements.txt` needed no changes — nothing in it
is platform-pinned; pip already resolves Linux wheels for every listed version on a Linux box.
**Cross-platform Tesseract pathing:** `ocr/pipeline.py` gained `_resolve_tesseract_cmd()` —
priority order is an explicit `TESSERACT_CMD` env var (any platform), then
`shutil.which("tesseract")` (resolves `packages.txt`'s apt-installed `/usr/bin/tesseract` on
Community Cloud), only then the Windows UB-Mannheim default as a last resort. This was the only
hardcoded OS-specific path anywhere in the source tree (confirmed by grepping the whole
codebase for `C:\`) — `db/connection.py`'s `DEFAULT_DB_PATH` was already `pathlib.Path`-based
and needed no change.
**Secrets:** `config/synonyms.py` and `verify/groq_verifier.py` stay Streamlit-free (§2) and
keep reading `GROQ_API_KEY` via plain `os.environ.get(...)`, unchanged — rather than importing
`streamlit` into either (which would break that deliberate layering and their standalone
unit-testability), new `run/secrets_bootstrap.py::bootstrap_groq_api_key()` bridges
`st.secrets["GROQ_API_KEY"]` into `os.environ` once at `app.py` startup, **only** when
`GROQ_API_KEY` isn't already set — local dev (`.env` via `python-dotenv`) never even touches
`st.secrets`. New `.streamlit/secrets.toml.example` documents the format; confirmed via
`git check-ignore -v` that `.gitignore`'s existing `.streamlit/secrets.toml` rule matches only
the real file, not the `.example` variant (no `.gitignore` change was needed — it already had
this rule from checklist 0.6).
**PaddleOCR resource ceiling — reporting back, per this item's own instruction:** this checklist
item does not deploy the app for real, so Community Cloud's actual resource ceiling against
PaddleOCR's footprint remains **unverified**, not solved — flagged as an explicit open risk in
both PROJECT_HARNESS.md §8 and README.md rather than silently assumed fine. If a real deployment
shows it doesn't fit, the options (paid tier vs. Tesseract-primary for cloud) both change the
stack and need a go-ahead first, not a unilateral fix.
**A second real risk found and documented, not previously called out**: Community Cloud's
container filesystem is ephemeral, so `db/tender_mapper.db` resets to freshly-seeded on every
redeploy/restart — any Config-tab edits away from the seeded schema are silently lost across a
restart. Not a regression against anything the spec promised (§2 only ever meant
single-session persistence), but a real operational gap worth surfacing before this goes in
front of real users.
**Verification — two suites, orchestrated by `tests/verify_deployment_config.py`, both
passing**: `verify_deployment_config_unit.py` (7/7, no Streamlit) — `TESSERACT_CMD` env var
wins outright; with it unset, a monkeypatched `shutil.which` simulating a genuine Linux hit is
used; with neither, falls back to the Windows default without raising; the secrets bridge
leaves an already-set `GROQ_API_KEY` untouched without ever consulting `st.secrets`, correctly
copies a value across when absent from the environment but present in a fake `st.secrets`, and
doesn't crash when a fake `st.secrets.get` raises (simulating no `secrets.toml` at all).
`verify_deployment_config_ui.py` (3/3, `AppTest`) — confirms against the dev machine's real,
genuinely-absent `.streamlit/secrets.toml` (no mock) that the real `st.secrets` object doesn't
crash app startup, and that the app stays fully interactive afterward. **Full regression suite
(18 top-level test files, the widest run yet in this project) passes clean; also confirmed
against the real production DB** via a direct `AppTest` boot with `st.cache_resource.clear()`
first.*

### [x] 5.3 — Run tab UI lifecycle, reviewer control decluttering & cloud OCR performance
User-directed post-completion refinement (not part of the original numbered checklist; folded
into Phase 5), delivered across two requests in the same session. On a fresh boot or right after
"Next Company", the Results section rendered every row as ⚠️ Flagged (0.00) and stacked one
"Search again" expander per flagged column down the whole screen before the reviewer had
uploaded anything to search against; separately, checklist 5.2's flagged-not-solved PaddleOCR
resource-ceiling risk needed a first real mitigation, not just documentation.
✅ *Done 2026-09-23 — **Run-completion gate**: new `run/results.py::HAS_RUN_KEY`
(`st.session_state["mapping_has_run"]`) + `is_mapping_complete()`. `app.py`'s Results section
now only calls `render_results_section`/`render_export_section` when `is_mapping_complete()` is
true; otherwise it shows one placeholder callout ("Upload tender documents above and click
'▶️ Run Mapping' to populate compliance results.") in their place. `run/run_button.py` sets the
flag only once `resolve_all_columns()` has actually produced a results dict — never on the
early "nothing to run" returns (empty upload, empty config, zero documents processed), so those
states correctly keep showing the placeholder too. `run/results.py::reset_run_state()`
(checklist 4.3) clears the flag back to `False`, so "Next Company" returns to the same pre-run
placeholder rather than a stale-looking empty grid.
**Consolidated manual re-search**: `run/results.py::_render_manual_research` now takes
`all_columns` across every table (not one call per table) and renders exactly ONE
`st.expander("⚠️ Manual Re-Search: Review Flagged Items (N flagged)")` — only when at least one
column is flagged — containing a single `st.selectbox` listing every flagged column (options
prefixed `❗`, e.g. `❗ Item 4: WHO GMP/GMA Certificate (Confidence: 0.00)`, via new
`_short_requirement_label()`: the part of `requirement_text` before its em dash when present,
else a truncated prefix) and one custom-terms box + "Search again" button scoped to whichever
column is currently selected (`custom_terms_{id}`/`research_{id}`, same keys as before, so
switching the dropdown starts from a blank box rather than carrying over unrelated text).
**Verification**: reworked five existing `AppTest` suites for the new gate/consolidation —
`verify_results_ui.py`, `verify_manual_research_ui.py`, `verify_error_handling_ui.py`,
`verify_excel_export_ui.py`, `verify_next_company_reset.py`. Suites that intentionally bypass
the real OCR/Groq pipeline (injecting `resolution_results` directly, per their own established
style) now set `mapping_has_run = True` directly to simulate a completed run before exercising
the gated UI; suites that already drive the real "▶️ Run Mapping" button needed no change there.
`verify_next_company_reset.py` and `verify_results_ui.py` gained explicit assertions that the
grid, summary metrics, and re-search expander are ALL absent (and the placeholder IS present)
both on a fresh cold start and immediately after a "Next Company" click — directly covering this
item's own verification requirement. `verify_manual_research_ui.py` was the most substantially
reworked: dropdown-option assertions (`Selectbox.options`, the formatted display strings)
replace the old per-column-expander-presence assertions, and `Selectbox.select(column_id)` is
used to switch the target column before interacting with that column's now-conditionally-
rendered text box/button (two-step: select + rerun to regenerate the tree with the new column's
widgets, only then interact with them — a real `AppTest` mechanic, not simplifiable to one
`.run()`).
**Cloud OCR performance adjustments**: `ocr/pipeline.py::_get_paddle_ocr()`'s `enable_mkldnn`
is now `sys.platform == "linux"`-gated instead of unconditionally `False` — off on this Windows
dev box (required, per checklist 2.3's confirmed PP-OCRv6/oneDNN crash), on for Community
Cloud's CPU vectorization. **Directed, unverified against a real Linux box** — flagged in
PROJECT_HARNESS.md §8/§7, not silently assumed safe. New `choose_engine_order(needs_ocr_count)`
+ `HEAVY_LOAD_THRESHOLD = 15`: `resolve_pdf_text()` counts a PDF's `needs_ocr` pages (checklist
2.2) once, up front, and routes the WHOLE document through Tesseract-primary/PaddleOCR-fallback
above the threshold (lighter/faster engine for bulk scans, trading some accuracy to stay inside
Community Cloud's ~1GB ceiling) or PaddleOCR-primary/Tesseract-fallback at or under it (accuracy
is worth it at that volume) — a per-document decision, so it can't ping-pong mid-document.
`ocr_page()` gained `primary_engine`/`fallback_engine` params (default to the original
PaddleOCR-primary order, so no existing call site or test needed to change); its internal engine
dispatch changed from a dict of function references captured once at import time to a small
`_engine_func(name)` resolver that re-reads the module-level `_ocr_with_paddle`/
`_ocr_with_tesseract` names fresh on every call — a fixed dict would have silently broken this
project's established test pattern of monkeypatching those two names directly, since the dict
would keep pointing at the original functions regardless. **Verification**: four new tests in
`tests/verify_ocr_pipeline.py` — `choose_engine_order` unit-tested at/just-below/just-above/well-
above the threshold; a light-load PDF (3 pages needing OCR) routing end-to-end through
`resolve_pdf_text` via PaddleOCR-primary with zero Tesseract calls; a heavy-load PDF
(`HEAVY_LOAD_THRESHOLD + 1` pages) routing via Tesseract-primary with zero PaddleOCR calls; the
same heavy-load scenario with Tesseract itself mocked to fail, confirming every page still falls
back to PaddleOCR (proving the swap demotes it rather than dropping it) — suite now 44/44,
including the two pre-existing real-engine tests (real PaddleOCR success, real Tesseract
fallback) confirmed still passing on this Windows box with the new platform-gated `enable_mkldnn`
logic in place. **Full regression suite (18 top-level test files) passes clean; also confirmed
against the real production DB.***

### [x] 5.4 — Groq API rate-limit fix, granular ingest progress & real-time streaming
User-directed, post-deployment refinement (not part of the original numbered checklist; folded
into Phase 5). Live on Community Cloud, the app made hundreds of Groq calls per run (one per
BM25 candidate) and blocked the UI until the entire resolution loop finished — slow, and it
burned through the free tier's rate limits.
✅ *Done 2026-09-23 — **Batched Groq verification**: `verify/groq_verifier.py` rewritten from the
ground up. `verify_candidates_batch()` puts every candidate's text into ONE prompt
(`[Candidate 1]`, `[Candidate 2]`, ...) and asks the model for a single JSON payload:
`{best_candidate (1-N, or 0 for "none match"), confidence, match_snippet, reasoning}`.
`best_candidate` is only ever used to index back into the real candidate list already held with
certainty — the model can steer WHICH known candidate wins and how confident the result is, but
can never fabricate a pdf_name/page identity, generalizing checklist 3.2's original "never trust
the model's echo" principle from an implicit single candidate to an explicit numbered set. This
guarantees exactly ONE Groq API call per column regardless of candidate count. Old
`verify_candidate`/`verify_candidates` (per-candidate, thread-pool-within-a-column) removed
entirely; `resolve_column()` kept its exact public signature so `run/pipeline_runner.py` and
`run/results.py`'s manual re-search needed no call-site changes beyond the internals.
**Real bug found and fixed via the live test** (not caught by mocks, since mocks don't have real
model judgment to get wrong): on a single-candidate pool that genuinely does NOT satisfy the
requirement, the model's own `reasoning` correctly said "does not satisfy the requirement" — but
it returned `confidence: 0.96` anyway, conflating "how sure am I about my own judgment" with "how
strongly does the evidence show a match." Fixed by rewording the JSON schema's confidence
description to state explicitly that confidence reflects match STRENGTH, not judgment certainty,
and that `best_candidate=0` must pair with low (0.0-0.4) confidence. Re-ran the identical live
scenario after the fix: confidence dropped from 0.96 to 0.1, correctly. This is exactly the kind
of thing a live call against the real model catches that a hand-written mock JSON response never
would.
**Candidate cap + concurrency**: `run/pipeline_runner.py::resolve_all_columns` now caps BM25
retrieval to `TOP_K_CANDIDATES = 5` per column (down from the wide 15-20 pool) before candidates
ever reach Groq. BM25 search itself (which reads the shared sqlite3 `conn` via
`crud.get_synonyms`) runs sequentially, up front, for every column on the calling thread — a
single `sqlite3.Connection` is not safe for concurrent multi-thread queries even with
`check_same_thread=False` (see `db/connection.py`), a risk identified and designed around
*before* writing any concurrent code, not discovered after. Only the Groq calls themselves - the
slow, rate-limited step, and the only step that no longer touches `conn` once candidates are in
hand - run through a small bounded `ThreadPoolExecutor` **across columns**
(`COLUMN_MAX_WORKERS = 3`, a `COLUMN_SUBMIT_DELAY_SECONDS = 1.0` stagger between each submission).
Both constants are resolved fresh from the module on every call rather than baked into literal
parameter defaults, specifically so tests can monkeypatch them to run fast — the same pattern
`ocr/pipeline.py::_engine_func()` already established for the same reason (checklist 5.3).
Results are collected via `as_completed()`, so `progress_callback` (now carrying `column_id` and
the `VerificationResult` itself, not just `done/total/name`) fires in **completion order**, not
configured order — this is what makes the live streaming UI below genuinely live.
**Granular ingest progress**: `run_ocr_and_build_index` gained a `document_progress_callback`
(fires once per document, before its pages start processing, as `(doc_index, doc_total,
pdf_name)`) - separate from the existing per-page callback, which only ever tracked progress
within whichever document is currently running. `run/run_button.py` renders both into the UI: a
document counter line ("Processing document X of Y (filename.pdf) — Extracting text...") via
`st.empty()`, above the existing per-page progress bar.
**Real-time streaming**: new `run/results.py::build_live_preview_dataframe()` — every configured
column across every table, combined into one read-only table with a "Table" column, showing a
blank/pending row for anything not yet resolved (rows fill in, they don't appear/disappear).
`run/run_button.py` renders it into an `st.empty()` placeholder inside the `progress_callback`,
so it re-renders every time a column's single Groq call completes — a reviewer watches rows
populate live instead of the whole grid appearing only once everything is done. Both the live
table and the document/page progress placeholders are emptied once the run finishes; the script
then falls straight through to `render_results_section()`'s real, editable `st.data_editor` later
in the same script pass — the "swap to interactive" is just the next step of one script run, not
a separate rerun, so there's no widget-focus-resetting extra interaction in between.
**OCR fast-path (confirmed, no code change needed)**: audited `ocr/text_check.py` and
`ocr/pipeline.py::resolve_pdf_text` — `has_usable_text` pages already resolve as `engine="native"`
unconditionally, with neither PaddleOCR nor Tesseract ever invoked, regardless of whether the
page also carries an embedded image. This was already strictly enforced since checklist 2.2/2.3;
re-confirmed via `verify_ocr_pipeline.py`'s existing "OCR engines never invoked" assertions
rather than assumed.
**Verification**: `verify_groq_verifier_unit.py` rewritten around the batched API (28/28) -
including an explicit "evaluating 5 candidates costs exactly ONE Groq call" assertion, an
out-of-range/hallucinated-index-can't-escape-the-real-candidate-list test, and the full
resilience-contract suite (missing key, network drop, malformed JSON, 429-retry-with-backoff)
re-proven against the new single-call shape. `verify_groq_verifier_live.py` rewritten to send a
genuine WHO-GMP match and a passing-mention false positive in the SAME batched call (this is the
test that caught the confidence-semantics bug above). `verify_column_resolution_ui.py` (through
the real "Run Mapping" button, real OCR, real submission stagger) gained the literal
**"a 23-column run makes EXACTLY 23 Groq API calls" terminal-log assertion** this checklist item
asked for, plus assertions that no live-preview-table or document-counter content leaks into the
final rendered tree after the run completes. `verify_column_resolution_unit.py`,
`verify_manual_research_ui.py`, `verify_error_handling_unit.py`/`_ui.py` updated for the new
response schema and the `progress_callback` signature change; `verify_error_handling_unit.py`
gained a direct unit test for `document_progress_callback`'s call order/count/content across a
5-document batch including documents that go on to fail. AppTest cannot observe a script's
mid-execution incremental renders (only the tree after the whole script finishes), so the "rows
visibly populate live" claim itself rests on: (a) the same `st.empty()` + repeated-call pattern
this codebase already used successfully for `ocr_progress`/`resolve_progress`, (b) the
`progress_callback` firing in genuine completion order with correctly-accumulating partial state
(unit-tested), and (c) confirmation that the placeholders are cleanly torn down with nothing
leaked into the final state (AppTest-tested) - not a direct browser observation of the live
update itself, which this environment has no tool to drive. **Full regression suite (18
top-level test files) passes clean; also confirmed against the real production DB.** The two
live-only Groq suites (`verify_groq_verifier_live.py`, `verify_column_resolution_live.py`) were
intermittently rate-limited by this session's own heavy live-testing volume at various points
while this work was done, confirmed via isolated diagnostic calls to be genuine transient
account-level 429s, not a code defect - the resilience contract degraded gracefully every single
time (retried, then flagged for human review) and never crashed.*
