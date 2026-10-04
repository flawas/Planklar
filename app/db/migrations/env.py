from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.db import models  # noqa: F401  (registriert die Tabellen)
from app.db.base import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    # Eine bereits übergebene Verbindung (Tests) hat Vorrang vor der Konfiguration.
    connection = context.config.attributes.get("connection")
    if connection is None:
        settings = get_settings()
        engine = create_engine(settings.migration_database_url or settings.database_url)
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connection)


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
