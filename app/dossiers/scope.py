"""Mandantentrennung: der einzige erlaubte Zugriffspfad auf Dossier, Dokument und Seite.

Jede Abfrage ist an ein Büro gebunden. Fremde Objekte sind nicht von nicht
vorhandenen zu unterscheiden (`NotFoundError`, in der Web-Schicht 404).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.users import current_user
from app.db.models import (
    Befund,
    Dokument,
    Dossier,
    Ergebnis,
    LlmNutzung,
    Pruefstatus,
    Pruefung,
    Seite,
    User,
)
from app.db.rls import set_buero_kontext
from app.db.session import get_session


class NotFoundError(LookupError):
    """Objekt existiert nicht oder gehört einem anderen Büro."""


class BueroScope:
    def __init__(self, session: Session, buero_id: uuid.UUID) -> None:
        self.session = session
        self.buero_id = buero_id
        set_buero_kontext(session, buero_id)  # RLS: zweite Schutzschicht neben den Filtern

    # Dossier
    def list_dossiers(self) -> Sequence[Dossier]:
        stmt = select(Dossier).where(Dossier.buero_id == self.buero_id)
        return self.session.scalars(stmt.order_by(Dossier.created_at)).all()

    def anzahl_dossiers(self) -> int:
        """Nur die Anzahl, keine Inhalte (Plattform-Übersicht)."""
        stmt = select(func.count()).select_from(Dossier).where(Dossier.buero_id == self.buero_id)
        return self.session.scalar(stmt) or 0

    def get_dossier(self, dossier_id: uuid.UUID) -> Dossier:
        stmt = select(Dossier).where(Dossier.id == dossier_id, Dossier.buero_id == self.buero_id)
        dossier = self.session.scalars(stmt).one_or_none()
        if dossier is None:
            raise NotFoundError
        return dossier

    def lock_dossier(self, dossier_id: uuid.UUID) -> Dossier:
        """Wie `get_dossier`, sperrt die Zeile aber bis zum Ende der Transaktion (FOR UPDATE)."""
        stmt = (
            select(Dossier)
            .where(Dossier.id == dossier_id, Dossier.buero_id == self.buero_id)
            .with_for_update()
        )
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

    def list_abgelaufene_dossiers(self, vor: datetime) -> Sequence[Dossier]:
        """Dossiers des Büros, vor `vor` angelegt und nicht zur Evaluation freigegeben."""
        stmt = select(Dossier).where(
            Dossier.buero_id == self.buero_id,
            Dossier.created_at < vor,
            Dossier.evaluation_einverstanden.is_(False),
        )
        return self.session.scalars(stmt.order_by(Dossier.created_at)).all()

    def delete_dossier(self, dossier_id: uuid.UUID) -> None:
        """Löscht das Dossier samt Dokumenten, Seiten, Prüfläufen und Befunden (nur DB)."""
        dossier = self.get_dossier(dossier_id)
        for pruefung in self.list_pruefungen(dossier_id):
            self.session.delete(pruefung)
        self.session.delete(dossier)
        self.session.flush()

    # Dokument
    def list_dokumente(self, dossier_id: uuid.UUID) -> Sequence[Dokument]:
        self.get_dossier(dossier_id)
        stmt = select(Dokument).where(Dokument.dossier_id == dossier_id)
        return self.session.scalars(stmt.order_by(Dokument.created_at)).all()

    def hat_dokument(self, dossier_id: uuid.UUID, sha256: str) -> bool:
        self.get_dossier(dossier_id)
        stmt = select(Dokument.id).where(
            Dokument.dossier_id == dossier_id, Dokument.sha256 == sha256
        )
        return self.session.scalar(stmt) is not None

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
        fields.pop("buero_id", None)
        self.get_dossier(dossier_id)
        dokument = Dokument(dossier_id=dossier_id, buero_id=self.buero_id, **fields)
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

    def get_or_add_seite(self, dokument_id: uuid.UUID, nummer: int) -> Seite:
        """Seite (Dokument, Nummer); wird angelegt, falls noch nicht vorhanden."""
        self.get_dokument(dokument_id)
        stmt = select(Seite).where(Seite.dokument_id == dokument_id, Seite.nummer == nummer)
        seite = self.session.scalars(stmt).one_or_none()
        if seite is None:
            seite = Seite(dokument_id=dokument_id, buero_id=self.buero_id, nummer=nummer)
            self.session.add(seite)
            self.session.flush()
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

    def hat_aktiven_lauf(self, dossier_id: uuid.UUID, lease: timedelta) -> bool:
        """Prüft, ob ein Lauf wirklich aktiv ist; verwaiste Läufe werden `fehlgeschlagen`.

        Aktiv ist ein Lauf mit gültiger Lease bzw. ein noch nie geclaimter, jüngerer als `lease`.
        Ein Lauf mit abgelaufener Lease (Worker abgestürzt, Task verloren) blockiert nicht.
        """
        jetzt = datetime.now(UTC)
        aktiv = False
        for p in self.list_pruefungen(dossier_id):
            if p.status != Pruefstatus.LAEUFT:
                continue
            frist = p.lauf_bis or (p.gestartet_am + lease)
            if frist > jetzt:
                aktiv = True
            else:
                p.status = Pruefstatus.FEHLGESCHLAGEN
                p.beendet_am = jetzt
        self.session.flush()
        return aktiv

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
            dossier_id=dossier_id,
            buero_id=self.buero_id,
            regelset_hash=regelset_hash,
            modellversion=modellversion,
        )
        self.session.add(pruefung)
        self.session.flush()
        return pruefung

    def update_pruefung(self, pruefung_id: uuid.UUID, **fields: Any) -> Pruefung:
        fields.pop("id", None)
        fields.pop("dossier_id", None)
        pruefung = self.get_pruefung(pruefung_id)
        for key, value in fields.items():
            setattr(pruefung, key, value)
        self.session.flush()
        return pruefung

    def claim_pruefung(self, pruefung_id: uuid.UUID, lease: timedelta) -> bool:
        """Reserviert den Lauf atomar (Lease); False, wenn ein anderer Worker ihn hält."""
        self.get_pruefung(pruefung_id)
        jetzt = datetime.now(UTC)
        stmt = (
            update(Pruefung)
            .where(
                Pruefung.id == pruefung_id,
                (Pruefung.lauf_bis.is_(None)) | (Pruefung.lauf_bis < jetzt),
            )
            .values(lauf_bis=jetzt + lease)
        )
        claimed = self.session.execute(stmt).rowcount == 1
        self.session.flush()
        return claimed

    def release_pruefung(self, pruefung_id: uuid.UUID) -> None:
        self.get_pruefung(pruefung_id)
        self.session.execute(
            update(Pruefung).where(Pruefung.id == pruefung_id).values(lauf_bis=None)
        )
        self.session.flush()
        self.session.expire_all()

    def seite_fertig(self, pruefung_id: uuid.UUID, lease: timedelta) -> None:
        """Zählt den Fortschritt atomar hoch und verlängert die Lease."""
        self.get_pruefung(pruefung_id)
        self.session.execute(
            update(Pruefung)
            .where(Pruefung.id == pruefung_id)
            .values(seiten_fertig=Pruefung.seiten_fertig + 1, lauf_bis=datetime.now(UTC) + lease)
        )
        self.session.flush()
        self.session.expire_all()

    # Befund
    def save_befund(
        self,
        pruefung_id: uuid.UUID,
        *,
        regel_id: str,
        ergebnis: Ergebnis,
        belege: list[str] | None = None,
    ) -> Befund:
        """Schreibt den Befund je Regel neu; ein vorhandener Override bleibt erhalten."""
        self.get_pruefung(pruefung_id)
        stmt = select(Befund).where(Befund.pruefung_id == pruefung_id, Befund.regel_id == regel_id)
        befund = self.session.scalars(stmt).one_or_none()
        if befund is None:
            return self.add_befund(pruefung_id, regel_id=regel_id, ergebnis=ergebnis, belege=belege)
        befund.ergebnis = ergebnis
        befund.belege = belege or []
        self.session.flush()
        return befund

    def prune_befunde(self, pruefung_id: uuid.UUID, behalten: set[str]) -> None:
        """Entfernt Befunde von Regeln, die im Lauf nicht mehr anwendbar sind."""
        pruefung = self.get_pruefung(pruefung_id)
        for befund in list(pruefung.befunde):
            if befund.regel_id not in behalten:
                pruefung.befunde.remove(befund)
        self.session.flush()

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
            pruefung_id=pruefung_id,
            buero_id=self.buero_id,
            regel_id=regel_id,
            ergebnis=ergebnis,
            belege=belege or [],
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

    def clear_override(self, befund_id: uuid.UUID) -> Befund:
        befund = self.get_befund(befund_id)
        befund.override_ergebnis = None
        befund.override_begruendung = None
        befund.override_am = None
        self.session.flush()
        return befund

    # LLM-Nutzung (Abrechnung)
    def add_llm_nutzung(self, **fields: Any) -> LlmNutzung:
        fields.pop("buero_id", None)
        nutzung = LlmNutzung(buero_id=self.buero_id, **fields)
        self.session.add(nutzung)
        self.session.flush()
        return nutzung

    def llm_nutzung_summen(self, von: datetime, bis: datetime) -> Sequence[Any]:
        """Aufrufe, Token und Kosten je Modell im Zeitraum [von, bis)."""
        stmt = (
            select(
                LlmNutzung.modell,
                func.count().label("aufrufe"),
                func.sum(LlmNutzung.input_tokens).label("input_tokens"),
                func.sum(LlmNutzung.output_tokens).label("output_tokens"),
                func.sum(LlmNutzung.kosten_usd).label("kosten_usd"),
                func.count().filter(LlmNutzung.kosten_usd.is_(None)).label("ohne_preis"),
            )
            .where(
                LlmNutzung.buero_id == self.buero_id,
                LlmNutzung.created_at >= von,
                LlmNutzung.created_at < bis,
            )
            .group_by(LlmNutzung.modell)
            .order_by(LlmNutzung.modell)
        )
        return self.session.execute(stmt).all()


def get_scope(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> BueroScope:
    """FastAPI-Dependency: Scope des angemeldeten Users."""
    return BueroScope(session, user.buero_id)


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden")
