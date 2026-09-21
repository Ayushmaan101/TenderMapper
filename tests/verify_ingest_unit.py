"""Checklist 2.1 verification — unit-level (no Streamlit).

Drives ingest/pipeline.normalize_uploads() directly with fake
UploadedFile-like objects, covering: direct single/multi PDF uploads,
zips with valid PDFs (including nested subfolders and zip-in-zip),
unsupported files mixed in alongside valid PDFs, macOS junk filtering,
Zip Slip / path traversal rejection, a mislabeled non-PDF with a .pdf
extension, filename collisions across sources, an empty upload, and the
size/count safety limits.

Run: python tests/verify_ingest_unit.py
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.pipeline import normalize_uploads  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))
    print(f"{'OK  ' if condition else 'FAIL'} {label}")


class FakeUploadedFile:
    """Minimal stand-in for streamlit's UploadedFile: .name, .size, .getvalue()."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self.data = data
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self.data


def pdf_bytes(marker: str = "") -> bytes:
    return f"%PDF-1.4\n%fake pdf content {marker}\n%%EOF".encode()


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    return buf.getvalue()


# ------------------------------------------------------- direct uploads --


def test_direct_single_pdf() -> None:
    result = normalize_uploads([FakeUploadedFile("invoice.pdf", pdf_bytes("A"))])
    check("single direct PDF -> 1 document", len(result.documents) == 1)
    check("single direct PDF -> no warnings", result.warnings == [])
    check("single direct PDF -> correct name/bytes/source", result.documents[0].name == "invoice.pdf" and result.documents[0].data == pdf_bytes("A") and result.documents[0].source_path == "invoice.pdf")


def test_direct_multi_pdf() -> None:
    files = [FakeUploadedFile(f"doc{i}.pdf", pdf_bytes(str(i))) for i in range(5)]
    result = normalize_uploads(files)
    check("5 direct PDFs -> 5 documents, no warnings", len(result.documents) == 5 and result.warnings == [])
    check("5 direct PDFs -> names all preserved", {d.name for d in result.documents} == {f"doc{i}.pdf" for i in range(5)})


def test_empty_upload() -> None:
    result = normalize_uploads([])
    check("empty list -> empty result, no crash", result.documents == [] and result.warnings == [])
    result_none = normalize_uploads(None)
    check("None -> empty result, no crash", result_none.documents == [] and result_none.warnings == [])


def test_non_pdf_non_zip_rejected() -> None:
    files = [FakeUploadedFile("invoice.pdf", pdf_bytes()), FakeUploadedFile("notes.docx", b"fake docx content")]
    result = normalize_uploads(files)
    check("mixed batch -> valid PDF still accepted", len(result.documents) == 1 and result.documents[0].name == "invoice.pdf")
    check("mixed batch -> .docx rejected with a warning naming it", any("notes.docx" in w for w in result.warnings))


def test_mislabeled_non_pdf() -> None:
    files = [FakeUploadedFile("fake.pdf", b"this is not actually a pdf, just text with a .pdf name")]
    result = normalize_uploads(files)
    check("fake .pdf content -> rejected, not silently accepted", result.documents == [])
    check("fake .pdf content -> warning explains it's not a valid PDF", any("not a valid PDF" in w for w in result.warnings))


# ------------------------------------------------------------------ zips --


def test_zip_with_valid_pdfs_nested() -> None:
    zip_bytes = make_zip({
        "top.pdf": pdf_bytes("top"),
        "scans/sub.pdf": pdf_bytes("sub"),
        "scans/deeper/deepest.pdf": pdf_bytes("deepest"),
    })
    result = normalize_uploads([FakeUploadedFile("CompanyA.zip", zip_bytes)])
    check("zip with nested folders -> all 3 PDFs extracted", len(result.documents) == 3 and result.warnings == [])
    names = {d.name for d in result.documents}
    check("zip with nested folders -> correct basenames", names == {"top.pdf", "sub.pdf", "deepest.pdf"})
    source_paths = {d.source_path for d in result.documents}
    check(
        "zip with nested folders -> source_path preserves the archive structure",
        source_paths == {"CompanyA.zip/top.pdf", "CompanyA.zip/scans/sub.pdf", "CompanyA.zip/scans/deeper/deepest.pdf"},
    )


