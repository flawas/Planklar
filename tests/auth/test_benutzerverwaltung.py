import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Buero, Dossier, Kanton, Rolle, User, Vorhabenstyp
from tests.auth.conftest import PASSWORD, make_user
from tests.auth.test_auth import login


def _in_buero(db: Session, admin: User, email: str, **kw: object) -> User:
    user = User(buero_id=admin.buero_id, email=email, hashed_password="x", **kw)
    db.add(user)
    db.commit()
    return user


def test_liste_nur_eigenes_buero(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    _in_buero(db, admin, "m@a.ch")
    make_user(db, "fremd@b.ch")
    login(client, "admin@a.ch")
    r = client.get("/admin/users")
    assert r.status_code == 200
    assert [u["email"] for u in r.json()] == ["admin@a.ch", "m@a.ch"]
    assert r.json()[0]["rolle"] == "buero_admin"


def test_mitarbeiter_erhaelt_403(client: TestClient, db: Session) -> None:
    user = make_user(db, "m@a.ch")
    login(client, "m@a.ch")
    assert client.get("/admin/users").status_code == 403
    assert client.patch(f"/admin/users/{user.id}", json={"is_active": False}).status_code == 403
    assert client.delete(f"/admin/users/{user.id}").status_code == 403


def test_rolle_aendern_und_deaktivieren(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    m = _in_buero(db, admin, "m@a.ch")
    login(client, "admin@a.ch")
    r = client.patch(f"/admin/users/{m.id}", json={"rolle": "buero_admin"})
    assert r.status_code == 200
    assert r.json()["rolle"] == "buero_admin"
    r = client.patch(f"/admin/users/{m.id}", json={"is_active": False})
    assert r.json()["is_active"] is False
    assert r.json()["rolle"] == "buero_admin"


def test_fremder_benutzer_404(client: TestClient, db: Session) -> None:
    make_user(db, "admin@a.ch", admin=True)
    fremd = make_user(db, "fremd@b.ch", admin=True)
    login(client, "admin@a.ch")
    assert client.patch(f"/admin/users/{fremd.id}", json={"is_active": False}).status_code == 404
    assert (
        client.patch(f"/admin/users/{fremd.id}", json={"rolle": "mitarbeiter"}).status_code == 404
    )
    assert client.delete(f"/admin/users/{fremd.id}").status_code == 404
    assert client.patch(f"/admin/users/{uuid.uuid4()}", json={}).status_code == 404
    db.refresh(fremd)
    assert fremd.is_active and fremd.rolle == Rolle.BUERO_ADMIN


def test_letzter_admin_geschuetzt(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    login(client, "admin@a.ch")
    url = f"/admin/users/{admin.id}"
    assert client.patch(url, json={"rolle": "mitarbeiter"}).status_code == 409
    assert client.patch(url, json={"is_active": False}).status_code == 409
    assert client.delete(url).status_code == 409
    db.refresh(admin)
    assert admin.is_active and admin.rolle == Rolle.BUERO_ADMIN


def test_admin_darf_sich_degradieren_wenn_weiterer_admin_existiert(
    client: TestClient, db: Session
) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    _in_buero(db, admin, "zweiter@a.ch", rolle=Rolle.BUERO_ADMIN)
    login(client, "admin@a.ch")
    assert (
        client.patch(f"/admin/users/{admin.id}", json={"rolle": "mitarbeiter"}).status_code == 200
    )


def test_inaktiver_zweiter_admin_zaehlt_nicht(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    _in_buero(db, admin, "zweiter@a.ch", rolle=Rolle.BUERO_ADMIN, is_active=False)
    login(client, "admin@a.ch")
    assert client.delete(f"/admin/users/{admin.id}").status_code == 409


def test_loeschen_behaelt_dossiers(client: TestClient, db: Session) -> None:
    admin = make_user(db, "admin@a.ch", admin=True)
    m = _in_buero(db, admin, "m@a.ch")
    dossier = Dossier(
        buero_id=admin.buero_id,
        kanton=Kanton.LU,
        gemeinde="Luzern",
        vorhabenstyp=next(iter(Vorhabenstyp)),
    )
    db.add(dossier)
    db.commit()
    m_id = m.id
    login(client, "admin@a.ch")
    assert client.delete(f"/admin/users/{m_id}").status_code == 204
    db.expire_all()
    assert db.get(User, m_id) is None
    assert db.get(Dossier, dossier.id) is not None


def test_passwort_aendern(client: TestClient, db: Session) -> None:
    make_user(db, "m@a.ch")
    login(client, "m@a.ch")
    r = client.post(
        "/auth/me/password", json={"old_password": PASSWORD, "new_password": "neues-passwort-1"}
    )
    assert r.status_code == 204
    client.cookies.clear()
    assert login(client, "m@a.ch").status_code == 400
    assert login(client, "m@a.ch", "neues-passwort-1").status_code == 204


def test_passwort_aendern_altes_falsch(client: TestClient, db: Session) -> None:
    make_user(db, "m@a.ch")
    login(client, "m@a.ch")
    r = client.post(
        "/auth/me/password", json={"old_password": "falsch", "new_password": "neues-passwort-1"}
    )
    assert r.status_code == 400
    client.cookies.clear()
    assert login(client, "m@a.ch").status_code == 204


def test_passwort_aendern_zu_kurz(client: TestClient, db: Session) -> None:
    make_user(db, "m@a.ch")
    login(client, "m@a.ch")
    r = client.post("/auth/me/password", json={"old_password": PASSWORD, "new_password": "kurz"})
    assert r.status_code == 400


def test_passwort_aendern_ohne_login_401(client: TestClient, db: Session) -> None:
    r = client.post("/auth/me/password", json={"old_password": "a", "new_password": "b"})
    assert r.status_code == 401


def test_szenario_buero_a_admin_sieht_und_aendert_buero_b_nicht(
    client: TestClient, db: Session
) -> None:
    make_user(db, "admin@a.ch", admin=True)
    b_admin = make_user(db, "admin@b.ch", admin=True)
    b_user = _in_buero(db, b_admin, "m@b.ch")
    login(client, "admin@a.ch")
    emails = [u["email"] for u in client.get("/admin/users").json()]
    assert not any(e.endswith("@b.ch") for e in emails)
    for target in (b_admin, b_user):
        assert (
            client.patch(f"/admin/users/{target.id}", json={"is_active": False}).status_code == 404
        )
        assert (
            client.patch(f"/admin/users/{target.id}", json={"rolle": "mitarbeiter"}).status_code
            == 404
        )
        assert client.delete(f"/admin/users/{target.id}").status_code == 404
    db.expire_all()
    rest = db.execute(select(User).where(User.buero_id == b_admin.buero_id)).scalars().all()
    assert len(rest) == 2 and all(u.is_active for u in rest)
    assert db.get(Buero, b_admin.buero_id) is not None
