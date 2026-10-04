"""Architekturtest: mandantengebundene Modelle nur über `BueroScope` (CLAUDE.md, ADR 0005).

Statische Prüfung des Quellcodes in `app/`, ohne Datenbank. Erlaubt ist der Zugriff nur in
`app/dossiers/scope.py`; die Modelldefinitionen in `app/db/models.py` sind ausgenommen.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
ERLAUBT = {APP / "dossiers" / "scope.py", APP / "db" / "models.py"}
GESCHUETZT = {"Dossier", "Dokument", "Seite", "Pruefung", "Befund"}
# Konstruktionen, die Zeilen eines Modells lesen oder verändern
ABFRAGEN = {"select", "update", "delete", "insert", "query", "get", "get_one", "merge", "refresh"}


def _namen(knoten: ast.AST) -> set[str]:
    """Alle Namen (`Dossier`, `db.Dossier`, `models.Dossier.id`) unterhalb eines Knotens."""
    gefunden: set[str] = set()
    for n in ast.walk(knoten):
        if isinstance(n, ast.Name):
            gefunden.add(n.id)
        elif isinstance(n, ast.Attribute):
            gefunden.add(n.attr)
    return gefunden


def _aufrufname(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def verstoesse(quelle: str, dateiname: str = "<test>") -> list[str]:
    """Stellen, an denen ein geschütztes Modell ausserhalb von `BueroScope` abgefragt wird."""
    treffer: list[str] = []
    for n in ast.walk(ast.parse(quelle, dateiname)):
        if not isinstance(n, ast.Call) or _aufrufname(n) not in ABFRAGEN:
            continue
        # `d.get("x")` auf einem dict hat keine Modellargumente; wir prüfen nur Modellnamen
        modelle = set().union(*(_namen(a) for a in [*n.args, *(k.value for k in n.keywords)]))
        for modell in sorted(modelle & GESCHUETZT):
            treffer.append(f"{dateiname}:{n.lineno}: {_aufrufname(n)}({modell})")
    return treffer


def test_app_greift_nur_ueber_scope_auf_mandantenmodelle_zu() -> None:
    gefunden: list[str] = []
    for pfad in sorted(APP.rglob("*.py")):
        if pfad in ERLAUBT:
            continue
        gefunden += verstoesse(pfad.read_text(encoding="utf-8"), str(pfad.relative_to(APP.parent)))
    assert not gefunden, "Zugriff an BueroScope vorbei:\n" + "\n".join(gefunden)


@pytest.mark.parametrize("modell", sorted(GESCHUETZT))
@pytest.mark.parametrize(
    "vorlage",
    [
        "select({m})",
        "select({m}.id).where({m}.id == 1)",
        "select(db.{m})",
        "session.get({m}, i)",
        "self.session.get(models.{m}, i)",
        "session.query({m})",
        "update({m}).values(x=1)",
        "delete({m})",
    ],
)
def test_erkennt_umgehung(vorlage: str, modell: str) -> None:
    assert verstoesse(vorlage.format(m=modell))


@pytest.mark.parametrize(
    "quelle",
    [
        "select(User)",
        "session.get(User, 1)",
        "select(Buero.id)",
        "config.get('Dossier')",
        "scope.get_dossier(i)",
    ],
)
def test_erlaubte_zugriffe_sind_keine_treffer(quelle: str) -> None:
    assert not verstoesse(quelle)
