"""Dokument-Upload ohne HTTP-Wissen: Validierung, Doppel-Erkennung, Ablage."""

import hashlib
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath

import pymupdf
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Dokument, Dossier
from app.dossiers.scope import BueroScope
from app.pipeline.preprocess import open_pdf
from app.storage import Storage

PDF_MAGIC = b"%PDF-"


class UploadError(Exception):
    """Fachlicher Upload-Fehler; `code` ist ein stabiler Fehlercode ohne Inhalte."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@lru_cache
def get_storage() -> Storage:
    return Storage()


def basename(name: str) -> str:
    """Reiner Dateiname ohne Pfadanteile (POSIX und Windows)."""
    return PurePosixPath(PureWindowsPath(name).name).name or "dokument.pdf"


def _page_count(data: bytes) -> int:
    try:
        with open_pdf(data) as doc:
            if doc.needs_pass:
                raise UploadError("PDF_ENCRYPTED")
            return doc.page_count
    except UploadError:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError):
        raise UploadError("PDF_INVALID") from None


def upload_dokument(
    session: Session,
    storage: Storage,
    dossier: Dossier,
    dateiname: str,
    data: bytes,
    max_bytes: int,
) -> Dokument:
    if len(data) > max_bytes:
        raise UploadError("FILE_TOO_LARGE")
    if not data.startswith(PDF_MAGIC):
        raise UploadError("NOT_A_PDF")
    pages = _page_count(data)
    if pages < 1:
        raise UploadError("PDF_INVALID")
    sha256 = hashlib.sha256(data).hexdigest()
    scope = BueroScope(session, dossier.buero_id)  # setzt auch den RLS-Kontext
    if scope.hat_dokument(dossier.id, sha256):
        raise UploadError("DUPLICATE")
    key = storage.put(dossier.buero_id, dossier.id, sha256, data)
    try:
        dokument = scope.add_dokument(
            dossier.id,
            dateiname=dateiname[:500],
            sha256=sha256,
            seitenzahl=pages,
            speicherpfad=key,
        )
        session.commit()
    except IntegrityError:  # paralleler Upload desselben Dokuments
        session.rollback()
        raise UploadError("DUPLICATE") from None
    return dokument
