"""Szenariotest «Zwei Büros»: Büro B erreicht über keinen Pfad Daten von Büro A.

Deckt Web, API, Worker und Retention ab (Epic #130, Block 5). Jede Verweigerung wird gegen
den Zugriff des Besitzers gegengeprüft, damit ein 404 nicht aus einem anderen Defekt stammt.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Befund, Dokument, Dossier, Ergebnis, Pruefstatus, Pruefung, Seite
from app.dossiers.retention import loesche_abgelaufene_dossiers
from app.dossiers.scope import BueroScope, NotFoundError
from app.dossiers.service import upload_dokument
from app.main import app
from app.storage import Storage
from app.worker import run_pruefung_task, run_retention_task
from tests.auth.conftest import make_user
from tests.dossiers.conftest import make_pdf
from tests.dossiers.test_upload import login, make_dossier
from tests.web.test_login import csrf_token

REGEL = "LU-PBV55-2a-situationsplan"


@dataclass
class Welt:
    db: Session
    storage: Storage
    a: TestClient
    b: TestClient
    buero_b: uuid.UUID
    dossier: Dossier
    dokument: Dokument
    seite: Seite
    pruefung: Pruefung
    befund: Befund

    @property
    def basis(self) -> str:
        return f"/dossiers/{self.dossier.id}"

    @property
    def lauf(self) -> str:
        return f"{self.basis}/pruefungen/{self.pruefung.id}"


@pytest.fixture
def welt(db: Session, storage: Storage, client: TestClient) -> Welt:
    ua, ub = make_user(db, "a@buero-a.ch"), make_user(db, "b@buero-b.ch")
    dossier = make_dossier(db, ua)
    upload_dokument(db, storage, dossier, "plan.pdf", make_pdf(2), 10**8)
    dokument = db.scalars(select(Dokument).where(Dokument.dossier_id == dossier.id)).one()
    scope = BueroScope(db, ua.buero_id)
    seite = scope.get_or_add_seite(dokument.id, 1)
    pruefung = scope.add_pruefung(dossier.id, regelset_hash="a" * 64, modellversion="fake")
    scope.update_pruefung(pruefung.id, status=Pruefstatus.ABGESCHLOSSEN)
    befund = scope.add_befund(
        pruefung.id, regel_id=REGEL, ergebnis=Ergebnis.FEHLT, belege=[str(seite.id)]
    )
    db.commit()
    a = client
    login(a, "a@buero-a.ch")
    b = TestClient(app, base_url="https://testserver")
    login(b, "b@buero-b.ch")
    assert ub.buero_id != ua.buero_id
    return Welt(db, storage, a, b, ub.buero_id, dossier, dokument, seite, pruefung, befund)


def _unveraendert(w: Welt) -> None:
    w.db.expire_all()
    p = w.db.get(Pruefung, w.pruefung.id)
    assert p is not None and p.status is Pruefstatus.ABGESCHLOSSEN
    b = w.db.get(Befund, w.befund.id)
    assert b is not None and b.ergebnis is Ergebnis.FEHLT and b.override_ergebnis is None
    d = w.db.get(Dossier, w.dossier.id)
    assert d is not None and d.gemeinde == "Luzern"


def test_api_fremdes_buero_sieht_nichts(welt: Welt) -> None:
    w = welt
    lesen = [
        w.basis,
        f"{w.basis}/erwartete-unterlagen",
        f"{w.basis}/pruefungen",
        w.lauf,
        f"{w.lauf}/befunde",
        f"{w.lauf}/overrides",
        f"{w.basis}/seiten/{w.seite.id}/vorschau-url",
    ]
    for pfad in lesen:
        assert w.a.get(pfad).status_code == 200, pfad
        assert w.b.get(pfad).status_code == 404, pfad
    assert w.b.get("/dossiers").json() == []
    assert len(w.a.get("/dossiers").json()) == 1


def test_api_fremdes_buero_kann_nicht_schreiben(welt: Welt, enqueued: list) -> None:  # type: ignore[type-arg]
    w = welt
    antworten = [
        w.b.patch(w.basis, json={"gemeinde": "Hack"}),
        w.b.post(f"{w.basis}/dokumente", files={"file": ("x.pdf", make_pdf(), "application/pdf")}),
        w.b.post(f"{w.basis}/pruefungen"),
        w.b.put(
            f"{w.lauf}/befunde/{w.befund.id}/override",
            json={"ergebnis": Ergebnis.ERFUELLT.value, "begruendung": "Fremd"},
        ),
    ]
    assert [r.status_code for r in antworten] == [404] * 4
    assert enqueued == []
    assert w.db.scalar(select(func.count()).select_from(Dokument)) == 1
    assert w.db.scalar(select(func.count()).select_from(Pruefung)) == 1
    _unveraendert(w)


def test_web_fremdes_buero_sieht_nichts(welt: Welt) -> None:
    w = welt
    seiten = [
        f"{w.basis}/ansicht",
        f"{w.basis}/pruefstatus",
        f"{w.lauf}/bericht",
        f"{w.lauf}/bericht.pdf",
    ]
    for pfad in seiten:
        assert w.a.get(pfad).status_code == 200, pfad
        r = w.b.get(pfad)
        assert r.status_code == 404, pfad
        assert "Luzern" not in r.text
    assert "Luzern" not in w.b.get("/vorhaben").text


def test_web_fremdes_buero_kann_nicht_schreiben(welt: Welt, enqueued: list) -> None:  # type: ignore[type-arg]
    w = welt
    token = csrf_token(w.b)
    r = w.b.post(f"{w.basis}/pruefen", data={"csrf_token": token}, follow_redirects=False)
    assert r.status_code == 404
    assert enqueued == []
    _unveraendert(w)


def test_worker_fremdes_buero_kann_lauf_nicht_ausfuehren(welt: Welt) -> None:
    w = welt
    with pytest.raises(NotFoundError):
        run_pruefung_task(str(w.buero_b), str(w.pruefung.id))
    _unveraendert(w)


def test_worker_unbekanntes_buero_kann_lauf_nicht_ausfuehren(welt: Welt) -> None:
    with pytest.raises(NotFoundError):
        run_pruefung_task(str(uuid.uuid4()), str(welt.pruefung.id))
    _unveraendert(welt)


def test_retention_loescht_je_buero_nur_eigene_abgelaufene_dossiers(
    welt: Welt, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = welt
    db = w.db
    a_id, a_buero, sha = w.dossier.id, w.dossier.buero_id, w.dokument.sha256
    jetzt = datetime.now(UTC)
    scope_b = BueroScope(db, w.buero_b)
    alt = jetzt - timedelta(days=400)
    b_alt = scope_b.add_dossier(
        kanton=w.dossier.kanton,
        gemeinde="Schwyz",
        vorhabenstyp=w.dossier.vorhabenstyp,
        created_at=alt,
    )
    b_frei = scope_b.add_dossier(
        kanton=w.dossier.kanton,
        gemeinde="Schwyz",
        vorhabenstyp=w.dossier.vorhabenstyp,
        created_at=alt,
        evaluation_einverstanden=True,
    )
    db.commit()
    # Das Dossier von A ist jung: ein Lauf für B darf es nicht erfassen.
    report = loesche_abgelaufene_dossiers(db, w.storage, 30)
    assert report.geloescht == [b_alt.id]
    assert report.fehlgeschlagen == []
    db.expire_all()
    assert db.get(Dossier, b_alt.id) is None
    assert db.get(Dossier, b_frei.id) is not None
    assert db.get(Dossier, a_id) is not None
    assert w.storage.get(a_buero, a_id, sha)
    _unveraendert(w)

    # Altert Büro A, gilt dasselbe für dessen Daten; die Objekte von B bleiben unberührt.
    BueroScope(db, a_buero).update_dossier(a_id, created_at=alt)
    db.commit()
    monkeypatch.setattr("app.dossiers.service.get_storage", lambda: w.storage)
    ergebnis = run_retention_task()
    assert ergebnis["geloescht"] == [str(a_id)]
    db.expire_all()
    assert db.get(Dossier, a_id) is None
    assert db.scalar(select(func.count()).select_from(Befund)) == 0
    assert db.get(Dossier, b_frei.id) is not None
    with pytest.raises(Exception):  # noqa: B017, PT011 - Objekt ist weg
        w.storage.get(a_buero, a_id, sha)
