"""Feste Plantyp-Liste und Text-Heuristik für die Seitenklassifikation."""

import re
from dataclasses import dataclass
from enum import StrEnum


class Plantyp(StrEnum):
    BAUGESUCHSFORMULAR = "Baugesuchsformular"
    SITUATIONSPLAN = "Situationsplan"
    GRUNDRISS = "Grundriss"
    SCHNITT = "Schnitt"
    FASSADE_ANSICHT = "Fassade/Ansicht"
    UMGEBUNGSPLAN = "Umgebungsplan"
    ENTWAESSERUNGSPLAN = "Entwässerungsplan"
    KATASTERPLAN = "Katasterplan"
    GRUNDBUCHAUSZUG = "Grundbuchauszug"
    BAUBESCHRIEB = "Baubeschrieb"
    ENERGIENACHWEIS = "Energienachweis"
    DEKLARATION_ERDBEBENSICHERHEIT = "Deklaration Erdbebensicherheit"
    SONSTIGES = "Sonstiges"


# Muster je Plantyp (auf kleingeschriebenem Text). Bewusst eng gehalten.
_PATTERNS: dict[Plantyp, tuple[re.Pattern[str], ...]] = {
    Plantyp.BAUGESUCHSFORMULAR: (re.compile(r"\bbaugesuch(s)?(formular)?\b"),),
    Plantyp.SITUATIONSPLAN: (
        re.compile(r"\bsituation(s)?(plan)?\b"),
        re.compile(r"\bsituation\s*1\s*:\s*\d+"),
    ),
    Plantyp.GRUNDRISS: (re.compile(r"\bgrundriss(e)?\b"),),
    Plantyp.SCHNITT: (re.compile(r"\bschnitt(e)?\b"),),
    Plantyp.FASSADE_ANSICHT: (re.compile(r"\bfassade(n)?\b"), re.compile(r"\bansicht(en)?\b")),
    Plantyp.UMGEBUNGSPLAN: (re.compile(r"\bumgebung(s)?(plan|gestaltung)?\b"),),
    Plantyp.ENTWAESSERUNGSPLAN: (
        re.compile(r"\bentwässerung(s)?(plan)?\b"),
        re.compile(r"\bkanalisation(s)?(plan)?\b"),
    ),
    Plantyp.KATASTERPLAN: (
        re.compile(r"\bkataster(plan)?\b"),
        re.compile(r"\bamtliche vermessung\b"),
    ),
    Plantyp.GRUNDBUCHAUSZUG: (re.compile(r"\bgrundbuchauszug\b"),),
    Plantyp.BAUBESCHRIEB: (re.compile(r"\bbaubeschrieb\b"), re.compile(r"\bbaubeschreibung\b")),
    Plantyp.ENERGIENACHWEIS: (re.compile(r"\benergienachweis\b"),),
    Plantyp.DEKLARATION_ERDBEBENSICHERHEIT: (re.compile(r"\berdbeben(sicherheit)?\b"),),
}

# Ergebnis, wenn genau ein Typ passt: Basis plus Zuschlag je weiteren Treffer.
_CONFIDENCE_SINGLE = 0.8
_CONFIDENCE_MULTI_PATTERN = 0.9
# Mehrere Typen treffen: niedrige Konfidenz, damit das Vision-Modell entscheidet.
_CONFIDENCE_AMBIGUOUS = 0.3


@dataclass(frozen=True)
class Klassifikation:
    plantyp: Plantyp
    konfidenz: float  # 0.0 bis 1.0
    kandidaten: tuple[Plantyp, ...] = ()


def classify_text(text: str) -> Klassifikation:
    """Heuristik über Textlayer/Plankopf. Entscheidet nie allein: niedrige Konfidenz
    bei Mehrdeutigkeit, ``Sonstiges`` mit 0.0 ohne Treffer."""
    lowered = text.lower()
    hits = [typ for typ, patterns in _PATTERNS.items() if any(p.search(lowered) for p in patterns)]
    if not hits:
        return Klassifikation(Plantyp.SONSTIGES, 0.0)
    if len(hits) > 1:
        return Klassifikation(hits[0], _CONFIDENCE_AMBIGUOUS, tuple(hits))
    typ = hits[0]
    matched = sum(1 for p in _PATTERNS[typ] if p.search(lowered))
    confidence = _CONFIDENCE_MULTI_PATTERN if matched > 1 else _CONFIDENCE_SINGLE
    return Klassifikation(typ, confidence, (typ,))
