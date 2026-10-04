import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Einladung
from app.mail import FakeMailer, get_mailer
from app.main import app
from tests.auth.conftest import make_user
from tests.web.test_login import csrf_token, do_login


def admin_session(client: TestClient, db: Session, mailer: FakeMailer) -> str:
    app.dependency_overrides[get_mailer] = lambda: mailer
    make_user(db, "admin@a.ch", admin=True)
    assert do_login(client, "admin@a.ch").status_code == 303
    return csrf_token(client)


def einladen(client: TestClient, token: str, email: str = "neu@x.ch"):  # type: ignore[no-untyped-def]
    return client.post("/einladungen", data={"email": email, "csrf_token": token})


def test_einladen_zeigt_eintrag_und_versendet_mail(client: TestClient, db: Session) -> None:
    mailer = FakeMailer()
    token = admin_session(client, db, mailer)
    r = einladen(client, token)
    assert r.status_code == 200
    assert "Einladung versandt" in r.text and "neu@x.ch" in r.text
    assert len(mailer.outbox) == 1
    app.dependency_overrides.pop(get_mailer, None)


def test_zweite_einladung_zeigt_hinweis_statt_duplikat(client: TestClient, db: Session) -> None:
    mailer = FakeMailer()
    token = admin_session(client, db, mailer)
    einladen(client, token)
    r = einladen(client, token, "NEU@x.ch")
    assert r.status_code == 409
    assert "bereits eine offene Einladung" in r.text
    assert "Erneut senden" in r.text
    assert len(db.execute(select(Einladung)).scalars().all()) == 1
    app.dependency_overrides.pop(get_mailer, None)


def test_erneut_senden_und_widerrufen(client: TestClient, db: Session) -> None:
    mailer = FakeMailer()
    token = admin_session(client, db, mailer)
    einladen(client, token)
    eid = db.execute(select(Einladung.id)).scalar_one()
    r = client.post(f"/einladungen/{eid}/erneut", data={"csrf_token": token})
    assert r.status_code == 200 and len(mailer.outbox) == 2
    offen = db.execute(select(Einladung).where(Einladung.revoked_at.is_(None))).scalar_one()
    r = client.post(f"/einladungen/{offen.id}/widerruf", data={"csrf_token": token})
    assert "Einladung widerrufen" in r.text
    assert not re.search(r"/widerruf", r.text)
    app.dependency_overrides.pop(get_mailer, None)


def test_mitarbeiter_und_csrf(client: TestClient, db: Session) -> None:
    mailer = FakeMailer()
    admin_session(client, db, mailer)
    assert einladen(client, "falsch").status_code == 403
    client.cookies.clear()
    make_user(db, "ma@a.ch")
    do_login(client, "ma@a.ch")
    assert client.get("/einladungen").status_code == 403
    assert einladen(client, csrf_token(client)).status_code == 403
    app.dependency_overrides.pop(get_mailer, None)
