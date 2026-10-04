"""Büro-Kontext für PostgreSQL Row-Level Security (ADR 0005).

Die Policies vergleichen `buero_id` mit `app.buero_id`. `SET LOCAL` gilt nur für eine
Transaktion; deshalb merkt sich die Session das Büro (`session.info`) und setzt es bei
jedem Transaktionsbeginn neu. Ohne Kontext liefern Abfragen keine Zeilen (fail closed).
"""

import uuid

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction

INFO_KEY = "buero_id"
_SET = text("SELECT set_config('app.buero_id', :buero_id, true)")


def set_buero_kontext(session: Session, buero_id: uuid.UUID) -> None:
    """Bindet die Session an ein Büro (laufende und folgende Transaktionen)."""
    session.info[INFO_KEY] = buero_id
    session.execute(_SET, {"buero_id": str(buero_id)})


@event.listens_for(Session, "after_begin")
def _kontext_setzen(session: Session, _: SessionTransaction, connection: Connection) -> None:
    buero_id = session.info.get(INFO_KEY)
    if buero_id is not None:
        connection.execute(_SET, {"buero_id": str(buero_id)})
