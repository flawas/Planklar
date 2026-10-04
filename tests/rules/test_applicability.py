from typing import Any

import pytest

from app.rules.applicability import (
    Anwendbarkeit,
    applicable_rules,
    bewerte,
    used_variables,
)
from app.rules.models import Kanton, Regel
from app.rules.resolve import Regelset, regelset_hash


def _regel(when: Any, rid: str = "R1") -> Regel:
    return Regel.model_validate(
        {
            "id": rid,
            "titel": "T",
            "scope": {"kanton": "LU"},
            "when": when,
            "requires": {"typ": "dokument"},
            "check": "manuell",
            "schwere": "hinweis",
            "quelle": {"erlass": "E", "paragraph": "§ 1", "url": "https://example.org"},
            "stand": "2026-01-01",
        }
    )


def _set(*regeln: Regel) -> Regelset:
    return Regelset(kanton=Kanton.LU, gemeinde=None, regeln=regeln, hash=regelset_hash(regeln))


EQ = {"==": [{"var": "gewaesserbezug"}, True]}
IN = {"in": [{"var": "vorhabenstyp"}, ["neubau_efh_mfh", "umbau_anbau"]]}


@pytest.mark.parametrize(
    ("when", "vorhaben", "erwartet"),
    [
        (True, {}, Anwendbarkeit.ANWENDBAR),
        (False, {}, Anwendbarkeit.NICHT_ANWENDBAR),
        (EQ, {"gewaesserbezug": True}, Anwendbarkeit.ANWENDBAR),
        (EQ, {"gewaesserbezug": False}, Anwendbarkeit.NICHT_ANWENDBAR),
        (IN, {"vorhabenstyp": "umbau_anbau"}, Anwendbarkeit.ANWENDBAR),
        (IN, {"vorhabenstyp": "abbruch"}, Anwendbarkeit.NICHT_ANWENDBAR),
        (EQ, {}, Anwendbarkeit.UNBEKANNT),
        (EQ, {"gewaesserbezug": None}, Anwendbarkeit.UNBEKANNT),
        (IN, {"andere": 1}, Anwendbarkeit.UNBEKANNT),
        # Eine fehlende Variable genügt, auch wenn die andere Seite schon "false" ergäbe.
        ({"and": [EQ, IN]}, {"vorhabenstyp": "abbruch"}, Anwendbarkeit.UNBEKANNT),
        (
            {"and": [EQ, IN]},
            {"gewaesserbezug": True, "vorhabenstyp": "abbruch"},
            Anwendbarkeit.NICHT_ANWENDBAR,
        ),
        # Default angegeben: Variable gilt nicht als fehlend.
        ({"==": [{"var": ["x", False]}, False]}, {}, Anwendbarkeit.ANWENDBAR),
        # Punktpfad
        ({"==": [{"var": "a.b"}, 1]}, {"a": {"b": 1}}, Anwendbarkeit.ANWENDBAR),
        ({"==": [{"var": "a.b"}, 1]}, {"a": {}}, Anwendbarkeit.UNBEKANNT),
        # falsy, aber vorhanden
        ({"==": [{"var": "n"}, 0]}, {"n": 0}, Anwendbarkeit.ANWENDBAR),
    ],
)
def test_bewerte(when: Any, vorhaben: dict[str, Any], erwartet: Anwendbarkeit) -> None:
    assert bewerte(_regel(when), vorhaben).anwendbarkeit == erwartet


def test_fehlende_variablen_werden_genannt() -> None:
    b = bewerte(_regel({"and": [EQ, IN]}), {})
    assert b.fehlende_variablen == ("gewaesserbezug", "vorhabenstyp")


def test_applicable_rules_laesst_nichts_weg() -> None:
    rs = _set(_regel(True, "A"), _regel(False, "B"), _regel(EQ, "C"))
    result = applicable_rules(rs, {})
    assert [(b.regel.id, b.anwendbarkeit) for b in result] == [
        ("A", Anwendbarkeit.ANWENDBAR),
        ("B", Anwendbarkeit.NICHT_ANWENDBAR),
        ("C", Anwendbarkeit.UNBEKANNT),
    ]


def test_rein_und_vorhaben_unveraendert() -> None:
    vorhaben = {"gewaesserbezug": True}
    rs = _set(_regel(EQ))
    assert applicable_rules(rs, vorhaben) == applicable_rules(rs, vorhaben)
    assert vorhaben == {"gewaesserbezug": True}


def test_used_variables() -> None:
    assert used_variables({"and": [EQ, IN, {"var": ["z", 1]}]}) == {
        "gewaesserbezug",
        "vorhabenstyp",
    }
