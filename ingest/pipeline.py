"""Upload ingestion: turn whatever a person selected in the file uploader -
loose PDFs, a zip, several zips, a folder's worth of files dropped at
once - into a clean, deduplicated list[IngestedDocument] plus a list of
human-readable warnings for anything rejected along the way.

Accepts anything with a Streamlit UploadedFile-shaped interface
(.name: str, .getvalue() -> bytes) - real UploadedFile objects from
st.file_uploader, or a plain test double. Nothing in this module imports
streamlit or touches st.session_state; the caller (app.py) owns that.

Zip handling is recursive (a zip inside a zip inside a zip, bounded by
MAX_ZIP_DEPTH), guards against Zip Slip / path traversal, filters out
macOS junk (__MACOSX/, .DS_Store, AppleDouble "._*" resource forks), and
bounds total entry count / uncompressed size against zip bombs.
"""
from __future__ import annotations

import io
import zipfile
from typing import Protocol

from ingest.models import IngestedDocument, IngestResult

PDF_MAGIC = b"%PDF-"

MAX_ZIP_DEPTH = 5
MAX_TOTAL_ENTRIES = 5000
MAX_TOTAL_UNCOMPRESSED_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB


class UploadedFileLike(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


class _Budget:
    """Shared, mutable counters threaded through a recursive zip walk, so
    limits apply across the WHOLE upload batch, not per-zip.
    """

    def __init__(self, max_entries: int, max_bytes: int):
        self.entries_seen = 0
        self.bytes_seen = 0
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.exceeded = False

    def charge(self, uncompressed_size: int) -> bool:
        """Returns False (and flips .exceeded) the moment either limit
        would be crossed; the caller should stop processing that source
        immediately."""
        if self.exceeded:
            return False
        self.entries_seen += 1
        self.bytes_seen += uncompressed_size
        if self.entries_seen > self.max_entries or self.bytes_seen > self.max_bytes:
            self.exceeded = True
            return False
        return True


def normalize_uploads(
    uploaded_files: list[UploadedFileLike] | None,
    *,
    max_entries: int = MAX_TOTAL_ENTRIES,
    max_bytes: int = MAX_TOTAL_UNCOMPRESSED_BYTES,
) -> IngestResult:
    """The single entry point. Never raises for bad input - every
    rejection becomes a warning and processing continues with whatever's
    left in the batch.
    """
    result = IngestResult()
    if not uploaded_files:
        return result

    budget = _Budget(max_entries, max_bytes)
    seen_names: dict[str, int] = {}  # lowercased name -> count, for dedup

    for uploaded in uploaded_files:
        name = uploaded.name
        try:
            data = uploaded.getvalue()
        except Exception as exc:  # noqa: BLE001 - a genuinely unreadable upload
            result.warnings.append(f"Could not read '{name}': {exc}")
            continue

        if not budget.charge(len(data)):
            result.warnings.append(
                f"Stopped processing uploads: batch exceeds the size/count safety "
                f"limit ({budget.max_entries} entries / {budget.max_bytes // (1024*1024)} MiB). "
                f"'{name}' and anything after it in this batch were skipped."
            )
            break

        lower = name.lower()
        if lower.endswith(".zip"):
            _process_zip_bytes(data, source_prefix=name, depth=0, result=result, budget=budget, seen_names=seen_names)
        elif lower.endswith(".pdf"):
            _accept_pdf_candidate(name=name, data=data, source_path=name, result=result, seen_names=seen_names)
        else:
            result.warnings.append(f"Skipped '{name}': not a .pdf or .zip file.")

        if budget.exceeded:
            break

    return result


def _process_zip_bytes(
    data: bytes,
    *,
    source_prefix: str,
    depth: int,
    result: IngestResult,
    budget: _Budget,
    seen_names: dict[str, int],
) -> None:
    if depth >= MAX_ZIP_DEPTH:
        result.warnings.append(
            f"Skipped '{source_prefix}': zip nesting exceeds the safety limit "
            f"({MAX_ZIP_DEPTH} levels)."
        )
        return

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        result.warnings.append(f"Skipped '{source_prefix}': not a valid zip archive.")
        return

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            member_path = info.filename.replace("\\", "/")
            display_path = f"{source_prefix}/{member_path}"

            if _is_junk_entry(member_path):
                continue  # known OS/archive noise - not worth a warning

            if not _is_safe_zip_member(member_path):
                result.warnings.append(
                    f"Skipped '{display_path}': unsafe path in zip archive "
                    f"(possible path traversal / Zip Slip attempt)."
                )
                continue

            if not budget.charge(info.file_size):
                result.warnings.append(
                    f"Stopped processing '{source_prefix}': archive exceeds the "
                    f"size/count safety limit ({budget.max_entries} entries / "
                    f"{budget.max_bytes // (1024*1024)} MiB)."
                )
                return

            try:
                member_bytes = zf.read(info)
            except Exception as exc:  # noqa: BLE001 - corrupt member, skip it
                result.warnings.append(f"Skipped '{display_path}': could not read from archive ({exc}).")
                continue

            basename = member_path.rsplit("/", 1)[-1]
            lower = basename.lower()

            if lower.endswith(".zip"):
                _process_zip_bytes(
                    member_bytes,
                    source_prefix=display_path,
                    depth=depth + 1,
                    result=result,
                    budget=budget,
                    seen_names=seen_names,
                )
            elif lower.endswith(".pdf"):
                _accept_pdf_candidate(
                    name=basename, data=member_bytes, source_path=display_path,
                    result=result, seen_names=seen_names,
                )
            else:
                result.warnings.append(f"Skipped '{display_path}': not a .pdf or .zip file.")

            if budget.exceeded:
                return


def _accept_pdf_candidate(
    *, name: str, data: bytes, source_path: str, result: IngestResult, seen_names: dict[str, int]
) -> None:
    if not data.startswith(PDF_MAGIC):
        result.warnings.append(
            f"Skipped '{source_path}': has a .pdf name but its content is not a "
            f"valid PDF (missing %PDF header)."
        )
        return

    final_name = _dedupe_name(name, seen_names)
    if final_name != name:
        result.warnings.append(
            f"'{source_path}' was renamed to '{final_name}' because another "
            f"document in this upload already uses the name '{name}'."
        )

    result.documents.append(IngestedDocument(name=final_name, data=data, source_path=source_path))


def _dedupe_name(name: str, seen_names: dict[str, int]) -> str:
    key = name.lower()
    count = seen_names.get(key, 0)
    seen_names[key] = count + 1
    if count == 0:
        return name

    if "." in name:
        stem, ext = name.rsplit(".", 1)
        candidate = f"{stem} ({count + 1}).{ext}"
    else:
        candidate = f"{name} ({count + 1})"

    # Extremely unlikely, but if the renamed candidate itself collides
    # (e.g. the batch also independently contains that exact name),
    # keep incrementing until it's unique.
    while candidate.lower() in seen_names:
        count += 1
        if "." in name:
            stem, ext = name.rsplit(".", 1)
            candidate = f"{stem} ({count + 1}).{ext}"
        else:
            candidate = f"{name} ({count + 1})"
    seen_names[candidate.lower()] = 1
    return candidate


def _is_junk_entry(member_path: str) -> bool:
    """Known noise that real-world zips (especially from macOS) carry
    around: the __MACOSX metadata folder, .DS_Store, and AppleDouble
    resource-fork siblings (._SomeFile.pdf) - which would otherwise pass
    the .pdf extension check and then fail the PDF-magic-byte check with
    a confusing 'not a valid PDF' warning. Silently dropped, no warning:
    the user didn't put these there on purpose.
    """
    parts = member_path.split("/")
    if parts and parts[0] == "__MACOSX":
        return True
    basename = parts[-1] if parts else member_path
    if basename == ".DS_Store":
        return True
    if basename.startswith("._"):
        return True
    return False


def _is_safe_zip_member(member_path: str) -> bool:
    """Rejects absolute paths, drive-letter paths, parent-directory
    traversal, and embedded NUL bytes. Defense in depth: this code never
    extracts to disk (zf.read() only ever returns bytes into memory), so
    Zip Slip can't actually occur via this module today - but the
    resulting names/paths are surfaced in the UI and could feed a future
    on-disk export, so untrusted archive-supplied paths are validated
    here rather than trusted anywhere downstream.
    """
    if "\x00" in member_path:
        return False
    if member_path.startswith("/") or member_path.startswith("\\"):
        return False
    if len(member_path) >= 2 and member_path[1] == ":":  # e.g. "C:..."
        return False
    segments = member_path.split("/")
    if any(seg == ".." for seg in segments):
        return False
    return True
