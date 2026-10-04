import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import BaseUserDatabase
from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_session

COOKIE_NAME = "liquet_session"

_password_helper = PasswordHelper()


def hash_password(password: str) -> str:
    return _password_helper.hash(password)


def get_auth_secret() -> str:
    secret = get_settings().auth_secret
    if not secret:
        raise RuntimeError("AUTH_SECRET ist nicht gesetzt")
    return secret


class SyncSQLAlchemyUserDatabase(BaseUserDatabase[User, uuid.UUID]):
    """FastAPI-Users-Adapter auf der synchronen Session von `app.db.session`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def get(self, id: uuid.UUID) -> User | None:
        return self.session.get(User, id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return self.session.execute(stmt).scalar_one_or_none()

    async def create(self, create_dict: dict[str, Any]) -> User:
        user = User(**create_dict)
        self.session.add(user)
        self.session.commit()
        return user

    async def update(self, user: User, update_dict: dict[str, Any]) -> User:
        for key, value in update_dict.items():
            setattr(user, key, value)
        self.session.add(user)
        self.session.commit()
        return user

    async def delete(self, user: User) -> None:
        self.session.delete(user)
        self.session.commit()


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # Passwort-Reset und E-Mail-Verifizierung sind nicht exponiert; Tokens bleiben ungenutzt.
    async def validate_password(self, password: str, user: Any) -> None:
        if len(password) < 10:
            raise exceptions.InvalidPasswordException("Passwort zu kurz (mind. 10 Zeichen)")

    async def on_after_login(
        self, user: User, request: Request | None = None, response: Any = None
    ) -> None:
        return None


def get_user_db(session: Session = Depends(get_session)) -> Iterator[SyncSQLAlchemyUserDatabase]:
    yield SyncSQLAlchemyUserDatabase(session)


def get_user_manager(
    user_db: SyncSQLAlchemyUserDatabase = Depends(get_user_db),
) -> Iterator[UserManager]:
    yield UserManager(user_db)


def _cookie_transport() -> CookieTransport:
    s = get_settings()
    return CookieTransport(
        cookie_name=COOKIE_NAME,
        cookie_max_age=s.auth_session_seconds,
        cookie_secure=s.auth_cookie_secure,
        cookie_httponly=True,
        cookie_samesite=s.auth_cookie_samesite,
    )


def _jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
    return JWTStrategy(
        secret=get_auth_secret(), lifetime_seconds=get_settings().auth_session_seconds
    )


cookie_backend = AuthenticationBackend[User, uuid.UUID](
    name="cookie",
    transport=_cookie_transport(),
    get_strategy=_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [cookie_backend])

current_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
