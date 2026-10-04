"""Anwendbarkeit von Regeln: `when` (JSON Logic) gegen die Vorhabens-Attribute."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from json_logic import jsonLogic
from pydantic import BaseModel, ConfigDict

from app.rules.models import Regel
from app.rules.resolve import Regelset


class Anwendbarkeit(StrEnum):
    ANWENDBAR = "anwendbar"
    NICHT_ANWENDBAR = "nicht_anwendbar"
    UNBEKANNT = "unbekannt"


class Bewertung(BaseModel):
    """Anwendbarkeit einer Regel; bei `unbekannt` mit den fehlenden Variablen."""

    model_config = ConfigDict(frozen=True)

    regel: Regel
    anwendbarkeit: Anwendbarkeit
    fehlende_variablen: tuple[str, ...] = ()


def used_variables(logic: Any) -> frozenset[str]:
    """Alle Variablen ohne Default, die ein JSON-Logic-Ausdruck liest."""
    found: set[str] = set()
    if isinstance(logic, Mapping):
        for op, arg in logic.items():
            if op == "var":
                name, has_default = _var_name(arg)
                if name and not has_default:
                    found.add(name)
            found |= used_variables(arg)
    elif isinstance(logic, list | tuple):
        for item in logic:
            found |= used_variables(item)
    return frozenset(found)


def _var_name(arg: Any) -> tuple[str, bool]:
    if isinstance(arg, list | tuple):
        if not arg:
            return "", False
        return str(arg[0]), len(arg) > 1
    return str(arg), False


def _is_missing(name: str, vorhaben: Mapping[str, Any]) -> bool:
    """Punktpfade wie `a.b` werden aufgelöst; `None` gilt als fehlend."""
    current: Any = vorhaben
    for part in name.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return True
        current = current[part]
    return current is None


def bewerte(regel: Regel, vorhaben: Mapping[str, Any]) -> Bewertung:
    """Wertet `when` aus. Fehlende Variablen ergeben `unbekannt`, nie `nicht_anwendbar`."""
    if isinstance(regel.when, bool):
        ok = Anwendbarkeit.ANWENDBAR if regel.when else Anwendbarkeit.NICHT_ANWENDBAR
        return Bewertung(regel=regel, anwendbarkeit=ok)
    fehlend = tuple(sorted(n for n in used_variables(regel.when) if _is_missing(n, vorhaben)))
    if fehlend:
        return Bewertung(
            regel=regel, anwendbarkeit=Anwendbarkeit.UNBEKANNT, fehlende_variablen=fehlend
        )
    ergebnis = jsonLogic(regel.when, dict(vorhaben))
    ok = Anwendbarkeit.ANWENDBAR if ergebnis is True else Anwendbarkeit.NICHT_ANWENDBAR
    return Bewertung(regel=regel, anwendbarkeit=ok)


def applicable_rules(regelset: Regelset, vorhaben: Mapping[str, Any]) -> tuple[Bewertung, ...]:
    """Bewertung aller Regeln (Reihenfolge wie im Regelset); nichts wird still weggelassen.

    Nur ein ausdrücklich wahres Ergebnis gilt als `anwendbar`; unbekannte Regeln
    bleiben mit Markierung enthalten. Rein und deterministisch.
    """
    return tuple(bewerte(r, vorhaben) for r in regelset.regeln)
