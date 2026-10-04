import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Befund, Dokument, Dossier, Ergebnis, Pruefstatus, Pruefung, Seite, User
from app.dossiers.scope import BueroScope
from app.storage import Storage
from tests.auth.conftest import make_user
from tests.dossiers.conftest import make_pdf
from tests.dossiers.conftest import storage as storage  # noqa: F401
from tests.dossiers.test_upload import make_dossier
from tests.web.test_login import do_login

ERFUELLT = "LU-PBV55-1-baugesuchsformular"
MANUELL = "LU-PBV56-1-unterschriftenblatt"
FEHLT = "LU-PBV55-2a-situationsplan"


@pytest.fixture
def bericht(
    client: TestClient,
    db: Session,
    storage: Storage,  # noqa: F811
) -> Iterator[tuple[User, Dossier, Pruefung, dict[str, Befund], Seite]]:
    user = make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    dossier = make_dossier(db, user)
    scope = BueroScope(db, user.buero_id)
    data = make_pdf(2)
    from app.dossiers.service import upload_dokument

    upload_dokument(db, storage, dossier, "plan.pdf", data, 10**8)
    dok = db.scalars(select(Dokument).where(Dokument.dossier_id == dossier.id)).one()
    seite = Seite(dokument_id=dok.id, nummer=2)
    db.add(seite)
    db.flush()
    pruefung = scope.add_pruefung(dossier.id, regelset_hash="a" * 64, modellversion="fake")
    scope.update_pruefung(pruefung.id, status=Pruefstatus.ABGESCHLOSSEN)
    befunde = {
        ERFUELLT: scope.add_befund(
            pruefung.id, regel_id=ERFUELLT, ergebnis=Ergebnis.ERFUELLT, belege=[str(seite.id)]
        ),
        MANUELL: scope.add_befund(pruefung.id, regel_id=MANUELL, ergebnis=Ergebnis.MANUELL),
        FEHLT: scope.add_befund(pruefung.id, regel_id=FEHLT, ergebnis=Ergebnis.FEHLT),
    }
    db.commit()
    yield user, dossier, pruefung, befunde, seite


def url(dossier: Dossier, pruefung: Pruefung, suffix: str = "bericht") -> str:
    return f"/dossiers/{dossier.id}/pruefungen/{pruefung.id}/{suffix}"


def token(client: TestClient, dossier: Dossier) -> str:
    m = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get(f"/dossiers/{dossier.id}/ansicht").text
    )
    assert m
    return m.group(1)


