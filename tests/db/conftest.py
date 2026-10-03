from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings


def _reset(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Leere PostgreSQL-Test-DB; verweigert Datenbanken, deren Name nicht auf "test" endet."""
    url = get_settings().database_url
    if not (make_url(url).database or "").endswith("test"):
        pytest.skip("DATABASE_URL zeigt nicht auf eine Test-Datenbank (Name endet auf 'test')")
    engine = create_engine(url)
    _reset(engine)
    yield engine
    _reset(engine)
    engine.dispose()
