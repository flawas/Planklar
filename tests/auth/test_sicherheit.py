"""Login-Rate-Limit, Audit-Log und Session-Invalidierung (Issue #142)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db.models import AuditEreignis, LoginFehlversuch, User
from tests.auth.conftest import PASSWORD, make_user
from tests.auth.test_auth import login


@pytest.fixture(autouse=True)
def _grenzen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGIN_MAX_FEHLVERSUCHE_EMAIL", "3")
    monkeypatch.setenv("LOGIN_MAX_FEHLVERSUCHE_IP", "5")
    get_settings.cache_clear()


def _aktionen(db: Session) -> list[str]:
    db.expire_all()
    stmt = select(AuditEreignis.aktion).order_by(AuditEreignis.zeitpunkt, AuditEreignis.id)
    return list(db.execute(stmt).scalars())


# --- Rate-Limit ---


def test_sperre_nach_fehlversuchen_pro_email(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    for _ in range(3):
        assert login(client, "a@a.ch", "falsch").status_code == 400
    r = login(client, "a@a.ch", "falsch")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0


def test_sperre_gilt_auch_fuer_richtiges_passwort(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    for _ in range(3):
        login(client, "a@a.ch", "falsch")
    assert login(client, "a@a.ch").status_code == 429


def test_unbekannte_email_wird_gleich_gezaehlt(client: TestClient, db: Session) -> None:
    for _ in range(3):
        assert login(client, "x@nirgends.ch").status_code == 400
    assert login(client, "x@nirgends.ch").status_code == 429


def test_email_gross_klein_zaehlt_gleich(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    for mail in ("A@a.ch", "a@A.ch", "a@a.ch"):
        login(client, mail, "falsch")
    assert login(client, "a@a.ch").status_code == 429


def test_sperre_pro_email_trifft_andere_konten_nicht(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    make_user(db, "b@b.ch")
    for _ in range(3):
        login(client, "a@a.ch", "falsch")
    assert login(client, "b@b.ch").status_code == 204


def test_sperre_pro_ip(client: TestClient, db: Session) -> None:
    make_user(db, "b@b.ch")
    for i in range(5):
        assert login(client, f"x{i}@nirgends.ch", "falsch").status_code == 400
    assert login(client, "b@b.ch").status_code == 429


def test_erfolg_setzt_email_zaehler_zurueck(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    for _ in range(2):
        login(client, "a@a.ch", "falsch")
    assert login(client, "a@a.ch").status_code == 204
    for _ in range(2):
        assert login(client, "a@a.ch", "falsch").status_code == 400


def test_sperre_endet_nach_fenster(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user(db, "a@a.ch")
    for _ in range(3):
        login(client, "a@a.ch", "falsch")
    assert login(client, "a@a.ch").status_code == 429
    monkeypatch.setenv("LOGIN_FENSTER_SEKUNDEN", "0")
    get_settings.cache_clear()
    assert login(client, "a@a.ch").status_code == 204


def test_fehlversuche_speichern_keine_klartextdaten(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    login(client, "a@a.ch", "falsch")
    db.expire_all()
    zeilen = db.execute(select(LoginFehlversuch)).scalars().all()
    assert zeilen
    for z in zeilen:
        assert "a@a.ch" not in f"{z.art}{z.schluessel}"
        assert "testclient" not in z.schluessel


def test_web_login_sperre(client: TestClient, db: Session) -> None:
    from app.web import csrf

    make_user(db, "a@a.ch")
    token = csrf.new_token()
    client.cookies.set(csrf.CSRF_COOKIE, token)

    def versuch(pw: str):  # type: ignore[no-untyped-def]
        return client.post(
            "/login",
            data={"email": "a@a.ch", "password": pw, "csrf_token": token},
            follow_redirects=False,
        )

    for _ in range(3):
        assert versuch("falsch").status_code == 400
    r = versuch(PASSWORD)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


# --- Audit ---


def test_audit_login_ereignisse(client: TestClient, db: Session) -> None:
    user = make_user(db, "a@a.ch")
    login(client, "a@a.ch", "falsch")
    login(client, "a@a.ch")
    assert _aktionen(db) == [audit.LOGIN_FEHLGESCHLAGEN, audit.LOGIN_OK]
    ereignis = db.execute(select(AuditEreignis)).scalars().first()
    assert ereignis is not None
    assert ereignis.user_id == user.id
    assert ereignis.buero_id == user.buero_id


def test_audit_gesperrter_login(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    for _ in range(4):
        login(client, "a@a.ch", "falsch")
    assert _aktionen(db).count(audit.LOGIN_GESPERRT) == 1


def test_audit_benutzeraktionen(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    login(client, "admin@a.ch")
    r = client.post("/admin/users", json={"email": "neu@a.ch", "password": "langes-passwort-1"})
    neu_id = uuid.UUID(r.json()["id"])
    client.patch(f"/admin/users/{neu_id}", json={"rolle": "buero_admin"})
    client.patch(f"/admin/users/{neu_id}", json={"is_active": False})
    client.patch(f"/admin/users/{neu_id}", json={"is_active": True})
    client.delete(f"/admin/users/{neu_id}")
    assert _aktionen(db)[1:] == [
        audit.USER_ANGELEGT,
        audit.USER_ROLLE_GEAENDERT,
        audit.USER_DEAKTIVIERT,
        audit.USER_AKTIVIERT,
        audit.USER_GELOESCHT,
    ]
    ereignisse = db.execute(
        select(AuditEreignis).where(AuditEreignis.aktion == audit.USER_GELOESCHT)
    ).scalar_one()
    assert (ereignisse.buero_id, ereignisse.user_id, ereignisse.objekt_id) == (
        admin.buero_id,
        admin.id,
        neu_id,
    )
    assert ereignisse.objekt_typ == "user"


def test_audit_ohne_aenderung_kein_ereignis(client: TestClient, db: Session) -> None:
    make_user(db, "admin@a.ch", admin=True)
    login(client, "admin@a.ch")
    me = client.get("/auth/me").json()["id"]
    client.patch(f"/admin/users/{me}", json={"rolle": "buero_admin"})
    assert _aktionen(db) == [audit.LOGIN_OK]


def test_audit_passwortaenderung(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    login(client, "a@a.ch")
    r = client.post(
        "/auth/me/password", json={"old_password": PASSWORD, "new_password": "neues-passwort-1"}
    )
    assert r.status_code == 204
    assert _aktionen(db)[-1] == audit.PASSWORT_GEAENDERT


def test_audit_enthaelt_keine_personendaten(client: TestClient, db: Session) -> None:
    make_user(db, "geheim@personen.ch", admin=True)
    login(client, "geheim@personen.ch", "falsch")
    login(client, "unbekannt@personen.ch", "falsch")
    login(client, "geheim@personen.ch")
    r = client.post(
        "/admin/users", json={"email": "neu@personen.ch", "password": "langes-passwort-1"}
    )
    client.delete(f"/admin/users/{r.json()['id']}")
    db.expire_all()
    spalten = {c.name for c in AuditEreignis.__table__.columns}
    assert spalten == {
        "id",
        "buero_id",
        "user_id",
        "aktion",
        "objekt_typ",
        "objekt_id",
        "zeitpunkt",
    }
    for e in db.execute(select(AuditEreignis)).scalars():
        werte = " ".join(str(getattr(e, s)) for s in spalten)
        assert "personen.ch" not in werte
        assert "langes-passwort" not in werte


# --- Session-Invalidierung ---


def _zweiter_client(db: Session, email: str) -> TestClient:
    from app.main import app

    c = TestClient(app, base_url="https://testserver")
    assert login(c, email).status_code == 204
    assert c.get("/auth/me").status_code == 200
    return c


def test_session_bei_deaktivierung_ungueltig(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    ziel = User(buero_id=admin.buero_id, email="m@a.ch", hashed_password=admin.hashed_password)
    db.add(ziel)
    db.commit()
    sitzung = _zweiter_client(db, "m@a.ch")
    login(client, "admin@a.ch")
    client.patch(f"/admin/users/{ziel.id}", json={"is_active": False})
    assert sitzung.get("/auth/me").status_code == 401
    # Reaktivierung belebt die alte Sitzung nicht wieder
    client.patch(f"/admin/users/{ziel.id}", json={"is_active": True})
    assert sitzung.get("/auth/me").status_code == 401
    assert login(sitzung, "m@a.ch").status_code == 204
    assert sitzung.get("/auth/me").status_code == 200


def test_session_bei_rollenwechsel_ungueltig(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    ziel = User(buero_id=admin.buero_id, email="m@a.ch", hashed_password=admin.hashed_password)
    db.add(ziel)
    db.commit()
    sitzung = _zweiter_client(db, "m@a.ch")
    login(client, "admin@a.ch")
    client.patch(f"/admin/users/{ziel.id}", json={"rolle": "buero_admin"})
    assert sitzung.get("/auth/me").status_code == 401


def test_session_bei_passwortaenderung_ungueltig(client: TestClient, db: Session) -> None:
    make_user(db, "a@a.ch")
    login(client, "a@a.ch")
    zweite = _zweiter_client(db, "a@a.ch")
    r = client.post(
        "/auth/me/password", json={"old_password": PASSWORD, "new_password": "neues-passwort-1"}
    )
    assert r.status_code == 204
    assert zweite.get("/auth/me").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert login(client, "a@a.ch", "neues-passwort-1").status_code == 204


def test_session_ohne_aenderung_bleibt_gueltig(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    login(client, "admin@a.ch")
    client.patch(f"/admin/users/{admin.id}", json={"rolle": "buero_admin"})
    assert client.get("/auth/me").status_code == 200
