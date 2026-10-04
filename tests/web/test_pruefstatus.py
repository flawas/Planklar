import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Dossier, Pruefstatus, User
from app.dossiers.scope import BueroScope
from app.storage import Storage
from tests.auth.conftest import make_user
from tests.dossiers.conftest import enqueued as enqueued  # noqa: F401
from tests.dossiers.conftest import make_pdf
from tests.dossiers.conftest import storage as storage  # noqa: F401
from tests.dossiers.test_upload import make_dossier
from tests.web.test_login import do_login

HX = {"HX-Request": "true"}


@pytest.fixture
def dossier(client: TestClient, db: Session) -> tuple[User, Dossier]:
    user = make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    return user, make_dossier(db, user)


def token(client: TestClient, d: Dossier) -> str:
    m = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get(f"/dossiers/{d.id}/ansicht").text
    )
    assert m
    return m.group(1)


def mit_dokument(db: Session, storage: Storage, user: User, d: Dossier) -> None:  # noqa: F811
    from app.dossiers.service import upload_dokument

    upload_dokument(db, storage, d, "plan.pdf", make_pdf(2), 10**8)
    db.commit()


def test_dossier_zeigt_pruefen_button_ohne_lauf(client: TestClient, dossier) -> None:  # type: ignore[no-untyped-def]
    _, d = dossier
    html = client.get(f"/dossiers/{d.id}/ansicht").text
    assert ">Prüfen</button>" in html
    assert f'hx-post="/dossiers/{d.id}/pruefen"' in html
    assert "hx-trigger" not in html


def test_start_ohne_dokumente_zeigt_verstaendlichen_fehler(client: TestClient, dossier) -> None:  # type: ignore[no-untyped-def]
    _, d = dossier
    r = client.post(f"/dossiers/{d.id}/pruefen", data={"csrf_token": token(client, d)}, headers=HX)
    assert r.status_code == 422
    assert "Bitte laden Sie zuerst Dokumente hoch." in r.text
    assert 'id="pruefung"' in r.text


def test_start_per_htmx_liefert_polling_partial(  # type: ignore[no-untyped-def]
    client: TestClient, db: Session, storage: Storage, dossier, enqueued
) -> None:
    user, d = dossier
    mit_dokument(db, storage, user, d)
    r = client.post(f"/dossiers/{d.id}/pruefen", data={"csrf_token": token(client, d)}, headers=HX)
    assert r.status_code == 200
    assert f'hx-get="/dossiers/{d.id}/pruefstatus"' in r.text
    assert 'hx-trigger="every 2s"' in r.text
    assert "Prüfung läuft" in r.text
    assert len(enqueued) == 1


def test_zweiter_start_meldet_laufende_pruefung(  # type: ignore[no-untyped-def]
    client: TestClient, db: Session, storage: Storage, dossier, enqueued
) -> None:
    user, d = dossier
    mit_dokument(db, storage, user, d)
    data = {"csrf_token": token(client, d)}
    client.post(f"/dossiers/{d.id}/pruefen", data=data, headers=HX)
    r = client.post(f"/dossiers/{d.id}/pruefen", data=data, headers=HX)
    assert r.status_code == 409
    assert "läuft bereits eine Prüfung" in r.text
    assert "hx-trigger" in r.text  # Polling läuft weiter


def test_broker_ausfall_zeigt_fehler_und_erneut_button(  # type: ignore[no-untyped-def]
    client: TestClient, db: Session, storage: Storage, dossier, monkeypatch
) -> None:
    def kaputt(buero_id: str, pruefung_id: str) -> None:
        raise ConnectionError

    monkeypatch.setattr("app.dossiers.router.run_pruefung_task.delay", kaputt)
    user, d = dossier
    mit_dokument(db, storage, user, d)
    r = client.post(f"/dossiers/{d.id}/pruefen", data={"csrf_token": token(client, d)}, headers=HX)
    assert r.status_code == 503
    assert "konnte nicht gestartet werden" in r.text
    assert "Erneut prüfen" in r.text
    assert "hx-trigger" not in r.text


def test_status_laeuft_fertig_und_fehlgeschlagen(  # type: ignore[no-untyped-def]
    client: TestClient, db: Session, dossier
) -> None:
    user, d = dossier
    scope = BueroScope(db, user.buero_id)
    p = scope.add_pruefung(d.id, regelset_hash="a" * 64, modellversion="fake")
    scope.update_pruefung(p.id, seiten_gesamt=4, seiten_fertig=1)
    db.commit()
    url = f"/dossiers/{d.id}/pruefstatus"
    r = client.get(url)
    assert "1 von 4 Seiten" in r.text and 'value="1"' in r.text and "every 2s" in r.text

    scope.update_pruefung(p.id, status=Pruefstatus.ABGESCHLOSSEN)
    db.commit()
    r = client.get(url)
    assert "every 2s" not in r.text
    assert f"/dossiers/{d.id}/pruefungen/{p.id}/bericht" in r.text

    scope.update_pruefung(p.id, status=Pruefstatus.FEHLGESCHLAGEN)
    db.commit()
    r = client.get(url)
    assert "ist fehlgeschlagen" in r.text and "Erneut prüfen" in r.text


def test_status_fremdes_dossier_404(client: TestClient, db: Session, dossier) -> None:  # type: ignore[no-untyped-def]
    fremd = make_user(db, "b@buero-b.ch")
    fremdes = make_dossier(db, fremd)
    assert client.get(f"/dossiers/{fremdes.id}/pruefstatus").status_code == 404


def test_status_ohne_login_401(client: TestClient, db: Session) -> None:
    user = make_user(db, "a@buero-a.ch")
    d = make_dossier(db, user)
    assert client.get(f"/dossiers/{d.id}/pruefstatus").status_code == 401


def test_start_ohne_htmx_leitet_weiter(  # type: ignore[no-untyped-def]
    client: TestClient, db: Session, storage: Storage, dossier, enqueued
) -> None:
    user, d = dossier
    mit_dokument(db, storage, user, d)
    r = client.post(
        f"/dossiers/{d.id}/pruefen",
        data={"csrf_token": token(client, d)},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].endswith("/bericht")
