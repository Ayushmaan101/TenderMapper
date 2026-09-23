# PROJECT HARNESS — AIIMS Tender Compliance Mapper

> **This file is the single source of truth for scope, architecture, and tech stack.**
>
> Rules of engagement:
> - Re-read this file before starting **any** new checklist step.
> - Update it whenever the user approves a change to plan or stack.
> - Never silently deviate from it. Propose changes, get a go-ahead, then edit here first.

---

## 1. Overview

### What this is
A Streamlit app that maps a company's uploaded PDF documents to a configurable table
schema, by finding **which PDF and which page number(s)** satisfy each schema row's
requirement.

### Why it exists
Tenders (e.g. AIIMS pharma tenders) require companies to submit scanned document folders
as proof of compliance against a schema of requirements — "WHO-GMP certificate",
"narcotic license", "GST registration", and so on. Those submissions are scanned PDFs.
A human currently has to page through them to locate the proof for each requirement row.
This app does that locating.

### What the system's job actually is
**Purely retrieval.** For a given schema row's requirement text, return:

```json
{
  "pdf_name": "string",
  "page_number_or_range": "string",
  "confidence": 0.0,
  "match_snippet": "string"
}
```

### What the system's job is NOT
It does not judge tender eligibility. It does not gate anything. It does not generate
documents. It does not decide pass/fail. It finds pages. A human reviews the result.

See §6 (Explicit Non-Goals) for the full list.

---

## 2. Tech Stack — FINALIZED

**Do not substitute anything in this section without asking the user first.**

| Layer | Choice | Notes |
|---|---|---|
| App framework | **Streamlit** | Chosen over Vercel — this is a synchronous, compute-heavy pipeline that would blow serverless timeout limits |
| PDF handling | **PyMuPDF (`fitz`)** | Page iteration, text extraction, page rasterization for OCR |
| Text-layer pre-check | **PyMuPDF `get_text()` per page** | If a page already has a usable text layer, skip OCR for that page. Only OCR pages that don't. |
| OCR (primary) | **PaddleOCR** | Free, open-source, no API cost |
| OCR (fallback) | **Tesseract** (via `pytesseract`) | Free, open-source, no API cost. Used when PaddleOCR fails/unavailable. |
| Search / retrieval | **BM25 (`rank_bm25`)** over extracted+OCR'd page text | |
| Fuzzy term matching | **`rapidfuzz`** | Handles term variants / OCR noise |
| Synonym expansion | **Groq (`openai/gpt-oss-120b`), one-time at config-time** | See §4. Model substituted from the originally-planned Llama 3.3 70B — see §9 Change Log, 2026-09-21. |
| Verification / rerank | **Groq (`openai/gpt-oss-120b`)** | Structured JSON output (`pdf_name, page_number_or_range, confidence, match_snippet, reasoning`). See §3 step 7. Model substituted from the originally-planned Llama 3.3 70B for the same reason as synonym expansion (§9, checklist 1.4) — kept consistent across both Groq call sites per explicit approval, checklist 3.2. |
| Config storage | **SQLite** | User-scoped, persists across runs and restarts |
| Results editing | **`st.data_editor`** | Reviewer can correct flagged/wrong cells |
| Export | **Excel via `openpyxl`** | Matches the configured schema |
| Secrets | **`python-dotenv`** | Groq API key |

### Retrieval approach — explicitly decided
BM25 + `rapidfuzz` + stored synonyms. **NOT** semantic/embedding search. **NOT** a vector
index. Explicitly rejected for now, in favor of keeping retrieval fully inspectable and
free of extra infrastructure.

> Revisit only if real usage data shows BM25 + synonyms is missing things.

**No embedding model anywhere in this stack unless the user explicitly approves adding
one later.**

### The actual safety net
The safety net is **not** the search method. It is **confidence flagging**: any row
without a clean high-confidence match renders as flagged/incomplete in the UI for human
review — never silently blank, never silently wrong.

---

## 3. Pipeline Steps

Run per **column** (per requirement), for every column in every configured table.

```
                 ┌─────────────────────────────────────┐
  uploaded PDFs  │ 1. Ingest (zip / folder / multi-PDF)│
                 └──────────────────┬──────────────────┘
                                    ▼
                 ┌─────────────────────────────────────┐
                 │ 2. Per page: text-layer pre-check   │
                 │    PyMuPDF get_text()               │
                 └───────┬─────────────────────┬───────┘
                 usable text            no/poor text
                         │                     ▼
                         │      ┌──────────────────────────────┐
                         │      │ 3. OCR page                  │
                         │      │    PaddleOCR → Tesseract f/b │
                         │      └──────────────┬───────────────┘
                         ▼                     ▼
                 ┌─────────────────────────────────────┐
                 │ 4. Page text store                  │
                 │ 5. Section/clause ref extraction    │
                 └──────────────────┬──────────────────┘
                                    ▼
                 ┌─────────────────────────────────────┐
                 │ 6. BM25 search: requirement terms   │
                 │    + stored synonyms (+ rapidfuzz)  │
                 │    → top 15–20 candidate pages      │
                 └──────────────────┬──────────────────┘
                                    ▼
                 ┌─────────────────────────────────────┐
                 │ 7. Groq verification / rerank       │
                 │    → {pdf, page(s), conf, snippet}  │
                 └──────────────────┬──────────────────┘
                                    ▼
                 ┌─────────────────────────────────────┐
                 │ 8. Confidence flagging → review UI  │
                 │ 9. Manual re-search (custom terms)  │
                 │ 10. Editable results → Excel export │
                 └─────────────────────────────────────┘
```

### Step detail

**1. Ingest.** Accept **all three** input modes: a zip, a folder, or multiple separate PDF
files. Session-scoped.

**2. Text-layer pre-check.** For each page, `page.get_text()` via PyMuPDF. If the page
already has a usable text layer, use it and **skip OCR for that page**. OCR is expensive;
only pay for it where it's needed. Some PDFs in a scanned folder do have a real text layer.

