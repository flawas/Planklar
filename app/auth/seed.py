"""Legt Büro und Admin-Benutzer an: python -m app.auth.seed <Büro> <E-Mail>

Das Passwort wird aus der Umgebungsvariable SEED_PASSWORD gelesen (nie als Argument).
"""

import os
import sys

from sqlalchemy.orm import Session

from app.auth.users import hash_password
from app.db.models import Buero, User
from app.db.session import get_sessionmaker


def seed_admin(session: Session, buero_name: str, email: str, password: str) -> User:
    buero = Buero(name=buero_name)
    user = User(
        buero=buero,
        email=email,
        hashed_password=hash_password(password),
        is_superuser=True,
        is_verified=True,
    )
    session.add_all([buero, user])
    session.commit()
    return user


def main() -> None:
    if len(sys.argv) != 3 or not os.environ.get("SEED_PASSWORD"):
        sys.exit("Aufruf: SEED_PASSWORD=... python -m app.auth.seed <Büro> <E-Mail>")
    with get_sessionmaker()() as session:
        seed_admin(session, sys.argv[1], sys.argv[2], os.environ["SEED_PASSWORD"])


if __name__ == "__main__":
    main()
