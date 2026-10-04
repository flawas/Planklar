import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Dokument, Seite
from app.dossiers import vorschau
from app.storage import Storage
from tests.auth.conftest import make_user
from tests.dossiers.test_dossier_api import BODY
from tests.dossiers.test_pruefung_api import _upload
from tests.dossiers.test_upload import login


def _mit_seite(client: TestClient, db: Session, email: str = "a@buero-a.ch") -> tuple[str, Seite]:
    make_user(db, email)
    login(client, email)
    did = str(client.post("/dossiers", json=BODY).json()["id"])
    _upload(client, did)
    dok = db.scalars(select(Dokument).where(Dokument.dossier_id == uuid.UUID(did))).one()
    seite = Seite(dokument_id=dok.id, nummer=1)
    db.add(seite)
    db.commit()
    return did, seite


def test_vorschau_liefert_png_ueber_signierte_url(
    client: TestClient, db: Session, storage: Storage
) -> None:
    did, seite = _mit_seite(client, db)
    r = client.get(f"/dossiers/{did}/seiten/{seite.id}/vorschau-url")
    assert r.status_code == 200
    assert r.json()["gueltig_sekunden"] > 0
    bild = client.get(r.json()["url"])
    assert bild.status_code == 200
    assert bild.headers["content-type"] == "image/png"
    assert bild.content.startswith(b"\x89PNG")
    assert "no-store" in bild.headers["cache-control"]


def test_abgelaufenes_oder_manipuliertes_token_abgewiesen(
    client: TestClient, db: Session, storage: Storage
) -> None:
    _, seite = _mit_seite(client, db)
    buero_id = seite.dokument.dossier.buero_id
    alt = vorschau.sign(buero_id, seite.id, ttl=1, now=0)
    assert client.get(vorschau.PREFIX + alt).status_code == 404
    gut = vorschau.sign(buero_id, seite.id)
    assert client.get(vorschau.PREFIX + gut[:-2] + "xx").status_code == 404
    assert client.get(vorschau.PREFIX + "murks").status_code == 404


def test_vorschau_ohne_anmeldung_abgewiesen(
    client: TestClient, db: Session, storage: Storage
) -> None:
    did, seite = _mit_seite(client, db)
    url = client.get(f"/dossiers/{did}/seiten/{seite.id}/vorschau-url").json()["url"]
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_fremdbuero_abgewiesen(client: TestClient, db: Session, storage: Storage) -> None:
    did, seite = _mit_seite(client, db)
    url = client.get(f"/dossiers/{did}/seiten/{seite.id}/vorschau-url").json()["url"]
    client.cookies.clear()
    make_user(db, "b@buero-b.ch")
    login(client, "b@buero-b.ch")
    assert client.get(f"/dossiers/{did}/seiten/{seite.id}/vorschau-url").status_code == 404
    assert client.get(url).status_code == 404  # Token eines anderen Büros
    fremd = vorschau.url_fuer(seite.dokument.dossier.buero_id, seite.id)
    assert client.get(fremd).status_code == 404