**Error handling (checklist 5.1):** a PDF PyMuPDF cannot open at all (corrupt bytes) or cannot
read without a password (`doc.needs_pass`) raises `ocr.text_check.PdfProcessingError` — one
exception type regardless of which underlying PyMuPDF failure mode occurred. A zero-page PDF
is explicitly *not* an error (opens fine, `page_count == 0`) and returns an empty result
instead. `run/pipeline_runner.py` (checklist 5.1, a real slice of step 3's future orchestration
below) catches `PdfProcessingError` **per document**, so one bad sibling never aborts a batch.

**3. OCR.** Pages that failed the pre-check get OCR'd. PaddleOCR is primary, Tesseract the
fallback, for a typical document — but which engine is primary is actually decided **per PDF**
by `ocr/pipeline.py::choose_engine_order()` (Run tab UI lifecycle refinement, 2026-09-23): for a
PDF with more than `HEAVY_LOAD_THRESHOLD` (15) pages needing OCR, Tesseract becomes primary and
PaddleOCR the fallback instead, to stay inside Streamlit Community Cloud's memory ceiling on
bulk scans — see §8's open-risks note for the full reasoning and its unverified-on-real-Linux
caveat.

**4. Page text store.** One text record per (pdf, page). This is what BM25 indexes.

**5. Section/clause reference extraction.** Separately index any "Section X, Clause Y"
style references found per page during OCR/extraction. This is a **lightweight secondary
lookup**, not the main path — it catches pages that reference a requirement by section
number only, with none of the requirement's vocabulary present.

**6. BM25 + synonym-aware search.** Query = the column's requirement text terms **plus its
stored synonyms** (see §4). `rapidfuzz` handles term variants and OCR noise. Returns a
**wide candidate pool: top 15–20 candidate pages per schema row** — deliberately wide,
not top-5, because verification happens downstream.

**7. Groq verification / rerank.** Groq (Llama 3.3 70B) reads each candidate page's text
alongside the schema row's requirement text and returns structured JSON:
`{pdf_name, page_number_or_range, confidence (0-1), match_snippet}`.

This functions as retrieve-then-rerank, but it does **verification and extraction** too,
not just scoring.

**8. Confidence flagging.** Any row without a clean high-confidence match renders as
flagged/incomplete for human review. Never silently blank. Never silently wrong.

**Threshold (decided in checklist 4.2): `CONFIDENCE_THRESHOLD = 0.70`.** A row is flagged when
verification never succeeded (covers both "never resolved yet" and "the Groq call itself
failed") **or** its confidence is below 0.70 — not a plain confidence check, so a column that's
simply never been run flags identically to one Groq genuinely scored low, rather than looking
falsely clean by default.

**9. Manual override.** Flagged rows get a **"search again with custom terms"** box in the
UI, so a human reviewer can type the exact term they can see in the document and re-run
BM25 — **without touching the Config panel**. This is a run-tab affordance, not a config
edit.

The reviewer's custom terms drive BM25 **retrieval only** (no stored synonyms mixed in — this
is the reviewer overriding the search). Groq **verification** still judges the result against
the column's real, unmodified `requirement_text` — custom terms help find the candidate page,
they never redefine what "satisfies the requirement" means.

**Session-state contract for the search index (checklist 4.2, to be populated by checklist
3.3):** `st.session_state["corpus_index"]` (a `search.bm25_index.CorpusIndex`),
`st.session_state["page_texts"]` (`dict[(pdf_name, page_number), str]`), and
`st.session_state["reference_index"]` (an `ocr.references.ReferenceIndex`, optional). Checklist
3.3's per-column resolution loop is expected to build and store these once, at the start of a
company's run, for both the automatic resolution loop and manual re-search to share — not
rebuilt per column and not rebuilt per manual re-search click.

**10. Results + export.** Editable table per configured table (`st.data_editor`), exported
to Excel via `openpyxl` matching the configured schema.

**Export shape (decided in checklist 4.4):** one worksheet per `schema_table`, one row per
`schema_column` — same row orientation as the Run tab's own results grid (§5 step 4). Exported
columns: `Status, Requirement, PDF Name, Page Number / Range, Confidence, Match Snippet` —
deliberately not the short "Column" label the Run tab also shows; the full requirement text is
what a reader outside this app needs. `CONFIDENCE_THRESHOLD`/`is_flagged()` live in
`verify/groq_verifier.py` (alongside `VerificationResult`), not in `run/results.py`, so
`export/excel_export.py` can use the exact same flagging rule without depending on a UI-layer
package.

---

## 4. Data Model / Schema Config

### Storage
**SQLite.** User-scoped.

### Persistence rules — important
| Thing | Scope | Wiped on "Next Company"? | Wiped on app restart? |
|---|---|---|---|
| Schema config (tables, columns, requirement text, synonyms) | **User-scoped** | **No** | **No** |
| Company name | Session | **Yes** | Yes |
| Uploaded PDFs / zip / folder | Session | **Yes** | Yes |
| Resolved results table | Session | **Yes** | Yes |

Config **only** changes when the user explicitly edits it from the Config tab.

### What the config holds
- Number of tables
- Number of columns per table
- Column names / requirement text per column
- Stored synonym list per column (viewable and editable)

### Synonym expansion — one-time, at config-time
When a schema row is configured, **one** Groq call generates alternate phrasings and
abbreviations for its key terms. Those are stored **with the schema row in the config DB**.

This is **not** per-search-run. BM25 searches original terms + stored synonyms, read
straight from the DB.

### Config panel behavior
- A dedicated **"Config" tab/page**, separate from the main run tab.
- Lets the user define table count, column count per table, column names/requirement text,
  and view/edit the stored synonym list per column.
- Persisted in SQLite; does **not** reset between companies; does **not** reset on app
  restart.

### First-ever-run auto-seeding
On first-ever run, the config is **auto-seeded** with the two tables in `SEED_SCHEMA` (see
§4.1), exactly as given, so the app is usable immediately without the user having to manually
enter the schema first. The user can then edit/add/remove from this seeded baseline via the
Config tab at any time.

Seeding is gated by a persisted `has_been_seeded` flag in a small `app_meta` key-value table
(`db/meta.py`), not a live "is schema_table empty" check — the latter can't distinguish "never
seeded" from "the user deliberately deleted every table," and would silently re-seed the
defaults back in on the next app start after such a deletion. The flag is set once, right
after the one real seed, and nothing in this codebase ever unsets it.

