"""Benutzerverwaltung im Büro: immer auf das Büro des handelnden Admins beschränkt."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db.models import Rolle, User


class UserNotFoundError(Exception):
    """Benutzer existiert nicht oder gehört zu einem anderen Büro."""


class LastAdminError(Exception):
    """Der letzte aktive Büro-Admin darf nicht degradiert, deaktiviert oder gelöscht werden."""


def _audit(
    session: Session, aktion: str, buero_id: uuid.UUID, akteur_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    audit.protokolliere(
        session, aktion, buero_id=buero_id, user_id=akteur_id, objekt_typ="user", objekt_id=user_id
    )


def list_users(session: Session, buero_id: uuid.UUID) -> list[User]:
    stmt = select(User).where(User.buero_id == buero_id).order_by(User.email)
    return list(session.execute(stmt).scalars())


def _ist_aktiver_admin(user: User) -> bool:
    return user.is_active and user.rolle == Rolle.BUERO_ADMIN


def _andere_aktive_admins(session: Session, user: User) -> int:
    stmt = select(func.count()).where(
        User.buero_id == user.buero_id,
        User.id != user.id,
        User.is_active.is_(True),
        User.rolle == Rolle.BUERO_ADMIN,
    )
    return session.execute(stmt).scalar_one()


def _admins_sperren(session: Session, buero_id: uuid.UUID) -> None:
    """Alle Admin-Zeilen des Büros in fester Reihenfolge sperren.

    Nur so serialisieren sich gleichzeitige Änderungen an verschiedenen Admins desselben Büros;
    die feste Reihenfolge verhindert Deadlocks.
    """
    stmt = (
        select(User.id)
        .where(User.buero_id == buero_id, User.rolle == Rolle.BUERO_ADMIN)
        .order_by(User.id)
        .with_for_update()
    )
    session.execute(stmt).all()


def _benutzer_laden(session: Session, buero_id: uuid.UUID, user_id: uuid.UUID) -> User:
    _admins_sperren(session, buero_id)
    user = session.execute(
        select(User).where(User.id == user_id, User.buero_id == buero_id).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        session.rollback()
        raise UserNotFoundError
    return user


def update_user(
    session: Session,
    buero_id: uuid.UUID,
    user_id: uuid.UUID,
    akteur_id: uuid.UUID,
    *,
    rolle: Rolle | None = None,
    is_active: bool | None = None,
) -> User:
    # Admins sperren, damit zwei gleichzeitige Änderungen nicht beide den "letzten" Admin treffen
    user = _benutzer_laden(session, buero_id, user_id)
    neue_rolle = rolle if rolle is not None else user.rolle
    neu_aktiv = is_active if is_active is not None else user.is_active
    bleibt_admin = neu_aktiv and neue_rolle == Rolle.BUERO_ADMIN
    if _ist_aktiver_admin(user) and not bleibt_admin and _andere_aktive_admins(session, user) == 0:
        session.rollback()
        raise LastAdminError
    ereignisse = []
    if neue_rolle != user.rolle:
        ereignisse.append(audit.USER_ROLLE_GEAENDERT)
    if neu_aktiv != user.is_active:
        ereignisse.append(audit.USER_AKTIVIERT if neu_aktiv else audit.USER_DEAKTIVIERT)
    if ereignisse:
        # Bestehende Sitzungen enden bei Rollenwechsel und (De-)Aktivierung
        user.session_version += 1
    user.rolle = neue_rolle
    user.is_active = neu_aktiv
    for aktion in ereignisse:
        _audit(session, aktion, buero_id, akteur_id, user.id)
    session.commit()
    return user


def delete_user(
    session: Session, buero_id: uuid.UUID, user_id: uuid.UUID, akteur_id: uuid.UUID
) -> None:
    user = _benutzer_laden(session, buero_id, user_id)
    if _ist_aktiver_admin(user) and _andere_aktive_admins(session, user) == 0:
        session.rollback()
        raise LastAdminError
    session.delete(user)
    _audit(session, audit.USER_GELOESCHT, buero_id, akteur_id, user_id)
    session.commit()
