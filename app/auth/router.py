import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi_users import exceptions
from sqlalchemy.orm import Session

from app.auth import einladung as svc
from app.auth.schemas import (
    AdminUserCreate,
    EinladungCreate,
    EinladungRead,
    ResetAnfrage,
    TokenEinloesen,
    UserCreate,
    UserRead,
)
from app.auth.tokens import TokenError
from app.auth.users import (
    UserManager,
    cookie_backend,
    current_user,
    fastapi_users,
    get_user_manager,
    require_buero_admin,
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
    background.add_task(send_safely, mailer, mail)
    return einladung


@admin_router.get("/einladungen", response_model=list[EinladungRead])
def list_einladungen(
    admin: User = Depends(require_buero_admin), db: Session = Depends(get_session)
) -> object:
    return svc.liste_einladungen(db, admin.buero_id)


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
