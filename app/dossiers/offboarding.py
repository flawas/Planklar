"""Büro-Offboarding (Vertragsende, revDSG): löscht ein Büro samt Dossiers, Objekten und Benutzern.

Objekte zuerst, dann DB: Scheitert ein Schritt, ist der Lauf idempotent wiederholbar.
Aufruf: `python -m app.dossiers.offboarding <buero_id> --bestaetigen`.
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Buero, Einladung, User
from app.dossiers.scope import BueroScope
from app.storage import Storage


class BueroNichtGefundenError(LookupError):
    """Büro existiert nicht (mehr)."""


class PlattformAdminError(ValueError):
    """Das Büro enthält einen Plattform-Admin; er muss zuerst verschoben oder entfernt werden."""


@dataclass
class OffboardingReport:
    """Nur Zähler und IDs, keine Namen, Dateinamen oder Inhalte."""

    buero_id: uuid.UUID
    dossiers: int = 0
    dokumente: int = 0
    benutzer: int = 0
    fehlgeschlagen: list[uuid.UUID] = field(default_factory=list)
    praefix_fehlgeschlagen: bool = False


def loesche_buero(session: Session, storage: Storage, buero_id: uuid.UUID) -> OffboardingReport:
    """Löscht Dossiers (DB und S3), Benutzer und das Büro. Andere Büros bleiben unberührt.

    Scheitert ein Dossier, bleibt das Büro samt Benutzern bestehen (`fehlgeschlagen`);
    ein erneuter Aufruf räumt den Rest ab. Auch Einladungen (E-Mail-Adressen) werden gelöscht;
    Passwort-Resets verschwinden per `ON DELETE CASCADE` mit den Benutzern.

    Bewusst ausserhalb von `BueroScope`: Das ist eine Plattform-Operation (CLI) über das
    Büro selbst. `buero`, `user` und `einladung` haben keine RLS (Migration 0011); die
    mandantengebundenen Daten (Dossier, Dokument, ...) laufen über `BueroScope`.
    """
    if session.get(Buero, buero_id) is None:
        raise BueroNichtGefundenError
    benutzer = session.scalars(select(User).where(User.buero_id == buero_id)).all()
    if any(u.is_plattform_admin for u in benutzer):
        raise PlattformAdminError

    report = OffboardingReport(buero_id=buero_id)
    scope = BueroScope(session, buero_id)
    for dossier in list(scope.list_dossiers()):
        dossier_id = dossier.id
        try:
            dokumente = list(scope.list_dokumente(dossier_id))
            for dokument in dokumente:
                storage.delete(buero_id, dossier_id, dokument.sha256)
            scope.delete_dossier(dossier_id)
            session.commit()
        except Exception:  # noqa: BLE001 - Fehlercode statt Inhalt, Wiederholung räumt nach
            session.rollback()
            report.fehlgeschlagen.append(dossier_id)
        else:
            report.dossiers += 1
            report.dokumente += len(dokumente)
    if report.fehlgeschlagen:
        return report

    # Verwaiste Objekte (ohne Dokument-Zeile) gehören ebenfalls zum Büro-Präfix.
    try:
        storage.delete_buero_prefix(buero_id)
    except Exception:  # noqa: BLE001 - Büro bleibt bestehen, Wiederholung räumt nach
        report.praefix_fehlgeschlagen = True
        return report

    report.benutzer = len(benutzer)
    session.execute(delete(Einladung).where(Einladung.buero_id == buero_id))
    session.execute(delete(User).where(User.buero_id == buero_id))
    session.execute(delete(Buero).where(Buero.id == buero_id))
    session.commit()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Büro samt allen Daten unwiderruflich löschen")
    parser.add_argument("buero_id", type=uuid.UUID)
    parser.add_argument("--bestaetigen", action="store_true", help="Löschung wirklich ausführen")
    args = parser.parse_args(argv)
    if not args.bestaetigen:
        print("Abbruch: ohne --bestaetigen wird nichts gelöscht.", file=sys.stderr)
        return 2

    from app.db.session import get_sessionmaker
    from app.dossiers.service import get_storage

    with get_sessionmaker()() as session:
        try:
            report = loesche_buero(session, get_storage(), args.buero_id)
        except BueroNichtGefundenError:
            print("Fehler: Büro nicht gefunden.", file=sys.stderr)
            return 1
        except PlattformAdminError:
            print("Fehler: Büro enthält einen Plattform-Admin.", file=sys.stderr)
            return 1
    print(
        f"Büro {report.buero_id}: {report.dossiers} Dossiers, {report.dokumente} Dokumente, "
        f"{report.benutzer} Benutzer gelöscht."
    )
    if report.fehlgeschlagen:
        print(f"Fehlgeschlagen (erneut ausführen): {len(report.fehlgeschlagen)} Dossiers")
        return 1
    if report.praefix_fehlgeschlagen:
        print("Fehlgeschlagen (erneut ausführen): Büro-Präfix im Speicher", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
