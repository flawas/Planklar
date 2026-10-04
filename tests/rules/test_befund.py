from typing import Any

import pytest

from app.rules.befund import (
    Ergebnis,
    Evidenz,
    Merkmal,
    Schwellen,
    SeitenBefund,
    pruefe,
)
from app.rules.models import Regel


def _regel(check: str, **requires: Any) -> Regel:
    return Regel.model_validate(
        {
            "id": "R1",
            "titel": "T",
            "scope": {"kanton": "LU"},
            "when": True,
            "requires": {"typ": "x", **requires},
            "check": check,
            "schwere": "fehlt_blockierend",
            "quelle": {"erlass": "E", "paragraph": "§ 1", "url": "https://example.org"},
            "stand": "2026-01-01",
        }
    )


def _seite(sid: str, plantyp: str, konf: float = 0.95, **merkmale: Merkmal) -> SeitenBefund:
    return SeitenBefund(seite_id=sid, plantyp=plantyp, konfidenz=konf, merkmale=merkmale)


def _m(wert: Any = True, konf: float = 0.95, einig: bool = True) -> Merkmal:
    return Merkmal(wert=wert, konfidenz=konf, einig=einig)


# --- ki_klassifikation ---------------------------------------------------------


def test_klassifikation_erfuellt_mit_seitenreferenz() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    b = pruefe(r, Evidenz(seiten=(_seite("s1", "Grundriss"), _seite("s2", "Schnitt"))))
    assert (b.ergebnis, b.seiten) == (Ergebnis.ERFUELLT, ("s1",))


def test_klassifikation_fehlende_unterlage_nie_erfuellt() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    assert pruefe(r, Evidenz()).ergebnis == Ergebnis.FEHLT
    assert pruefe(r, Evidenz(seiten=(_seite("s1", "Schnitt"),))).ergebnis == Ergebnis.FEHLT


def test_klassifikation_niedrige_konfidenz_unsicher() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    b = pruefe(r, Evidenz(seiten=(_seite("s1", "Grundriss", 0.5),)))
    assert (b.ergebnis, b.seiten) == (Ergebnis.UNSICHER, ("s1",))


def test_klassifikation_unklare_seite_kann_dokument_sein() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    b = pruefe(r, Evidenz(seiten=(_seite("s1", "Sonstiges", 0.3),)))
    assert b.ergebnis == Ergebnis.UNSICHER


def test_klassifikation_schwelle_konfigurierbar() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    e = Evidenz(seiten=(_seite("s1", "Grundriss", 0.7),))
    assert pruefe(r, e).ergebnis == Ergebnis.UNSICHER
    assert pruefe(r, e, Schwellen(klassifikation=0.6)).ergebnis == Ergebnis.ERFUELLT
    assert pruefe(r, e, Schwellen(klassifikation=0.9)).ergebnis == Ergebnis.UNSICHER


def test_klassifikation_ohne_dokument_in_regel_unsicher() -> None:
    assert pruefe(_regel("ki_klassifikation"), Evidenz()).ergebnis == Ergebnis.UNSICHER


def test_nan_konfidenz_nie_erfuellt() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    e = Evidenz(
        seiten=(
            SeitenBefund.model_construct(
                seite_id="s1", plantyp="Grundriss", konfidenz=float("nan"), merkmale={}
            ),
        )
    )
    assert pruefe(r, e).ergebnis == Ergebnis.UNSICHER


# --- plan_merkmal --------------------------------------------------------------


def test_merkmal_erfuellt() -> None:
    r = _regel("plan_merkmal", dokument="Situationsplan", merkmal="nordpfeil")
    e = Evidenz(seiten=(_seite("s1", "Situationsplan", nordpfeil=_m()),))
    b = pruefe(r, e)
    assert (b.ergebnis, b.seiten) == (Ergebnis.ERFUELLT, ("s1",))


def test_merkmal_ohne_plantyp_im_dossier_fehlt() -> None:
    r = _regel("plan_merkmal", dokument="Situationsplan", merkmal="nordpfeil")
    assert pruefe(r, Evidenz()).ergebnis == Ergebnis.FEHLT
    assert pruefe(r, Evidenz(seiten=(_seite("s1", "Schnitt"),))).ergebnis == Ergebnis.FEHLT


def test_merkmal_nicht_vorhanden_oder_verneint_fehlt() -> None:
    r = _regel("plan_merkmal", dokument="Situationsplan", merkmal="nordpfeil")
    assert pruefe(r, Evidenz(seiten=(_seite("s1", "Situationsplan"),))).ergebnis == Ergebnis.FEHLT
    e = Evidenz(seiten=(_seite("s1", "Situationsplan", nordpfeil=_m(False)),))
    assert pruefe(r, e).ergebnis == Ergebnis.FEHLT


@pytest.mark.parametrize("merkmal", [_m(konf=0.4), _m(einig=False)])
def test_merkmal_unsicher_bei_niedriger_konfidenz_oder_abweichung(merkmal: Merkmal) -> None:
    r = _regel("plan_merkmal", dokument="Situationsplan", merkmal="nordpfeil")
    e = Evidenz(seiten=(_seite("s1", "Situationsplan", nordpfeil=merkmal),))
    assert pruefe(r, e).ergebnis == Ergebnis.UNSICHER