Seeding happens **only** when the DB is empty — never on subsequent runs, never as a reset.

### 4.1 Seeded schema
The exact seed text lives in a dedicated seed module in code (single source in code, mirrored
here as a summary only). Line breaks and formatting **within each cell** must be preserved
exactly as the user supplied them.

**Table 1 — 10 columns**, single row of requirement text per column:

1. Item no. as per tender
2. Name of the items
3. Manufacturing & Market standing/experience certificate — min. "Three Years", certified by
   Centre/State Drug Controller, Performa Section-XVII, issued not more than one year before
   tender opening
4. WHO GMP/GMA Certificate — valid WHO-GMP / valid Schedule 'M' certificate, not more than
   five years old
5. Valid manufacturing license issued by Centre/State Drug Controller indicating product list
   (incl. PSU 3-year market standing clause)
6. Valid narcotic license issued by Central/State Excise Commissioner
7. At least one analysis batch report per molecule quoted (min. two reports, 2 different years
   of the last four FYs: 2021-22 … 2025-26)
8. Sole manufacturer → Proprietary drug certificate from competent authority in India
9. Newly introduced drugs/molecules — DCGI certificate, MMC relaxation, Form-45 for imported
   drugs/formulations
10. Production-Capacity assessment certificate — CA / State Drug Controller, batch-wise
    production detail, analysis batch reports across 2 of last 3 years, Performa Section-XIX
    (separate sheets per schedule)

**Table 2 — S.No + DOCUMENTS, 13 rows:**

1. "Tender Acceptance Form"
2. Checklist and list of item quoted
3. Section VIII Clause 11 — CA-audited annual turnover across three consecutive FYs, with
   per-category thresholds (narcotics/enemas ₹1.5 Cr; creams/ointments/IV fluids ₹30 Cr;
   tablets/capsules/injections ₹150 Cr; 25% open-market trading clause + CA certificate)
4. Section VIII Clause 10 — GST Registration Certificate + up-to-date-returns letter + last
   1 year's returns
5. Section VIII Clause 18 — Information as per Section-XVII format
6. Section VIII Clause 13 — Non-conviction certificate (Drugs and Cosmetics Act, 1940), incl.
   molecule-list undertaking fallback, issued within preceding one year
7. Performance certificate — 02 years of supply within last 05 FYs (2020-21 … 2025-26), from
   Govt. Hospital/PSU/reputed hospital/Institution/International buyer, on purchaser letterhead,
   issued within preceding one year
8. Section VIII Clause 16 — ₹10 non-judicial stamp paper self-attested certificate: no
   vigilance/CBI case, not blacklisted/debarred, + 3-year blacklisting disclosure
9. Section VIII Clause 17 — undertaking to supply during contract validity; 45-day supply-order
   liability
10. Documents confirming Sole Proprietorship / Partnership / Private Limited Firm in country
    of origin
11. Section VIII Clause 15 — guarantee against deterioration within stated potency period for
    biologicals and other limited-life products
12. Section VIII Clause 19 — Section-XVI (A) notarized ₹100 affidavit undertaking (Drugs and
    Cosmetics Rules, 1945, standard quality); (B) ₹100 affidavit 5-point declaration
13. OEM Authorization

> **Generalization requirement:** nothing downstream may hardcode "2 tables of 10 and 13 rows".
> The Config tab can change table count, column count, and row count at any time, and the whole
> pipeline and UI must follow whatever is configured.

---

## 5. Main Workflow (Run tab)

Distinct from the Config tab.

1. **Load config.** On landing in the run tab, load the **current persisted config** (seeded
   tables initially, or whatever the user has since edited via the Config tab). This config is
   **read-only in the run tab** — it can only be changed from the Config tab.
2. **Company input.** User enters a company name and uploads that company's documents. Accept
   **a zip, a folder, or multiple separate PDF files — all three input modes.**
