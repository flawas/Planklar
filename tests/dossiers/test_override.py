import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Ergebnis
from app.dossiers.scope import BueroScope
from app.storage import Storage
from tests.auth.conftest import make_user
from tests.dossiers.test_dossier_api import BODY
from tests.dossiers.test_pruefung_api import _upload
from tests.dossiers.test_upload import login


def _befund(
    client: TestClient, db: Session, enqueued: list[tuple[str, str]], email: str = "a@buero-a.ch"
) -> tuple[str, str, str]:
    make_user(db, email)
    login(client, email)
    did = str(client.post("/dossiers", json=BODY).json()["id"])
    _upload(client, did)
    pid = client.post(f"/dossiers/{did}/pruefungen").json()["id"]
    scope = BueroScope(db, uuid.UUID(enqueued[0][0]))
    befund = scope.save_befund(uuid.UUID(pid), regel_id="lu.r1", ergebnis=Ergebnis.FEHLT)
    db.commit()
    return did, pid, str(befund.id)


def test_override_mit_begruendung_behaelt_original(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did, pid, bid = _befund(client, db, enqueued)
    url = f"/dossiers/{did}/pruefungen/{pid}"
    r = client.put(
        f"{url}/befunde/{bid}/override", json={"ergebnis": "erfüllt", "begruendung": " Liegt vor "}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ergebnis"] == "fehlt"
    assert body["override_ergebnis"] == "erfüllt"
    assert body["override_begruendung"] == "Liegt vor"
    assert body["override_am"]
    export = client.get(f"{url}/overrides").json()
    assert [e["regel_id"] for e in export] == ["lu.r1"]
    assert export[0]["ergebnis"] == "fehlt"
    assert export[0]["override_ergebnis"] == "erfüllt"


def test_override_ohne_begruendung_abgelehnt(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did, pid, bid = _befund(client, db, enqueued)
    url = f"/dossiers/{did}/pruefungen/{pid}"
    for text in ("", "   "):
        r = client.put(
            f"{url}/befunde/{bid}/override", json={"ergebnis": "erfüllt", "begruendung": text}
        )
        assert r.status_code == 422
    assert client.get(f"{url}/overrides").json() == []


def test_override_fremdbuero_abgewiesen(
    client: TestClient, db: Session, storage: Storage, enqueued: list[tuple[str, str]]
) -> None:
    did, pid, bid = _befund(client, db, enqueued)
    client.cookies.clear()
    make_user(db, "b@buero-b.ch")
    login(client, "b@buero-b.ch")
    url = f"/dossiers/{did}/pruefungen/{pid}"
    r = client.put(
        f"{url}/befunde/{bid}/override", json={"ergebnis": "erfüllt", "begruendung": "x"}
    )
    assert r.status_code == 404
    assert client.get(f"{url}/overrides").status_code == 404
