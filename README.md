# AIIMS Tender Compliance Mapper

A Streamlit app that maps a company's uploaded PDF documents to a configurable
compliance schema, finding which PDF + page number(s) satisfy each schema
row's requirement.

Purely retrieval: for each schema row it returns `{pdf_name,
page_number_or_range, confidence, match_snippet}`. It does not judge tender
eligibility and does not gate anything — a human reviews every result.

See **[PROJECT_HARNESS.md](PROJECT_HARNESS.md)** for the full scope,
architecture, tech stack, pipeline, and data model. See
**[CHECKLIST.md](CHECKLIST.md)** for build progress.

## Setup

```bash
conda activate tender-mapper
pip install -r requirements.txt
cp .env.example .env   # then fill in GROQ_API_KEY
```

Tesseract (the OCR fallback) is a system binary, not a pip package — install
it separately. On Windows, the UB-Mannheim build installs to
`C:\Program Files\Tesseract-OCR\tesseract.exe` by default.

## Run

```bash
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app pointing at this
   repo/branch, main file `app.py`. `requirements.txt` and `packages.txt` (system packages —
   `tesseract-ocr` plus the headless graphics libs `opencv`/PaddleOCR need on a minimal Debian
   container) are both picked up automatically, no extra config needed.
3. In the app's **Settings → Secrets** panel, add `GROQ_API_KEY = "your-real-key"` — see
   `.streamlit/secrets.toml.example` for the exact format. (Local dev keeps using `.env`
   instead; Community Cloud has no `.env` file, so this is the one piece of config that's
   genuinely platform-specific.)
4. Deploy. The first OCR call on the live app will be slow — PaddleOCR downloads its model
   weights on first use, not at install time.

**Known open risks** (see PROJECT_HARNESS.md §8 for the full writeup):
- **PaddleOCR's memory footprint against Community Cloud's free-tier resource ceiling is
  unverified** — this hasn't been deployed for real yet to confirm it fits. If it doesn't,
  either a paid tier or making Tesseract primary for cloud deployments are the options — either
  is a real stack change, not a default to reach for.
- **The config DB is not persistent storage on Community Cloud** — its container filesystem is
  ephemeral, so `db/tender_mapper.db` resets to freshly-seeded on every redeploy/restart,
  discarding any Config-tab edits away from the seeded schema.

## Project layout

| Directory | Responsibility |
|---|---|
| `config/` | Config tab: schema CRUD, config-time synonym expansion (Groq) |
| `ingest/` | Normalizes uploaded zip/folder/PDFs into a session document list |
| `ocr/` | Text-layer pre-check, PaddleOCR/Tesseract OCR, section/clause extraction |
| `search/` | BM25 + synonym + rapidfuzz candidate retrieval |
| `verify/` | Groq verification/rerank of candidates into structured results |
| `export/` | Excel export (openpyxl) matching the configured schema |
| `db/` | SQLite connection + schema/column/synonym models |
| `seed/` | Verbatim first-run seed schema (Table 1 + Table 2) |

## Non-goals

No eligibility judgment, no gating between tables, no document generation, no
RAG, no semantic/embedding search. See PROJECT_HARNESS.md §6 for the full list.
