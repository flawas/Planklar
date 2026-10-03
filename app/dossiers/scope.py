"""Mandantentrennung: der einzige erlaubte Zugriffspfad auf Dossier, Dokument und Seite.

Jede Abfrage ist an ein Büro gebunden. Fremde Objekte sind nicht von nicht
vorhandenen zu unterscheiden (`NotFoundError`, in der Web-Schicht 404).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.users import current_user
from app.db.models import Dokument, Dossier, Seite, User
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


def get_scope(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> BueroScope:
    """FastAPI-Dependency: Scope des angemeldeten Users."""
    return BueroScope(session, user.buero_id)


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden")
