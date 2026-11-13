"""Staging store of data uploads: "preview, then confirm".

    upload ──► DATA_DIR/staging/<token>.<ext>   (+ <token>.json: who, what, checksum, validation report)
                 │  every check runs here; nothing is imported, the live dataset keeps serving
                 ├─ "Confirm import" ──► DATA_DIR/uploads/<UTC timestamp>-<sha256[:16]>.<ext>  (os.replace = atomic)
                 │                        then the existing import (parse → write → flip `is_active` in one transaction)
                 └─ cancelled / expired (STAGING_TTL_MINUTES) / failed ──► deleted

Why a separate folder: a file only reaches the upload store (and the import history) after it passed every check and
an admin confirmed the report, so a half-checked or rejected file can never become a dataset. Tokens are random
(unguessable) and bound to the admin who made the preview.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from ..config import get_settings

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
CHUNK = 1 << 20
_lock = threading.Lock()  # promote / discard / cleanup never interleave


class StagingError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Staged:
    token: str
    kind: str  # "master" | "escalation" – what the admin said the file is
    file_name: str  # cleaned display name (never used for paths)
    suffix: str
    size: int
    sha256: str
    user_id: int
    created: float  # epoch seconds
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return get_settings().staging_dir / f"{self.token}{self.suffix}"

    @property
    def expires(self) -> float:
        return self.created + get_settings().staging_ttl_minutes * 60


def _meta(token: str) -> Path:
    return get_settings().staging_dir / f"{token}.json"


def receive(stream: BinaryIO, suffix: str) -> tuple[str, Path, int, str]:
    """Stream an upload into the staging folder under a new token, enforcing UPLOAD_MAX_MB while reading (a too large
    file is cut off and deleted, never held in memory). Returns (token, path, size, sha256)."""
    import hashlib

    s = get_settings()
    s.staging_dir.mkdir(parents=True, exist_ok=True)
    cleanup()
    token = secrets.token_urlsafe(24)
    path = s.staging_dir / f"{token}{suffix}"
    limit, size, h = s.upload_max_mb * 1024 * 1024, 0, hashlib.sha256()
    try:
        with path.open("wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise StagingError(413, f"File exceeds {s.upload_max_mb} MB")
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return token, path, size, h.hexdigest()


def save(st: Staged) -> None:
    _meta(st.token).write_text(json.dumps(asdict(st), default=str), encoding="utf-8")


def load(token: str, user_id: int) -> Staged:
    """The staged upload of this token – only for the admin who made it, only while it has not expired."""
    if not TOKEN_RE.fullmatch(token or ""):
        raise StagingError(404, "Preview not found – please upload the file again")
    meta = _meta(token)
    try:
        st = Staged(**json.loads(meta.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        raise StagingError(404, "Preview not found or already used – please upload the file again") from None
    if st.user_id != user_id:
        raise StagingError(404, "Preview not found – please upload the file again")
    if time.time() > st.expires or not st.path.exists():
        discard(token)
        raise StagingError(410, f"The preview expired (kept {get_settings().staging_ttl_minutes} minutes) – please upload the file again")
    return st


def promote(st: Staged) -> Path:
    """Move a confirmed upload into the upload store under <UTC timestamp>-<sha256[:16]>.<ext> (atomic rename on the
    same disk) and drop its staging record. The checksum is verified again first: the staged file is never trusted."""
    from .service import sha256_of

    s = get_settings()
    with _lock:
        if not st.path.exists():
            raise StagingError(410, "The staged file is gone – please upload the file again")
        if sha256_of(st.path) != st.sha256:
            discard(st.token)
            raise StagingError(409, "The staged file changed after the preview – please upload the file again")
        s.upload_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        target = s.upload_dir / f"{stamp}-{st.sha256[:16]}{st.suffix}"
        n = 1
        while target.exists():  # same file confirmed twice in one second: never overwrite
            target = s.upload_dir / f"{stamp}-{st.sha256[:16]}-{n}{st.suffix}"
            n += 1
        os.replace(st.path, target)
        _meta(st.token).unlink(missing_ok=True)
    return target


def discard(token: str) -> None:
    if not TOKEN_RE.fullmatch(token or ""):
        return
    with _lock:
        folder = get_settings().staging_dir
        for p in folder.glob(f"{token}.*"):
            p.unlink(missing_ok=True)


def cleanup() -> int:
    """Delete expired previews (and orphan files older than the TTL). Runs before every new upload."""
    s = get_settings()
    folder = s.staging_dir
    if not folder.exists():
        return 0
    cutoff = time.time() - s.staging_ttl_minutes * 60
    removed = 0
    with _lock:
        for p in folder.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    return removed
