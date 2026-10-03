import uuid
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.users import current_user
from app.config import get_settings
from app.db.models import Dokument, User
from app.db.session import get_session
from app.dossiers.schemas import DokumentRead
from app.dossiers.service import (
    DossierNotFoundError,
    UploadError,
    get_dossier,
    get_storage,
    upload_dokument,
)
from app.storage import Storage

dossier_router = APIRouter(prefix="/dossiers", tags=["dossiers"])

_STATUS = {
    "FILE_TOO_LARGE": status.HTTP_413_CONTENT_TOO_LARGE,
    "NOT_A_PDF": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "PDF_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "PDF_ENCRYPTED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "DUPLICATE": status.HTTP_409_CONFLICT,
}


def _basename(name: str) -> str:
    return PurePosixPath(PureWindowsPath(name).name).name or "dokument.pdf"


@dossier_router.post(
    "/{dossier_id}/dokumente", response_model=DokumentRead, status_code=status.HTTP_201_CREATED
)
async def upload(
    dossier_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
) -> Dokument:
    try:
        dossier = get_dossier(session, user.buero_id, dossier_id)
    except DossierNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DOSSIER_NOT_FOUND") from None
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)  # nie mehr als Limit + 1 Byte in den Speicher
    try:
        return upload_dokument(
            session, storage, dossier, _basename(file.filename or ""), data, limit
        )
    except UploadError as exc:
        raise HTTPException(_STATUS[exc.code], exc.code) from None
