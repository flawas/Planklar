"""Szenario-Tests Luzern: erwartete Anforderungen je Vorhabenstyp x Gemeinde.

Die Erwartungen stehen als Daten in `tests/rules/data/szenarien_lu.yaml`.
"""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.rules.applicability import Anwendbarkeit, applicable_rules
from app.rules.loader import load_catalog
from app.rules.models import Kanton
from app.rules.resolve import resolve
from app.rules.validate import DEFAULT_ROOT, validate_catalog

DATA = Path(__file__).parent / "data" / "szenarien_lu.yaml"
SZENARIEN: list[dict[str, Any]] = yaml.safe_load(DATA.read_text(encoding="utf-8"))


@pytest.mark.parametrize("szenario", SZENARIEN, ids=[s["name"] for s in SZENARIEN])
def test_erwartete_anforderungen(szenario: dict[str, Any]) -> None:
    regelset = resolve(Kanton.LU, szenario["gemeinde"])
    bewertungen = applicable_rules(regelset, szenario["vorhaben"])
    assert not [b for b in bewertungen if b.anwendbarkeit is Anwendbarkeit.UNBEKANNT]
    anwendbar = sorted(
        b.regel.id for b in bewertungen if b.anwendbarkeit is Anwendbarkeit.ANWENDBAR
    )
    assert anwendbar == sorted(szenario["erwartet"])


def test_szenarien_decken_alle_vorhabenstypen_und_gemeinden() -> None:
    typen = {s["vorhaben"]["vorhabenstyp"] for s in SZENARIEN}
    gemeinden = {s["gemeinde"] for s in SZENARIEN}
    assert typen == {"neubau_efh_mfh", "umbau_anbau", "heizungsersatz_waermepumpe"}
    assert set(load_catalog(DEFAULT_ROOT)[Kanton.LU].gemeinden) <= gemeinden


def test_erwartete_ids_existieren() -> None:
    lu = load_catalog(DEFAULT_ROOT)[Kanton.LU]
    alle = {r.id for r in lu.basis} | {r.id for g in lu.gemeinden.values() for r in g}
    erwartet = {i for s in SZENARIEN for i in s["erwartet"]}
    assert erwartet <= alle


def _katalog_mit_regel(tmp_path: Path, regel: dict[str, Any]) -> Path:
    (tmp_path / "LU" / "gemeinden").mkdir(parents=True)
    (tmp_path / "LU" / "kanton.yaml").write_text(yaml.safe_dump([regel]), encoding="utf-8")
    return tmp_path


_REGEL: dict[str, Any] = {
    "id": "LU-TEST-1",
    "titel": "Testregel",
    "scope": {"kanton": "LU"},
    "when": True,
    "requires": {"typ": "dokument", "dokument": "Testdokument"},
    "check": "manuell",
    "schwere": "hinweis",
    "quelle": {"erlass": "PBV LU", "paragraph": "§ 1", "url": "https://example.org"},
    "stand": "2026-01-01",
}


def test_testregel_ist_gueltig(tmp_path: Path) -> None:
    assert validate_catalog(_katalog_mit_regel(tmp_path, _REGEL)) == []


@pytest.mark.parametrize("feld", ["quelle", "stand"])
def test_regel_ohne_quelle_oder_stand_schlaegt_fehl(tmp_path: Path, feld: str) -> None:
    regel = copy.deepcopy(_REGEL)
    del regel[feld]
    assert validate_catalog(_katalog_mit_regel(tmp_path, regel))


@pytest.mark.parametrize("teil", ["erlass", "paragraph", "url"])
def test_regel_mit_leerer_quelle_schlaegt_fehl(tmp_path: Path, teil: str) -> None:
    regel = copy.deepcopy(_REGEL)
    regel["quelle"][teil] = ""
    assert validate_catalog(_katalog_mit_regel(tmp_path, regel))


def test_echter_katalog_hat_quelle_und_stand() -> None:
    lu = load_catalog(DEFAULT_ROOT)[Kanton.LU]
    regeln = [*lu.basis, *(r for g in lu.gemeinden.values() for r in g)]
    assert regeln
    for r in regeln:
        assert r.quelle.erlass and r.quelle.paragraph and r.quelle.url and r.stand, r.id
