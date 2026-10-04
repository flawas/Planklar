import uuid
from collections.abc import Iterator
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import BaseUserDatabase
from fastapi_users.jwt import decode_jwt, generate_jwt
from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.auth import login_schutz
from app.config import get_settings
from app.db.models import Rolle, User
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


class LoginGesperrtError(HTTPException):
    def __init__(self, sekunden: int) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "LOGIN_RATE_LIMITED",
            headers={"Retry-After": str(sekunden)},
        )


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # Passwort-Reset und E-Mail-Verifizierung sind nicht exponiert; Tokens bleiben ungenutzt.
    def __init__(self, user_db: SyncSQLAlchemyUserDatabase, ip: str | None = None) -> None:
        super().__init__(user_db)
        self._session = user_db.session
        self._ip = ip

    async def validate_password(self, password: str, user: Any) -> None:
        if len(password) < 10:
            raise exceptions.InvalidPasswordException("Passwort zu kurz (mind. 10 Zeichen)")

    async def authenticate(self, credentials: Any) -> User | None:
        """Wie fastapi-users, verweigert aber Benutzern gesperrter Büros den Login.

        Zählt Fehlversuche je E-Mail und IP und sperrt temporär (`LoginGesperrtError`, 429).
        """
        email = credentials.username
        sekunden = login_schutz.sperre_verbleibend(self._session, email, self._ip)
        if sekunden:
            self._audit_login(audit.LOGIN_GESPERRT, await self.user_db.get_by_email(email))
            raise LoginGesperrtError(sekunden)
        user = await super().authenticate(credentials)
        if user is not None and (not buero_ist_aktiv(user) or not user.is_active):
            user = None
        if user is None:
            login_schutz.fehlversuch_erfassen(self._session, email, self._ip)
            self._audit_login(audit.LOGIN_FEHLGESCHLAGEN, await self.user_db.get_by_email(email))
            return None
        login_schutz.zuruecksetzen(self._session, email)
        return user

    def _audit_login(self, aktion: str, user: User | None) -> None:
        audit.protokolliere(
            self._session,
            aktion,
            buero_id=user.buero_id if user else None,
            user_id=user.id if user else None,
            objekt_typ="user" if user else None,
            objekt_id=user.id if user else None,
        )
        self._session.commit()

    async def on_after_login(
        self, user: User, request: Request | None = None, response: Any = None
    ) -> None:
        self._audit_login(audit.LOGIN_OK, user)


def buero_ist_aktiv(user: User) -> bool:
    """Plattform-Admins bleiben von der Büro-Sperre ausgenommen (Entsperrung)."""
    return user.is_plattform_admin or user.buero.aktiv


def get_user_db(session: Session = Depends(get_session)) -> Iterator[SyncSQLAlchemyUserDatabase]:
    yield SyncSQLAlchemyUserDatabase(session)


def get_user_manager(
    request: Request,
    user_db: SyncSQLAlchemyUserDatabase = Depends(get_user_db),
) -> Iterator[UserManager]:
    yield UserManager(user_db, ip=request.client.host if request.client else None)


def _cookie_transport() -> CookieTransport:
    s = get_settings()
    return CookieTransport(
        cookie_name=COOKIE_NAME,
        cookie_max_age=s.auth_session_seconds,
        cookie_secure=s.auth_cookie_secure,
        cookie_httponly=True,
        cookie_samesite=s.auth_cookie_samesite,
    )


class VersionedJWTStrategy(JWTStrategy[User, uuid.UUID]):
    """JWT mit `session_version` des Benutzers: Erhöhung entwertet alle früheren Tokens."""

    async def write_token(self, user: User) -> str:
        data = {"sub": str(user.id), "aud": self.token_audience, "sv": user.session_version}
        return generate_jwt(data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm)

    async def read_token(
        self, token: str | None, user_manager: BaseUserManager[User, uuid.UUID]
    ) -> User | None:
        if token is None:
            return None
        try:
            data = decode_jwt(
                token, self.decode_key, self.token_audience, algorithms=[self.algorithm]
            )
        except jwt.PyJWTError:
            return None
        user = await super().read_token(token, user_manager)
        if user is None or data.get("sv") != user.session_version:
            return None
        return user


def _jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
    return VersionedJWTStrategy(
        secret=get_auth_secret(), lifetime_seconds=get_settings().auth_session_seconds
    )


cookie_backend = AuthenticationBackend[User, uuid.UUID](
    name="cookie",
    transport=_cookie_transport(),
    get_strategy=_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [cookie_backend])

_active_user = fastapi_users.current_user(active=True)


def current_user(user: User = Depends(_active_user)) -> User:
    """Angemeldeter, aktiver Benutzer eines aktiven Büros (auch für bestehende Sitzungen)."""
    if not buero_ist_aktiv(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user


def require_buero_admin(user: User = Depends(current_user)) -> User:
    if user.rolle != Rolle.BUERO_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return user


def require_plattform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_plattform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return user
