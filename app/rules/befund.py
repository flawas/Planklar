"""Befundlogik: Ergebnis einer Regel pro Prüfmethode aus der vorliegenden Evidenz.

Rein und deterministisch. Im Zweifel nie `erfüllt`: fehlende, widersprüchliche oder
niedrig-konfidente Evidenz ergibt `unsicher` (oder `fehlt`, wenn die Unterlage
nachweislich nicht vorliegt).

Erwartete `requires`-Felder je Prüfmethode:

- `ki_klassifikation`: `dokument` (Plantyp, der vorliegen muss)
- `plan_merkmal`: `merkmal` (Name), optional `dokument` (Plantyp) und `wert` (Sollwert)
- `formularfeld`: `feld` (Name), optional `wert` (Sollwert)
- `manuell`: keine; massgeblich ist die Bestätigung zur Regel-`id`
"""

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.rules.models import Check, Regel


class Ergebnis(StrEnum):
    ERFUELLT = "erfüllt"
    FEHLT = "fehlt"
    UNSICHER = "unsicher"
    MANUELL = "manuell"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Schwellen(_Frozen):
    """Mindestkonfidenz; darunter gilt Evidenz als unsicher."""

    klassifikation: float = Field(default=0.8, ge=0, le=1)
    merkmal: float = Field(default=0.8, ge=0, le=1)


class Merkmal(_Frozen):
    """Extrahiertes Merkmal; `einig=False` bei abweichenden Wiederholungen."""

    wert: Any
    konfidenz: float = Field(ge=0, le=1)
    einig: bool = True


class SeitenBefund(_Frozen):
    seite_id: str
    plantyp: str
    konfidenz: float = Field(ge=0, le=1)
    merkmale: Mapping[str, Merkmal] = Field(default_factory=dict)


class Evidenz(_Frozen):
    """Alles, was einer Prüfung zur Verfügung steht."""

    seiten: tuple[SeitenBefund, ...] = ()
    formularfelder: Mapping[str, Any] = Field(default_factory=dict)
    bestaetigungen: Mapping[str, bool] = Field(default_factory=dict)  # Regel-id -> bestätigt


class Befund(_Frozen):
    regel_id: str
    ergebnis: Ergebnis
    seiten: tuple[str, ...] = ()
    grund: str


def pruefe(regel: Regel, evidenz: Evidenz, schwellen: Schwellen | None = None) -> Befund:
    """Ergebnis einer (anwendbaren) Regel; Unbekanntes ergibt nie `erfüllt`."""
    s = schwellen or Schwellen()
    match regel.check:
        case Check.KI_KLASSIFIKATION:
            return _klassifikation(regel, evidenz, s)
        case Check.PLAN_MERKMAL:
            return _plan_merkmal(regel, evidenz, s)
        case Check.FORMULARFELD:
            return _formularfeld(regel, evidenz)
        case Check.MANUELL:
            return _manuell(regel, evidenz)
    return _befund(regel, Ergebnis.UNSICHER, "Unbekannte Prüfmethode")  # pragma: no cover


def _befund(regel: Regel, ergebnis: Ergebnis, grund: str, seiten: tuple[str, ...] = ()) -> Befund:
    return Befund(regel_id=regel.id, ergebnis=ergebnis, seiten=seiten, grund=grund)


def _param(regel: Regel, name: str) -> Any:
    extra = regel.requires.model_extra or {}
    return extra.get(name)


def _sicher(konfidenz: float, schwelle: float) -> bool:
    return not math.isnan(konfidenz) and konfidenz >= schwelle


def _klassifikation(regel: Regel, evidenz: Evidenz, s: Schwellen) -> Befund:
    dokument = _param(regel, "dokument")
    if not isinstance(dokument, str) or not dokument:
        return _befund(regel, Ergebnis.UNSICHER, "Regel nennt kein Dokument")
    treffer = tuple(p for p in evidenz.seiten if p.plantyp == dokument)
    sicher = tuple(p.seite_id for p in treffer if _sicher(p.konfidenz, s.klassifikation))
    if sicher:
        return _befund(regel, Ergebnis.ERFUELLT, f"{dokument} erkannt", sicher)
    unsichere = tuple(
        p.seite_id
        for p in evidenz.seiten
        if p.plantyp == dokument or not _sicher(p.konfidenz, s.klassifikation)
    )
    if unsichere:
        return _befund(
            regel, Ergebnis.UNSICHER, f"{dokument} nur mit niedriger Konfidenz", unsichere
        )
    return _befund(regel, Ergebnis.FEHLT, f"{dokument} nicht im Dossier")


