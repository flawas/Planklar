import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Ergebnis, Pruefstatus
from app.dossiers.scope import BueroScope
from app.storage import Storage
from tests.auth.conftest import make_user
from tests.dossiers.conftest import make_pdf
from tests.dossiers.test_dossier_api import BODY
from tests.dossiers.test_upload import login


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.dossiers.router.run_pruefung_task.delay",
        lambda buero_id, pruefung_id: calls.append((buero_id, pruefung_id)),
    )
    return calls


def _dossier(client: TestClient, db: Session, email: str = "a@buero-a.ch") -> str:
    make_user(db, email)
    login(client, email)
    return str(client.post("/dossiers", json=BODY).json()["id"])


def _upload(client: TestClient, dossier_id: str) -> None:
    r = client.post(
        f"/dossiers/{dossier_id}/dokumente",
        files={"file": ("plan.pdf", make_pdf(2), "application/pdf")},
    )
    assert r.status_code == 201


def test_start_ohne_dokumente_verweigert(
    client: TestClient, db: Session, enqueued: list[tuple[str, str]]
) -> None:
    did = _dossier(client, db)
    r = client.post(f"/dossiers/{did}/pruefungen")
    assert r.status_code == 422
    assert r.json()["detail"] == "KEINE_DOKUMENTE"
    assert enqueued == []
    assert client.get(f"/dossiers/{did}/pruefungen").json() == []


def test_start_status_und_befunde(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did = _dossier(client, db)
    _upload(client, did)
    r = client.post(f"/dossiers/{did}/pruefungen")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "laeuft"
    assert body["dossier_id"] == did
    assert len(body["regelset_hash"]) == 64
    assert len(enqueued) == 1
    assert enqueued[0][1] == body["id"]

    url = f"/dossiers/{did}/pruefungen/{body['id']}"
    assert client.get(url).json() == body
    assert client.get(f"/dossiers/{did}/pruefungen").json() == [body]
    assert client.get(f"{url}/befunde").json() == []

    scope = BueroScope(db, uuid.UUID(enqueued[0][0]))
    pid = uuid.UUID(body["id"])
    scope.save_befund(pid, regel_id="lu.r1", ergebnis=Ergebnis.FEHLT, belege=["s1"])
    scope.update_pruefung(pid, status=Pruefstatus.ABGESCHLOSSEN, seiten_gesamt=2, seiten_fertig=2)
    db.commit()
    status = client.get(url).json()
    assert (status["status"], status["seiten_gesamt"], status["seiten_fertig"]) == (
        "abgeschlossen",
        2,
        2,
    )
    befunde = client.get(f"{url}/befunde").json()
    assert [(b["regel_id"], b["ergebnis"], b["belege"]) for b in befunde] == [
        ("lu.r1", "fehlt", ["s1"])
    ]
    assert befunde[0]["override_ergebnis"] is None


def test_laufender_pruefung_kein_zweiter_start(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did = _dossier(client, db)
    _upload(client, did)
    first = client.post(f"/dossiers/{did}/pruefungen")
    second = client.post(f"/dossiers/{did}/pruefungen")
    assert second.status_code == 409
    assert second.json()["detail"] == "PRUEFUNG_LAEUFT"
    assert len(enqueued) == 1
    assert first.status_code == 202


def test_fremdes_buero_bekommt_404(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did = _dossier(client, db)
    _upload(client, did)
    pid = client.post(f"/dossiers/{did}/pruefungen").json()["id"]
    client.post("/auth/logout")
    make_user(db, "b@buero-b.ch")
    login(client, "b@buero-b.ch")
    enqueued.clear()

    assert client.post(f"/dossiers/{did}/pruefungen").status_code == 404
    assert client.get(f"/dossiers/{did}/pruefungen").status_code == 404
    assert client.get(f"/dossiers/{did}/pruefungen/{pid}").status_code == 404
    assert client.get(f"/dossiers/{did}/pruefungen/{pid}/befunde").status_code == 404
    assert enqueued == []


def test_pruefung_gehoert_zum_dossier_im_pfad(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did = _dossier(client, db)
    _upload(client, did)
    pid = client.post(f"/dossiers/{did}/pruefungen").json()["id"]
    other = client.post("/dossiers", json=BODY).json()["id"]
    assert client.get(f"/dossiers/{other}/pruefungen/{pid}").status_code == 404
    assert client.get(f"/dossiers/{other}/pruefungen/{pid}/befunde").status_code == 404
