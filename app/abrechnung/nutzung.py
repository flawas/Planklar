"""Erfassung und Auswertung der LLM-Nutzung pro Büro (Grundlage der Abrechnung).

Erfasst werden nur Modell, Zweck, Token und Kosten, nie Frage, Bild oder Antwort. Jeder Aufruf
wird in einer eigenen, sofort committeten Transaktion gespeichert; so bleibt der Verbrauch auch
dann erhalten, wenn der Prüflauf später zurückgerollt wird oder abbricht.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Buero
from app.db.rls import INFO_KEY
from app.db.session import get_sessionmaker
from app.dossiers.scope import BueroScope
from app.pipeline.llm import Verbrauch, nutzung_senke


@contextmanager
def nutzung_erfassen(buero_id: uuid.UUID, pruefung_id: uuid.UUID | None = None) -> Iterator[None]:
    """Bucht alle LLM-Aufrufe im Block auf das Büro (und optional den Prüflauf)."""

    def senke(zweck: str, modell: str, verbrauch: Verbrauch) -> None:
        with get_sessionmaker()() as session:
            BueroScope(session, buero_id).add_llm_nutzung(
                pruefung_id=pruefung_id,
                zweck=zweck,
                modell=modell,
                input_tokens=verbrauch.input_tokens,
                output_tokens=verbrauch.output_tokens,
                kosten_usd=verbrauch.kosten_usd,
            )
            session.commit()

    with nutzung_senke(senke):
        yield


@dataclass(frozen=True)
class ModellNutzung:
    modell: str
    aufrufe: int
    input_tokens: int
    output_tokens: int
    kosten_usd: Decimal
    ohne_preis: int  # Aufrufe ohne bekannten Preis; Summe ist dann eine Untergrenze


@dataclass(frozen=True)
class BueroNutzung:
    buero_id: uuid.UUID
    buero: str
    modelle: list[ModellNutzung]

    @property
    def aufrufe(self) -> int:
        return sum(m.aufrufe for m in self.modelle)

    @property
    def input_tokens(self) -> int:
        return sum(m.input_tokens for m in self.modelle)

    @property
    def output_tokens(self) -> int:
        return sum(m.output_tokens for m in self.modelle)

    @property
    def kosten_usd(self) -> Decimal:
        return sum((m.kosten_usd for m in self.modelle), Decimal(0))


def monatsgrenzen(monat: date) -> tuple[datetime, datetime]:
    """[Beginn, Beginn des Folgemonats) in UTC."""
    von = datetime(monat.year, monat.month, 1, tzinfo=UTC)
    bis = datetime(monat.year + monat.month // 12, monat.month % 12 + 1, 1, tzinfo=UTC)
    return von, bis


def nutzung_je_modell(scope: BueroScope, von: datetime, bis: datetime) -> list[ModellNutzung]:
    return [
        ModellNutzung(
            modell=z.modell,
            aufrufe=z.aufrufe,
            input_tokens=int(z.input_tokens or 0),
            output_tokens=int(z.output_tokens or 0),
            kosten_usd=z.kosten_usd or Decimal(0),
            ohne_preis=z.ohne_preis,
        )
        for z in scope.llm_nutzung_summen(von, bis)
    ]


def monatsauswertung(session: Session, monat: date) -> list[BueroNutzung]:
    """Verbrauch aller Büros im Monat (Plattform-Admin); je Büro unter dessen RLS-Kontext."""
    von, bis = monatsgrenzen(monat)
    bueros = session.execute(select(Buero.id, Buero.name).order_by(Buero.name)).all()
    ergebnis = [
        BueroNutzung(buero_id, name, nutzung_je_modell(BueroScope(session, buero_id), von, bis))
        for buero_id, name in bueros
    ]
    session.info.pop(INFO_KEY, None)  # Plattform-Session bleibt an kein Büro gebunden
    session.rollback()
    return ergebnis
