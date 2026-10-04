"""Erwartete Unterlagen eines Dossiers: Regelset auflösen, Anwendbarkeit bewerten (ohne HTTP)."""

from typing import Any

from pydantic import BaseModel

from app.db.models import Dossier
from app.rules.applicability import Anwendbarkeit, applicable_rules
from app.rules.models import Kanton
from app.rules.resolve import resolve


class ErwarteteUnterlage(BaseModel):
    regel_id: str
    titel: str
    dokument: str
    schwere: str
    pruefmethode: str
    anwendbarkeit: Anwendbarkeit
    fehlende_variablen: list[str]
    erlass: str
    paragraph: str
    url: str
    stand: str


class ErwarteteUnterlagen(BaseModel):
    kanton: str
    gemeinde: str
    regelset_hash: str
    unterlagen: list[ErwarteteUnterlage]


def vorhaben_attribute(dossier: Dossier) -> dict[str, Any]:
    """Variablen für `when`: Basisangaben des Dossiers plus gesetzte Attribute."""
    return {
        **dossier.attribute,
        "kanton": dossier.kanton.value,
        "gemeinde": dossier.gemeinde,
        "vorhabenstyp": dossier.vorhabenstyp.value,
    }


def erwartete_unterlagen(dossier: Dossier) -> ErwarteteUnterlagen:
    """Dokument-Regeln des effektiven Regelsets, die anwendbar oder noch unbekannt sind.

    Die Entscheidung liegt ausschliesslich in `app.rules`; nicht anwendbare Regeln fehlen,
    unbekannte bleiben mit den fehlenden Angaben markiert.
    """
    regelset = resolve(Kanton(dossier.kanton.value), dossier.gemeinde)
    unterlagen = [
        ErwarteteUnterlage(
            regel_id=b.regel.id,
            titel=b.regel.titel,
            dokument=str(b.regel.requires.model_extra.get("dokument", b.regel.titel))
            if b.regel.requires.model_extra
            else b.regel.titel,
            schwere=b.regel.schwere.value,
            pruefmethode=b.regel.check.value,
            anwendbarkeit=b.anwendbarkeit,
            fehlende_variablen=list(b.fehlende_variablen),
            erlass=b.regel.quelle.erlass,
            paragraph=b.regel.quelle.paragraph,
            url=b.regel.quelle.url,
            stand=b.regel.stand.isoformat(),
        )
        for b in applicable_rules(regelset, vorhaben_attribute(dossier))
        if b.regel.requires.typ == "dokument" and b.anwendbarkeit != Anwendbarkeit.NICHT_ANWENDBAR
    ]
    return ErwarteteUnterlagen(
        kanton=dossier.kanton.value,
        gemeinde=dossier.gemeinde,
        regelset_hash=regelset.hash,
        unterlagen=unterlagen,
    )
