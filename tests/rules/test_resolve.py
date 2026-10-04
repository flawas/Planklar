from pathlib import Path
from typing import Any

import pytest
import yaml

from app.rules.models import Kanton
from app.rules.resolve import resolve


def _rule(rid: str, gemeinde: str | None = None, **extra: Any) -> dict[str, Any]:
    scope: dict[str, Any] = {"kanton": "LU"}
    if gemeinde:
        scope["gemeinde"] = gemeinde
    return {
        "id": rid,
        "titel": f"Regel {rid}",
        "scope": scope,
        "when": True,
        "requires": {"typ": "dokument"},
        "check": "manuell",
        "schwere": "hinweis",
        "quelle": {"erlass": "E", "paragraph": "§ 1", "url": "https://example.org"},
        "stand": "2026-01-01",
        **extra,
    }


def _catalog(tmp_path: Path, basis: list[dict], gemeinde: list[dict] | None = None) -> Path:
    (tmp_path / "LU" / "gemeinden").mkdir(parents=True)
    (tmp_path / "LU" / "kanton.yaml").write_text(yaml.safe_dump(basis), encoding="utf-8")
    if gemeinde is not None:
        (tmp_path / "LU" / "gemeinden" / "g.yaml").write_text(
            yaml.safe_dump(gemeinde), encoding="utf-8"
        )
    return tmp_path


def _ids(root: Path, gemeinde: str | None) -> list[str]:
    return [r.id for r in resolve(Kanton.LU, gemeinde, root).regeln]


def test_gemeinde_ergaenzt(tmp_path: Path) -> None:
    root = _catalog(tmp_path, [_rule("A")], [_rule("B", "Luzern")])
    assert _ids(root, "Luzern") == ["A", "B"]
    assert _ids(root, None) == ["A"]
    assert _ids(root, "Unbekannt") == ["A"]


def test_gemeinde_ersetzt_bei_gleicher_id(tmp_path: Path) -> None:
    root = _catalog(tmp_path, [_rule("A")], [_rule("A", "Luzern", titel="Lokal")])
    (regel,) = resolve(Kanton.LU, "Luzern", root).regeln
    assert regel.titel == "Lokal"
    assert regel.scope.gemeinde == "Luzern"


def test_gemeinde_deaktiviert(tmp_path: Path) -> None:
    root = _catalog(tmp_path, [_rule("A"), _rule("B")], [_rule("A", "Luzern", disabled=True)])
    assert _ids(root, "Luzern") == ["B"]
    assert _ids(root, None) == ["A", "B"]


def test_hash_stabil_bei_reihenfolge(tmp_path: Path) -> None:
    r1 = _catalog(tmp_path / "x", [_rule("A"), _rule("B")])
    r2 = _catalog(tmp_path / "y", [_rule("B"), _rule("A")])
    assert resolve(Kanton.LU, None, r1).hash == resolve(Kanton.LU, None, r2).hash
    assert len(resolve(Kanton.LU, None, r1).hash) == 64


def test_hash_aendert_sich_bei_inhalt(tmp_path: Path) -> None:
    r1 = _catalog(tmp_path / "x", [_rule("A")])
    r2 = _catalog(tmp_path / "y", [_rule("A", titel="Anders")])
    assert resolve(Kanton.LU, None, r1).hash != resolve(Kanton.LU, None, r2).hash


@pytest.mark.parametrize("gemeinde", [None, "Luzern"])
def test_hash_deterministisch(tmp_path: Path, gemeinde: str | None) -> None:
    root = _catalog(tmp_path, [_rule("A")], [_rule("B", "Luzern")])
    assert resolve(Kanton.LU, gemeinde, root).hash == resolve(Kanton.LU, gemeinde, root).hash
