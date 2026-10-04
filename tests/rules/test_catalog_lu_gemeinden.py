"""Tests für rules/LU/gemeinden (Luzern, Weggis): Overrides und Ergänzungen zur Kantonsbasis."""

import pytest

from app.rules.loader import load_catalog
from app.rules.models import Kanton
from app.rules.validate import DEFAULT_ROOT, validate_catalog

LU = load_catalog(DEFAULT_ROOT)[Kanton.LU]
BASIS_IDS = {r.id for r in LU.basis}


def test_catalog_valid() -> None:
    assert validate_catalog(DEFAULT_ROOT) == []


def test_gemeinden_geladen() -> None:
    assert set(LU.gemeinden) == {"Luzern", "Weggis"}


@pytest.mark.parametrize("gemeinde", ["Luzern", "Weggis"])
def test_quelle_und_stand(gemeinde: str) -> None:
    for r in LU.gemeinden[gemeinde]:
        assert r.quelle.url.startswith("https://") and r.stand, r.id


def test_luzern_override_ersetzt_basisregel() -> None:
    override = {r.id for r in LU.gemeinden["Luzern"]} & BASIS_IDS
    assert override == {"LU-PBV55-5-beilagenverzeichnis"}


def test_weggis_nur_ergaenzung() -> None:
    assert not {r.id for r in LU.gemeinden["Weggis"]} & BASIS_IDS


def test_keine_materiellen_regeln() -> None:
    verboten = ("einhaltung", "ausnützung", "ausnutzung", "zonenplan", "zonenkonform")
    for regeln in LU.gemeinden.values():
        assert not any(w in r.titel.lower() for r in regeln for w in verboten)
