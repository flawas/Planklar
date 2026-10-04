import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.auth.users import current_user
from app.config import get_settings
from app.db.models import Befund, Dokument, Dossier, Pruefstatus, Pruefung, User
from app.db.session import get_session
from app.dossiers import vorschau
from app.dossiers.erwartung import ErwarteteUnterlagen, erwartete_unterlagen
from app.dossiers.pruefung import LEASE, start_pruefung
from app.dossiers.schemas import (
    BefundRead,
    DokumentRead,
    DossierCreate,
    DossierRead,
    DossierUpdate,
    OverrideCreate,
    OverrideExport,
    PruefungRead,
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
from app.storage import ObjectNotFoundError, Storage
from app.worker import run_pruefung_task

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


@dossier_router.get("/{dossier_id}/erwartete-unterlagen", response_model=ErwarteteUnterlagen)
def read_erwartete_unterlagen(
    dossier_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> ErwarteteUnterlagen:
    try:
        return erwartete_unterlagen(scope.get_dossier(dossier_id))
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


@dossier_router.post(
    "/{dossier_id}/pruefungen", response_model=PruefungRead, status_code=status.HTTP_202_ACCEPTED
)
def start_pruefung_endpoint(
    dossier_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> Pruefung:
    try:
        if not scope.list_dokumente(dossier_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "KEINE_DOKUMENTE")
        scope.lock_dossier(dossier_id)  # serialisiert gleichzeitige Starts
        if scope.hat_aktiven_lauf(dossier_id, LEASE):
            raise HTTPException(status.HTTP_409_CONFLICT, "PRUEFUNG_LAEUFT")
        pruefung = start_pruefung(scope, dossier_id)
    except NotFoundError:
        raise not_found() from None
    scope.session.commit()
    try:
        run_pruefung_task.delay(str(scope.buero_id), str(pruefung.id))
    except Exception:
        scope.update_pruefung(
            pruefung.id, status=Pruefstatus.FEHLGESCHLAGEN, beendet_am=datetime.now(UTC)
        )
        scope.session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "WORKER_NICHT_ERREICHBAR"
        ) from None
    return pruefung


@dossier_router.get("/{dossier_id}/pruefungen", response_model=list[PruefungRead])
def list_pruefungen(
    dossier_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> list[Pruefung]:
    try:
        return list(scope.list_pruefungen(dossier_id))
    except NotFoundError:
        raise not_found() from None


def _pruefung_im_dossier(
    scope: BueroScope, dossier_id: uuid.UUID, pruefung_id: uuid.UUID
) -> Pruefung:
    try:
        pruefung = scope.get_pruefung(pruefung_id)
    except NotFoundError:
        raise not_found() from None
    if pruefung.dossier_id != dossier_id:
        raise not_found()
    return pruefung


@dossier_router.get("/{dossier_id}/pruefungen/{pruefung_id}", response_model=PruefungRead)
def read_pruefung(
    dossier_id: uuid.UUID, pruefung_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> Pruefung:
    return _pruefung_im_dossier(scope, dossier_id, pruefung_id)


@dossier_router.get(
    "/{dossier_id}/pruefungen/{pruefung_id}/befunde", response_model=list[BefundRead]
)
def list_befunde(
    dossier_id: uuid.UUID, pruefung_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> list[Befund]:
    _pruefung_im_dossier(scope, dossier_id, pruefung_id)
    return list(scope.list_befunde(pruefung_id))


class VorschauUrl(BaseModel):
    url: str
    gueltig_sekunden: int


@dossier_router.get("/{dossier_id}/seiten/{seite_id}/vorschau-url", response_model=VorschauUrl)
def vorschau_url(
    dossier_id: uuid.UUID, seite_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> VorschauUrl:
    try:
        seite = scope.get_seite(seite_id)
        if scope.get_dokument(seite.dokument_id).dossier_id != dossier_id:
            raise NotFoundError
    except NotFoundError:
        raise not_found() from None
    return VorschauUrl(
        url=vorschau.url_fuer(scope.buero_id, seite.id),
        gueltig_sekunden=get_settings().signed_url_ttl_seconds,
    )


vorschau_router = APIRouter(tags=["dossiers"])


@vorschau_router.get("/vorschau/{token}", response_class=Response)
def vorschau_bild(
    token: str,
    scope: BueroScope = Depends(get_scope),
    storage: Storage = Depends(get_storage),
) -> Response:
    try:
        buero_id, seite_id = vorschau.verify(token)
        if buero_id != scope.buero_id:
            raise vorschau.TokenError
        seite = scope.get_seite(seite_id)
        png = vorschau.render_seite(scope, storage, seite)
    except (vorschau.TokenError, NotFoundError, ObjectNotFoundError):
        raise not_found() from None
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


def _befund_in_pruefung(scope: BueroScope, pruefung: Pruefung, befund_id: uuid.UUID) -> Befund:
    try:
        befund = scope.get_befund(befund_id)
    except NotFoundError:
        raise not_found() from None
    if befund.pruefung_id != pruefung.id:
        raise not_found()
    return befund


@dossier_router.put(
    "/{dossier_id}/pruefungen/{pruefung_id}/befunde/{befund_id}/override",
    response_model=BefundRead,
)
def set_override(
    dossier_id: uuid.UUID,
    pruefung_id: uuid.UUID,
    befund_id: uuid.UUID,
    body: OverrideCreate,
    scope: BueroScope = Depends(get_scope),
) -> Befund:
    pruefung = _pruefung_im_dossier(scope, dossier_id, pruefung_id)
    _befund_in_pruefung(scope, pruefung, befund_id)
    befund = scope.set_override(befund_id, body.ergebnis, body.begruendung)
    scope.session.commit()
    return befund


@dossier_router.get(
    "/{dossier_id}/pruefungen/{pruefung_id}/overrides", response_model=list[OverrideExport]
)
def list_overrides(
    dossier_id: uuid.UUID, pruefung_id: uuid.UUID, scope: BueroScope = Depends(get_scope)
) -> list[OverrideExport]:
    pruefung = _pruefung_im_dossier(scope, dossier_id, pruefung_id)
    return [
        OverrideExport(
            befund_id=b.id,
            regel_id=b.regel_id,
            ergebnis=b.ergebnis,
            override_ergebnis=b.override_ergebnis,
            override_begruendung=b.override_begruendung or "",
            override_am=b.override_am,
            regelset_hash=pruefung.regelset_hash,
            modellversion=pruefung.modellversion,
        )
        for b in scope.list_befunde(pruefung_id)
        if b.override_ergebnis is not None and b.override_am is not None
    ]
