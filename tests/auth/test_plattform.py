import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Buero, Dossier, Einladung, Kanton, Rolle, User, Vorhabenstyp
from app.mail import FakeMailer, get_mailer
from app.main import app
from tests.auth.conftest import make_user
from tests.auth.test_auth import login
from tests.web.test_login import do_login


@pytest.fixture
def mailer(client: TestClient) -> FakeMailer:
    fake = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: fake
    yield fake  # type: ignore[misc]
    app.dependency_overrides.pop(get_mailer, None)


def plattform_login(client: TestClient, db: Session) -> User:
    user = make_user(db, "root@liquet.ch", plattform=True)
    login(client, "root@liquet.ch")
    return user


@pytest.mark.parametrize("admin", [False, True])
def test_nur_plattform_admin(client: TestClient, db: Session, admin: bool) -> None:
    other = make_user(db, "x@x.ch", admin=admin)
    login(client, "x@x.ch")
    assert client.get("/plattform/bueros").status_code == 403
    assert (
        client.post("/plattform/bueros", json={"name": "N", "admin_email": "a@n.ch"}).status_code
        == 403
    )
    assert (
        client.patch(f"/plattform/bueros/{other.buero_id}", json={"aktiv": False}).status_code
        == 403
    )


def test_anonym_abgewiesen(client: TestClient) -> None:
    assert client.get("/plattform/bueros").status_code == 401


def test_buero_anlegen_laedt_ersten_admin_ein(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    plattform_login(client, db)
    r = client.post("/plattform/bueros", json={"name": "Neu AG", "admin_email": "Chef@Neu.ch"})
    assert r.status_code == 201
    assert r.json() | {"id": None} == {
        "id": None,
        "name": "Neu AG",
        "aktiv": True,
        "benutzer": 0,
        "dossiers": 0,
    }
    einladung = db.execute(select(Einladung)).scalar_one()
    assert einladung.rolle == Rolle.BUERO_ADMIN and einladung.email == "chef@neu.ch"
    assert str(einladung.buero_id) == r.json()["id"]
    token = re.search(r"/einladung/(\S+)", mailer.outbox[0].text).group(1)  # type: ignore[union-attr]
    client.cookies.clear()
    r = client.post(
        "/auth/einladung/einloesen", json={"token": token, "password": "neu-passwort-123"}
    )
    assert r.status_code == 201 and r.json()["rolle"] == "buero_admin"
    assert login(client, "chef@neu.ch", "neu-passwort-123").status_code == 204


def test_buero_anlegen_mit_bestehender_email_legt_nichts_an(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    plattform_login(client, db)
    anzahl = len(db.scalars(select(Buero)).all())
    r = client.post("/plattform/bueros", json={"name": "Neu", "admin_email": "root@liquet.ch"})
    assert r.status_code == 409
    db.expire_all()
    assert len(db.scalars(select(Buero)).all()) == anzahl
    assert not mailer.outbox


def test_sperren_entsperren_umbenennen(client: TestClient, db: Session) -> None:
    plattform_login(client, db)
    ziel = make_user(db, "u@z.ch")
    url = f"/plattform/bueros/{ziel.buero_id}"
    assert client.patch(url, json={"aktiv": False}).json()["aktiv"] is False
    client.cookies.clear()
    assert login(client, "u@z.ch").status_code == 400  # Login gesperrt
    login(client, "root@liquet.ch")
    r = client.patch(url, json={"aktiv": True, "name": "Umbenannt"})
    assert r.json()["aktiv"] is True and r.json()["name"] == "Umbenannt"
    assert client.patch(f"/plattform/bueros/{ziel.id}", json={"aktiv": False}).status_code == 404


def test_nur_metadaten(client: TestClient, db: Session) -> None:
    plattform_login(client, db)
    fremd = make_user(db, "u@z.ch")
    db.add(
        Dossier(
            buero_id=fremd.buero_id,
            kanton=Kanton.LU,
            gemeinde="Geheimhausen",
            vorhabenstyp=Vorhabenstyp.NEUBAU_EFH_MFH,
            attribute={"bauherr": "Privatperson Muster"},
        )
    )
    db.commit()
    r = client.get("/plattform/bueros")
    zeile = next(b for b in r.json() if b["id"] == str(fremd.buero_id))
    assert set(zeile) == {"id", "name", "aktiv", "benutzer", "dossiers"}
    assert zeile["dossiers"] == 1 and zeile["benutzer"] == 1
    assert "Geheimhausen" not in r.text and "Privatperson" not in r.text and "u@z.ch" not in r.text
    seite = client.get("/plattform")
    assert seite.status_code == 200
    assert "Geheimhausen" not in seite.text and "Privatperson" not in seite.text
    assert "u@z.ch" not in seite.text


# Web-UI


def csrf_token(client: TestClient) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/plattform").text)
    assert m
    return m.group(1)


def test_web_zugriff(client: TestClient, db: Session) -> None:
    assert client.get("/plattform", follow_redirects=False).headers["location"] == "/login"
    make_user(db, "a@a.ch", admin=True)
    do_login(client, "a@a.ch")
    assert client.get("/plattform").status_code == 403
    assert client.post("/plattform/neu", data={"name": "X"}).status_code == 403


def test_web_buero_anlegen_und_sperren(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    make_user(db, "root@liquet.ch", plattform=True)
    do_login(client, "root@liquet.ch")
    tok = csrf_token(client)
    assert (
        client.post("/plattform/neu", data={"name": "N", "admin_email": "a@n.ch"}).status_code
        == 403
    )
    r = client.post(
        "/plattform/neu", data={"csrf_token": tok, "name": "Neu AG", "admin_email": "a@n.ch"}
    )
    assert r.status_code == 200 and "Büro angelegt" in r.text and "Neu AG" in r.text
    assert mailer.outbox[0].an == "a@n.ch"
    bad = client.post(
        "/plattform/neu", data={"csrf_token": tok, "name": "X", "admin_email": "kaputt"}
    )
    assert bad.status_code == 422
    neu = db.execute(select(Buero).where(Buero.name == "Neu AG")).scalar_one()
    r = client.post(f"/plattform/{neu.id}/status", data={"csrf_token": tok, "aktiv": "0"})
    assert r.status_code == 200 and "Entsperren" in r.text
    db.refresh(neu)
    assert neu.aktiv is False
    r = client.post(f"/plattform/{neu.id}/name", data={"csrf_token": tok, "name": "Neu GmbH"})
    assert r.status_code == 200
    db.refresh(neu)
    assert neu.name == "Neu GmbH"
