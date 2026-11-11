"""Ticket attachments: validation and storage.

A file is accepted only when its extension is allowed, the browser's MIME type does not contradict it and the first
bytes of the file match the format (so a renamed .exe is refused even with a .pdf name). Files are stored under
DATA_DIR/tickets/<ticket id>/ with a random name – never the client's file name, never a public folder – and are
read back only through the API after the permission check (app.api.tickets).
"""

from __future__ import annotations

import hashlib
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ..config import get_settings

# extension -> (content type served on download, MIME types a browser may send for it)
ALLOWED: dict[str, tuple[str, frozenset[str]]] = {
    ".pdf": ("application/pdf", frozenset({"application/pdf"})),
    ".doc": ("application/msword", frozenset({"application/msword"})),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"})),
    ".xls": ("application/vnd.ms-excel", frozenset({"application/vnd.ms-excel"})),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})),
    ".jpg": ("image/jpeg", frozenset({"image/jpeg", "image/pjpeg"})),
    ".jpeg": ("image/jpeg", frozenset({"image/jpeg", "image/pjpeg"})),
    ".png": ("image/png", frozenset({"image/png"})),
}
# Browsers send these when they do not know the type (common for Office files on Windows); the content check decides.
GENERIC_MIME = frozenset({"", "application/octet-stream", "application/zip", "application/x-zip-compressed", "binary/octet-stream"})
# Formats a browser can show itself ("Preview"); everything else is downloaded.
INLINE_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc / .xls container


class AttachmentError(ValueError):
    """A file that cannot be accepted (message is shown to the user; `status` = HTTP status of the answer)."""

    def __init__(self, message: str, status: int = 415) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class StoredFile:
    file_name: str
    stored_name: str
    content_type: str
    size: int
    sha256: str


def allowed_list() -> str:
    return ", ".join(e[1:].upper() for e in ALLOWED if e != ".jpeg")


def clean_name(name: str | None) -> str:
    base = Path(name or "file").name.strip() or "file"
    return re.sub(r"[^\w .()\-]", "_", base)[:200]


def _content_ok(path: Path, ext: str) -> bool:
    with path.open("rb") as f:
        head = f.read(8)
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".doc", ".xls"):
        return head.startswith(OLE)
    if ext in (".docx", ".xlsx"):
        if not head.startswith(b"PK\x03\x04"):
            return False
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
        except (zipfile.BadZipFile, OSError):
            return False
        part = "word/document.xml" if ext == ".docx" else "xl/workbook.xml"
        return "[Content_Types].xml" in names and part in names
    return False


def check_meta(file_name: str | None, mime: str | None) -> tuple[str, str]:
    """(clean display name, extension) – before any byte is stored."""
    display = clean_name(file_name)
    ext = Path(display).suffix.lower()
    if ext not in ALLOWED:
        raise AttachmentError(f"{display}: file type not allowed – use {allowed_list()}")
    m = (mime or "").split(";")[0].strip().lower()
    if m not in GENERIC_MIME and m not in ALLOWED[ext][1]:
        raise AttachmentError(f"{display}: the file type ({m}) does not match its extension")
    return display, ext


def save(ticket_id: int, file_name: str | None, mime: str | None, stream: BinaryIO, budget: int) -> StoredFile:
    """Validate and store one file. `budget` = bytes still allowed for this submission. Raises AttachmentError and
    leaves nothing behind when the file is refused."""
    s = get_settings()
    display, ext = check_meta(file_name, mime)
    limit = min(s.ticket_file_max_mb * 1024 * 1024, budget)
    folder = s.ticket_dir / str(int(ticket_id))
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = folder / stored_name
    digest = hashlib.sha256()
    size = 0
    ok = False
    try:
        with target.open("wb") as out:
            while chunk := stream.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    if size > s.ticket_file_max_mb * 1024 * 1024:
                        raise AttachmentError(f"{display}: larger than {s.ticket_file_max_mb} MB", 413)
                    raise AttachmentError(f"The files together are larger than {s.ticket_upload_max_mb} MB", 413)
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise AttachmentError(f"{display}: the file is empty", 422)
        if not _content_ok(target, ext):
            raise AttachmentError(f"{display}: the content is not a valid {ext[1:].upper()} file")
        ok = True
        return StoredFile(display, stored_name, ALLOWED[ext][0], size, digest.hexdigest())
    finally:
        if not ok:
            target.unlink(missing_ok=True)


def path_of(ticket_id: int, stored_name: str) -> Path:
    """Absolute path of a stored file; refuses anything that would leave the ticket's folder."""
    root = (get_settings().ticket_dir / str(int(ticket_id))).resolve()
    p = (root / stored_name).resolve()
    if p.parent != root or not re.fullmatch(r"[0-9a-f]{32}\.[a-z]{3,4}", stored_name):
        raise AttachmentError("Invalid file reference", 404)
    return p


def remove(ticket_id: int, stored_names: list[str]) -> None:
    for name in stored_names:
        try:
            path_of(ticket_id, name).unlink(missing_ok=True)
        except (AttachmentError, OSError):
            pass
