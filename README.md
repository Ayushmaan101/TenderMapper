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
