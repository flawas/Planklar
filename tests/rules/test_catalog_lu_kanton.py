"""Szenario-Tests für rules/LU/kanton.yaml (formelle Beilagen, keine Baurechtsprüfung)."""

import re
from typing import Any

import pytest
import yaml

from app.rules.validate import DEFAULT_ROOT, validate_catalog

PATH = DEFAULT_ROOT / "LU" / "kanton.yaml"
RULES: list[dict[str, Any]] = yaml.safe_load(PATH.read_text(encoding="utf-8"))

GRUNDSET = {
    "LU-PBV55-1-baugesuchsformular",
    "LU-PBV56-1-unterschriftenblatt",
    "LU-PBV55-2a-situationsplan",
    "LU-PBV55-2b-grundriss",
    "LU-PBV55-2b-fassade",
    "LU-PBV55-2b-schnitt",
    "LU-PBV55-2c-umgebungsplan",
    "LU-PBV55-2e-entwaesserungsplan",
    "LU-PBV55-5-beilagenverzeichnis",
}

PLAENE = {
    "LU-PBV55-2b-grundriss",
    "LU-PBV55-2b-fassade",
    "LU-PBV55-2b-schnitt",
    "LU-PBV55-2c-umgebungsplan",
    "LU-PBV55-2e-entwaesserungsplan",
}


def jsonLogic(expr: Any, data: dict[str, Any]) -> Any:
    """Minimaler Auswerter für die im Katalog verwendeten Operatoren (Engine folgt separat)."""
    if not isinstance(expr, dict):
        return expr
    ((op, args),) = expr.items()
    if op == "var":
        return data.get(args)
    vals = [jsonLogic(a, data) for a in args]
    if op == "==":
        return vals[0] == vals[1]
    if op == "in":
        return vals[0] in vals[1]
    if op == "and":
        return all(vals)
    raise NotImplementedError(op)


def erwartet(**attribute: Any) -> set[str]:
    return {r["id"] for r in RULES if jsonLogic(r["when"], attribute)}


def test_catalog_valid() -> None:
    assert validate_catalog(DEFAULT_ROOT) == []


def test_all_rules_scope_lu_kanton() -> None:
    assert all(r["scope"] == {"kanton": "LU"} for r in RULES)


def test_every_rule_has_source_and_stand() -> None:
    for r in RULES:
        assert r["quelle"]["erlass"] and r["quelle"]["paragraph"]
        assert r["quelle"]["url"].startswith("https://")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["stand"]))


def test_no_substantive_rules() -> None:
    verboten = ("einhaltung", "ausnützung", "ausnutzung", "zonenplan", "zonenkonform")
    for r in RULES:
        assert not any(w in r["titel"].lower() for w in verboten), r["id"]


@pytest.mark.parametrize("vorhabenstyp", ["neubau_efh_mfh", "umbau_anbau"])
def test_grundset(vorhabenstyp: str) -> None:
    ids = erwartet(vorhabenstyp=vorhabenstyp)
    assert GRUNDSET <= ids


def test_neubau_ohne_umbau_hinweis() -> None:
    assert "LU-PBV55-4-farbkennzeichnung" not in erwartet(vorhabenstyp="neubau_efh_mfh")


def test_umbau_farbkennzeichnung() -> None:
    assert "LU-PBV55-4-farbkennzeichnung" in erwartet(vorhabenstyp="umbau_anbau")


def test_heizungsersatz_hat_formular_und_situation() -> None:
    ids = erwartet(vorhabenstyp="heizungsersatz_waermepumpe")
    assert {"LU-PBV55-1-baugesuchsformular", "LU-PBV55-2a-situationsplan"} <= ids
    assert not PLAENE & ids


@pytest.mark.parametrize(
    ("attr", "regel"),
    [
        ("gewaesserbezug", "LU-WEG-gewaesser-querprofil"),
        ("kantonsstrassenbezug", "LU-WEG-kantonsstrasse-gelaendeschnitt"),
        ("waldbezug", "LU-WEG-wald-querprofil"),
    ],
)
def test_bezug_regeln(attr: str, regel: str) -> None:
    assert regel not in erwartet(vorhabenstyp="neubau_efh_mfh", **{attr: False})
    assert regel in erwartet(vorhabenstyp="neubau_efh_mfh", **{attr: True})


def test_ausserhalb_bauzone_nur_umbau() -> None:
    regel = "LU-WEG-abz-fotos-fassaden"
    assert regel in erwartet(vorhabenstyp="umbau_anbau", ausserhalb_bauzone=True)
    assert regel not in erwartet(vorhabenstyp="umbau_anbau", ausserhalb_bauzone=False)


def test_fehlende_bezugsangabe_ist_dokumentiert() -> None:
    """Unbekannte Angabe (None) lässt die Regel entfallen; der Katalog hält das fest."""
    kopf = PATH.read_text(encoding="utf-8").split("\n- id:", 1)[0]
    assert "Pflichtangaben" in kopf and "unsicher" in kopf
    assert "LU-WEG-gewaesser-querprofil" not in erwartet(vorhabenstyp="neubau_efh_mfh")
