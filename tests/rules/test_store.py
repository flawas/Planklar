from functools import partial
from pathlib import Path
from typing import Any

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db.models import Regel, Regelset
from app.rules.loader import RegelLadeFehler
from app.rules.store import lade_katalog, pruefe_katalog


def _rule(rid: str, gemeinde: str | None = None) -> dict[str, Any]:
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
    }


def _katalog(root: Path, basis: list[dict[str, Any]], gemeinde: list[dict[str, Any]]) -> Path:
    (root / "LU" / "gemeinden").mkdir(parents=True)
    (root / "LU" / "kanton.yaml").write_text(yaml.safe_dump(basis), encoding="utf-8")
    (root / "LU" / "gemeinden" / "g.yaml").write_text(yaml.safe_dump(gemeinde), encoding="utf-8")
    return root


@pytest.fixture
def session(engine: Engine):
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with Session(engine) as s:
        yield s


def test_laedt_kantons_und_gemeindeset(session: Session, tmp_path: Path) -> None:
    root = _katalog(tmp_path, [_rule("a"), _rule("b")], [_rule("c", "Luzern")])
    neu = lade_katalog(session, "abc123", root)
    assert {(r.gemeinde, len(r.regeln)) for r in neu} == {(None, 2), ("Luzern", 3)}
    assert {r.git_commit for r in neu} == {"abc123"}
    assert all(len(r.regelset_hash) == 64 and r.geladen_am for r in neu)


def test_unveraenderter_katalog_erzeugt_keine_duplikate(session: Session, tmp_path: Path) -> None:
    root = _katalog(tmp_path, [_rule("a")], [_rule("c", "Luzern")])
    lade_katalog(session, "abc123", root)
    assert lade_katalog(session, "def456", root) == []
    assert session.scalar(select(func.count()).select_from(Regelset)) == 2
    assert session.scalar(select(func.count()).select_from(Regel)) == 3


def test_geaenderter_katalog_legt_neuen_stand_an(session: Session, tmp_path: Path) -> None:
    root = _katalog(tmp_path, [_rule("a")], [_rule("c", "Luzern")])
    lade_katalog(session, "abc123", root)
    (root / "LU" / "kanton.yaml").write_text(
        yaml.safe_dump([_rule("a"), _rule("b")]), encoding="utf-8"
    )
    neu = lade_katalog(session, "def456", root)
    assert len(neu) == 2
    assert session.scalar(select(func.count()).select_from(Regelset)) == 4


def test_ungueltiger_katalog_schreibt_nichts(session: Session, tmp_path: Path) -> None:
    root = _katalog(tmp_path, [_rule("a")], [_rule("c", "Luzern")])
    (root / "LU" / "kanton.yaml").write_text("- id: x\n", encoding="utf-8")
    with pytest.raises(RegelLadeFehler, match="kanton.yaml"):
        lade_katalog(session, "abc123", root)
    assert session.scalar(select(func.count()).select_from(Regelset)) == 0


def test_echter_katalog_ist_ladbar() -> None:
    assert pruefe_katalog()


def test_ungueltiger_katalog_verhindert_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "LU").mkdir()
    (tmp_path / "LU" / "kanton.yaml").write_text("kein: liste\n", encoding="utf-8")
    monkeypatch.setattr(main, "lade_katalog", partial(lade_katalog, root=tmp_path))
    with pytest.raises(RegelLadeFehler, match="kanton.yaml"), TestClient(main.app):
        pass
