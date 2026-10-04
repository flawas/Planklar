import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_users import exceptions
from sqlalchemy.orm import Session

from app import audit
from app.auth import verwaltung
from app.auth.schemas import (
    AdminUserCreate,
    PasswordChange,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.auth.users import (
    UserManager,
    cookie_backend,
    current_user,
    fastapi_users,
    get_user_manager,
    hash_password,
    require_buero_admin,
)
from app.db.models import User
from app.db.session import get_session

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
    # Neue Session-Version: alle bisherigen Sitzungen (auch diese) enden, neu anmelden
    await manager.user_db.update(
        user,
        {
            "hashed_password": hash_password(payload.new_password),
            "session_version": user.session_version + 1,
        },
    )
    audit.protokolliere(
        manager.user_db.session,
        audit.PASSWORT_GEAENDERT,
        buero_id=user.buero_id,
        user_id=user.id,
        objekt_typ="user",
        objekt_id=user.id,
    )
    manager.user_db.session.commit()


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
        user = await manager.create(data, safe=True)
        audit.protokolliere(
            manager.user_db.session,
            audit.USER_ANGELEGT,
            buero_id=admin.buero_id,
            user_id=admin.id,
            objekt_typ="user",
            objekt_id=user.id,
        )
        manager.user_db.session.commit()
        return user
    except exceptions.UserAlreadyExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "USER_ALREADY_EXISTS") from None
    except exceptions.InvalidPasswordException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_PASSWORD") from None


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
            session,
            admin.buero_id,
            user_id,
            admin.id,
            rolle=payload.rolle,
            is_active=payload.is_active,
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
        verwaltung.delete_user(session, admin.buero_id, user_id, admin.id)
    except verwaltung.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden") from None
    except verwaltung.LastAdminError:
        raise HTTPException(status.HTTP_409_CONFLICT, "LAST_ADMIN") from None
