"""Dokument-Upload ohne HTTP-Wissen: Validierung, Doppel-Erkennung, Ablage."""

import hashlib
import uuid
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath

import pymupdf
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Dokument, Dossier
from app.pipeline.preprocess import open_pdf
from app.storage import Storage

PDF_MAGIC = b"%PDF-"


class UploadError(Exception):
    """Fachlicher Upload-Fehler; `code` ist ein stabiler Fehlercode ohne Inhalte."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DossierNotFoundError(Exception):
    pass


@lru_cache
def get_storage() -> Storage:
    return Storage()


def basename(name: str) -> str:
    """Reiner Dateiname ohne Pfadanteile (POSIX und Windows)."""
    return PurePosixPath(PureWindowsPath(name).name).name or "dokument.pdf"


def get_dossier(session: Session, buero_id: uuid.UUID, dossier_id: uuid.UUID) -> Dossier:
    """Dossier nur im eigenen Büro; sonst gleich wie nicht vorhanden."""
    dossier = session.scalar(
        select(Dossier).where(Dossier.id == dossier_id, Dossier.buero_id == buero_id)
    )
    if dossier is None:
        raise DossierNotFoundError
    return dossier


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
    exists = session.scalar(
        select(Dokument.id).where(Dokument.dossier_id == dossier.id, Dokument.sha256 == sha256)
    )
    if exists is not None:
        raise UploadError("DUPLICATE")
    key = storage.put(dossier.buero_id, dossier.id, sha256, data)
    dokument = Dokument(
        dossier_id=dossier.id,
        buero_id=dossier.buero_id,
        dateiname=dateiname[:500],
        sha256=sha256,
        seitenzahl=pages,
        speicherpfad=key,
    )
    session.add(dokument)
    try:
        session.commit()
    except IntegrityError:  # paralleler Upload desselben Dokuments
        session.rollback()
        raise UploadError("DUPLICATE") from None
    return dokument
