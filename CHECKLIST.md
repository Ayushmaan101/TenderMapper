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
rerank), also specced as Llama 3.3 70B. See PROJECT_HARNESS.md §2, §8.
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
**Two real environment issues found and fixed** (documented in PROJECT_HARNESS.md §7/§8, not
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
PROJECT_HARNESS.md §2/§8 updated to drop the "unconfirmed" flag left on this row after 1.4).
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