def test_merkmal_unsicherer_plantyp_unsicher() -> None:
    r = _regel("plan_merkmal", dokument="Situationsplan", merkmal="nordpfeil")
    e = Evidenz(seiten=(_seite("s1", "Situationsplan", 0.4, nordpfeil=_m()),))
    assert pruefe(r, e).ergebnis == Ergebnis.UNSICHER


def test_merkmal_sollwert() -> None:
    r = _regel("plan_merkmal", dokument="Situationsplan", merkmal="massstab", wert="1:500")
    gut = Evidenz(seiten=(_seite("s1", "Situationsplan", massstab=_m("1:500")),))
    falsch = Evidenz(seiten=(_seite("s1", "Situationsplan", massstab=_m("1:100")),))
    assert pruefe(r, gut).ergebnis == Ergebnis.ERFUELLT
    assert pruefe(r, falsch).ergebnis == Ergebnis.FEHLT


def test_merkmal_mehrere_seiten_erfuellt_nur_wenn_alle_ok() -> None:
    r = _regel("plan_merkmal", dokument="Grundriss", merkmal="massstab")
    ok = _seite("s1", "Grundriss", massstab=_m("1:100"))
    luecke = _seite("s2", "Grundriss")
    unklar = _seite("s3", "Grundriss", massstab=_m(konf=0.2))
    assert pruefe(r, Evidenz(seiten=(ok,))).ergebnis == Ergebnis.ERFUELLT
    b = pruefe(r, Evidenz(seiten=(ok, luecke)))
    assert (b.ergebnis, b.seiten) == (Ergebnis.FEHLT, ("s2",))
    assert pruefe(r, Evidenz(seiten=(ok, luecke, unklar))).ergebnis == Ergebnis.UNSICHER


def test_merkmal_schwelle_konfigurierbar() -> None:
    r = _regel("plan_merkmal", dokument="Grundriss", merkmal="massstab")
    e = Evidenz(seiten=(_seite("s1", "Grundriss", massstab=_m(konf=0.7)),))
    assert pruefe(r, e).ergebnis == Ergebnis.UNSICHER
    assert pruefe(r, e, Schwellen(merkmal=0.6)).ergebnis == Ergebnis.ERFUELLT


def test_merkmal_ohne_name_unsicher() -> None:
    assert pruefe(_regel("plan_merkmal"), Evidenz()).ergebnis == Ergebnis.UNSICHER


# --- formularfeld --------------------------------------------------------------


def test_formularfeld() -> None:
    r = _regel("formularfeld", feld="bauherr")
    assert pruefe(r, Evidenz(formularfelder={"bauherr": "Muster AG"})).ergebnis == Ergebnis.ERFUELLT
    assert pruefe(r, Evidenz()).ergebnis == Ergebnis.FEHLT
    assert pruefe(r, Evidenz(formularfelder={"bauherr": "  "})).ergebnis == Ergebnis.FEHLT
    assert pruefe(r, Evidenz(formularfelder={"bauherr": None})).ergebnis == Ergebnis.FEHLT


@pytest.mark.parametrize("wert", [None, "", "  ", False, 0, 0.0, [], {}, ()])
def test_formularfeld_leere_werte_fehlen(wert: Any) -> None:
    r = _regel("formularfeld", feld="x")
    assert pruefe(r, Evidenz(formularfelder={"x": wert})).ergebnis == Ergebnis.FEHLT


@pytest.mark.parametrize("wert", [True, 1, "a", ["a"], {"k": 1}])
def test_formularfeld_gefuellte_werte_erfuellt(wert: Any) -> None:
    r = _regel("formularfeld", feld="x")
    assert pruefe(r, Evidenz(formularfelder={"x": wert})).ergebnis == Ergebnis.ERFUELLT


def test_formularfeld_sollwert_und_ohne_feld() -> None:
    r = _regel("formularfeld", feld="heizung", wert="waermepumpe")
    assert pruefe(r, Evidenz(formularfelder={"heizung": "oel"})).ergebnis == Ergebnis.FEHLT
    assert (
        pruefe(r, Evidenz(formularfelder={"heizung": "waermepumpe"})).ergebnis == Ergebnis.ERFUELLT
    )
    assert pruefe(_regel("formularfeld"), Evidenz()).ergebnis == Ergebnis.UNSICHER


# --- manuell -------------------------------------------------------------------


def test_manuell() -> None:
    r = _regel("manuell")
    assert pruefe(r, Evidenz()).ergebnis == Ergebnis.MANUELL
    assert pruefe(r, Evidenz(bestaetigungen={"R1": True})).ergebnis == Ergebnis.ERFUELLT
    assert pruefe(r, Evidenz(bestaetigungen={"R1": False})).ergebnis == Ergebnis.FEHLT
    assert pruefe(r, Evidenz(bestaetigungen={"R2": True})).ergebnis == Ergebnis.MANUELL


# --- Querschnitt ---------------------------------------------------------------


@pytest.mark.parametrize("check", ["ki_klassifikation", "plan_merkmal", "formularfeld", "manuell"])
def test_leere_evidenz_ist_nie_erfuellt(check: str) -> None:
    r = _regel(check, dokument="Grundriss", merkmal="m", feld="f")
    assert pruefe(r, Evidenz()).ergebnis != Ergebnis.ERFUELLT


def test_deterministisch() -> None:
    r = _regel("ki_klassifikation", dokument="Grundriss")
    e = Evidenz(seiten=(_seite("s1", "Grundriss"),))
    assert pruefe(r, e) == pruefe(r, e)
