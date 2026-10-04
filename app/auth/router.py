import re
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi_users import exceptions
from sqlalchemy.orm import Session

from app.abrechnung.nutzung import monatsauswertung
from app.auth import einladung as svc
from app.auth import plattform, verwaltung
from app.auth.schemas import (
    AdminUserCreate,
    BueroCreate,
    BueroNutzungRead,
    BueroRead,
    BueroUpdate,
    EinladungCreate,
    EinladungRead,
    ModellNutzungRead,
    PasswordChange,
    ResetAnfrage,
    TokenEinloesen,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.auth.tokens import TokenError
from app.auth.users import (
    UserManager,
    cookie_backend,
    current_user,
    fastapi_users,
    get_user_manager,
    hash_password,
    require_buero_admin,
    require_plattform_admin,
)
from app.db.models import User
from app.db.session import get_session
from app.mail import Mailer, get_mailer, send_safely

auth_router = APIRouter(prefix="/auth", tags=["auth"])
# Login/Logout; bewusst kein Register-Router: Benutzer legen Admin oder Seed an.
auth_router.include_router(fastapi_users.get_auth_router(cookie_backend))


@auth_router.get("/me", response_model=UserRead)
def me(user: User = Depends(current_user)) -> User:
    return user


@auth_router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange,
    user: User = Depends(current_user),
    manager: UserManager = Depends(get_user_manager),
) -> None:
    """Passwort am eigenen Konto ändern; das alte Passwort ist Pflicht."""
    verified, _ = manager.password_helper.verify_and_update(
        payload.old_password, user.hashed_password
    )
    if not verified:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_OLD_PASSWORD")
    try:
        await manager.validate_password(payload.new_password, user)
    except exceptions.InvalidPasswordException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_PASSWORD") from None
    await manager.user_db.update(user, {"hashed_password": hash_password(payload.new_password)})


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    admin: User = Depends(require_buero_admin),
    manager: UserManager = Depends(get_user_manager),
) -> User:
    """Legt einen normalen Benutzer im Büro des Admins an (Mandantentrennung)."""
    data = UserCreate(email=payload.email, password=payload.password, buero_id=admin.buero_id)
    try:
        return await manager.create(data, safe=True)
    except exceptions.UserAlreadyExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "USER_ALREADY_EXISTS") from None
    except exceptions.InvalidPasswordException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_PASSWORD") from None


async def _passwort_pruefen(manager: UserManager, password: str) -> None:
    try:
        await manager.validate_password(password, None)
    except exceptions.InvalidPasswordException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_PASSWORD") from None


@admin_router.post(
    "/einladungen", response_model=EinladungRead, status_code=status.HTTP_201_CREATED
)
def create_einladung(
    payload: EinladungCreate,
    background: BackgroundTasks,
    admin: User = Depends(require_buero_admin),
    db: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
) -> object:
    try:
        einladung, mail = svc.erstelle_einladung(db, admin.buero_id, payload.email, payload.rolle)
    except svc.EmailExistiertError:
        raise HTTPException(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_REGISTERED") from None
    except svc.EinladungOffenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "INVITATION_ALREADY_OPEN") from None
    background.add_task(send_safely, mailer, mail)
    return einladung


@admin_router.get("/einladungen", response_model=list[EinladungRead])
def list_einladungen(
    admin: User = Depends(require_buero_admin), db: Session = Depends(get_session)
) -> object:
    return svc.liste_einladungen(db, admin.buero_id)


