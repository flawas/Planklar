import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from tests.auth.conftest import PASSWORD, make_user


def login(client: TestClient, email: str, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return client.post("/auth/login", data={"username": email, "password": password})


def test_login_ok_setzt_sicheres_cookie(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    r = login(client, "a@buero-a.ch")
    assert r.status_code == 204
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_login_falsches_passwort(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    assert login(client, "a@buero-a.ch", "falsch").status_code == 400


def test_login_unbekannter_benutzer(client: TestClient, db: Session) -> None:
    assert login(client, "x@nirgends.ch").status_code == 400


def test_login_inaktiver_benutzer(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch", active=False)
    assert login(client, "a@buero-a.ch").status_code == 400


def test_geschuetzte_route_ohne_login_401(client: TestClient, db: Session) -> None:
    assert client.get("/auth/me").status_code == 401


def test_me_liefert_buero(client: TestClient, db: Session) -> None:
    user = make_user(db, "a@buero-a.ch")
    login(client, "a@buero-a.ch")
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "a@buero-a.ch"
    assert r.json()["buero_id"] == str(user.buero_id)
    assert "hashed_password" not in r.json()


def test_logout_beendet_session(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    login(client, "a@buero-a.ch")
    assert client.post("/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401


def test_logout_ohne_login_401(client: TestClient, db: Session) -> None:
    assert client.post("/auth/logout").status_code == 401


def test_keine_oeffentliche_registrierung(client: TestClient, db: Session) -> None:
    r = client.post("/auth/register", json={"email": "n@x.ch", "password": PASSWORD})
    assert r.status_code == 404


def test_admin_legt_benutzer_im_eigenen_buero_an(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@buero-a.ch", superuser=True)
    login(client, "admin@buero-a.ch")
    r = client.post("/admin/users", json={"email": "neu@buero-a.ch", "password": PASSWORD})
    assert r.status_code == 201
    assert r.json()["buero_id"] == str(admin.buero_id)
    assert r.json()["is_superuser"] is False
    client.cookies.clear()
    assert login(client, "neu@buero-a.ch").status_code == 204


def test_admin_endpunkt_nur_fuer_superuser(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    login(client, "a@buero-a.ch")
    r = client.post("/admin/users", json={"email": "neu@x.ch", "password": PASSWORD})
    assert r.status_code == 403


def test_admin_endpunkt_ohne_login_401(client: TestClient, db: Session) -> None:
    r = client.post("/admin/users", json={"email": "neu@x.ch", "password": PASSWORD})
    assert r.status_code == 401


def test_doppelte_email_409(client: TestClient, db: Session) -> None:
    make_user(db, "admin@buero-a.ch", superuser=True)
    login(client, "admin@buero-a.ch")
    r = client.post("/admin/users", json={"email": "admin@buero-a.ch", "password": PASSWORD})
    assert r.status_code == 409


def test_login_name_mit_wildcard_trifft_keinen_benutzer(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    make_user(db, "b@buero-a.ch")
    assert login(client, "%").status_code == 400
    assert login(client, "%@buero-a.ch").status_code == 400


def test_email_mit_unterstrich_ist_kein_duplikat(client: TestClient, db: Session) -> None:
    make_user(db, "admin@buero-a.ch", superuser=True)
    make_user(db, "aXb@x.ch")
    login(client, "admin@buero-a.ch")
    r = client.post("/admin/users", json={"email": "a_b@x.ch", "password": PASSWORD})
    assert r.status_code == 201


def test_login_ignoriert_gross_kleinschreibung(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    assert login(client, "A@Buero-A.ch").status_code == 204


def test_oidc_standardmaessig_deaktiviert() -> None:
    s = Settings()
    assert s.oidc_enabled is False


def test_oidc_aktiviert_ohne_umsetzung_schlaegt_laut_fehl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth.oidc import ensure_oidc_disabled

    monkeypatch.setenv("OIDC_ENABLED", "true")
    with pytest.raises(RuntimeError):
        ensure_oidc_disabled(Settings())


def test_fehlendes_secret_wird_abgelehnt(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth.users import get_auth_secret

    monkeypatch.setenv("AUTH_SECRET", "")
    with pytest.raises(RuntimeError):
        get_auth_secret()


def test_seed_admin_kann_sich_anmelden(client: TestClient, db: Session) -> None:
    from app.auth.seed import seed_admin

    user = seed_admin(db, "Büro Seed", "seed@buero.ch", PASSWORD)
    assert user.is_superuser
    assert login(client, "seed@buero.ch").status_code == 204
