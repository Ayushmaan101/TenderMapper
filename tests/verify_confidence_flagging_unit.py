"""Checklist 4.2 verification — unit-level (no Streamlit).

Pure logic test for is_flagged()/CONFIDENCE_THRESHOLD: unresolved rows
(success=False, the blank placeholder every column starts as),
low-confidence rows, and the exact threshold boundary.

Run: python tests/verify_confidence_flagging_unit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run.results import CONFIDENCE_THRESHOLD, _BLANK_RESULT, is_flagged  # noqa: E402
from verify.groq_verifier import VerificationResult  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def result(confidence: float, success: bool = True) -> VerificationResult:
    return VerificationResult(
        pdf_name="a.pdf", page_number_or_range="1", confidence=confidence,
        match_snippet="x", reasoning="x", success=success,
    )


def main() -> None:
    check(f"CONFIDENCE_THRESHOLD is 0.70 as specified", CONFIDENCE_THRESHOLD == 0.70)

    check("the blank/never-resolved placeholder is flagged", is_flagged(_BLANK_RESULT))
    check("success=False (a failed verification call) is flagged regardless of confidence", is_flagged(result(0.99, success=False)))

    check("confidence 0.0, success=True -> flagged", is_flagged(result(0.0)))
    check("confidence 0.3 (well below threshold) -> flagged", is_flagged(result(0.3)))
    check("confidence 0.69 (just below threshold) -> flagged", is_flagged(result(0.69)))
    check("confidence exactly 0.70 (the threshold itself) -> NOT flagged", not is_flagged(result(0.70)))
    check("confidence 0.71 (just above threshold) -> NOT flagged", not is_flagged(result(0.71)))
    check("confidence 0.95 (high confidence) -> NOT flagged", not is_flagged(result(0.95)))
    check("confidence 1.0 (maximum) -> NOT flagged", not is_flagged(result(1.0)))

    if all(ok for _, ok in checks):
        print(f"ALL CHECKS PASSED ({len(checks)}/{len(checks)})")
        sys.exit(0)
    else:
        failed = [label for label, ok in checks if not ok]
        print(f"FAILED {len(failed)}/{len(checks)}:")
        for label in failed:
            print(f"  - {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