@admin_router.post(
    "/einladungen/{einladung_id}/erneut",
    response_model=EinladungRead,
    status_code=status.HTTP_201_CREATED,
)
def sende_einladung_erneut(
    einladung_id: uuid.UUID,
    background: BackgroundTasks,
    admin: User = Depends(require_buero_admin),
    db: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
) -> object:
    try:
        ergebnis = svc.sende_einladung_erneut(db, admin.buero_id, einladung_id)
    except svc.EmailExistiertError:
        raise HTTPException(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_REGISTERED") from None
    if ergebnis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    einladung, mail = ergebnis
    background.add_task(send_safely, mailer, mail)
    return einladung


@admin_router.delete("/einladungen/{einladung_id}", status_code=status.HTTP_204_NO_CONTENT)
def widerrufe_einladung(
    einladung_id: uuid.UUID,
    admin: User = Depends(require_buero_admin),
    db: Session = Depends(get_session),
) -> Response:
    if not svc.widerrufe_einladung(db, admin.buero_id, einladung_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _token_fehler(exc: TokenError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, exc.code)


@auth_router.post(
    "/einladung/einloesen", response_model=UserRead, status_code=status.HTTP_201_CREATED
)
async def einladung_einloesen(
    payload: TokenEinloesen,
    manager: UserManager = Depends(get_user_manager),
    db: Session = Depends(get_session),
) -> object:
    await _passwort_pruefen(manager, payload.password)
    try:
        return svc.loese_einladung_ein(db, payload.token, payload.password)
    except TokenError as exc:
        raise _token_fehler(exc) from None
    except svc.EmailExistiertError:
        raise HTTPException(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_REGISTERED") from None


@auth_router.post("/passwort-reset/anfordern", status_code=status.HTTP_202_ACCEPTED)
def reset_anfordern(
    payload: ResetAnfrage,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
) -> dict[str, str]:
    """Antwortet immer gleich, unabhängig davon, ob die E-Mail existiert."""
    mail = svc.erstelle_reset(db, payload.email)
    if mail is not None:
        background.add_task(send_safely, mailer, mail)
    return {"status": "angefordert"}


@auth_router.post("/passwort-reset/einloesen", status_code=status.HTTP_204_NO_CONTENT)
async def reset_einloesen(
    payload: TokenEinloesen,
    manager: UserManager = Depends(get_user_manager),
    db: Session = Depends(get_session),
) -> Response:
    await _passwort_pruefen(manager, payload.password)
    try:
        svc.loese_reset_ein(db, payload.token, payload.password)
    except TokenError as exc:
        raise _token_fehler(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/users", response_model=list[UserRead])
def list_users(
    admin: User = Depends(require_buero_admin), session: Session = Depends(get_session)
) -> list[User]:
    return verwaltung.list_users(session, admin.buero_id)


@admin_router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: User = Depends(require_buero_admin),
    session: Session = Depends(get_session),
) -> User:
    try:
        return verwaltung.update_user(
            session, admin.buero_id, user_id, rolle=payload.rolle, is_active=payload.is_active
        )
    except verwaltung.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden") from None
    except verwaltung.LastAdminError:
        raise HTTPException(status.HTTP_409_CONFLICT, "LAST_ADMIN") from None


@admin_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_buero_admin),
    session: Session = Depends(get_session),
) -> None:
    try:
        verwaltung.delete_user(session, admin.buero_id, user_id)
    except verwaltung.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden") from None
    except verwaltung.LastAdminError:
        raise HTTPException(status.HTTP_409_CONFLICT, "LAST_ADMIN") from None


plattform_router = APIRouter(prefix="/plattform", tags=["plattform"])


def _buero_antwort(session: Session, buero_id: uuid.UUID) -> plattform.BueroUebersicht:
    return next(b for b in plattform.liste_bueros(session) if b.id == buero_id)


@plattform_router.get("/bueros", response_model=list[BueroRead])
def list_bueros(
    _: User = Depends(require_plattform_admin), session: Session = Depends(get_session)
) -> object:
    return plattform.liste_bueros(session)


@plattform_router.get("/abrechnung", response_model=list[BueroNutzungRead])
def abrechnung(
    monat: str,
    _: User = Depends(require_plattform_admin),
    session: Session = Depends(get_session),
) -> object:
    """LLM-Nutzung (Aufrufe, Token, Kosten) je Büro für einen Monat `JJJJ-MM`."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", monat):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monat im Format JJJJ-MM")
    jahr, nr = (int(t) for t in monat.split("-"))
    return [
        BueroNutzungRead(
            buero_id=b.buero_id,
            buero=b.buero,
            aufrufe=b.aufrufe,
            input_tokens=b.input_tokens,
            output_tokens=b.output_tokens,
            kosten_usd=b.kosten_usd,
            modelle=[ModellNutzungRead(**vars(m)) for m in b.modelle],
        )
        for b in monatsauswertung(session, date(jahr, nr, 1))
    ]


@plattform_router.post("/bueros", response_model=BueroRead, status_code=status.HTTP_201_CREATED)
def create_buero(
    payload: BueroCreate,
    background: BackgroundTasks,
    _: User = Depends(require_plattform_admin),
    session: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
) -> object:
    try:
        buero, mail = plattform.lege_buero_an(session, payload.name, payload.admin_email)
    except svc.EmailExistiertError:
        raise HTTPException(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_REGISTERED") from None
    background.add_task(send_safely, mailer, mail)
    return _buero_antwort(session, buero.id)


@plattform_router.patch("/bueros/{buero_id}", response_model=BueroRead)
def update_buero(
    buero_id: uuid.UUID,
    payload: BueroUpdate,
    _: User = Depends(require_plattform_admin),
    session: Session = Depends(get_session),
) -> object:
    try:
        if payload.name is not None:
            plattform.benenne_um(session, buero_id, payload.name)
        if payload.aktiv is not None:
            plattform.setze_aktiv(session, buero_id, payload.aktiv)
    except plattform.BueroNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden") from None
    return _buero_antwort(session, buero_id)
