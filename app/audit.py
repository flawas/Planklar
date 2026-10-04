"""Audit-Log: hält fest, wer wann was getan hat. Nur IDs und Aktionscodes, nie Inhalte."""

import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditEreignis

LOGIN_OK = "login_erfolg"
LOGIN_FEHLGESCHLAGEN = "login_fehlgeschlagen"
LOGIN_GESPERRT = "login_gesperrt"
USER_ANGELEGT = "user_angelegt"
USER_ROLLE_GEAENDERT = "user_rolle_geaendert"
USER_AKTIVIERT = "user_aktiviert"
USER_DEAKTIVIERT = "user_deaktiviert"
USER_GELOESCHT = "user_geloescht"
PASSWORT_GEAENDERT = "passwort_geaendert"


def protokolliere(
    session: Session,
    aktion: str,
    *,
    buero_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    objekt_typ: str | None = None,
    objekt_id: uuid.UUID | None = None,
) -> None:
    """Fügt das Ereignis der Transaktion hinzu; der Aufrufer committet zusammen mit der Aktion."""
    session.add(
        AuditEreignis(
            buero_id=buero_id,
            user_id=user_id,
            aktion=aktion,
            objekt_typ=objekt_typ,
            objekt_id=objekt_id,
        )
    )
