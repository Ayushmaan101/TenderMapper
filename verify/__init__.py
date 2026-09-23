"""Verify package.

Groq (openai/gpt-oss-120b — see PROJECT_HARNESS.md §2/§8: llama-3.3-70b-versatile,
the originally-planned model, does not exist on this account; kept consistent
with the same substitution made for checklist 1.4) retrieve-then-rerank +
verification + extraction step: reads each BM25 candidate page's text against
a schema row's requirement text and returns structured JSON
{pdf_name, page_number_or_range, confidence, match_snippet, reasoning}.
See PROJECT_HARNESS.md §3 step 7 and CHECKLIST.md item 3.2.
"""
