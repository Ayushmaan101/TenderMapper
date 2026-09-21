"""Verify package.

Groq (Llama 3.3 70B) retrieve-then-rerank + verification + extraction step:
reads each BM25 candidate page's text against a schema row's requirement
text and returns structured JSON {pdf_name, page_number_or_range,
confidence, match_snippet}. See PROJECT_HARNESS.md §3 step 7 and
CHECKLIST.md item 3.2.
"""
