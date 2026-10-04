"""Rolle `liquet_app` und Prüfung, dass die App RLS nicht umgeht (ADR 0005).

`python -m app.db.app_role` läuft nach `alembic upgrade head` mit der Migrations-URL und setzt
Login und Passwort (`DB_APP_PASSWORD`) der Rolle. `rls_umgehbar` prüft die App-Verbindung.
"""

import os

from sqlalchemy import Connection, create_engine, text

from app.config import get_settings

_PRUEFUNG = text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")


def rls_umgehbar(conn: Connection) -> bool:
    """True, wenn `current_user` Superuser ist oder BYPASSRLS hat (RLS wäre wirkungslos)."""
    return bool(conn.scalar(_PRUEFUNG))


def main() -> None:
    settings = get_settings()
    passwort = os.environ.get("DB_APP_PASSWORD", "")
    if not passwort:
        raise SystemExit("DB_APP_PASSWORD fehlt")
    engine = create_engine(settings.migration_database_url or settings.database_url)
    with engine.begin() as conn:
        # ALTER ROLE nimmt keine Bind-Parameter; Literal über quote_literal des Servers.
        literal = conn.scalar(text("SELECT quote_literal(:p)"), {"p": passwort})
        conn.execute(text(f"ALTER ROLE liquet_app LOGIN PASSWORD {literal}"))
    engine.dispose()


if __name__ == "__main__":
    main()
