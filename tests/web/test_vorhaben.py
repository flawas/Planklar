import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Dossier
from tests.auth.conftest import make_user
from tests.web.test_login import do_login

HX = {"HX-Request": "true"}


def start(client: TestClient, db: Session, email: str = "a@buero-a.ch") -> str:
    make_user(db, email)
    do_login(client, email)
    r = client.get("/vorhaben/neu")
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m
    return m.group(1)


def post(client: TestClient, tok: str, **data: str):  # type: ignore[no-untyped-def]
    return client.post(
        "/vorhaben/schritt",
        data={"csrf_token": tok, **data},
        headers=HX,
        follow_redirects=False,
    )


def test_ohne_login_umleitung(client: TestClient, db: Session) -> None:
    assert client.get("/vorhaben/neu", follow_redirects=False).status_code == 303


def test_seite_schritt_eins_barrierefrei(client: TestClient, db: Session) -> None:
    start(client, db)
    r = client.get("/vorhaben/neu")
    assert r.status_code == 200
    assert "Das Tool gibt Hinweise und entscheidet nichts." in r.text
    assert "Schritt 1 von 5: Kanton" in r.text
    assert '<label for="kanton-1">Luzern</label>' in r.text
    assert 'aria-current="step"' in r.text and "<legend>" in r.text


