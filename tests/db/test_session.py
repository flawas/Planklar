from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.session import get_session


def test_get_session_liefert_funktionierende_session(engine: Engine) -> None:
    gen = get_session()
    session = next(gen)
    assert isinstance(session, Session)
    assert session.execute(text("select 1")).scalar() == 1
    gen.close()
