import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Befund, Buero, Dokument, Dossier, Ergebnis, Kanton, User, Vorhabenstyp
from app.dossiers.offboarding import (
    BueroNichtGefundenError,
    PlattformAdminError,
    loesche_buero,
    main,
)
from app.dossiers.scope import BueroScope
from app.storage import Storage
from tests.dossiers.conftest import make_pdf

SHA = "b" * 64


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _buero(session: Session, storage: Storage, name: str) -> tuple[Buero, Dossier]:
    b = Buero(name=name)
    session.add(b)
    session.flush()
    session.add(User(buero_id=b.id, email=f"{name}@example.org", hashed_password="x"))
    scope = BueroScope(session, b.id)
    d = scope.add_dossier(
        kanton=Kanton.LU, gemeinde="Luzern", vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU
    )
    key = storage.put(b.id, d.id, SHA, make_pdf())
    scope.add_dokument(d.id, dateiname="x.pdf", sha256=SHA, seitenzahl=1, speicherpfad=key)
    p = scope.add_pruefung(d.id, regelset_hash="h", modellversion="m")
    scope.add_befund(p.id, regel_id="r", ergebnis=Ergebnis.FEHLT)
    session.commit()
    return b, d


def _vorhanden(storage: Storage, b: Buero, d: Dossier) -> bool:
    try:
        storage.get(b.id, d.id, SHA)
    except Exception:
        return False
    return True


def test_loescht_buero_und_laesst_anderes_unberuehrt(session: Session, storage: Storage) -> None:
    a, da = _buero(session, storage, "a")
    b, db_ = _buero(session, storage, "b")
    a_id, da_id = a.id, da.id

    report = loesche_buero(session, storage, a_id)

    assert (report.dossiers, report.dokumente, report.benutzer) == (1, 1, 1)
    session.expire_all()
    assert session.get(Buero, a_id) is None
    assert session.scalar(select(func.count()).select_from(User).where(User.buero_id == a_id)) == 0
    assert not _vorhanden(storage, a, da)
    assert session.get(Buero, b.id) is not None
    assert session.scalar(select(func.count()).select_from(User)) == 1
    assert session.get(Dossier, db_.id) is not None
    assert session.scalar(select(func.count()).select_from(Dokument)) == 1
    assert session.scalar(select(func.count()).select_from(Befund)) == 1
    assert _vorhanden(storage, b, db_)
    assert da_id != db_.id


def test_unbekanntes_buero(session: Session, storage: Storage) -> None:
    with pytest.raises(BueroNichtGefundenError):
        loesche_buero(session, storage, uuid.uuid4())


def test_plattform_admin_blockiert(session: Session, storage: Storage) -> None:
    a, da = _buero(session, storage, "a")
    session.scalars(select(User).where(User.buero_id == a.id)).one().is_plattform_admin = True
    session.commit()
    with pytest.raises(PlattformAdminError):
        loesche_buero(session, storage, a.id)
    assert _vorhanden(storage, a, da)


def test_speicherfehler_behaelt_buero_und_wiederholung_raeumt_ab(
    session: Session, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, da = _buero(session, storage, "a")
    a_id = a.id
    original = storage.delete

    def kaputt(*_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(storage, "delete", kaputt)
    report = loesche_buero(session, storage, a_id)
    assert report.fehlgeschlagen == [da.id]
    assert session.get(Buero, a_id) is not None

    monkeypatch.setattr(storage, "delete", original)
    report = loesche_buero(session, storage, a_id)
    assert report.fehlgeschlagen == []
    assert session.get(Buero, a_id) is None


def test_cli_ohne_bestaetigung_loescht_nichts(session: Session, storage: Storage) -> None:
    a, _ = _buero(session, storage, "a")
    assert main([str(a.id)]) == 2
    assert session.get(Buero, a.id) is not None
