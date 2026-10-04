"""Mandantentrennung: der einzige erlaubte Zugriffspfad auf Dossier, Dokument und Seite.

Jede Abfrage ist an ein Büro gebunden. Fremde Objekte sind nicht von nicht
vorhandenen zu unterscheiden (`NotFoundError`, in der Web-Schicht 404).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.users import current_user
from app.db.models import Befund, Dokument, Dossier, Ergebnis, Pruefung, Seite, User
from app.db.session import get_session


class NotFoundError(LookupError):
    """Objekt existiert nicht oder gehört einem anderen Büro."""


class BueroScope:
    def __init__(self, session: Session, buero_id: uuid.UUID) -> None:
        self.session = session
        self.buero_id = buero_id

    # Dossier
    def list_dossiers(self) -> Sequence[Dossier]:
        stmt = select(Dossier).where(Dossier.buero_id == self.buero_id)
        return self.session.scalars(stmt.order_by(Dossier.created_at)).all()

    def get_dossier(self, dossier_id: uuid.UUID) -> Dossier:
        stmt = select(Dossier).where(Dossier.id == dossier_id, Dossier.buero_id == self.buero_id)
        dossier = self.session.scalars(stmt).one_or_none()
        if dossier is None:
            raise NotFoundError
        return dossier

    def add_dossier(self, **fields: Any) -> Dossier:
        """Legt ein Dossier im eigenen Büro an; `buero_id` kann nicht überschrieben werden."""
        fields.pop("buero_id", None)
        dossier = Dossier(buero_id=self.buero_id, **fields)
        self.session.add(dossier)
        self.session.flush()
        return dossier

    def update_dossier(self, dossier_id: uuid.UUID, **fields: Any) -> Dossier:
        fields.pop("buero_id", None)
        fields.pop("id", None)
        dossier = self.get_dossier(dossier_id)
        for key, value in fields.items():
            setattr(dossier, key, value)
        self.session.flush()
        return dossier

    def delete_dossier(self, dossier_id: uuid.UUID) -> None:
        self.session.delete(self.get_dossier(dossier_id))
        self.session.flush()

    # Dokument
    def list_dokumente(self, dossier_id: uuid.UUID) -> Sequence[Dokument]:
        self.get_dossier(dossier_id)
        stmt = select(Dokument).where(Dokument.dossier_id == dossier_id)
        return self.session.scalars(stmt.order_by(Dokument.created_at)).all()

    def get_dokument(self, dokument_id: uuid.UUID) -> Dokument:
        stmt = (
            select(Dokument)
            .join(Dossier, Dokument.dossier_id == Dossier.id)
            .where(Dokument.id == dokument_id, Dossier.buero_id == self.buero_id)
        )
        dokument = self.session.scalars(stmt).one_or_none()
        if dokument is None:
            raise NotFoundError
        return dokument

    def add_dokument(self, dossier_id: uuid.UUID, **fields: Any) -> Dokument:
        fields.pop("dossier_id", None)
        self.get_dossier(dossier_id)
        dokument = Dokument(dossier_id=dossier_id, **fields)
        self.session.add(dokument)
        self.session.flush()
        return dokument

    def delete_dokument(self, dokument_id: uuid.UUID) -> None:
        self.session.delete(self.get_dokument(dokument_id))
        self.session.flush()

    # Seite
    def list_seiten(self, dokument_id: uuid.UUID) -> Sequence[Seite]:
        self.get_dokument(dokument_id)
        stmt = select(Seite).where(Seite.dokument_id == dokument_id).order_by(Seite.nummer)
        return self.session.scalars(stmt).all()

    def get_seite(self, seite_id: uuid.UUID) -> Seite:
        stmt = (
            select(Seite)
            .join(Dokument, Seite.dokument_id == Dokument.id)
            .join(Dossier, Dokument.dossier_id == Dossier.id)
            .where(Seite.id == seite_id, Dossier.buero_id == self.buero_id)
        )
        seite = self.session.scalars(stmt).one_or_none()
        if seite is None:
            raise NotFoundError
        return seite

    def update_seite(self, seite_id: uuid.UUID, **fields: Any) -> Seite:
        fields.pop("id", None)
        fields.pop("dokument_id", None)
        seite = self.get_seite(seite_id)
        for key, value in fields.items():
            setattr(seite, key, value)
        self.session.flush()
        return seite

    # Prüflauf
    def list_pruefungen(self, dossier_id: uuid.UUID) -> Sequence[Pruefung]:
        self.get_dossier(dossier_id)
        stmt = select(Pruefung).where(Pruefung.dossier_id == dossier_id)
        return self.session.scalars(stmt.order_by(Pruefung.gestartet_am)).all()

    def get_pruefung(self, pruefung_id: uuid.UUID) -> Pruefung:
        stmt = (
            select(Pruefung)
            .join(Dossier, Pruefung.dossier_id == Dossier.id)
            .where(Pruefung.id == pruefung_id, Dossier.buero_id == self.buero_id)
        )
        pruefung = self.session.scalars(stmt).one_or_none()
        if pruefung is None:
            raise NotFoundError
        return pruefung

    def add_pruefung(
        self, dossier_id: uuid.UUID, *, regelset_hash: str, modellversion: str
    ) -> Pruefung:
        """Startet einen Prüflauf; Regelset-Hash und Modellversion sind Pflicht."""
        self.get_dossier(dossier_id)
        pruefung = Pruefung(
            dossier_id=dossier_id, regelset_hash=regelset_hash, modellversion=modellversion
        )
        self.session.add(pruefung)
        self.session.flush()
        return pruefung

    # Befund
    def list_befunde(self, pruefung_id: uuid.UUID) -> Sequence[Befund]:
        self.get_pruefung(pruefung_id)
        stmt = select(Befund).where(Befund.pruefung_id == pruefung_id).order_by(Befund.regel_id)
        return self.session.scalars(stmt).all()

    def get_befund(self, befund_id: uuid.UUID) -> Befund:
        stmt = (
            select(Befund)
            .join(Pruefung, Befund.pruefung_id == Pruefung.id)
            .join(Dossier, Pruefung.dossier_id == Dossier.id)
            .where(Befund.id == befund_id, Dossier.buero_id == self.buero_id)
        )
        befund = self.session.scalars(stmt).one_or_none()
        if befund is None:
            raise NotFoundError
        return befund

    def add_befund(
        self,
        pruefung_id: uuid.UUID,
        *,
        regel_id: str,
        ergebnis: Ergebnis,
        belege: list[str] | None = None,
    ) -> Befund:
        self.get_pruefung(pruefung_id)
        befund = Befund(
            pruefung_id=pruefung_id, regel_id=regel_id, ergebnis=ergebnis, belege=belege or []
        )
        self.session.add(befund)
        self.session.flush()
        return befund

    def set_override(self, befund_id: uuid.UUID, ergebnis: Ergebnis, begruendung: str) -> Befund:
        if not begruendung.strip():
            raise ValueError("Override braucht eine Begründung")
        befund = self.get_befund(befund_id)
        befund.override_ergebnis = ergebnis
        befund.override_begruendung = begruendung.strip()
        befund.override_am = datetime.now(UTC)
        self.session.flush()
        return befund


def get_scope(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> BueroScope:
    """FastAPI-Dependency: Scope des angemeldeten Users."""
    return BueroScope(session, user.buero_id)


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden")
