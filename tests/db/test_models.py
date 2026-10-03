import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Buero, User


@pytest.fixture
def session(engine: Engine):
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with Session(engine) as s:
        yield s


def test_user_gehoert_zu_buero(session: Session) -> None:
    buero = Buero(name="Muster AG")
    session.add(User(email="a@example.org", hashed_password="x", buero=buero))
    session.commit()
    assert buero.users[0].buero_id == buero.id
    assert buero.users[0].is_active is True


def test_user_braucht_buero(session: Session) -> None:
    session.add(User(email="a@example.org", hashed_password="x"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_email_eindeutig(session: Session) -> None:
    buero = Buero(name="Muster AG")
    session.add_all(
        [
            User(email="a@example.org", hashed_password="x", buero=buero),
            User(email="a@example.org", hashed_password="y", buero=buero),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()
