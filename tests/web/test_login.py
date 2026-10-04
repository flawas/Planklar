import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth.conftest import PASSWORD, make_user

FOOTER = "Das Tool gibt Hinweise und entscheidet nichts."


def csrf_token(client: TestClient) -> str:
    r = client.get("/login")
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m
    return m.group(1)


def do_login(client: TestClient, email: str, password: str = PASSWORD, token: str | None = None):  # type: ignore[no-untyped-def]
    token = token if token is not None else csrf_token(client)
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_login_seite_deutsch_mit_footer_und_htmx(client: TestClient, db: Session) -> None:
    r = client.get("/login")
    assert r.status_code == 200
    assert '<html lang="de-CH">' in r.text
    assert "Anmelden" in r.text and "Passwort" in r.text
    assert FOOTER in r.text
    assert "/static/htmx.min.js" in r.text
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_startseite_ohne_login_leitet_um(client: TestClient, db: Session) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_ok_leitet_um_und_setzt_session(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    r = do_login(client, "a@buero-a.ch")
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "httponly" in r.headers["set-cookie"].lower()
    home = client.get("/")
    assert home.status_code == 200
    assert "a@buero-a.ch" in home.text
    assert FOOTER in home.text
    assert client.get("/login", follow_redirects=False).status_code == 303


def test_login_falsches_passwort_deutsche_fehlermeldung(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    r = do_login(client, "a@buero-a.ch", "falsch")
    assert r.status_code == 400
    assert "E-Mail oder Passwort ist falsch." in r.text
    assert 'role="alert"' in r.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_inaktiver_benutzer(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch", active=False)
    assert do_login(client, "a@buero-a.ch").status_code == 400


def test_login_ohne_csrf_token_abgelehnt(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    client.get("/login")
    r = do_login(client, "a@buero-a.ch", token="")
    assert r.status_code == 403
    assert "abgelaufen" in r.text
    assert "set-cookie" not in r.headers or "liquet_session" not in r.headers["set-cookie"]


def test_login_mit_gefaelschtem_csrf_token_abgelehnt(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    client.get("/login")
    assert do_login(client, "a@buero-a.ch", token="x.y").status_code == 403


def test_login_ohne_csrf_cookie_abgelehnt(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    token = csrf_token(client)
    client.cookies.clear()
    assert do_login(client, "a@buero-a.ch", token=token).status_code == 403


def test_fehlermeldung_escaped_eingabe(client: TestClient, db: Session) -> None:
    r = do_login(client, '"><script>x</script>')
    assert "<script>x" not in r.text


def test_logout_beendet_session(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").text)
    assert token
    r = client.post("/logout", data={"csrf_token": token.group(1)}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303


def test_logout_ohne_csrf_abgelehnt(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    r = client.post("/logout", data={}, follow_redirects=False)
    assert r.status_code == 403
    assert client.get("/", follow_redirects=False).status_code == 200
