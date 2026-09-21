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
| Synonym expansion | **Groq (`openai/gpt-oss-120b`), one-time at config-time** | See §4. Model substituted from the originally-planned Llama 3.3 70B — see §8 Change Log, 2026-09-21. |
| Verification / rerank | **Groq (Llama 3.3 70B — ⚠️ unconfirmed, see note)** | Structured JSON output. See §3 step 7. **Not yet built (checklist 3.2).** The synonym-expansion work below found that `llama-3.3-70b-versatile` does not exist at all on this Groq account's live `/models` list — no Llama chat model does. The same substitution decision will very likely be needed here too; re-check `/models` and ask before building 3.2. |
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

**3. OCR.** Pages that failed the pre-check get OCR'd. PaddleOCR is primary. Tesseract is
the fallback.

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

**9. Manual override.** Flagged rows get a **"search again with custom terms"** box in the
UI, so a human reviewer can type the exact term they can see in the document and re-run
BM25 — **without touching the Config panel**. This is a run-tab affordance, not a config
edit.

**10. Results + export.** Editable table per configured table (`st.data_editor`), exported
to Excel via `openpyxl` matching the configured schema.

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
4. **Render.** Once all columns across all tables are resolved, render the results as an
   **editable table per configured table** (`st.data_editor`). Layout must hold up regardless of
   how many tables/columns/rows are configured.
5. **Next Company button** (below the results). Clicking it must:
   - Clear the company name field
   - Clear all uploaded PDFs/zip/folder for that session
   - Clear the resolved results table from the UI
   - **Leave the table/column config completely untouched** — it only changes via the Config tab
   - Return the user to a fresh upload state, ready for the next company, using the same
     persisted config
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
| **`paddleocr`** | Version-coupled to `paddlepaddle` (3.x ↔ 3.x). Downloads detection/recognition model weights **on first use**, not at install — so the first OCR call needs network access and takes a while. Pulls a wide dependency tail. | Pin both. Warm the models once during setup rather than during a user's first run. |
| **`pytesseract`** | It is only a **wrapper**. The actual Tesseract binary is **not** a pip package and is **not currently installed on this machine** (`tesseract` is not on PATH). The fallback OCR path will fail until it's installed separately. | Install the Tesseract Windows binary (UB-Mannheim build) and either add it to PATH or set `pytesseract.pytesseract.tesseract_cmd`. Needed before the OCR-fallback checklist item can be verified. |
| **`pymupdf`** | Low risk — ships prebuilt wheels. Note the import name is `fitz`, the distribution name is `pymupdf`. | — |
| **`streamlit`** | Low risk. `st.data_editor` is required and is well past its introduction version. | — |
| **`rank_bm25`** | Pure Python, unmaintained-but-stable at 0.2.2. No wheels issue. It has **no built-in tokenizer** — tokenization is ours to own. | — |
| **`groq`** | Low risk. Needs `GROQ_API_KEY` via `.env` / `python-dotenv`. | Key not yet provided. |
| **`rapidfuzz` / `openpyxl` / `python-dotenv`** | Low risk — prebuilt wheels, no native build step. | — |

**Deployment note:** Streamlit Community Cloud runs Linux, not Windows. PaddleOCR's size and
Tesseract's system-binary requirement both matter there — Community Cloud has a resource
ceiling, and Tesseract needs a `packages.txt` `apt` entry rather than a pip entry. This is
called out as a real risk against the deployment checklist item, not a solved problem.

---

## 8. Change Log

| Date | Change | Approved by user? |
|---|---|---|
| 2026-09-21 | Initial harness created from user's finalized spec. Conda env `tender-mapper` (Python 3.11.16) created and verified activatable. | Yes — original spec |
| 2026-09-21 | All pinned dependencies installed into `tender-mapper` (checklist 0.5). PaddleOCR model weights pre-downloaded/cached (`~/.paddlex/official_models`) so first OCR run in-app won't cold-start. Tesseract 5.4.0 binary confirmed at `C:\Program Files\Tesseract-OCR\tesseract.exe` — user installed it themselves; app code must set `pytesseract.pytesseract.tesseract_cmd` to this path explicitly rather than relying on PATH. `GROQ_API_KEY` present in `.env`. Note for future code: PyMuPDF emits a deprecation warning on `import fitz`, prefers `import pymupdf` — harmless today, but new code should use `import pymupdf as fitz` or `import pymupdf` directly. Note: `paddlepaddle`'s own resolution pulled `numpy` 2.4.6, then installing the rest (`paddlex` pin) downgraded it to 2.3.5 — still satisfies paddlepaddle's `numpy>=1.21`; no action needed, just recorded so a future "why did numpy change" isn't a mystery. | Yes — checklist 0.5 |
| 2026-09-21 | Checklist 1.3: added `app_meta` key-value table + `has_been_seeded` flag (fixing the seeding-gate gap noted in 1.2's change), built the Config tab UI, wired `seed_if_empty()` into app startup via a `st.cache_resource`-cached DB connection in `app.py`. `db/connection.py` now opens with `check_same_thread=False` (required for that cached cross-thread connection). Established `streamlit.testing.v1.AppTest` (ships with the already-pinned `streamlit` package — no new dependency) as this project's pattern for testing Streamlit UI behavior headlessly, in place of browser automation. | Yes — user-requested seeding fix + checklist 1.3 |
| 2026-09-21 | Checklist 1.4: **model substitution, approved by user** — `llama-3.3-70b-versatile` (the harness's originally-specified model) does not exist at all on this Groq account's live `/models` list (confirmed via direct API query; not renamed, absent — no Llama chat model is present). Switched to `openai/gpt-oss-120b` for synonym expansion. Flagged the same risk against the not-yet-built verification/rerank step (checklist 3.2), which was also specified as Llama 3.3 70B — see §2 table. Built `config/synonyms.py` (Groq call + JSON parsing tolerant of markdown code fences + `merge_new_synonyms`, additive-only, never overwrites existing synonyms) and wired it into `config/ui.py` at exactly three trigger points (column create, column edit *only if requirement_text changed*, manual "Generate Synonyms" button) — never on mere navigation. A live-call regression run surfaced a real bug (not flakiness): `max_tokens=600` was too small for `openai/gpt-oss-120b`'s JSON-mode output on this prompt, occasionally truncating before valid JSON completed (HTTP 400 `json_validate_failed`, `"max completion tokens reached before generating a valid document"`). Fixed by raising `max_tokens` to 1536; kept a 3-attempt retry as defense-in-depth for genuine transients (rate limits, connection errors) on top of that fix. | Yes — checklist 1.4 |
