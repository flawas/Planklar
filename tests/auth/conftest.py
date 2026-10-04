import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.auth.users import hash_password
from app.config import get_settings
from app.db.base import Base
from app.db.models import Buero, Rolle, User
from app.main import app

PASSWORD = "geheim-123"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUTH_SECRET", "test-secret-test-secret-test-secret")
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def make_user(
    db: Session,
    email: str,
    *,
    admin: bool = False,
    plattform: bool = False,
    active: bool = True,
    buero_aktiv: bool = True,
) -> User:
    buero = Buero(name=f"Büro {uuid.uuid4().hex[:6]}", aktiv=buero_aktiv)
    user = User(
        buero=buero,
        email=email,
        hashed_password=hash_password(PASSWORD),
        rolle=Rolle.BUERO_ADMIN if admin else Rolle.MITARBEITER,
        is_plattform_admin=plattform,
        is_active=active,
    )
    db.add_all([buero, user])
    db.commit()
    return user


@pytest.fixture
def client(db: Session) -> TestClient:
    # https, damit der Secure-Cookie vom Test-Client mitgeschickt wird
    return TestClient(app, base_url="https://testserver")