def test_bericht_zeigt_ampel_mit_text_symbol_und_quelle(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    r = client.get(url(dossier, pruefung))
    assert r.status_code == 200
    for text in ("Erfüllt", "Fehlt", "Manuell prüfen", "Unsicher"):
        assert text in r.text
    for symbol in ("✓", "✗", "✎"):
        assert symbol in r.text
    assert "PBV LU (SRL Nr. 736)" in r.text and "§ 55 Abs. 1" in r.text
    assert "https://srl.lu.ch/" in r.text
    assert "Stand 2026-10-03" in r.text
    assert "Das Tool gibt Hinweise und entscheidet nichts." in r.text
    assert "bewillig" in r.text.lower()  # Hinweis: keine Aussage zur Bewilligung
    assert "wird bewilligt" not in r.text.lower()


def test_bericht_sortiert_kritisches_zuerst(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    html = client.get(url(dossier, pruefung)).text
    assert FEHLT in html and MANUELL in html
    assert html.index(FEHLT) < html.index(MANUELL)
    assert html.index("ampel-fehlt") < html.index("ampel-erfuellt")


def test_beleg_mit_vorschau_url(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    html = client.get(url(dossier, pruefung)).text
    assert "Beleg: plan.pdf, Seite 2" in html
    m = re.search(r'src="(/vorschau/[^"]+)"', html)
    assert m
    img = client.get(m.group(1))
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")


def test_bericht_fremdbuero_404(client: TestClient, db: Session, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    client.cookies.clear()
    make_user(db, "b@buero-b.ch")
    do_login(client, "b@buero-b.ch")
    assert client.get(url(dossier, pruefung)).status_code == 404
    assert client.get(url(dossier, pruefung, "bericht.pdf")).status_code == 404


def test_bericht_ohne_login_leitet_um(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    client.cookies.clear()
    r = client.get(url(dossier, pruefung), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_laufender_lauf_zeigt_fortschritt_und_pollt(  # type: ignore[no-untyped-def]
    client: TestClient, db: Session, bericht
) -> None:
    user, dossier, pruefung, _, _ = bericht
    BueroScope(db, user.buero_id).update_pruefung(
        pruefung.id, status=Pruefstatus.LAEUFT, seiten_gesamt=4, seiten_fertig=1
    )
    db.commit()
    html = client.get(url(dossier, pruefung)).text
    assert "1 von 4 Seiten" in html and 'hx-trigger="every 3s"' in html


def test_override_ueber_htmx_teilupdate(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    tok = token(client, dossier)
    ziel = url(dossier, pruefung, f"befunde/{befunde[FEHLT].id}/override")
    r = client.post(
        ziel,
        data={"csrf_token": tok, "ergebnis": "erfüllt", "begruendung": "Liegt als Papier bei"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert r.text.lstrip().startswith("<article")  # nur der Befund, keine ganze Seite
    assert "Liegt als Papier bei" in r.text and "Übersteuert von «Fehlt» zu «Erfüllt»" in r.text
    assert r.headers["hx-retarget"] == f"#befund-{befunde[FEHLT].id}"


def test_override_ohne_begruendung_abgelehnt(client: TestClient, db: Session, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    r = client.post(
        url(dossier, pruefung, f"befunde/{befunde[FEHLT].id}/override"),
        data={"csrf_token": token(client, dossier), "ergebnis": "erfüllt", "begruendung": "  "},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 422 and "Begründung" in r.text
    db.expire_all()
    assert db.get(Befund, befunde[FEHLT].id).override_ergebnis is None  # type: ignore[union-attr]


def test_override_ohne_js_leitet_zum_bericht(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    r = client.post(
        url(dossier, pruefung, f"befunde/{befunde[FEHLT].id}/override"),
        data={"csrf_token": token(client, dossier), "ergebnis": "unsicher", "begruendung": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith(url(dossier, pruefung))


def test_override_ohne_csrf_verweigert(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    r = client.post(
        url(dossier, pruefung, f"befunde/{befunde[FEHLT].id}/override"),
        data={"csrf_token": "falsch", "ergebnis": "erfüllt", "begruendung": "x"},
    )
    assert r.status_code == 403


def test_manuell_abhaken_und_zuruecknehmen(client: TestClient, db: Session, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    tok = token(client, dossier)
    basis = f"befunde/{befunde[MANUELL].id}"
    r = client.post(
        url(dossier, pruefung, f"{basis}/bestaetigen"),
        data={"csrf_token": tok},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200 and "Manuell geprüft und bestätigt." in r.text
    db.expire_all()
    b = db.get(Befund, befunde[MANUELL].id)
    assert b and b.ergebnis == Ergebnis.MANUELL and b.override_ergebnis == Ergebnis.ERFUELLT
    r = client.post(
        url(dossier, pruefung, f"{basis}/zuruecksetzen"),
        data={"csrf_token": tok},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Befund, befunde[MANUELL].id).override_ergebnis is None  # type: ignore[union-attr]


def test_abhaken_nur_bei_manuell(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    r = client.post(
        url(dossier, pruefung, f"befunde/{befunde[FEHLT].id}/bestaetigen"),
        data={"csrf_token": token(client, dossier)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 409


def test_override_fremdbuero_404(client: TestClient, db: Session, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, befunde, _ = bericht
    client.cookies.clear()
    make_user(db, "b@buero-b.ch")
    do_login(client, "b@buero-b.ch")
    other = make_dossier(db, db.scalars(select(User).where(User.email == "b@buero-b.ch")).one())
    r = client.post(
        url(dossier, pruefung, f"befunde/{befunde[FEHLT].id}/override"),
        data={"csrf_token": token(client, other), "ergebnis": "erfüllt", "begruendung": "x"},
    )
    assert r.status_code == 404
    db.expire_all()
    assert db.get(Befund, befunde[FEHLT].id).override_ergebnis is None  # type: ignore[union-attr]


def test_pdf_export_enthaelt_quellen(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    r = client.get(url(dossier, pruefung, "bericht.pdf"))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    text = " ".join(p.get_text() for p in doc)
    assert "PBV LU (SRL Nr. 736)" in text and "§ 55 Abs. 1" in text
    assert "Das Tool gibt Hinweise und entscheidet nichts." in text
    assert "Übersteuern" not in text  # keine Bedienelemente im PDF


def test_pdf_nur_nach_abschluss(client: TestClient, db: Session, bericht) -> None:  # type: ignore[no-untyped-def]
    user, dossier, pruefung, _, _ = bericht
    BueroScope(db, user.buero_id).update_pruefung(pruefung.id, status=Pruefstatus.LAEUFT)
    db.commit()
    assert client.get(url(dossier, pruefung, "bericht.pdf")).status_code == 409


def test_dossier_seite_verlinkt_bericht_und_startet(client: TestClient, bericht) -> None:  # type: ignore[no-untyped-def]
    _, dossier, pruefung, _, _ = bericht
    html = client.get(f"/dossiers/{dossier.id}/ansicht").text
    assert f"/dossiers/{dossier.id}/pruefen" in html
    assert url(dossier, pruefung) in html
    assert uuid.UUID(str(pruefung.id))


def test_bericht_ohne_katalog_zeigt_eigenen_hinweis(  # type: ignore[no-untyped-def]
    client: TestClient, bericht, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.reports import bericht as modul
    from app.rules.loader import RegelLadeFehler

    def kaputt(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RegelLadeFehler(Path("x.yaml"), "defekt")

    monkeypatch.setattr(modul, "resolve", kaputt)
    _, dossier, pruefung, _, _ = bericht
    r = client.get(url(dossier, pruefung))
    assert r.status_code == 200
    assert "Regelkatalog nicht verfügbar" in r.text
    assert "nicht mehr im aktuellen Regelkatalog" not in r.text
    assert "defekt" not in caplog.text
