"""OCR package.

Per-page text-layer pre-check (PyMuPDF get_text()) to skip OCR where a real
text layer already exists; OCR pipeline for the rest (PaddleOCR primary,
Tesseract fallback); section/clause reference extraction as a secondary
index. See PROJECT_HARNESS.md §3 steps 2-5 and CHECKLIST.md items 2.2-2.4.
"""