def test_zip_with_unsupported_files_mixed_in() -> None:
    zip_bytes = make_zip({
        "invoice.pdf": pdf_bytes("inv"),
        "logo.png": b"\x89PNG fake png bytes",
        "notes.docx": b"fake docx bytes",
        "certificate.pdf": pdf_bytes("cert"),
    })
    result = normalize_uploads([FakeUploadedFile("Docs.zip", zip_bytes)])
    check("zip with mixed content -> both valid PDFs extracted", len(result.documents) == 2)
    check("zip with mixed content -> correct PDF names", {d.name for d in result.documents} == {"invoice.pdf", "certificate.pdf"})
    check("zip with mixed content -> .png triggers a warning", any("logo.png" in w for w in result.warnings))
    check("zip with mixed content -> .docx triggers a warning", any("notes.docx" in w for w in result.warnings))
    check("zip with mixed content -> exactly 2 warnings (one per unsupported file)", len(result.warnings) == 2)


def test_zip_macos_junk_silently_filtered() -> None:
    zip_bytes = make_zip({
        "invoice.pdf": pdf_bytes("inv"),
        "__MACOSX/._invoice.pdf": b"appledouble resource fork junk",
        "__MACOSX/scans/.DS_Store": b"junk",
        ".DS_Store": b"junk",
        "scans/._other.pdf": b"appledouble junk again",
    })
    result = normalize_uploads([FakeUploadedFile("MacExport.zip", zip_bytes)])
    check("macOS junk -> only the real PDF is extracted", len(result.documents) == 1 and result.documents[0].name == "invoice.pdf")
    check("macOS junk -> filtered silently, no warnings generated for it", result.warnings == [])


def test_nested_zip_in_zip() -> None:
    inner_zip = make_zip({"inner1.pdf": pdf_bytes("i1"), "inner2.pdf": pdf_bytes("i2")})
    outer_zip = make_zip({"outer.pdf": pdf_bytes("o"), "nested/Inner.zip": inner_zip})
    result = normalize_uploads([FakeUploadedFile("Outer.zip", outer_zip)])
    check("zip-in-zip -> all 3 PDFs extracted (outer + both inner)", len(result.documents) == 3 and result.warnings == [])
    names = {d.name for d in result.documents}
    check("zip-in-zip -> correct names across both levels", names == {"outer.pdf", "inner1.pdf", "inner2.pdf"})
    inner_doc = next(d for d in result.documents if d.name == "inner1.pdf")
    check(
        "zip-in-zip -> source_path traces through both archive levels",
        inner_doc.source_path == "Outer.zip/nested/Inner.zip/inner1.pdf",
    )


def test_zip_slip_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("normal.pdf", pdf_bytes("ok"))
        # Craft entries with unsafe paths directly via ZipInfo, bypassing
        # zipfile's own writestr path handling.
        for evil_name in ["../../evil.pdf", "/etc/evil.pdf", "..\\..\\evil.pdf", "C:/evil.pdf"]:
            info = zipfile.ZipInfo(evil_name)
            zf.writestr(info, pdf_bytes("evil"))
    result = normalize_uploads([FakeUploadedFile("Malicious.zip", buf.getvalue())])
    check("zip slip attempt -> only the legitimate PDF is accepted", len(result.documents) == 1 and result.documents[0].name == "normal.pdf")
    check("zip slip attempt -> every unsafe entry rejected with a warning", len(result.warnings) == 4)
    check(
        "zip slip attempt -> warnings explicitly mention path traversal / Zip Slip",
        all("traversal" in w or "Zip Slip" in w for w in result.warnings),
    )


