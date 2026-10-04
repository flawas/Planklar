import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.models import Regel, Regelset
from app.rules.loader import DEFAULT_ROOT, RegelLadeFehler
from app.rules.store import sync_catalog


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with Session(engine) as s:
        yield s


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(DEFAULT_ROOT / "LU", tmp_path / "LU")
    return tmp_path


def test_katalog_wird_geladen(session: Session, root: Path) -> None:
    assert sync_catalog(session, "abc123", root) == 1
    regelset = session.scalars(select(Regelset)).one()
    assert (regelset.kanton.value, regelset.gemeinde, regelset.git_ref) == ("LU", None, "abc123")
    assert len(regelset.hash) == 64
    assert regelset.geladen_am is not None
    assert len(regelset.regeln) > 0
    assert regelset.regeln[0].quelle["url"].startswith("http")


def test_unveraenderter_katalog_ohne_duplikate(session: Session, root: Path) -> None:
    sync_catalog(session, "abc123", root)
    assert sync_catalog(session, "def456", root) == 0
    assert session.scalar(select(func.count()).select_from(Regelset)) == 1
    n = session.scalar(select(func.count()).select_from(Regel))
    sync_catalog(session, "def456", root)
    assert session.scalar(select(func.count()).select_from(Regel)) == n


def test_geaenderter_katalog_erzeugt_neues_regelset(session: Session, root: Path) -> None:
    sync_catalog(session, "abc123", root)
    path = root / "LU" / "kanton.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("stand: 2026-10-03", "stand: 2026-10-04", 1)
    )
    assert sync_catalog(session, "def456", root) == 1
    assert session.scalar(select(func.count()).select_from(Regelset)) == 2


def test_ungueltiger_katalog_schreibt_nichts(session: Session, root: Path) -> None:
    (root / "LU" / "kanton.yaml").write_text("- id: kaputt\n", encoding="utf-8")
    with pytest.raises(RegelLadeFehler, match="kanton.yaml"):
        sync_catalog(session, "abc123", root)
    assert session.scalar(select(func.count()).select_from(Regelset)) == 0


def test_ungueltiger_katalog_verhindert_start(
    session: Session, monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    from app import main

    (root / "LU" / "kanton.yaml").write_text("kaputt: [", encoding="utf-8")
    monkeypatch.setattr(main, "sync_catalog", lambda s, ref: sync_catalog(s, ref, root))
    with pytest.raises(RegelLadeFehler, match="ungültiges YAML"):
        with TestClient(main.app):
            pass


def test_start_laedt_katalog(session: Session, monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    from app import main

    monkeypatch.setattr(main, "sync_catalog", lambda s, ref: sync_catalog(s, ref, root))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
    assert session.scalar(select(func.count()).select_from(Regelset)) == 1
