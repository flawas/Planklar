"""Einladung und Passwort-Reset (Services ohne HTTP-Wissen)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.tokens import (
    EINLADUNG_GUELTIG,
    RESET_GUELTIG,
    TokenError,
    hash_token,
    jetzt,
    neues_token,
    pruefe,
)
from app.auth.users import hash_password
from app.config import get_settings
from app.db.models import Einladung, PasswortReset, Rolle, User
from app.mail import Mail


class EmailExistiertError(Exception):
    pass


def _user_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.lower())
    return db.execute(stmt).scalar_one_or_none()


def erstelle_einladung(
    db: Session, buero_id: uuid.UUID, email: str, rolle: Rolle
) -> tuple[Einladung, Mail]:
    """Legt die Einladung an; offene Einladungen derselben Adresse im Büro werden widerrufen."""
    if _user_by_email(db, email) is not None:
        raise EmailExistiertError
    offene = db.execute(
        select(Einladung).where(
            Einladung.buero_id == buero_id,
            func.lower(Einladung.email) == email.lower(),
            Einladung.used_at.is_(None),
            Einladung.revoked_at.is_(None),
        )
    ).scalars()
    for alt in offene:
        alt.revoked_at = jetzt()
    token, token_hash = neues_token()
    einladung = Einladung(
        buero_id=buero_id,
        email=email.lower(),
        rolle=rolle,
        token_hash=token_hash,
        expires_at=jetzt() + EINLADUNG_GUELTIG,
    )
    db.add(einladung)
    db.commit()
    link = f"{get_settings().app_base_url.rstrip('/')}/einladung/{token}"
    mail = Mail(
        an=einladung.email,
        betreff="Einladung zu Liquet",
        text=(
            "Sie wurden zu Liquet eingeladen.\n\n"
            f"Konto einrichten (7 Tage gültig, einmalig verwendbar): {link}\n"
        ),
    )
    return einladung, mail


def liste_einladungen(db: Session, buero_id: uuid.UUID) -> list[Einladung]:
    stmt = (
        select(Einladung)
        .where(Einladung.buero_id == buero_id)
        .order_by(Einladung.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


def widerrufe_einladung(db: Session, buero_id: uuid.UUID, einladung_id: uuid.UUID) -> bool:
    """False, wenn die Einladung nicht existiert oder zu einem anderen Büro gehört."""
    einladung = db.execute(
        select(Einladung).where(Einladung.id == einladung_id, Einladung.buero_id == buero_id)
    ).scalar_one_or_none()
    if einladung is None:
        return False
    if einladung.used_at is None and einladung.revoked_at is None:
        einladung.revoked_at = jetzt()
        db.commit()
    return True


def loese_einladung_ein(db: Session, token: str, password: str) -> User:
    """Legt den Benutzer an. `TokenError` bei unbekanntem, widerrufenem, benutztem Token."""
    einladung = db.execute(
        select(Einladung).where(Einladung.token_hash == hash_token(token)).with_for_update()
    ).scalar_one_or_none()
    pruefe(einladung)
    assert einladung is not None
    if _user_by_email(db, einladung.email) is not None:
        raise EmailExistiertError
    user = User(
        buero_id=einladung.buero_id,
        email=einladung.email,
        hashed_password=hash_password(password),
        rolle=einladung.rolle,
        is_verified=True,
    )
    einladung.used_at = jetzt()
    db.add(user)
    db.commit()
    return user


def erstelle_reset(db: Session, email: str) -> Mail | None:
    """Liefert die Mail, falls ein aktiver Benutzer existiert; sonst None."""
    user = _user_by_email(db, email)
    if user is None or not user.is_active:
        return None
    token, token_hash = neues_token()
    db.add(
        PasswortReset(user_id=user.id, token_hash=token_hash, expires_at=jetzt() + RESET_GUELTIG)
    )
    db.commit()
    link = f"{get_settings().app_base_url.rstrip('/')}/passwort-reset/{token}"
    return Mail(
        an=user.email,
        betreff="Passwort zurücksetzen bei Liquet",
        text=(
            "Für Ihr Konto wurde ein neues Passwort angefordert.\n\n"
            f"Passwort festlegen (2 Stunden gültig, einmalig verwendbar): {link}\n\n"
            "Falls Sie das nicht waren, ignorieren Sie diese Nachricht.\n"
        ),
    )


def loese_reset_ein(db: Session, token: str, password: str) -> None:
    reset = db.execute(
        select(PasswortReset).where(PasswortReset.token_hash == hash_token(token)).with_for_update()
    ).scalar_one_or_none()
    pruefe(reset)
    assert reset is not None
    user = db.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise TokenError("TOKEN_INVALID")
    user.hashed_password = hash_password(password)
    reset.used_at = jetzt()
    db.commit()