def test_bad_zip_file() -> None:
    result = normalize_uploads([FakeUploadedFile("corrupt.zip", b"this is not a real zip file at all")])
    check("corrupt zip -> rejected with a clear warning, no crash", result.documents == [] and any("not a valid zip" in w for w in result.warnings))


# --------------------------------------------------------- deduplication --


def test_filename_collision_direct_uploads() -> None:
    files = [FakeUploadedFile("invoice.pdf", pdf_bytes("first")), FakeUploadedFile("invoice.pdf", pdf_bytes("second"))]
    result = normalize_uploads(files)
    check("duplicate direct filenames -> both kept, none dropped", len(result.documents) == 2)
    names = sorted(d.name for d in result.documents)
    check("duplicate direct filenames -> second one renamed", names == ["invoice (2).pdf", "invoice.pdf"])
    check("duplicate direct filenames -> a rename warning is recorded", any("renamed" in w for w in result.warnings))
    by_name = {d.name: d.data for d in result.documents}
    check(
        "duplicate direct filenames -> each renamed doc keeps its OWN distinct content",
        by_name["invoice.pdf"] == pdf_bytes("first") and by_name["invoice (2).pdf"] == pdf_bytes("second"),
    )


def test_filename_collision_across_zip_and_direct() -> None:
    zip_bytes = make_zip({"invoice.pdf": pdf_bytes("from-zip")})
    files = [FakeUploadedFile("invoice.pdf", pdf_bytes("direct")), FakeUploadedFile("Docs.zip", zip_bytes)]
    result = normalize_uploads(files)
    check("collision across a direct upload and a zip entry -> both kept", len(result.documents) == 2)
    names = sorted(d.name for d in result.documents)
    check("collision across direct+zip -> second renamed regardless of source", names == ["invoice (2).pdf", "invoice.pdf"])


def test_three_way_collision() -> None:
    files = [FakeUploadedFile(f"dup.pdf", pdf_bytes(str(i))) for i in range(3)]
    result = normalize_uploads(files)
    names = sorted(d.name for d in result.documents)
    check("three-way collision -> sequential renaming", names == ["dup (2).pdf", "dup (3).pdf", "dup.pdf"])


# ------------------------------------------------------------ safety caps --


def test_size_limit_stops_processing() -> None:
    files = [FakeUploadedFile(f"doc{i}.pdf", pdf_bytes(str(i))) for i in range(5)]
    result = normalize_uploads(files, max_bytes=10)  # far smaller than even one fake PDF
    check("tiny byte budget -> stops early rather than crashing", len(result.documents) < 5)
    check("tiny byte budget -> a clear limit warning is recorded", any("safety limit" in w for w in result.warnings))


def test_entry_count_limit_stops_processing() -> None:
    zip_bytes = make_zip({f"doc{i}.pdf": pdf_bytes(str(i)) for i in range(20)})
    result = normalize_uploads([FakeUploadedFile("Big.zip", zip_bytes)], max_entries=5)
    check("tiny entry-count budget -> stops well short of all 20", len(result.documents) <= 5)
    check("tiny entry-count budget -> a clear limit warning is recorded", any("safety limit" in w for w in result.warnings))


def main() -> None:
    test_direct_single_pdf()
    test_direct_multi_pdf()
    test_empty_upload()
    test_non_pdf_non_zip_rejected()
    test_mislabeled_non_pdf()
    test_zip_with_valid_pdfs_nested()
    test_zip_with_unsupported_files_mixed_in()
    test_zip_macos_junk_silently_filtered()
    test_nested_zip_in_zip()
    test_zip_slip_rejected()
    test_bad_zip_file()
    test_filename_collision_direct_uploads()
    test_filename_collision_across_zip_and_direct()
    test_three_way_collision()
    test_size_limit_stops_processing()
    test_entry_count_limit_stops_processing()

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
