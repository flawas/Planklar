import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Rolle, User
from tests.auth.conftest import PASSWORD, make_user
from tests.web.test_login import do_login

URL = "/benutzer"


def token(client: TestClient) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', client.get(URL).text)
    assert m
    return m.group(1)


def kollege(db: Session, admin: User, email: str, *, rolle: Rolle = Rolle.MITARBEITER) -> User:
    u = User(
        buero_id=admin.buero_id,
        email=email,
        hashed_password=admin.hashed_password,
        rolle=rolle,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def admin(client: TestClient, db: Session) -> User:
    u = make_user(db, "admin@buero-a.ch", admin=True)
    do_login(client, "admin@buero-a.ch")
    return u


def test_nur_buero_admin(client: TestClient, db: Session) -> None:
    make_user(db, "mitarbeiter@buero-a.ch")
    do_login(client, "mitarbeiter@buero-a.ch")
    assert client.get(URL).status_code == 403
    assert "/benutzer" not in client.get("/").text
    assert client.post(f"{URL}/passwort", data={}).status_code == 403
    assert client.post(f"{URL}/{'0' * 32}/loeschen", data={}).status_code == 403


def test_anonym_wird_zum_login_geleitet(client: TestClient) -> None:
    r = client.get(URL, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.post(f"{URL}/passwort", data={}).status_code == 401


def test_liste_nur_eigenes_buero(client: TestClient, db: Session, admin: User) -> None:
    kollege(db, admin, "kollegin@buero-a.ch")
    make_user(db, "fremd@buero-b.ch")
    r = client.get(URL)
    assert r.status_code == 200
    assert "kollegin@buero-a.ch" in r.text and "fremd@buero-b.ch" not in r.text
    assert 'href="/benutzer"' in r.text


def test_rolle_aendern(client: TestClient, db: Session, admin: User) -> None:
    k = kollege(db, admin, "kollegin@buero-a.ch")
    r = client.post(
        f"{URL}/{k.id}/rolle", data={"csrf_token": token(client), "rolle": "buero_admin"}
    )
    assert r.status_code == 200 and "Einstellungen gespeichert." in r.text
    db.expire_all()
    assert db.get(User, k.id).rolle == Rolle.BUERO_ADMIN  # type: ignore[union-attr]
    r = client.post(f"{URL}/{k.id}/rolle", data={"csrf_token": token(client), "rolle": "x"})
    assert r.status_code == 400


def test_deaktivieren_und_aktivieren(client: TestClient, db: Session, admin: User) -> None:
    k = kollege(db, admin, "kollegin@buero-a.ch")
    client.post(f"{URL}/{k.id}/status", data={"csrf_token": token(client), "aktiv": "0"})
    db.expire_all()
    assert db.get(User, k.id).is_active is False  # type: ignore[union-attr]
    client.post(f"{URL}/{k.id}/status", data={"csrf_token": token(client), "aktiv": "1"})
    db.expire_all()
    assert db.get(User, k.id).is_active is True  # type: ignore[union-attr]


def test_letzter_admin_geschuetzt(client: TestClient, db: Session, admin: User) -> None:
    r = client.post(f"{URL}/{admin.id}/status", data={"csrf_token": token(client), "aktiv": "0"})
    assert r.status_code == 409 and "letzte aktive Administrator" in r.text
    r = client.post(f"{URL}/{admin.id}/loeschen", data={"csrf_token": token(client)})
    assert r.status_code == 409


def test_loeschen_mit_bestaetigung(client: TestClient, db: Session, admin: User) -> None:
    k = kollege(db, admin, "kollegin@buero-a.ch")
    kid = k.id
    r = client.get(f"{URL}/{kid}/loeschen")
    assert r.status_code == 200 and "kollegin@buero-a.ch" in r.text
    db.expire_all()
    assert db.get(User, kid) is not None  # GET löscht nichts
    r = client.post(f"{URL}/{kid}/loeschen", data={"csrf_token": token(client)})
    assert r.status_code == 200 and "Benutzer gelöscht." in r.text
    db.expire_all()
    assert db.get(User, kid) is None


def test_fremdes_buero_nicht_veraenderbar(client: TestClient, db: Session, admin: User) -> None:
    fremd = make_user(db, "fremd@buero-b.ch")
    tok = token(client)
    assert client.post(f"{URL}/{fremd.id}/loeschen", data={"csrf_token": tok}).status_code == 404
    assert (
        client.post(f"{URL}/{fremd.id}/status", data={"csrf_token": tok, "aktiv": "0"}).status_code
        == 404
    )
    assert client.get(f"{URL}/{fremd.id}/loeschen").status_code == 404
    db.expire_all()
    assert db.get(User, fremd.id) is not None and db.get(User, fremd.id).is_active  # type: ignore[union-attr]


def test_csrf_pflicht(client: TestClient, db: Session, admin: User) -> None:
    k = kollege(db, admin, "kollegin@buero-a.ch")
    token(client)
    for pfad in (f"{k.id}/loeschen", f"{k.id}/status", f"{k.id}/rolle", "passwort"):
        assert client.post(f"{URL}/{pfad}", data={"csrf_token": "falsch"}).status_code == 403
    db.expire_all()
    assert db.get(User, k.id) is not None


def test_passwort_aendern(client: TestClient, db: Session, admin: User) -> None:
    neu = "ein-neues-passwort"
    r = client.post(
        f"{URL}/passwort",
        data={"csrf_token": token(client), "old_password": PASSWORD, "new_password": neu},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get(URL, follow_redirects=False).status_code == 303  # Sitzung beendet
    assert do_login(client, "admin@buero-a.ch", neu).status_code == 303


def test_passwort_fehler(client: TestClient, db: Session, admin: User) -> None:
    r = client.post(
        f"{URL}/passwort",
        data={"csrf_token": token(client), "old_password": "falsch", "new_password": "x" * 12},
    )
    assert r.status_code == 400 and "bisherige Passwort ist falsch" in r.text
    r = client.post(
        f"{URL}/passwort",
        data={"csrf_token": token(client), "old_password": PASSWORD, "new_password": "kurz"},
    )
    assert r.status_code == 400 and "mindestens 10 Zeichen" in r.text
