"""Prüflauf über alle Pipeline-Schritte (Celery-Task ist nur die dünne Hülle in `app.worker`).

Ablauf: Vorverarbeitung (Text, OCR-Fallback, Formularfelder, Render) -> Klassifikation ->
Merkmalsextraktion -> Regelauswertung. Seiten und Befunde werden gespeichert.

- Wiederholbar: Seiten werden je (Dokument, Nummer) überschrieben, Befunde je Regel
  aktualisiert (manuelle Overrides bleiben erhalten). Ein Retry liefert dasselbe Ergebnis,
  ohne Duplikate.
- Kein paralleler Lauf: ein atomarer Lease-Claim sperrt den Lauf; ein zweiter Start (Redelivery)
  tut nichts, solange die Lease gültig ist.
- Ein Fehler bei einer Seite (oder einem unlesbaren Dokument) stoppt den Lauf nicht: die
  Seite gilt als `Sonstiges` mit Konfidenz 0 bzw. ihre Merkmale als unsicher; der
  stabile Fehlercode steht in `Seite.merkmale["_fehler"]`. Daraus ergibt die Regel-Engine
  `unsicher`, nie `erfüllt`.
- Der Fortschritt (`seiten_fertig` von `seiten_gesamt`) wird nach jeder Seite committet.
- Keine Dokumentinhalte in Logs: nur Prüflauf-ID, Seitennummer und Fehlercode.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.abrechnung.nutzung import nutzung_erfassen
from app.config import get_settings
from app.db import models as db
from app.dossiers.scope import BueroScope
from app.pipeline.classify import VOTES, classify_page
from app.pipeline.formfields import load_field_map, normalize_fields
from app.pipeline.llm import LLMClient
from app.pipeline.merkmale import extract_merkmale, merkmale_fuer
from app.pipeline.plantyp import Plantyp
from app.pipeline.preprocess import PdfContent, preprocess
from app.pipeline.render import RenderedPage, render_pages
from app.rules.applicability import Anwendbarkeit, applicable_rules
from app.rules.befund import Ergebnis, Evidenz, Merkmal, SeitenBefund, pruefe
from app.rules.models import Kanton
from app.rules.resolve import resolve
from app.storage import Storage

log = logging.getLogger(__name__)

FEHLER_DOKUMENT = "DOKUMENT_NICHT_LESBAR"
FEHLER_KLASSIFIKATION = "KLASSIFIKATION_FEHLER"
FEHLER_MERKMALE = "MERKMALE_FEHLER"

# Ein Worker hält den Lauf per Lease; sie wird nach jeder Seite verlängert und verfällt bei Absturz.
LEASE = timedelta(minutes=10)


@dataclass(frozen=True)
class Fortschritt:
    status: db.Pruefstatus
    seiten_gesamt: int
    seiten_fertig: int


def fortschritt(scope: BueroScope, pruefung_id: uuid.UUID) -> Fortschritt:
    p = scope.get_pruefung(pruefung_id)
    return Fortschritt(p.status, p.seiten_gesamt, p.seiten_fertig)


def start_pruefung(scope: BueroScope, dossier_id: uuid.UUID) -> db.Pruefung:
    """Legt einen Prüflauf mit aktuellem Regelset-Hash und konfiguriertem Modell an."""
    dossier = scope.get_dossier(dossier_id)
    regelset = resolve(Kanton(dossier.kanton.value), dossier.gemeinde)
    return scope.add_pruefung(
        dossier_id,
        regelset_hash=regelset.hash,
        modellversion=get_settings().llm_model or "unbekannt",
    )


def _merkmal(eintrag: dict[str, Any]) -> Merkmal:
    """Pipeline-Merkmal -> Evidenz der Engine. Zweifel (Abweichung, unklar) bleibt unsicher."""
    sicher = eintrag.get("status") == "sicher"
    vorhanden = eintrag.get("vorhanden")
    einig = bool(eintrag.get("einstimmig"))
    stimmen = int(eintrag.get("stimmen") or 0)
    if sicher and einig and vorhanden == "nein":
        return Merkmal(wert=False, konfidenz=1.0)
    if sicher and einig and vorhanden == "ja":
        return Merkmal(wert=eintrag.get("wert") or True, konfidenz=min(stimmen / VOTES, 1.0))
    return Merkmal(wert=True, konfidenz=0.0, einig=False)


def _seitenbefund(seite: db.Seite) -> SeitenBefund:
    plantyp = seite.plantyp or Plantyp.SONSTIGES.value
    merkmale = dict(seite.merkmale or {})
    if "_fehler" in merkmale:
        # Seite nicht auswertbar: jedes Merkmal des Typs ist unsicher, nicht "fehlt"
        namen = merkmale_fuer(plantyp)
        eintraege = {n: _merkmal({}) for n in namen}
    else:
        eintraege = {n: _merkmal(e) for n, e in merkmale.items() if not n.startswith("_")}
    return SeitenBefund(
        seite_id=str(seite.id),
        plantyp=plantyp,
        konfidenz=seite.konfidenz or 0.0,
        merkmale=eintraege,
    )


def _verarbeite_seite(
    text: str,
    page: RenderedPage,
    client: LLMClient | None,
    modelle: set[str],
) -> dict[str, Any]:
    """Klassifikation und Merkmale einer Seite; Fehler werden zu Fehlercodes, nie geworfen."""
    try:
        klass = classify_page(text, page.png, client=client)
    except Exception as exc:
        log.warning("Klassifikation fehlgeschlagen (%s)", type(exc).__name__)
        return {
            "plantyp": Plantyp.SONSTIGES.value,
            "konfidenz": 0.0,
            "merkmale": {"_fehler": FEHLER_KLASSIFIKATION},
        }
    try:
        merkmale = extract_merkmale(klass.plantyp, page.png, client=client)
    except Exception as exc:
        log.warning("Merkmalsextraktion fehlgeschlagen (%s)", type(exc).__name__)
        merkmale = {"_fehler": FEHLER_MERKMALE}
    else:
        if merkmale["_meta"]["model"]:
            modelle.add(merkmale["_meta"]["model"])
    return {"plantyp": klass.plantyp.value, "konfidenz": klass.konfidenz, "merkmale": merkmale}


def _verarbeite_dokument(
    scope: BueroScope,
    storage: Storage,
    dossier: db.Dossier,
    dokument: db.Dokument,
    pruefung_id: uuid.UUID,
    canton: str,
    client: LLMClient | None,
    modelle: set[str],
    formularfelder: dict[str, str],
) -> None:
    content: PdfContent | None = None
    pages: list[RenderedPage] = []
    try:
        data = storage.get(dossier.buero_id, dossier.id, dokument.sha256)
        content = preprocess(data)
        pages = render_pages(data)
    except Exception as exc:
        log.warning("Dokument nicht lesbar (%s)", type(exc).__name__)
        content = None
    if content is not None:
        try:
            normalisiert = normalize_fields(content.form_fields, load_field_map(canton))
        except Exception as exc:  # defekte Feldzuordnung stoppt den Lauf nicht
            log.warning("Formularfelder nicht lesbar (%s)", type(exc).__name__)
        else:
            for key, value in normalisiert.values.items():
                if value and not formularfelder.get(key):
                    formularfelder[key] = value

    for nummer in range(1, dokument.seitenzahl + 1):
        seite = scope.get_or_add_seite(dokument.id, nummer)
        if content is None or nummer > len(pages) or nummer > len(content.pages):
            fields: dict[str, Any] = {
                "plantyp": Plantyp.SONSTIGES.value,
                "konfidenz": 0.0,
                "merkmale": {"_fehler": FEHLER_DOKUMENT},
            }
        else:
            fields = _verarbeite_seite(
                content.pages[nummer - 1].text, pages[nummer - 1], client, modelle
            )
        scope.update_seite(seite.id, **fields)
        scope.seite_fertig(pruefung_id, LEASE)
        scope.session.commit()


def run_pruefung(
    scope: BueroScope,
    storage: Storage,
    pruefung_id: uuid.UUID,
    *,
    client: LLMClient | None = None,
) -> db.Pruefung:
    """Führt den Prüflauf aus; wiederholbar (setzt den Fortschritt zurück, Overrides bleiben).

    Hält bereits ein anderer Worker den Lauf, wird er unverändert zurückgegeben.
    """
    pruefung = scope.get_pruefung(pruefung_id)
    if not scope.claim_pruefung(pruefung_id, LEASE):
        scope.session.rollback()
        log.warning("Prüflauf %s läuft bereits, Start ignoriert", pruefung_id)
        return scope.get_pruefung(pruefung_id)
    scope.session.commit()
    dossier = pruefung.dossier
    dokumente = list(scope.list_dokumente(dossier.id))
    scope.update_pruefung(
        pruefung_id,
        status=db.Pruefstatus.LAEUFT,
        beendet_am=None,
        seiten_gesamt=sum(d.seitenzahl for d in dokumente),
        seiten_fertig=0,
    )
    scope.session.commit()

    try:
        regelset = resolve(Kanton(dossier.kanton.value), dossier.gemeinde)
        modelle: set[str] = set()
        formularfelder: dict[str, str] = {}
        canton = dossier.kanton.value
        with nutzung_erfassen(scope.buero_id, pruefung_id):
            for dokument in dokumente:
                _verarbeite_dokument(
                    scope, storage, dossier, dokument, pruefung_id, canton, client, modelle,
                    formularfelder,
                )  # fmt: skip

        seiten = [s for d in dokumente for s in scope.list_seiten(d.id)]
        evidenz = Evidenz(
            seiten=tuple(_seitenbefund(s) for s in seiten), formularfelder=formularfelder
        )
        vorhaben = {
            **dossier.attribute,
            "kanton": dossier.kanton.value,
            "gemeinde": dossier.gemeinde,
            "vorhabenstyp": dossier.vorhabenstyp.value,
        }
        behalten: set[str] = set()
        for bewertung in applicable_rules(regelset, vorhaben):
            if bewertung.anwendbarkeit is Anwendbarkeit.NICHT_ANWENDBAR:
                continue
            if bewertung.anwendbarkeit is Anwendbarkeit.UNBEKANNT:
                ergebnis, belege = Ergebnis.UNSICHER, ()  # Attribute fehlen: nie still weglassen
            else:
                befund = pruefe(bewertung.regel, evidenz)
                ergebnis, belege = befund.ergebnis, befund.seiten
            behalten.add(bewertung.regel.id)
            scope.save_befund(
                pruefung_id,
                regel_id=bewertung.regel.id,
                ergebnis=db.Ergebnis(ergebnis.value),
                belege=list(belege),
            )
        scope.prune_befunde(pruefung_id, behalten)
        scope.release_pruefung(pruefung_id)
        scope.update_pruefung(
            pruefung_id,
            status=db.Pruefstatus.ABGESCHLOSSEN,
            beendet_am=datetime.now(UTC),
            regelset_hash=regelset.hash,
            modellversion=", ".join(sorted(modelle)) or pruefung.modellversion,
        )
    except Exception as exc:
        scope.session.rollback()
        scope.release_pruefung(pruefung_id)
        scope.update_pruefung(
            pruefung_id, status=db.Pruefstatus.FEHLGESCHLAGEN, beendet_am=datetime.now(UTC)
        )
        scope.session.commit()
        log.error("Prüflauf %s fehlgeschlagen (%s)", pruefung_id, type(exc).__name__)
        raise
    scope.session.commit()
    return scope.get_pruefung(pruefung_id)
