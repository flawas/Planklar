import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.users import current_user
from app.config import get_settings
from app.db.models import Dokument, Dossier, User
from app.db.session import get_session
from app.dossiers.schemas import (
    DokumentRead,
    DossierCreate,
    DossierRead,
    DossierUpdate,
    validate_attribute,
)
from app.dossiers.scope import BueroScope, NotFoundError, get_scope, not_found
from app.dossiers.service import (
    DossierNotFoundError,
    UploadError,
    basename,
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


@dossier_router.get("", response_model=list[DossierRead])
def list_dossiers(scope: BueroScope = Depends(get_scope)) -> list[Dossier]:
    return list(scope.list_dossiers())


@dossier_router.post("", response_model=DossierRead, status_code=status.HTTP_201_CREATED)
def create_dossier(body: DossierCreate, scope: BueroScope = Depends(get_scope)) -> Dossier:
    dossier = scope.add_dossier(**body.model_dump())
    scope.session.commit()
    return dossier


@dossier_router.get("/{dossier_id}", response_model=DossierRead)
def read_dossier(dossier_id: uuid.UUID, scope: BueroScope = Depends(get_scope)) -> Dossier:
    try:
        return scope.get_dossier(dossier_id)
    except NotFoundError:
        raise not_found() from None


@dossier_router.patch("/{dossier_id}", response_model=DossierRead)
def update_dossier(
    dossier_id: uuid.UUID, body: DossierUpdate, scope: BueroScope = Depends(get_scope)
) -> Dossier:
    try:
        dossier = scope.get_dossier(dossier_id)
    except NotFoundError:
        raise not_found() from None
    fields = body.model_dump(exclude_unset=True)
    typ = fields.get("vorhabenstyp", dossier.vorhabenstyp)
    if "attribute" in fields or "vorhabenstyp" in fields:
        try:
            fields["attribute"] = validate_attribute(
                typ, fields.get("attribute", dossier.attribute)
            )
        except ValidationError as exc:
            raise RequestValidationError(
                exc.errors(include_url=False, include_context=False)
            ) from None
    dossier = scope.update_dossier(dossier_id, **fields)
    scope.session.commit()
    return dossier


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
            session, storage, dossier, basename(file.filename or ""), data, limit
        )
    except UploadError as exc:
        raise HTTPException(_STATUS[exc.code], exc.code) from None
