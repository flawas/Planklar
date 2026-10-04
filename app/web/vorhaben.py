"""Vorhaben-Assistent: Schritte, Auswahllisten und Validierung als View-Model (ohne HTTP)."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.db.models import Kanton, Vorhabenstyp
from app.dossiers.schemas import ATTRIBUT_MODELLE, DossierCreate

SCHRITTE = ("Kanton", "Gemeinde", "Vorhabenstyp", "Verfahren", "Angaben")
LETZTER_SCHRITT = len(SCHRITTE)

KANTONE = {Kanton.LU.value: "Luzern", Kanton.SZ.value: "Schwyz"}

# Pilotgemeinden gemäss Implementationsplan (2 pro Kanton).
GEMEINDEN = {
    Kanton.LU.value: ["Luzern", "Weggis"],
    Kanton.SZ.value: ["Küssnacht", "Freienbach"],
}

TYPEN = {
    Vorhabenstyp.NEUBAU_EFH_MFH.value: "Neubau Ein- oder Mehrfamilienhaus",
    Vorhabenstyp.UMBAU_ANBAU.value: "Umbau oder Anbau",
    Vorhabenstyp.HEIZUNGSERSATZ_WAERMEPUMPE.value: "Heizungsersatz, Wärmepumpe",
}

VERFAHREN = {
    "ordentlich": "Ordentliches Baubewilligungsverfahren",
    "vereinfacht": "Vereinfachtes Verfahren",
}

BEZUGSFELDER = {
    "gewaesserbezug": "Gewässerbezug",
    "kantonsstrassenbezug": "Kantonsstrassenbezug",
    "waldbezug": "Waldbezug",
    "ausserhalb_bauzone": "Ausserhalb der Bauzone",
}
ZAHLFELDER = {"gebaeudehoehe_m": "Gebäudehöhe in Metern"}
TEXTFELDER = {"heizsystem": "Heizsystem"}

BASISFELDER = ("kanton", "gemeinde", "vorhabenstyp", "verfahren")
ALLE_ATTRIBUTFELDER = (*BEZUGSFELDER, *ZAHLFELDER, *TEXTFELDER)
ALLE_FELDER = (*BASISFELDER, *ALLE_ATTRIBUTFELDER)

MSG_WAHL = "Bitte treffen Sie eine Auswahl."
MSG_JA_NEIN = "Bitte wählen Sie Ja oder Nein."
MSG_ZAHL = "Bitte geben Sie eine Zahl grösser als 0 und höchstens 200 ein."
MSG_TEXT = "Die Eingabe ist zu lang (höchstens 100 Zeichen)."
MSG_ALLGEMEIN = "Die Angaben sind unvollständig oder ungültig."


@dataclass
class Feld:
    name: str
    label: str
    art: str  # "ja_nein", "zahl", "text"
    wert: str = ""
    fehler: str = ""


@dataclass
class SchrittView:
    """Fertiges View-Model für ein Schritt-Partial."""

    schritt: int
    werte: dict[str, str]
    fehler: dict[str, str] = field(default_factory=dict)
    meldung: str = ""

    @property
    def titel(self) -> str:
        return SCHRITTE[self.schritt - 1]

    @property
    def schritte(self) -> list[tuple[int, str]]:
        return list(enumerate(SCHRITTE, start=1))

    @property
    def letzter(self) -> bool:
        return self.schritt == LETZTER_SCHRITT

    @property
    def optionen(self) -> dict[str, str]:
        if self.schritt == 1:
            return KANTONE
        if self.schritt == 2:
            return {g: g for g in GEMEINDEN.get(self.werte.get("kanton", ""), [])}
        if self.schritt == 3:
            return TYPEN
        return VERFAHREN

    @property
    def feldname(self) -> str:
        return BASISFELDER[self.schritt - 1] if self.schritt <= 4 else ""

    @property
    def felder(self) -> list[Feld]:
        if self.schritt != LETZTER_SCHRITT:
            return []
        typ = self.werte.get("vorhabenstyp", "")
        modell = ATTRIBUT_MODELLE.get(Vorhabenstyp(typ)) if typ in TYPEN else None
        namen = set(modell.model_fields) if modell else set()
        felder: list[Feld] = []
        for name, label in BEZUGSFELDER.items():
            felder.append(Feld(name, label, "ja_nein", self.werte.get(name, "")))
        for name, label in ZAHLFELDER.items():
            if name in namen:
                felder.append(Feld(name, label, "zahl", self.werte.get(name, "")))
        for name, label in TEXTFELDER.items():
            if name in namen:
                felder.append(Feld(name, label, "text", self.werte.get(name, "")))
        for f in felder:
            f.fehler = self.fehler.get(f.name, "")
        return felder

    @property
    def versteckt(self) -> list[tuple[str, str]]:
        """Werte, die nicht im aktuellen Schritt bearbeitet werden, als hidden-Felder."""
        sichtbar = {self.feldname} if self.schritt <= 4 else {f.name for f in self.felder}
        return [(n, self.werte[n]) for n in ALLE_FELDER if self.werte.get(n) and n not in sichtbar]


def bereinigen(form: dict[str, str]) -> dict[str, str]:
    """Nur bekannte Felder, getrimmt; Gemeinde passend zum Kanton."""
    werte = {n: form.get(n, "").strip() for n in ALLE_FELDER if form.get(n, "").strip()}
    if werte.get("gemeinde") not in GEMEINDEN.get(werte.get("kanton", ""), []):
        werte.pop("gemeinde", None)
    return werte


def pruefe_schritt(schritt: int, werte: dict[str, str]) -> dict[str, str]:
    """Fehlermeldungen je Feld für den Schritt; leer = gültig."""
    if schritt <= 4:
        name = BASISFELDER[schritt - 1]
        erlaubt = {
            "kanton": set(KANTONE),
            "gemeinde": set(GEMEINDEN.get(werte.get("kanton", ""), [])),
            "vorhabenstyp": set(TYPEN),
            "verfahren": set(VERFAHREN),
        }[name]
        return {} if werte.get(name) in erlaubt else {name: MSG_WAHL}
    fehler: dict[str, str] = {}
    for name in BEZUGSFELDER:
        if werte.get(name) not in ("ja", "nein"):
            fehler[name] = MSG_JA_NEIN
    zahl = werte.get("gebaeudehoehe_m")
    if zahl:
        try:
            if not 0 < float(zahl.replace(",", ".")) <= 200:
                fehler["gebaeudehoehe_m"] = MSG_ZAHL
        except ValueError:
            fehler["gebaeudehoehe_m"] = MSG_ZAHL
    if len(werte.get("heizsystem", "")) > 100:
        fehler["heizsystem"] = MSG_TEXT
    return fehler


def zu_dossier(werte: dict[str, str]) -> DossierCreate | None:
    """Baut die validierte Eingabe; `None`, wenn das Backend-Schema ablehnt."""
    typ = werte.get("vorhabenstyp", "")
    modell = ATTRIBUT_MODELLE.get(Vorhabenstyp(typ)) if typ in TYPEN else None
    if modell is None:
        return None
    attribute: dict[str, Any] = {"verfahren": werte["verfahren"]}
    for name in BEZUGSFELDER:
        attribute[name] = werte[name] == "ja"
    for name in ZAHLFELDER:
        if name in modell.model_fields and werte.get(name):
            attribute[name] = float(werte[name].replace(",", "."))
    for name in TEXTFELDER:
        if name in modell.model_fields and werte.get(name):
            attribute[name] = werte[name]
    try:
        return DossierCreate(
            kanton=Kanton(werte["kanton"]),
            gemeinde=werte["gemeinde"],
            vorhabenstyp=Vorhabenstyp(typ),
            attribute=attribute,
        )
    except (ValidationError, ValueError, KeyError):
        return None
