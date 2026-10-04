"""Bericht eines Prüflaufs als View-Model (ohne HTTP), geteilt von Web-Ansicht und PDF.

Der Bericht zeigt nur, was die Regel-Engine entschieden hat (oder ein Mensch per Override);
er macht keine Bewilligungsaussage.
"""

import uuid
from dataclasses import dataclass, field

from app.db import models as db
from app.dossiers import vorschau
from app.dossiers.scope import BueroScope, NotFoundError
from app.rules.models import Kanton, Regel
from app.rules.resolve import resolve

HINWEIS = "Das Tool gibt Hinweise und entscheidet nichts."

# (Text, Symbol) je Ergebnis: Die Ampel nie nur über Farbe, sondern auch über Text und Symbol.
ANZEIGE: dict[db.Ergebnis, tuple[str, str]] = {
    db.Ergebnis.ERFUELLT: ("Erfüllt", "✓"),
    db.Ergebnis.FEHLT: ("Fehlt", "✗"),
    db.Ergebnis.UNSICHER: ("Unsicher", "?"),
    db.Ergebnis.MANUELL: ("Manuell prüfen", "✎"),
}
REIHENFOLGE = (db.Ergebnis.FEHLT, db.Ergebnis.UNSICHER, db.Ergebnis.MANUELL, db.Ergebnis.ERFUELLT)

MANUELL_BEGRUENDUNG = "Manuell geprüft und bestätigt."


@dataclass(frozen=True)
class Beleg:
    seite_id: uuid.UUID
    dokument: str
    nummer: int
    vorschau_url: str


@dataclass(frozen=True)
class Zeile:
    befund_id: uuid.UUID
    regel_id: str
    titel: str
    schwere: str
    erlass: str
    paragraph: str
    url: str
    stand: str
    original: db.Ergebnis
    ergebnis: db.Ergebnis  # wirksam: Override, sonst Original
    begruendung: str | None
    belege: list[Beleg] = field(default_factory=list)

    @property
    def uebersteuert(self) -> bool:
        return self.ergebnis != self.original or self.begruendung is not None

    @property
    def text(self) -> str:
        return ANZEIGE[self.ergebnis][0]

    @property
    def symbol(self) -> str:
        return ANZEIGE[self.ergebnis][1]

    @property
    def original_text(self) -> str:
        return ANZEIGE[self.original][0]


@dataclass(frozen=True)
class Bericht:
    pruefung: db.Pruefung
    dossier: db.Dossier
    zeilen: list[Zeile]
    zaehler: list[tuple[db.Ergebnis, str, str, int]]  # (Ergebnis, Text, Symbol, Anzahl)
    regelset_abweichend: bool


def _regeln(dossier: db.Dossier) -> tuple[dict[str, Regel], str | None]:
    try:
        regelset = resolve(Kanton(dossier.kanton.value), dossier.gemeinde)
    except Exception:  # fehlender Katalog: Bericht bleibt mit Regel-IDs lesbar
        return {}, None
    return {r.id: r for r in regelset.regeln}, regelset.hash


def _belege(scope: BueroScope, seite_ids: list[str]) -> list[Beleg]:
    result: list[Beleg] = []
    for raw in seite_ids:
        try:
            seite = scope.get_seite(uuid.UUID(raw))
            dok = scope.get_dokument(seite.dokument_id)
        except (ValueError, NotFoundError):
            continue
        result.append(
            Beleg(
                seite.id, dok.dateiname, seite.nummer, vorschau.url_fuer(scope.buero_id, seite.id)
            )
        )
    return result


def baue_bericht(scope: BueroScope, pruefung_id: uuid.UUID) -> Bericht:
    pruefung = scope.get_pruefung(pruefung_id)
    dossier = pruefung.dossier
    regeln, aktueller_hash = _regeln(dossier)
    zeilen: list[Zeile] = []
    for b in scope.list_befunde(pruefung_id):
        regel = regeln.get(b.regel_id)
        zeilen.append(
            Zeile(
                befund_id=b.id,
                regel_id=b.regel_id,
                titel=regel.titel if regel else b.regel_id,
                schwere=regel.schwere.value if regel else "",
                erlass=regel.quelle.erlass if regel else "",
                paragraph=regel.quelle.paragraph if regel else "",
                url=regel.quelle.url if regel else "",
                stand=regel.stand.isoformat() if regel else "",
                original=b.ergebnis,
                ergebnis=b.override_ergebnis or b.ergebnis,
                begruendung=b.override_begruendung,
                belege=_belege(scope, b.belege),
            )
        )
    zeilen.sort(key=lambda z: (REIHENFOLGE.index(z.ergebnis), z.regel_id))
    zaehler = [
        (e, ANZEIGE[e][0], ANZEIGE[e][1], sum(1 for z in zeilen if z.ergebnis == e))
        for e in REIHENFOLGE
    ]
    return Bericht(
        pruefung=pruefung,
        dossier=dossier,
        zeilen=zeilen,
        zaehler=zaehler,
        regelset_abweichend=aktueller_hash is not None and aktueller_hash != pruefung.regelset_hash,
    )
