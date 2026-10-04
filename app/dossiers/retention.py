"""Aufbewahrung: löscht Dossiers nach `RETENTION_DAYS` in DB und Objektspeicher."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Buero
from app.dossiers.scope import BueroScope
from app.storage import Storage


@dataclass
class LoeschReport:
    """Nur IDs, keine Dateinamen, Gemeinden oder Inhalte."""

    geloescht: list[uuid.UUID] = field(default_factory=list)
    fehlgeschlagen: list[uuid.UUID] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "geloescht": [str(i) for i in self.geloescht],
            "fehlgeschlagen": [str(i) for i in self.fehlgeschlagen],
        }


def loesche_abgelaufene_dossiers(
    session: Session,
    storage: Storage,
    retention_days: int,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> LoeschReport:
    """Löscht abgelaufene Dossiers ohne Evaluations-Einverständnis.

    Objekte zuerst, dann DB: Scheitert die DB, räumt der nächste Lauf idempotent nach.
    Ein Fehler bei einem Dossier stoppt die übrigen nicht.
    """
    grenze = now() - timedelta(days=retention_days)
    report = LoeschReport()
    for buero_id in session.scalars(select(Buero.id)).all():
        scope = BueroScope(session, buero_id)
        for dossier in list(scope.list_abgelaufene_dossiers(grenze)):
            dossier_id = dossier.id
            try:
                for dokument in scope.list_dokumente(dossier_id):
                    storage.delete(buero_id, dossier_id, dokument.sha256)
                scope.delete_dossier(dossier_id)
                session.commit()
            except Exception:  # noqa: BLE001 - Fehlercode statt Inhalt, nächster Lauf wiederholt
                session.rollback()
                report.fehlgeschlagen.append(dossier_id)
            else:
                report.geloescht.append(dossier_id)
    return report