def test_gemeinde_haengt_vom_kanton_ab(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = post(client, tok, schritt="1", aktion="weiter", kanton="LU")
    assert r.status_code == 200 and "<html" not in r.text
    assert "Weggis" in r.text and "Küssnacht" not in r.text
    r = post(client, tok, schritt="1", aktion="weiter", kanton="SZ")
    assert "Küssnacht" in r.text and "Weggis" not in r.text


def test_validierung_und_fremde_gemeinde(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = post(client, tok, schritt="1", aktion="weiter")
    assert r.status_code == 422 and "Bitte treffen Sie eine Auswahl." in r.text
    r = post(client, tok, schritt="2", aktion="weiter", kanton="LU", gemeinde="Küssnacht")
    assert r.status_code == 422
    r = post(client, tok, schritt="9", aktion="weiter")
    assert r.status_code == 400


def test_zurueck_behaelt_werte(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = post(client, tok, schritt="3", aktion="zurueck", kanton="LU", gemeinde="Weggis")
    assert "Schritt 2 von 5" in r.text and "checked" in r.text


def test_attribute_je_vorhabenstyp(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    basis = {"kanton": "LU", "gemeinde": "Luzern", "verfahren": "ordentlich"}
    r = post(client, tok, schritt="4", aktion="weiter", vorhabenstyp="neubau_efh_mfh", **basis)
    assert "Schritt 5 von 5" in r.text and "Gebäudehöhe" in r.text and "Heizsystem" in r.text
    r = post(
        client,
        tok,
        schritt="4",
        aktion="weiter",
        vorhabenstyp="heizungsersatz_waermepumpe",
        **basis,
    )
    assert "Gebäudehöhe" not in r.text and "Heizsystem" in r.text


def test_abschluss_speichert_und_oeffnet_dossier(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = post(
        client,
        tok,
        schritt="5",
        aktion="fertig",
        kanton="SZ",
        gemeinde="Küssnacht",
        vorhabenstyp="neubau_efh_mfh",
        verfahren="vereinfacht",
        gewaesserbezug="nein",
        kantonsstrassenbezug="ja",
        waldbezug="nein",
        ausserhalb_bauzone="nein",
        gebaeudehoehe_m="9,5",
        heizsystem="Wärmepumpe",
    )
    assert r.status_code == 204
    d = db.scalars(select(Dossier)).one()
    assert r.headers["HX-Redirect"] == f"/dossiers/{d.id}/ansicht"
    assert d.gemeinde == "Küssnacht" and d.attribute["kantonsstrassenbezug"] is True
    assert d.attribute["gebaeudehoehe_m"] == 9.5 and d.attribute["verfahren"] == "vereinfacht"
    assert client.get(r.headers["HX-Redirect"]).status_code == 200


def test_abschluss_ohne_js_leitet_um(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = client.post(
        "/vorhaben/schritt",
        data={
            "csrf_token": tok, "schritt": "5", "aktion": "fertig", "kanton": "LU",
            "gemeinde": "Luzern", "vorhabenstyp": "umbau_anbau", "verfahren": "ordentlich",
            "gewaesserbezug": "nein", "kantonsstrassenbezug": "nein", "waldbezug": "nein",
            "ausserhalb_bauzone": "nein",
        },
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].endswith("/ansicht")


def test_abschluss_unvollstaendig_und_csrf(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = post(
        client, tok, schritt="5", aktion="fertig", kanton="LU", gemeinde="Luzern",
        vorhabenstyp="umbau_anbau", verfahren="ordentlich", gebaeudehoehe_m="abc",
    )  # fmt: skip
    assert r.status_code == 422
    assert "Bitte wählen Sie Ja oder Nein." in r.text and "Bitte geben Sie eine Zahl" in r.text
    assert db.scalars(select(Dossier)).all() == []
    assert post(client, "falsch", schritt="1", aktion="weiter", kanton="LU").status_code == 403


def test_abschluss_ohne_verfahren_ergibt_422(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    r = post(
        client, tok, schritt="5", aktion="fertig", kanton="LU", gemeinde="Luzern",
        vorhabenstyp="umbau_anbau", gewaesserbezug="nein", kantonsstrassenbezug="nein",
        waldbezug="nein", ausserhalb_bauzone="nein",
    )  # fmt: skip
    assert r.status_code == 422
    assert db.scalars(select(Dossier)).all() == []


def _angelegt(client: TestClient, db: Session, tok: str) -> Dossier:
    post(
        client,
        tok,
        schritt="5",
        aktion="fertig",
        kanton="SZ",
        gemeinde="Küssnacht",
        vorhabenstyp="neubau_efh_mfh",
        verfahren="vereinfacht",
        gewaesserbezug="nein",
        kantonsstrassenbezug="ja",
        waldbezug="nein",
        ausserhalb_bauzone="nein",
        gebaeudehoehe_m="9,5",
    )
    return db.scalars(select(Dossier)).one()


def test_bearbeiten_vorbefuellt_und_speichert(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    d = _angelegt(client, db, tok)
    r = client.get(f"/dossiers/{d.id}/bearbeiten")
    assert r.status_code == 200 and "Vorhaben bearbeiten" in r.text
    assert re.search(r'value="SZ"\s+checked', r.text)
    r = post(
        client,
        tok,
        schritt="5",
        aktion="fertig",
        dossier_id=str(d.id),
        kanton="SZ",
        gemeinde="Freienbach",
        vorhabenstyp="neubau_efh_mfh",
        verfahren="ordentlich",
        gewaesserbezug="ja",
        kantonsstrassenbezug="ja",
        waldbezug="nein",
        ausserhalb_bauzone="nein",
    )
    assert r.status_code == 204 and r.headers["HX-Redirect"] == f"/dossiers/{d.id}/ansicht"
    db.expire_all()
    assert db.scalars(select(Dossier)).one().gemeinde == "Freienbach"
    d = db.scalars(select(Dossier)).one()
    assert d.attribute["gewaesserbezug"] is True and d.attribute["verfahren"] == "ordentlich"


def test_bearbeiten_fremdes_dossier_404(client: TestClient, db: Session) -> None:
    tok = start(client, db)
    d = _angelegt(client, db, tok)
    make_user(db, "b@buero-b.ch")
    do_login(client, "b@buero-b.ch")
    assert client.get(f"/dossiers/{d.id}/bearbeiten").status_code == 404
    r = post(
        client,
        tok,
        schritt="5",
        aktion="fertig",
        dossier_id=str(d.id),
        kanton="SZ",
        gemeinde="Freienbach",
        vorhabenstyp="neubau_efh_mfh",
        verfahren="ordentlich",
        gewaesserbezug="ja",
        kantonsstrassenbezug="ja",
        waldbezug="nein",
        ausserhalb_bauzone="nein",
    )
    assert r.status_code == 404
