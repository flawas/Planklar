import logging
import re
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.tokens import jetzt
from app.config import Settings
from app.db.models import Einladung, PasswortReset, Rolle, User
from app.mail import FakeMailer, Mail, MailError, SmtpMailer, get_mailer
from app.main import app
from tests.auth.conftest import PASSWORD, make_user
from tests.auth.test_auth import login

NEU = "neu-passwort-123"


@pytest.fixture
def mailer(client: TestClient) -> FakeMailer:
    fake = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: fake
    yield fake  # type: ignore[misc]
    app.dependency_overrides.pop(get_mailer, None)


def token_aus(mail: Mail) -> str:
    return re.search(r"/(?:einladung|passwort-reset)/(\S+)", mail.text).group(1)  # type: ignore[union-attr]


def einladen(client: TestClient, mailer: FakeMailer, email: str = "neu@x.ch") -> str:
    r = client.post("/admin/einladungen", json={"email": email})
    assert r.status_code == 201
    return token_aus(mailer.outbox[-1])


def admin_login(client: TestClient, db: Session) -> User:
    admin = make_user(db, "admin@a.ch", admin=True)
    login(client, "admin@a.ch")
    return admin


def test_einladung_einloesen_legt_benutzer_im_buero_an(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin = admin_login(client, db)
    token = einladen(client, mailer)
    assert mailer.outbox[0].an == "neu@x.ch"
    r = client.post("/auth/einladung/einloesen", json={"token": token, "password": NEU})
    assert r.status_code == 201
    assert r.json()["buero_id"] == str(admin.buero_id)
    user = db.execute(select(User).where(User.email == "neu@x.ch")).scalar_one()
    assert user.rolle == Rolle.MITARBEITER
    client.cookies.clear()
    assert login(client, "neu@x.ch", NEU).status_code == 204


def test_token_nur_gehasht_gespeichert(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    admin_login(client, db)
    token = einladen(client, mailer)
    row = db.execute(select(Einladung)).scalar_one()
    assert token not in (row.token_hash, row.email)
    assert len(row.token_hash) == 64
    assert row.expires_at - row.created_at <= timedelta(days=7, seconds=5)


def test_benutztes_token_fehler(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    admin_login(client, db)
    token = einladen(client, mailer)
    body = {"token": token, "password": NEU}
    assert client.post("/auth/einladung/einloesen", json=body).status_code == 201
    r = client.post("/auth/einladung/einloesen", json=body)
    assert (r.status_code, r.json()["detail"]) == (400, "TOKEN_USED")


def test_abgelaufenes_token_fehler(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    admin_login(client, db)
    token = einladen(client, mailer)
    row = db.execute(select(Einladung)).scalar_one()
    row.expires_at = jetzt() - timedelta(seconds=1)
    db.commit()
    r = client.post("/auth/einladung/einloesen", json={"token": token, "password": NEU})
    assert (r.status_code, r.json()["detail"]) == (400, "TOKEN_EXPIRED")
    assert db.execute(select(User).where(User.email == "neu@x.ch")).scalar_one_or_none() is None


def test_unbekanntes_token_fehler(client: TestClient, db: Session) -> None:
    r = client.post("/auth/einladung/einloesen", json={"token": "x", "password": NEU})
    assert (r.status_code, r.json()["detail"]) == (400, "TOKEN_INVALID")


def test_zu_kurzes_passwort(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    admin_login(client, db)
    token = einladen(client, mailer)
    r = client.post("/auth/einladung/einloesen", json={"token": token, "password": "kurz"})
    assert r.json()["detail"] == "INVALID_PASSWORD"


def test_bestehende_email_wird_abgewiesen(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    make_user(db, "da@x.ch")
    r = client.post("/admin/einladungen", json={"email": "DA@x.ch"})
    assert (r.status_code, r.json()["detail"]) == (409, "EMAIL_ALREADY_REGISTERED")
    assert mailer.outbox == []


def test_widerrufene_einladung_unbrauchbar(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    token = einladen(client, mailer)
    eid = client.get("/admin/einladungen").json()[0]["id"]
    assert client.delete(f"/admin/einladungen/{eid}").status_code == 204
    r = client.post("/auth/einladung/einloesen", json={"token": token, "password": NEU})
    assert r.json()["detail"] == "TOKEN_INVALID"


def test_zweite_einladung_derselben_adresse_wird_abgewiesen(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    einladen(client, mailer)
    r = client.post("/admin/einladungen", json={"email": "NEU@x.ch"})
    assert (r.status_code, r.json()["detail"]) == (409, "INVITATION_ALREADY_OPEN")
    assert len(mailer.outbox) == 1
    assert len(client.get("/admin/einladungen").json()) == 1


def test_nach_widerruf_ist_neue_einladung_moeglich(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    alt = einladen(client, mailer)
    eid = client.get("/admin/einladungen").json()[0]["id"]
    assert client.delete(f"/admin/einladungen/{eid}").status_code == 204
    neu = einladen(client, mailer)
    r = client.post("/auth/einladung/einloesen", json={"token": alt, "password": NEU})
    assert r.json()["detail"] == "TOKEN_INVALID"
    r = client.post("/auth/einladung/einloesen", json={"token": neu, "password": NEU})
    assert r.status_code == 201


def test_abgelaufene_einladung_blockiert_neue_nicht(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    einladen(client, mailer)
    alt = db.execute(select(Einladung)).scalar_one()
    alt.expires_at = jetzt() - timedelta(days=1)
    db.commit()
    einladen(client, mailer)


def test_user_email_eindeutig_ohne_gross_kleinschreibung(db: Session) -> None:
    make_user(db, "dup@x.ch")
    with pytest.raises(IntegrityError):
        make_user(db, "DUP@x.ch")
    db.rollback()


def test_fremdes_buero_kann_nicht_widerrufen_oder_sehen(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    einladen(client, mailer)
    eid = client.get("/admin/einladungen").json()[0]["id"]
    client.cookies.clear()
    make_user(db, "admin@b.ch", admin=True)
    login(client, "admin@b.ch")
    assert client.delete(f"/admin/einladungen/{eid}").status_code == 404
    assert client.get("/admin/einladungen").json() == []


def test_mitarbeiter_darf_nicht_einladen(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    make_user(db, "m@a.ch")
    login(client, "m@a.ch")
    assert client.post("/admin/einladungen", json={"email": "n@x.ch"}).status_code == 403
    assert client.get("/admin/einladungen").status_code == 403
    assert client.delete(f"/admin/einladungen/{Einladung.id.key}").status_code in (403, 422)


def test_einladung_ohne_login_401(client: TestClient, db: Session) -> None:
    assert client.post("/admin/einladungen", json={"email": "n@x.ch"}).status_code == 401


def test_reset_ablauf(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    make_user(db, "a@a.ch")
    r = client.post("/auth/passwort-reset/anfordern", json={"email": "a@a.ch"})
    assert r.status_code == 202
    token = token_aus(mailer.outbox[0])
    body = {"token": token, "password": NEU}
    assert client.post("/auth/passwort-reset/einloesen", json=body).status_code == 204
    assert login(client, "a@a.ch", NEU).status_code == 204
    assert login(client, "a@a.ch", PASSWORD).status_code == 400
    r = client.post("/auth/passwort-reset/einloesen", json=body)
    assert r.json()["detail"] == "TOKEN_USED"


def test_reset_antwort_verraet_existenz_nicht(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    make_user(db, "a@a.ch")
    bekannt = client.post("/auth/passwort-reset/anfordern", json={"email": "a@a.ch"})
    unbekannt = client.post("/auth/passwort-reset/anfordern", json={"email": "x@nirgends.ch"})
    assert (bekannt.status_code, bekannt.json()) == (unbekannt.status_code, unbekannt.json())
    assert len(mailer.outbox) == 1


def test_reset_abgelaufen(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    make_user(db, "a@a.ch")
    client.post("/auth/passwort-reset/anfordern", json={"email": "a@a.ch"})
    row = db.execute(select(PasswortReset)).scalar_one()
    row.expires_at = jetzt() - timedelta(seconds=1)
    db.commit()
    body = {"token": token_aus(mailer.outbox[0]), "password": NEU}
    r = client.post("/auth/passwort-reset/einloesen", json=body)
    assert r.json()["detail"] == "TOKEN_EXPIRED"


def test_keine_tokens_oder_mailinhalte_im_log(
    client: TestClient, db: Session, mailer: FakeMailer, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    admin_login(client, db)
    token = einladen(client, mailer, "geheim.person@x.ch")
    client.post("/auth/einladung/einloesen", json={"token": token, "password": NEU})
    client.post("/auth/passwort-reset/anfordern", json={"email": "geheim.person@x.ch"})
    reset = token_aus(mailer.outbox[-1])
    client.post("/auth/passwort-reset/einloesen", json={"token": reset, "password": NEU + "2"})
    log = caplog.text + "".join(str(getattr(r, "fields", "")) for r in caplog.records)
    for geheim in (token, reset, "geheim.person", NEU, "Konto einrichten"):
        assert geheim not in log


class _KaputtesSmtp:
    def __init__(self, *_: object, **__: object) -> None:
        raise OSError("verbindung mit geheim.person@x.ch verweigert")


def test_smtp_fehler_nur_als_code(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("app.mail.smtplib.SMTP", _KaputtesSmtp)
    s = Settings(smtp_host="mail.example", mail_from="liquet@example.ch")
    with pytest.raises(MailError) as exc:
        SmtpMailer(s).send(Mail("geheim.person@x.ch", "b", "t"))
    assert exc.value.code == "MAIL_SEND_FAILED"
    assert "geheim" not in str(exc.value) and exc.value.__cause__ is None


def test_smtp_ohne_konfiguration() -> None:
    with pytest.raises(MailError) as exc:
        SmtpMailer(Settings(smtp_host="")).send(Mail("a@x.ch", "b", "t"))
    assert exc.value.code == "MAIL_NOT_CONFIGURED"


def test_smtp_starttls_login_und_versand(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Smtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append(f"connect {host}:{port}")

        def __enter__(self) -> "Smtp":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def starttls(self) -> None:
            calls.append("starttls")

        def login(self, user: str, pw: str) -> None:
            calls.append(f"login {user}")

        def send_message(self, msg: object) -> None:
            calls.append("send")

    monkeypatch.setattr("app.mail.smtplib.SMTP", Smtp)
    s = Settings(smtp_host="h", smtp_port=2525, smtp_user="u", mail_from="f@x.ch")
    SmtpMailer(s).send(Mail("a@x.ch", "b", "t"))
    assert calls == ["connect h:2525", "starttls", "login u", "send"]


def test_erneut_senden_ersetzt_alte_einladung(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    alt = einladen(client, mailer)
    eid = client.get("/admin/einladungen").json()[0]["id"]
    r = client.post(f"/admin/einladungen/{eid}/erneut")
    assert r.status_code == 201
    neu = token_aus(mailer.outbox[-1])
    assert neu != alt
    r = client.post("/auth/einladung/einloesen", json={"token": alt, "password": NEU})
    assert r.json()["detail"] == "TOKEN_INVALID"
    r = client.post("/auth/einladung/einloesen", json={"token": neu, "password": NEU})
    assert r.status_code == 201


def test_erneut_senden_fremdes_oder_eingeloestes_404(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    admin_login(client, db)
    token = einladen(client, mailer)
    eid = client.get("/admin/einladungen").json()[0]["id"]
    client.post("/auth/einladung/einloesen", json={"token": token, "password": NEU})
    assert client.post(f"/admin/einladungen/{eid}/erneut").status_code == 404
    assert client.post(f"/admin/einladungen/{uuid.uuid4()}/erneut").status_code == 404