def _plan_merkmal(regel: Regel, evidenz: Evidenz, s: Schwellen) -> Befund:
    name = _param(regel, "merkmal")
    if not isinstance(name, str) or not name:
        return _befund(regel, Ergebnis.UNSICHER, "Regel nennt kein Merkmal")
    dokument = _param(regel, "dokument")
    if dokument is None:
        seiten = evidenz.seiten
    else:
        seiten = tuple(p for p in evidenz.seiten if p.plantyp == dokument)
        if not seiten:
            unklar = tuple(
                p.seite_id for p in evidenz.seiten if not _sicher(p.konfidenz, s.klassifikation)
            )
            if unklar:
                return _befund(regel, Ergebnis.UNSICHER, "Plantyp nicht sicher erkannt", unklar)
            return _befund(regel, Ergebnis.FEHLT, f"{dokument} nicht im Dossier")
        unsicher_typ = tuple(
            p.seite_id for p in seiten if not _sicher(p.konfidenz, s.klassifikation)
        )
        if unsicher_typ:
            return _befund(regel, Ergebnis.UNSICHER, "Plantyp nicht sicher erkannt", unsicher_typ)
    if not seiten:
        return _befund(regel, Ergebnis.FEHLT, "Keine Planseite im Dossier")

    soll = _param(regel, "wert")
    ok: list[str] = []
    unsicher: list[str] = []
    fehlt: list[str] = []
    for seite in seiten:
        merkmal = seite.merkmale.get(name)
        if merkmal is None or merkmal.wert is None:
            fehlt.append(seite.seite_id)
        elif not merkmal.einig or not _sicher(merkmal.konfidenz, s.merkmal):
            unsicher.append(seite.seite_id)
        elif soll is not None and merkmal.wert != soll:
            fehlt.append(seite.seite_id)
        elif merkmal.wert is False:
            fehlt.append(seite.seite_id)
        else:
            ok.append(seite.seite_id)
    if unsicher:
        return _befund(
            regel, Ergebnis.UNSICHER, f"{name} unsicher oder widersprüchlich", tuple(unsicher)
        )
    if fehlt:
        return _befund(regel, Ergebnis.FEHLT, f"{name} fehlt", tuple(fehlt))
    return _befund(regel, Ergebnis.ERFUELLT, f"{name} vorhanden", tuple(ok))


def _leer(wert: Any) -> bool:
    """Kein Inhalt: None, leerer String, False, 0 oder leere Collection (im Zweifel nie erfüllt)."""
    if isinstance(wert, str):
        return not wert.strip()
    if isinstance(wert, (bool, int, float, list, tuple, dict, set, frozenset)):
        return not wert
    return wert is None


def _formularfeld(regel: Regel, evidenz: Evidenz) -> Befund:
    feld = _param(regel, "feld")
    if not isinstance(feld, str) or not feld:
        return _befund(regel, Ergebnis.UNSICHER, "Regel nennt kein Feld")
    wert = evidenz.formularfelder.get(feld)
    if _leer(wert):
        return _befund(regel, Ergebnis.FEHLT, f"Feld {feld} leer oder nicht vorhanden")
    soll = _param(regel, "wert")
    if soll is not None and wert != soll:
        return _befund(regel, Ergebnis.FEHLT, f"Feld {feld} hat nicht den geforderten Wert")
    return _befund(regel, Ergebnis.ERFUELLT, f"Feld {feld} ausgefüllt")


def _manuell(regel: Regel, evidenz: Evidenz) -> Befund:
    bestaetigt = evidenz.bestaetigungen.get(regel.id)
    if bestaetigt is True:
        return _befund(regel, Ergebnis.ERFUELLT, "Vom Planer bestätigt")
    if bestaetigt is False:
        return _befund(regel, Ergebnis.FEHLT, "Vom Planer verneint")
    return _befund(regel, Ergebnis.MANUELL, "Bestätigung durch den Planer ausstehend")
