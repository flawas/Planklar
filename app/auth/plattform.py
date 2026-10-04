"""Büro-Onboarding durch den Plattform-Admin: ausschliesslich Metadaten (ADR 0005)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import einladung as svc
from app.db.models import Buero, Rolle, User
from app.db.rls import INFO_KEY
from app.dossiers.scope import BueroScope
from app.mail import Mail


class BueroNotFoundError(Exception):
    pass


@dataclass
class BueroUebersicht:
    """Name, Status und Zähler; bewusst keine Dossier- oder Benutzerdaten."""

    id: uuid.UUID
    name: str
    aktiv: bool
    benutzer: int
    dossiers: int


def liste_bueros(session: Session) -> list[BueroUebersicht]:
    zeilen = session.execute(select(User.buero_id, func.count()).group_by(User.buero_id))
    benutzer = {buero_id: anzahl for buero_id, anzahl in zeilen}
    bueros = session.execute(select(Buero).order_by(func.lower(Buero.name))).scalars().all()
    ergebnis = []
    for buero in bueros:
        # Dossier-Zähler nur über BueroScope (RLS-Kontext pro Büro)
        dossiers = BueroScope(session, buero.id).anzahl_dossiers()
        ergebnis.append(
            BueroUebersicht(
                id=buero.id,
                name=buero.name,
                aktiv=buero.aktiv,
                benutzer=benutzer.get(buero.id, 0),
                dossiers=dossiers,
            )
        )
    session.info.pop(INFO_KEY, None)  # Plattform-Session bleibt an kein Büro gebunden
    session.rollback()
    return ergebnis


def _buero_laden(session: Session, buero_id: uuid.UUID) -> Buero:
    buero = session.get(Buero, buero_id)
    if buero is None:
        raise BueroNotFoundError
    return buero


def lege_buero_an(session: Session, name: str, admin_email: str) -> tuple[Buero, Mail]:
    """Legt Büro und Einladung des ersten `buero_admin` in einer Transaktion an.

    `EmailExistiertError`, wenn die Adresse schon ein Konto hat; dann entsteht kein Büro.
    """
    buero = Buero(name=name.strip())
    session.add(buero)
    session.flush()
    try:
        _, mail = svc.erstelle_einladung(session, buero.id, admin_email, Rolle.BUERO_ADMIN)
    except Exception:
        session.rollback()
        raise
    return buero, mail


def benenne_um(session: Session, buero_id: uuid.UUID, name: str) -> Buero:
    buero = _buero_laden(session, buero_id)
    buero.name = name.strip()
    session.commit()
    return buero


def setze_aktiv(session: Session, buero_id: uuid.UUID, aktiv: bool) -> Buero:
    buero = _buero_laden(session, buero_id)
    buero.aktiv = aktiv
    session.commit()
    return buero