3. **Resolve.** For **every column in every configured table** — not just the two named tables;
   this must generalize to however many tables/columns the user has configured — run the full
   pipeline (text-layer check → OCR if needed → BM25 + synonym search → Groq verification) to
   resolve `{pdf_name, page_number_or_range, confidence}` for that column, using the column's
   stored requirement text + synonyms.

   **Status:** a "▶️ Run Mapping" button (checklist 5.1, `run/run_button.py` +
   `run/pipeline_runner.py`) does the ingest → text-layer-check → OCR → search-index portion of
   this today, with per-document error isolation, and populates `corpus_index`/`page_texts`/
   `reference_index`. **Checklist 3.3 (complete):** the same button then runs the actual
   per-column loop — `run/pipeline_runner.py::resolve_all_columns` iterates every column in every
   configured table (across all tables, not just the two named ones), BM25-searches the indexed
   corpus with that column's requirement text + stored synonyms, passes the top 15–20 candidates
   to `verify/groq_verifier.py::resolve_column` (bounded workers, early-stopping at confidence ≥
   0.90), and writes the top verified result per column straight into
   `st.session_state["resolution_results"]` — fully replacing any prior run's results each time
   (no attempt to merge with earlier manual edits; see checklist 4.4's note on why
   `VerificationResult.success` can't distinguish a human edit from a stale auto-result). A second
   `st.progress` bar reports live status per column as it resolves. Columns with no BM25 candidates
   at all resolve to a `success=False` placeholder rather than skipping silently. Genuinely
   unmatched columns still land low/zero-confidence and get picked up by checklist 4.2's
   `is_flagged()` exactly as before — the difference is they're now populated automatically on
   every run instead of only via manual re-search or direct grid edits.
4. **Render.** Once all columns across all tables are resolved, render the results as an
   **editable table per configured table** (`st.data_editor`). Layout must hold up regardless of
   how many tables/columns/rows are configured.

   **Row orientation (decided in checklist 4.1):** each results grid has one ROW per configured
   schema_column, not per the source tender document's own visual layout — Table 1's 10 items
   read as ten columns-in-one-row in the real document; Table 2's 13 read as thirteen rows.
   Config storage is uniform (N `schema_column` rows per table, each one resolvable requirement)
   regardless of how that table looked in the original document, and mimicking either original
   layout in the UI would require per-table hardcoding. One grid row per schema_column is the
   only representation that stays correct for an arbitrary, freely reconfigured schema.

   **Run-completion gate (Run tab UI lifecycle refinement, 2026-09-23):** the results grid,
   summary metrics, manual re-search controls, and the Excel export button are all hidden until
   `st.session_state["mapping_has_run"]` is true — set by `run/run_button.py` only once
   `resolve_all_columns()` has actually produced a results dict, never on the early "nothing to
   run" returns (empty upload, empty config, zero documents processed). Before that, the Results
   section shows one placeholder callout ("Upload tender documents above and click "▶️ Run
   Mapping" to populate compliance results.") instead of a grid full of every row showing
   ⚠️ Flagged (0.00) — which is what a fresh boot or a post-"Next Company" screen looked like
   before this gate existed. `run/results.py::is_mapping_complete()` is the single predicate
   both `app.py` (Results/Export sections) and this gate's own tests check against.

   **Consolidated manual re-search:** rather than one top-level `st.expander` per flagged row
   (which used to flood the screen on a schema with many flagged items), every flagged column
   across every table now shares a single `⚠️ Manual Re-Search: Review Flagged Items (N flagged)`
   expander, containing one `st.selectbox` to pick the target column (options prefixed `❗`, with
   a short label plus its current confidence — e.g. `❗ Item 4: WHO GMP/GMA Certificate
   (Confidence: 0.00)`) and a single custom-terms box + "Search again" button for whichever
   column is currently selected.
5. **Next Company button** (below the results). Clicking it must:
   - Clear the company name field
   - Clear all uploaded PDFs/zip/folder for that session
   - Clear the resolved results table from the UI
   - **Leave the table/column config completely untouched** — it only changes via the Config tab
   - Return the user to a fresh upload state, ready for the next company, using the same
     persisted config

   **Implementation (checklist 4.3):** `run/session_reset.py`, via an `on_click` callback (not
   an inline `if st.button(...)`) — resetting the company-name text_input's displayed value
   requires mutating its widget-backing session-state key before that widget re-renders, which
   Streamlit only permits from within a callback. The file uploader has no direct "clear" API,
   so `ingest/ui.py` keys it dynamically (`company_file_uploader_{generation}`) and bumps the
   generation on reset, forcing a brand-new widget instance with no memory of prior selections.
   `reset_run_state()` also clears `mapping_has_run` back to `False`, so the Run tab lands back
   on the pre-run placeholder for the next company rather than a stale/empty-looking grid.
6. **The core loop.** This company-in → resolve → review → "Next Company" cycle **is** the core
   loop of the app. Session-state management is built around it **explicitly, as its own
   checklist item** — not bolted onto the results UI as an afterthought.

---

## 6. Explicit Non-Goals

Things this project deliberately does **not** do:

- ❌ **No eligibility judgment.** The system does not decide whether a company qualifies.
- ❌ **No gating.** No gating logic between tables. Table 2 does not depend on Table 1's outcome.
- ❌ **No document generation.** It locates existing pages; it does not write documents.
- ❌ **No RAG.**
- ❌ **No semantic / embedding search.** No vector index. No embedding model anywhere in this
  stack unless the user explicitly approves adding one later.
- ❌ **No serverless deployment** (Vercel etc.) — rejected on timeout grounds.
- ❌ **No paid OCR API.** PaddleOCR and Tesseract only.
- ❌ **No per-search-run synonym generation.** Synonym expansion is one-time, at config-time.
- ❌ **No silent failure.** A row without a clean high-confidence match is flagged, never left
  silently blank or silently wrong.
- ❌ **No config reset between companies.** "Next Company" never touches schema config.
- ❌ **No hardcoding of the seeded schema's shape** anywhere downstream.

---

## 7. Environment

- **Conda env:** `tender-mapper`, **Python 3.11.16**
- **Conda install:** `C:\Users\Abhinav\anaconda3`
- **Env prefix:** `C:\Users\Abhinav\anaconda3\envs\tender-mapper`
- **Platform:** Windows 11, win-64
- **Dev setup:** VS Code + Claude Code

### Activation
`conda` is **not** on PATH in PowerShell, and no PowerShell profile exists, so
`conda activate tender-mapper` will not work in a plain PowerShell terminal as-is.

Working options:

```powershell
# Option A — run conda through its full path (works today, no setup)
& "C:\Users\Abhinav\anaconda3\Scripts\conda.exe" ...

# Option B — call the env's python directly (works today, no setup)
& "C:\Users\Abhinav\anaconda3\envs\tender-mapper\python.exe" ...

# Option C — one-time init so `conda activate` works in PowerShell (writes a PS profile)
& "C:\Users\Abhinav\anaconda3\Scripts\conda.exe" init powershell
# then restart the terminal and: conda activate tender-mapper
```

```bat
:: Option D — cmd / Anaconda Prompt
call C:\Users\Abhinav\anaconda3\Scripts\activate.bat tender-mapper
```

Option C has not been run — it modifies the user's PowerShell profile, so it needs a
go-ahead first.

### Known install friction (Windows / Python 3.11)

> Versions below were resolved against PyPI on 2026-09-21 for this exact interpreter.
> Nothing in `requirements.txt` has been installed yet.

| Package | Friction | Mitigation |
|---|---|---|
| **`paddlepaddle`** | Heaviest dependency by far (multi-hundred-MB wheel). Windows CPU wheels are published on PyPI, but Paddle 3.x pulls a large native toolchain and is the most likely single point of install failure. Also frequently needs the **MSVC runtime** present. | Install it **first and alone**, verify with `python -c "import paddle; paddle.utils.run_check()"` before installing `paddleocr`. If PyPI resolution fails, fall back to Paddle's own index: `pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/` |
| **`paddleocr`** | Version-coupled to `paddlepaddle` (3.x ↔ 3.x). Downloads detection/recognition model weights **on first use**, not at install — so the first OCR call needs network access and takes a while. Pulls a wide dependency tail. **On this machine, `PaddleOCR(...).predict()` crashes on every call with oneDNN enabled** (`enable_mkldnn=True`, the default) — a Paddle-internal PIR/oneDNN incompatibility (`ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`) inside the PP-OCRv6 detection model, not a bug in this project's code. Confirmed during checklist 2.3. | Pin both. Warm the models once during setup rather than during a user's first run. `ocr/pipeline.py` constructs `PaddleOCR(..., enable_mkldnn=(sys.platform == "linux"))` — required off on this Windows environment; gated on for Linux/Community Cloud instead (Run tab UI lifecycle refinement, 2026-09-23) to take advantage of CPU vectorization there — **unverified against a real Linux box**, see §8's open-risks note. It also disables `use_doc_orientation_classify`/`use_doc_unwarping` by default (kept `use_textline_orientation=True` per spec): those two preprocessing models are meant for photographed/warped documents, not this project's actual input (office-scanned tender PDFs), and were observed to occasionally zero out detection entirely on a clean test page — see checklist 2.3 for the full reasoning. |
| **`pytesseract`** | It is only a **wrapper**. The actual Tesseract binary is **not** a pip package and is **not currently installed on this machine** (`tesseract` is not on PATH). The fallback OCR path will fail until it's installed separately. | Install the Tesseract Windows binary (UB-Mannheim build) and either add it to PATH or set `pytesseract.pytesseract.tesseract_cmd`. Needed before the OCR-fallback checklist item can be verified. |
| **`pymupdf`** | Low risk — ships prebuilt wheels. Note the import name is `fitz`, the distribution name is `pymupdf`. | — |
| **`streamlit`** | Low risk. `st.data_editor` is required and is well past its introduction version. | — |
| **`rank_bm25`** | Pure Python, unmaintained-but-stable at 0.2.2. No wheels issue. It has **no built-in tokenizer** — tokenization is ours to own. | — |
| **`groq`** | Low risk. Needs `GROQ_API_KEY` via `.env` / `python-dotenv`. | Key not yet provided. |
| **`rapidfuzz` / `openpyxl` / `python-dotenv`** | Low risk — prebuilt wheels, no native build step. | — |

---

## 8. Deployment (Streamlit Community Cloud) — checklist 5.2

Streamlit Community Cloud runs Linux (Debian), not Windows — this project's own dev
environment (§7). Everything below exists to make the same codebase run correctly on both
without a fork or a manual per-platform edit.

### Config files Community Cloud reads automatically

- **`packages.txt`** (repo root) — apt packages Community Cloud installs before `pip install
  -r requirements.txt`. Contains `tesseract-ocr` (the OCR-fallback system binary; `pytesseract`
  is only a Python wrapper around it — see §7's `pytesseract` row) and the headless graphics
  libs (`libgl1`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1`) that
  `opencv-contrib-python` (pulled in transitively by `paddleocr`/`paddlepaddle`) needs just to
  **import**, let alone run, on a minimal Debian container with no desktop libs preinstalled.
- **`.streamlit/secrets.toml.example`** — documents the one secret this app needs
  (`GROQ_API_KEY`) without committing a real value. `.streamlit/secrets.toml` itself (the real
  file, if a developer creates one locally to test the `st.secrets` path) stays in `.gitignore`
  (confirmed with `git check-ignore -v` — the exact-path rule matches the real file, not the
  `.example` variant).

### Cross-platform Tesseract pathing

`ocr/pipeline.py::_resolve_tesseract_cmd()` resolves the binary in priority order: (1) an
explicit `TESSERACT_CMD` env var, any platform; (2) `shutil.which("tesseract")`, which finds
the standard `/usr/bin/tesseract` that `packages.txt`'s apt install puts on `PATH` on Community
Cloud (or any Linux/Mac box with Tesseract on `PATH`); (3) only as a last resort, the Windows
UB-Mannheim default install path, since that's this project's own local dev machine. Verified
by `tests/verify_deployment_config_unit.py` under all three branches, with `shutil.which`
monkeypatched to simulate a Linux hit and a total miss — the test asserts on behavior, not on
which OS it happens to run under, so it passes identically here and on real Linux CI.

### Secrets

Community Cloud has no `.env` file — secrets are set through its dashboard's "Settings →
Secrets" panel (paste the same `KEY = "value"` TOML syntax as `.streamlit/secrets.toml.example`)
and surfaced to a running app only via `st.secrets`. `config/synonyms.py` and
`verify/groq_verifier.py` are deliberately Streamlit-free (§2) and both already read
`GROQ_API_KEY` via a plain `os.environ.get(...)`, populated locally by `python-dotenv`'s
`load_dotenv()` from `.env`. Rather than importing `streamlit` into either of those two
pipeline modules (which would break that deliberate layering and their standalone
unit-testability), `run/secrets_bootstrap.py::bootstrap_groq_api_key()` — a small,
Streamlit-importing bridge module, called once from `app.py` at startup — copies
`st.secrets["GROQ_API_KEY"]` into `os.environ` **only if `GROQ_API_KEY` isn't already set**, so
local dev (where it's already set via `.env`) is completely unaffected and never even consults
`st.secrets`. `st.secrets` raising when no `secrets.toml` exists at all (the normal local-dev
case) is caught and treated as "nothing to bridge", not an error — verified against the *real*
`st.secrets` object (no mock) by `tests/verify_deployment_config_ui.py`, since this dev machine
genuinely has no `.streamlit/secrets.toml` on disk.

### Deploying

1. Push this repo to GitHub (a public repo, or a private one Community Cloud has access to).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app pointing at this repo,
   branch `master`, main file `app.py`. Community Cloud reads `requirements.txt` and
   `packages.txt` from the repo root automatically — no extra configuration needed for either.
3. In the app's **Settings → Secrets** panel, paste `GROQ_API_KEY = "..."` (the same syntax as
   `.streamlit/secrets.toml.example`) with a real key.
4. Deploy. First boot will be slow — PaddleOCR downloads its detection/recognition model
   weights on first use (§7's `paddleocr` row), not at install time, so the very first OCR call
   on the live app pays that download cost once.

### Known open risks — flagged, not solved

- **PaddleOCR's resource ceiling on Community Cloud's free tier is still unverified against a
  real deployment**, though a partial, user-directed mitigation now exists (Run tab UI lifecycle
  refinement, 2026-09-23): `ocr/pipeline.py::choose_engine_order()` makes Tesseract — lighter,
  faster, no large model held in memory — the *primary* engine (PaddleOCR demoted to fallback)
  for any single PDF with more than `HEAVY_LOAD_THRESHOLD` (15) pages needing OCR, trading a
  little per-page accuracy on bulk scans for staying inside the resource budget across a heavy
  document; PaddleOCR stays primary for lighter documents where its accuracy is worth the cost.
  `enable_mkldnn` is also now `sys.platform == "linux"`-gated (on for Community Cloud's CPU
  vectorization, off on this Windows dev box where oneDNN crashes PP-OCRv6 outright) — **this
  Linux branch has not been exercised on a real Linux box in this environment**; if the same
  crash reproduces there too, it needs to flip back to unconditionally off, not be left as-is.
  Neither change has been verified against a real deployment's actual memory ceiling — if
  PaddleOCR still doesn't fit even with Tesseract now handling the bulk case, the remaining
  option is a paid Community Cloud tier, which is a real cost decision and needs a report-back
  before committing to it, not something to decide unilaterally.
- **The SQLite config DB is not persistent storage on Community Cloud.** Found while working
  this checklist item, not previously documented: Community Cloud's container filesystem is
  ephemeral — every redeploy or app restart gets a fresh filesystem, so `db/tender_mapper.db`
  (§7's `DEFAULT_DB_PATH`) resets to freshly-seeded on every restart, silently discarding any
  Config-tab edits a real user made away from the seeded schema. This project's spec never
  called for cross-restart persistence beyond "SQLite for config persistence" (§2) in the
  context of a single running session, so this isn't a regression against anything promised —
  but it's a real operational gap a deployed user would hit, worth surfacing before this goes
  in front of real users, not silently discovered later.

---

## 9. Change Log

| Date | Change | Approved by user? |
|---|---|---|
| 2026-09-21 | Initial harness created from user's finalized spec. Conda env `tender-mapper` (Python 3.11.16) created and verified activatable. | Yes — original spec |
| 2026-09-21 | All pinned dependencies installed into `tender-mapper` (checklist 0.5). PaddleOCR model weights pre-downloaded/cached (`~/.paddlex/official_models`) so first OCR run in-app won't cold-start. Tesseract 5.4.0 binary confirmed at `C:\Program Files\Tesseract-OCR\tesseract.exe` — user installed it themselves; app code must set `pytesseract.pytesseract.tesseract_cmd` to this path explicitly rather than relying on PATH. `GROQ_API_KEY` present in `.env`. Note for future code: PyMuPDF emits a deprecation warning on `import fitz`, prefers `import pymupdf` — harmless today, but new code should use `import pymupdf as fitz` or `import pymupdf` directly. Note: `paddlepaddle`'s own resolution pulled `numpy` 2.4.6, then installing the rest (`paddlex` pin) downgraded it to 2.3.5 — still satisfies paddlepaddle's `numpy>=1.21`; no action needed, just recorded so a future "why did numpy change" isn't a mystery. | Yes — checklist 0.5 |
| 2026-09-21 | Checklist 1.3: added `app_meta` key-value table + `has_been_seeded` flag (fixing the seeding-gate gap noted in 1.2's change), built the Config tab UI, wired `seed_if_empty()` into app startup via a `st.cache_resource`-cached DB connection in `app.py`. `db/connection.py` now opens with `check_same_thread=False` (required for that cached cross-thread connection). Established `streamlit.testing.v1.AppTest` (ships with the already-pinned `streamlit` package — no new dependency) as this project's pattern for testing Streamlit UI behavior headlessly, in place of browser automation. | Yes — user-requested seeding fix + checklist 1.3 |
| 2026-09-21 | Checklist 1.4: **model substitution, approved by user** — `llama-3.3-70b-versatile` (the harness's originally-specified model) does not exist at all on this Groq account's live `/models` list (confirmed via direct API query; not renamed, absent — no Llama chat model is present). Switched to `openai/gpt-oss-120b` for synonym expansion. Flagged the same risk against the not-yet-built verification/rerank step (checklist 3.2), which was also specified as Llama 3.3 70B — see §2 table. Built `config/synonyms.py` (Groq call + JSON parsing tolerant of markdown code fences + `merge_new_synonyms`, additive-only, never overwrites existing synonyms) and wired it into `config/ui.py` at exactly three trigger points (column create, column edit *only if requirement_text changed*, manual "Generate Synonyms" button) — never on mere navigation. A live-call regression run surfaced a real bug (not flakiness): `max_tokens=600` was too small for `openai/gpt-oss-120b`'s JSON-mode output on this prompt, occasionally truncating before valid JSON completed (HTTP 400 `json_validate_failed`, `"max completion tokens reached before generating a valid document"`). Fixed by raising `max_tokens` to 1536; kept a 3-attempt retry as defense-in-depth for genuine transients (rate limits, connection errors) on top of that fix. | Yes — checklist 1.4 |
| 2026-09-21 | Checklist 2.3: built `ocr/pipeline.py` (rasterize via PyMuPDF at 200 dpi, PaddleOCR primary, Tesseract fallback, per-page cache, progress callback). Found and fixed two real environment issues, both now documented in §7's `paddleocr` row: (1) `PaddleOCR.predict()` crashes on every call with oneDNN enabled on this machine — fixed with `enable_mkldnn=False`, required, not optional; (2) the `use_doc_orientation_classify`/`use_doc_unwarping` preprocessing steps (meant for photographed/warped documents) were observed to zero out detection entirely on a clean synthetic test page — disabled by default as a judgment call given this project's actual input is office-scanned PDFs, not phone photos; `use_textline_orientation=True` (the user's spec) kept on. `Pillow` and `numpy` added to `requirements.txt` as explicit direct dependencies (were already installed transitively via `paddlepaddle`; `ocr/pipeline.py` now imports both directly). | Yes — checklist 2.3 |
| 2026-09-23 | Checklist 3.2: confirmed `openai/gpt-oss-120b` (same substitution as checklist 1.4, kept consistent across both Groq call sites per explicit approval) for `verify/groq_verifier.py`'s verification/rerank step. §2 table updated to drop the "unconfirmed" flag left on this row after 1.4. Live-tested the actual discrimination the prompt exists for: a genuine WHO-GMP certificate scored 0.95 confidence, a page that only mentions WHO-GMP in passing (pointing to "Annexure B" without providing the certificate) scored 0.0 — both against real requirement text from the seed schema, not synthetic stand-ins. | Yes — checklist 3.2 |
| 2026-09-23 | Checklist 4.1: built at the user's explicit direction ahead of checklist 3.3 (the per-column resolution loop) — the results UI reads/edits `st.session_state["resolution_results"]`, which 3.3 will populate later; unresolved columns render as blank placeholders identically to a real result. New `run/` package (`run/results.py`), mirroring the `config/`/`ingest/` pattern. **Row-orientation decision** (§5 step 4 updated with the reasoning): one results-grid row per `schema_column`, not per the source document's own layout — the only representation that stays correct for an arbitrary, freely reconfigured schema without per-table hardcoding. Reuses checklist 3.2's `VerificationResult` directly as the results-store value type rather than inventing a parallel data model. | Yes — user-directed build order + checklist 4.1 |
| 2026-09-23 | Checklist 4.2: `CONFIDENCE_THRESHOLD = 0.70` (§3 step 8). Added the "Status" column (⚠️ Flagged / ✅ Resolved) to every results grid, changing its shape from `(N, 6)` to `(N, 7)` — checklist 4.1's own test suite needed updating for this, expected and done in the same commit. Defined the `corpus_index`/`page_texts`/`reference_index` session-state contract (§3 step 9) that checklist 3.3 is expected to populate; manual re-search reads it directly and shows a graceful placeholder message when absent, same posture as 4.1's own placeholder handling. `_run_manual_research` takes no `db.crud` import and no `sqlite3.Connection` at all, so it can't write to the config DB even by accident — verified with a full DB fingerprint, byte-identical before/after. | Yes — checklist 4.2 |
| 2026-09-23 | Checklist 4.3: new `run/session_reset.py` (§5 step 5 updated with the implementation approach). Completed the session-state contract started in 4.2 — `run/results.py` gains `OCR_CACHE_KEY` alongside `corpus_index`/`page_texts`/`reference_index`, plus `reset_run_state()` clearing all four. `ingest/ui.py`'s file uploader is now keyed dynamically (`company_file_uploader_{generation}`) so it can be genuinely cleared (Streamlit has no direct "clear" API for `st.file_uploader`) — a real regression this caused in checklist 2.1's own test (which hardcoded the old fixed key) was found and fixed in the same commit. | Yes — checklist 4.3 |
| 2026-09-23 | Checklist 4.4: new `export/excel_export.py` (§5 step 10 updated with the export shape) + `run/export_ui.py`. Moved `CONFIDENCE_THRESHOLD`/`is_flagged` from `run/results.py` into `verify/groq_verifier.py` (alongside `VerificationResult`) before writing the export module — the first draft needed them from `run/results.py`, an inverted dependency for a UI-layer package; `run/results.py` re-exports both, unchanged behavior for existing importers. **Real bug found and fixed** (via this checklist's own export test): the results grid's edit-writeback (checklist 4.1) never set `success=True` on a manually corrected cell, so raising a row's confidence by hand left it stuck showing "Flagged" — fixed by flipping `success` only when an edited value genuinely differs from what's stored, not on every incidental rerender. Confirmed no regression against 4.1/4.2's own suites. | Yes — checklist 4.4 |
| 2026-09-23 | Checklist 5.1: per user's explicit direction, builds both the underlying pipeline error guards and a real, tested slice of checklist 3.3's end-to-end flow to verify them against — new "▶️ Run Mapping" button (`run/run_button.py` + `run/pipeline_runner.py`), which is genuine forward progress on 3.3 (ingest → text-check → OCR → search-index build), not throwaway scaffolding; 3.3 still needs the per-column BM25-search + Groq-verify loop on top of it (§5 step 3 updated with current status). `ocr/text_check.py` gained `PdfProcessingError`, raised for corrupt PDF bytes (`fitz.open()` itself raises) and password-protected PDFs (`doc.needs_pass`), explicitly *not* raised for a zero-page PDF (opens fine, not an error) — confirmed all three behaviors empirically against real PyMuPDF before writing the guards, not assumed. **Process discovery worth flagging for future test-writing**: this checklist's UI test was the first in this project to create multiple `AppTest` instances within one Python process; that exposed that `app.py`'s `st.cache_resource`-cached DB connection is silently shared across every `AppTest` instance in the same process regardless of the `TENDER_MAPPER_DB_PATH` env var (correct production behavior, surprising in a multi-instance test) — fixed with `st.cache_resource.clear()` before each scenario, now documented in the test itself. | Yes — user-directed scope (3.3 slice) + checklist 5.1 |
| 2026-09-23 | Checklist 3.3: completed the per-column resolution loop on top of 5.1's partial build — new `run/pipeline_runner.py::resolve_all_columns(conn, corpus_index, page_texts, reference_index=None, progress_callback=None)` iterates every column in every configured table, BM25-searches (`search/bm25_index.py::search`) with the column's requirement text + stored synonyms, hands the top candidates to `verify/groq_verifier.py::resolve_column` (bounded workers, early-stop ≥ 0.90), and writes the winning `VerificationResult` per column id; columns with zero BM25 candidates get a documented `success=False` placeholder instead of being skipped. `run/run_button.py` gained a "phase 2" after 5.1's ingest/OCR phase, with its own `st.progress` bar reporting live per-column status, writing the final dict into `st.session_state["resolution_results"]` (full overwrite each run — see §5 step 3's note on why prior manual edits aren't preserved). Deliberately sequential across columns, not parallelized (keeps total concurrent Groq load bounded at exactly `max_workers` instead of `max_workers × column_count`). **Real bug found and fixed**: the first draft of the mocked-Groq test fixture checked its marker phrase against the whole prompt string, but a column's own requirement text can legitimately contain its marker (e.g. "WHO GMP certificate"), so every candidate for that column trivially matched regardless of actual page content — with 5 bounded workers and early-stopping, whichever candidate's thread finished first non-deterministically "won"; confirmed via 3 consecutive runs producing different failures each time. Fixed by scoping the marker check to only the prompt's "Page text:" section. Confirmed deterministic via 5 consecutive clean runs. Three new suites: `tests/verify_column_resolution_unit.py` (17/17, mocked Groq, direct-match/synonym-only/no-match/multi-table/empty-corpus coverage), `tests/verify_column_resolution_live.py` (7/7, real Groq calls against the real seeded Table 1 schema), `tests/verify_column_resolution_ui.py` (12/12, `AppTest` through the real "Run Mapping" button with real OCR on a synthetic scanned PDF — required bumping `at.run(timeout=120)` since PaddleOCR's real inference exceeds AppTest's 3s default). Full 16-suite regression + a production-DB (`db/tender_mapper.db`) sanity boot both confirmed clean. | Yes — checklist 3.3 |
| 2026-09-23 | Checklist 5.2: new `packages.txt` (`tesseract-ocr` + headless graphics libs for `opencv`/PaddleOCR on Debian). `ocr/pipeline.py` gained cross-platform `_resolve_tesseract_cmd()` (`TESSERACT_CMD` → `shutil.which` → Windows default) — the only hardcoded OS-specific path in the source tree. New `run/secrets_bootstrap.py::bootstrap_groq_api_key()` bridges Streamlit Community Cloud's `st.secrets` into `os.environ` at `app.py` startup, only when `GROQ_API_KEY` isn't already set, keeping `config/synonyms.py`/`verify/groq_verifier.py` Streamlit-free and unchanged. New `.streamlit/secrets.toml.example`; the real `.streamlit/secrets.toml` was already `.gitignore`'d. Added this §8/§9 Deployment section documenting the deploy steps and two flagged-not-solved risks (PaddleOCR's memory footprint against Community Cloud's free tier is unverified without a real deployment; the config DB isn't persistent storage there — ephemeral container filesystem). Two new suites (`verify_deployment_config_unit.py` 7/7, `verify_deployment_config_ui.py` 3/3). Full regression (18 top-level suites) and a production-DB sanity boot both passed clean. | Yes — checklist 5.2 |
| 2026-09-23 | Run tab UI lifecycle refinement (user-directed, post-checklist polish, not a numbered checklist item at request time — folded into Phase 5 as 5.3): a fresh boot or a post-"Next Company" screen used to render every row as ⚠️ Flagged (0.00) plus one "Search again" expander per flagged column, stacking dozens of expanders down the screen. New `run/results.py::HAS_RUN_KEY`/`is_mapping_complete()` gate the results grid, summary metrics, manual re-search controls, and the export button behind `st.session_state["mapping_has_run"]` — `app.py` shows one placeholder callout instead when it's false; `run/run_button.py` sets it true only once `resolve_all_columns()` actually produces results; `reset_run_state()` (checklist 4.3) clears it back to `False`. §5 step 4 updated with the gate's design. Manual re-search (checklist 4.2) consolidated from one `st.expander` per flagged row into a single `⚠️ Manual Re-Search: Review Flagged Items (N flagged)` expander with an `st.selectbox` (options prefixed `❗`, e.g. `❗ Item 4: WHO GMP/GMA Certificate (Confidence: 0.00)` — the short label is the part of `requirement_text` before its em dash when present, else a truncated prefix) driving which single column's search box/button render. Six existing UI suites needed rework for the new gate/consolidation (`verify_results_ui.py`, `verify_manual_research_ui.py`, `verify_error_handling_ui.py`, `verify_excel_export_ui.py`, `verify_next_company_reset.py`) — each now either simulates a completed run by setting `mapping_has_run` directly (suites that intentionally bypass the real OCR/Groq pipeline) or already went through the real "Run Mapping" button; `verify_next_company_reset.py` and `verify_results_ui.py` gained explicit cold-start/post-reset "everything is hidden" assertions. Full regression (18 top-level suites) and a production-DB sanity boot both passed clean. | Yes — user-directed |
| 2026-09-23 | Cloud OCR performance adjustments (user-directed, same session as the Run tab UI lifecycle refinement — folded into Phase 5 as part of 5.3): `ocr/pipeline.py::_get_paddle_ocr()`'s `enable_mkldnn` is now `sys.platform == "linux"`-gated (off on this Windows dev box, where it's required to avoid a real PP-OCRv6/oneDNN crash confirmed in checklist 2.3; on for Community Cloud's CPU vectorization) — **directed, unverified against a real Linux box**, flagged in §8's open-risks note and §7's `paddleocr` row. New `ocr/pipeline.py::choose_engine_order(needs_ocr_count)` + `HEAVY_LOAD_THRESHOLD = 15`: `resolve_pdf_text()` counts each PDF's `needs_ocr` pages (checklist 2.2) once, up front, and routes the whole document through Tesseract-primary/PaddleOCR-fallback above the threshold, PaddleOCR-primary/Tesseract-fallback at or under it — a per-document decision, not per-page. `ocr_page()`'s signature grew `primary_engine`/`fallback_engine` params (defaulting to the original PaddleOCR-primary order, so every existing direct call/test is unaffected); its internal engine lookup was changed from a fixed dict built at import time to a small `_engine_func(name)` resolver that re-reads the module-level `_ocr_with_paddle`/`_ocr_with_tesseract` names on every call, specifically so the established test pattern of monkeypatching those two names directly keeps working unchanged. §3 step 3 and §8's open-risks note updated with the routing design. Four new tests in `verify_ocr_pipeline.py` (`choose_engine_order` at/below/above the threshold; light-load and heavy-load PDFs routing end-to-end through `resolve_pdf_text`; heavy-load-with-failing-Tesseract still falling back to PaddleOCR, proving the swap demotes rather than drops it) — suite now 44/44. Full regression (18 top-level suites) and a production-DB sanity boot both passed clean. | Yes — user-directed |
