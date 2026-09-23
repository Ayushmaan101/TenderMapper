"""Checklist 5.2 verification — unit-level (no Streamlit runtime).

Simulates a Linux / non-Windows environment purely by monkeypatching
os.environ and shutil.which — no Windows-only paths are assumed to exist
or not exist, so this test is itself meant to pass identically whether
run on this dev machine (Windows) or on a real Linux CI/Community Cloud
box.

Covers:
  - ocr/pipeline.py::_resolve_tesseract_cmd:
      * TESSERACT_CMD env var, when set, always wins (any platform)
      * with TESSERACT_CMD unset, a simulated Linux `which tesseract`
        hit (e.g. "/usr/bin/tesseract", what packages.txt's apt install
        resolves to on Community Cloud) is used
      * with TESSERACT_CMD unset AND no `which` hit, falls back to the
        Windows default as a last resort — never raises
  - run/secrets_bootstrap.py::bootstrap_groq_api_key:
      * GROQ_API_KEY already in os.environ -> left untouched, st.secrets
        never consulted at all (proves local-dev/.env path is unaffected)
      * GROQ_API_KEY absent from os.environ, present in st.secrets ->
        copied into os.environ (the Community Cloud path)
      * GROQ_API_KEY absent from both -> os.environ stays unset, no
        exception (a bare `st.secrets.get` raising, e.g. no
        secrets.toml at all - the normal local-dev case - must not
        crash startup)

Run: python tests/verify_deployment_config_unit.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


def main() -> None:
    import ocr.pipeline as pipeline

    saved_env = dict(os.environ)
    try:
        # --- TESSERACT_CMD env var always wins, regardless of `which` ---
        os.environ["TESSERACT_CMD"] = "/some/explicit/override/tesseract"
        cmd = pipeline._resolve_tesseract_cmd()
        check("TESSERACT_CMD env var wins outright when set", cmd == "/some/explicit/override/tesseract")

        # --- TESSERACT_CMD unset, simulate a Linux `which tesseract` hit ---
        del os.environ["TESSERACT_CMD"]
        import shutil as real_shutil

        original_which = real_shutil.which
        real_shutil.which = lambda name: "/usr/bin/tesseract" if name == "tesseract" else None
        try:
            cmd = pipeline._resolve_tesseract_cmd()
            check(
                "with TESSERACT_CMD unset, a simulated Linux `which tesseract` hit is used",
                cmd == "/usr/bin/tesseract",
            )
        finally:
            real_shutil.which = original_which

        # --- TESSERACT_CMD unset, no `which` hit at all -> Windows default fallback, no crash ---
        real_shutil.which = lambda name: None
        try:
            cmd = pipeline._resolve_tesseract_cmd()
            check(
                "with nothing resolvable, falls back to the Windows default path without raising",
                cmd == r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            )
        finally:
            real_shutil.which = original_which
    finally:
        os.environ.clear()
        os.environ.update(saved_env)

    # --- secrets bootstrap bridge ---
    import run.secrets_bootstrap as sb

    class _FakeSecrets:
        def __init__(self, values=None, raise_on_access=False):
            self._values = values or {}
            self._raise_on_access = raise_on_access

        def get(self, key):
            if self._raise_on_access:
                raise FileNotFoundError("no secrets.toml on this box")
            return self._values.get(key)

    saved_env2 = dict(os.environ)
    try:
        # 1. GROQ_API_KEY already set -> untouched, st.secrets never consulted
        os.environ["GROQ_API_KEY"] = "already-set-from-dotenv"
        sb.st.secrets = _FakeSecrets(values={"GROQ_API_KEY": "should-never-be-read"})
        sb.bootstrap_groq_api_key()
        check(
            "GROQ_API_KEY already in os.environ is left untouched (local-dev/.env path unaffected)",
            os.environ["GROQ_API_KEY"] == "already-set-from-dotenv",
        )

        # 2. GROQ_API_KEY absent, present in st.secrets -> copied across (Community Cloud path)
        del os.environ["GROQ_API_KEY"]
        sb.st.secrets = _FakeSecrets(values={"GROQ_API_KEY": "from-community-cloud-secrets"})
        sb.bootstrap_groq_api_key()
        check(
            "GROQ_API_KEY absent from os.environ but present in st.secrets is bridged across",
            os.environ.get("GROQ_API_KEY") == "from-community-cloud-secrets",
        )

        # 3. GROQ_API_KEY absent from both, st.secrets raises (no secrets.toml, normal local dev) -> no crash
        del os.environ["GROQ_API_KEY"]
        sb.st.secrets = _FakeSecrets(raise_on_access=True)
        try:
            sb.bootstrap_groq_api_key()
            no_crash = True
        except Exception:
            no_crash = False
        check("st.secrets raising (no secrets.toml at all) does not crash startup", no_crash)
        check("...and GROQ_API_KEY correctly stays unset", "GROQ_API_KEY" not in os.environ)
    finally:
        os.environ.clear()
        os.environ.update(saved_env2)

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
