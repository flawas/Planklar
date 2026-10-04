from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Kanton, Vorhabenstyp
from tests.auth.conftest import make_user
from tests.dossiers.test_upload import make_dossier
from tests.web.test_login import do_login


def test_uebersicht_leer(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    r = client.get("/vorhaben")
    assert r.status_code == 200 and "Noch keine Vorhaben erfasst." in r.text


def test_uebersicht_zeigt_nur_eigene_vorhaben_neueste_zuerst(
    client: TestClient, db: Session
) -> None:
    a = make_user(db, "a@buero-a.ch")
    b = make_user(db, "b@buero-b.ch")
    make_dossier(db, a)
    zweites = make_dossier(db, a)
    zweites.gemeinde = "Weggis"
    zweites.kanton = Kanton.LU
    zweites.vorhabenstyp = Vorhabenstyp.UMBAU_ANBAU
    fremd = make_dossier(db, b)
    fremd.gemeinde = "Küssnacht"
    db.commit()
    do_login(client, "a@buero-a.ch")
    html = client.get("/vorhaben").text
    assert "Küssnacht" not in html
    assert html.index("Weggis") < html.index("Luzern")  # neueste zuerst
    assert "Umbau oder Anbau" in html
    assert f"/dossiers/{zweites.id}/ansicht" in html
    assert "Noch keine" in html  # keine Prüfung


def test_uebersicht_ohne_login_leitet_um(client: TestClient) -> None:
    r = client.get("/vorhaben", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_startseite_verlinkt_uebersicht(client: TestClient, db: Session) -> None:
    make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    assert 'href="/vorhaben"' in client.get("/").text
