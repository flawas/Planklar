"""Legt Büro und Admin-Benutzer an: python -m app.auth.seed <Büro> <E-Mail>

Das Passwort wird aus der Umgebungsvariable SEED_PASSWORD gelesen (nie als Argument).

Nur für die lokale Entwicklung: `python -m app.auth.seed --dev` legt (idempotent) den
Standard-Login admin@liquet.ch / password an. Nie in Produktion verwenden.
"""

import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.users import hash_password
from app.db.models import Buero, Rolle, User
from app.db.session import get_sessionmaker


def seed_admin(session: Session, buero_name: str, email: str, password: str) -> User:
    buero = Buero(name=buero_name)
    user = User(
        buero=buero,
        email=email,
        hashed_password=hash_password(password),
        rolle=Rolle.BUERO_ADMIN,
        is_plattform_admin=True,
        is_verified=True,
    )
    session.add_all([buero, user])
    session.commit()
    return user


DEV_BUERO = "Liquet"
DEV_EMAIL = "admin@liquet.ch"
DEV_PASSWORD = "password"  # noqa: S105 - bewusst, nur lokale Entwicklung


def main() -> None:
    if sys.argv[1:] == ["--dev"]:
        with get_sessionmaker()() as session:
            exists = session.execute(select(User).where(User.email == DEV_EMAIL)).first()
            if exists:
                print(f"{DEV_EMAIL} existiert bereits.")
            else:
                seed_admin(session, DEV_BUERO, DEV_EMAIL, DEV_PASSWORD)
                print(f"{DEV_EMAIL} angelegt.")
        return
    if len(sys.argv) != 3 or not os.environ.get("SEED_PASSWORD"):
        sys.exit("Aufruf: SEED_PASSWORD=... python -m app.auth.seed <Büro> <E-Mail>")
    with get_sessionmaker()() as session:
        seed_admin(session, sys.argv[1], sys.argv[2], os.environ["SEED_PASSWORD"])


if __name__ == "__main__":
    main()
