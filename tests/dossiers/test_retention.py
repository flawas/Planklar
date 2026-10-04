import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Befund, Buero, Dokument, Dossier, Ergebnis, Kanton, Pruefung, Vorhabenstyp
from app.dossiers.retention import loesche_abgelaufene_dossiers
from app.dossiers.scope import BueroScope
from app.storage import Storage
from tests.dossiers.conftest import make_pdf

JETZT = datetime(2026, 6, 1, tzinfo=UTC)
SHA = "a" * 64


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _dossier(
    session: Session, storage: Storage, buero: Buero, alter_tage: int, einverstanden: bool = False
) -> Dossier:
    scope = BueroScope(session, buero.id)
    d = scope.add_dossier(
        kanton=Kanton.LU,
        gemeinde="Luzern",
        vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU,
        evaluation_einverstanden=einverstanden,
        created_at=JETZT - timedelta(days=alter_tage),
    )
    key = storage.put(buero.id, d.id, SHA, make_pdf())
    scope.add_dokument(d.id, dateiname="x.pdf", sha256=SHA, seitenzahl=1, speicherpfad=key)
    p = scope.add_pruefung(d.id, regelset_hash="h", modellversion="m")
    scope.add_befund(p.id, regel_id="r", ergebnis=Ergebnis.FEHLT)
    session.commit()
    return d


def _vorhanden(storage: Storage, buero: Buero, d: Dossier) -> bool:
    try:
        storage.get(buero.id, d.id, SHA)
    except Exception:
        return False
    return True


def test_loescht_abgelaufene_in_db_und_speicher(session: Session, storage: Storage) -> None:
    b = Buero(name="A")
    session.add(b)
    session.flush()
    alt = _dossier(session, storage, b, 31)
    jung = _dossier(session, storage, b, 29)
    alt_id = alt.id

    report = loesche_abgelaufene_dossiers(session, storage, 30, now=lambda: JETZT)

    assert report.geloescht == [alt_id]
    assert report.fehlgeschlagen == []
    assert session.get(Dossier, alt_id) is None
    assert session.scalar(select(func.count()).select_from(Dokument)) == 1
    assert session.scalar(select(func.count()).select_from(Pruefung)) == 1
    assert session.scalar(select(func.count()).select_from(Befund)) == 1
    assert not _vorhanden(storage, b, alt)
    assert _vorhanden(storage, b, jung)


def test_einverstaendnis_wird_nie_geloescht(session: Session, storage: Storage) -> None:
    b = Buero(name="A")
    session.add(b)
    session.flush()
    d = _dossier(session, storage, b, 400, einverstanden=True)

    report = loesche_abgelaufene_dossiers(session, storage, 30, now=lambda: JETZT)

    assert report.geloescht == []
    assert session.get(Dossier, d.id) is not None
    assert _vorhanden(storage, b, d)


def test_alle_bueros_werden_bedient(session: Session, storage: Storage) -> None:
    a, b = Buero(name="A"), Buero(name="B")
    session.add_all([a, b])
    session.flush()
    da, db_ = _dossier(session, storage, a, 40), _dossier(session, storage, b, 40)
    ids = {da.id, db_.id}

    report = loesche_abgelaufene_dossiers(session, storage, 30, now=lambda: JETZT)

    assert set(report.geloescht) == ids


def test_report_enthaelt_nur_ids(session: Session, storage: Storage) -> None:
    b = Buero(name="A")
    session.add(b)
    session.flush()
    _dossier(session, storage, b, 40)
    data = loesche_abgelaufene_dossiers(session, storage, 30, now=lambda: JETZT).as_dict()
    assert set(data) == {"geloescht", "fehlgeschlagen"}
    for ids in data.values():
        for i in ids:
            uuid.UUID(i)


def test_speicherfehler_stoppt_andere_nicht_und_wiederholt(
    session: Session, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = Buero(name="A")
    session.add(b)
    session.flush()
    kaputt, ok = _dossier(session, storage, b, 50), _dossier(session, storage, b, 40)
    kaputt_id, ok_id = kaputt.id, ok.id
    original = storage.delete

    def delete(buero_id: uuid.UUID, dossier_id: uuid.UUID, sha: str) -> None:
        if dossier_id == kaputt_id:
            raise RuntimeError("boom")
        original(buero_id, dossier_id, sha)

    monkeypatch.setattr(storage, "delete", delete)
    report = loesche_abgelaufene_dossiers(session, storage, 30, now=lambda: JETZT)
    assert report.fehlgeschlagen == [kaputt_id]
    assert report.geloescht == [ok_id]
    assert session.get(Dossier, kaputt_id) is not None

    monkeypatch.setattr(storage, "delete", original)
    report = loesche_abgelaufene_dossiers(session, storage, 30, now=lambda: JETZT)
    assert report.geloescht == [kaputt_id]


def test_task_und_beat_registriert() -> None:
    from app.worker import celery_app

    assert "liquet.retention.run" in celery_app.tasks
    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "liquet.retention.run" in tasks


def test_scope_listet_keine_fremden_abgelaufenen(session: Session, storage: Storage) -> None:
    a, b = Buero(name="A"), Buero(name="B")
    session.add_all([a, b])
    session.flush()
    _dossier(session, storage, a, 40)
    assert BueroScope(session, b.id).list_abgelaufene_dossiers(JETZT) == []
