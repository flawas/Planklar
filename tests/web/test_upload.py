import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Dokument, Dossier, User
from app.storage import Storage
from tests.auth.conftest import make_user
from tests.dossiers.conftest import make_pdf
from tests.dossiers.conftest import storage as storage  # noqa: F401
from tests.dossiers.test_upload import make_dossier
from tests.web.test_login import do_login


def token(client: TestClient, dossier: Dossier) -> str:
    r = client.get(f"/dossiers/{dossier.id}")
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m
    return m.group(1)


def up(client: TestClient, dossier: Dossier, files: list[tuple[str, bytes]], tok: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/dossiers/{dossier.id}/upload",
        data={"csrf_token": tok},
        files=[("files", (n, d, "application/pdf")) for n, d in files],
        headers={"HX-Request": "true"},
    )


@pytest.fixture
def setup(client: TestClient, db: Session, storage: Storage) -> tuple[User, Dossier, str]:  # noqa: F811
    user = make_user(db, "a@buero-a.ch")
    do_login(client, "a@buero-a.ch")
    dossier = make_dossier(db, user)
    return user, dossier, token(client, dossier)


def test_seite_zeigt_formular_und_leere_liste(client: TestClient, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier, _ = setup
    r = client.get(f"/dossiers/{dossier.id}")
    assert r.status_code == 200
    assert "multiple" in r.text and 'hx-post="/dossiers/' in r.text
    assert "Noch keine Dokumente" in r.text
    assert "Das Tool gibt Hinweise und entscheidet nichts." in r.text


def test_mehrfach_upload_liste_mit_seitenzahl(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier, tok = setup
    r = up(client, dossier, [("a.pdf", make_pdf(2, "a")), ("b.pdf", make_pdf(3, "b"))], tok)
    assert r.status_code == 200
    assert "<html" not in r.text  # Partial
    assert "a.pdf" in r.text and "b.pdf" in r.text
    assert "Hochgeladen (2 Seiten)" in r.text and "Hochgeladen (3 Seiten)" in r.text
    assert len(db.scalars(select(Dokument)).all()) == 2
    assert "<td>3</td>" in client.get(f"/dossiers/{dossier.id}").text


def test_fehlerzeile_je_datei_und_doppel(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier, tok = setup
    pdf = make_pdf(1)
    up(client, dossier, [("ok.pdf", pdf)], tok)
    r = up(
        client, dossier, [("zwei.pdf", pdf), ("kaputt.pdf", b"%PDF-xx"), ("x.txt", b"hallo")], tok
    )
    assert r.status_code == 200
    assert "zwei.pdf" in r.text and "Doppelt" in r.text
    assert "kaputt.pdf" in r.text and "beschädigt" in r.text
    assert "x.txt" in r.text and "kein PDF" in r.text
    assert len(db.scalars(select(Dokument)).all()) == 1


def test_dateiname_wird_escaped(client: TestClient, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier, tok = setup
    r = up(client, dossier, [("<b onclick=x>.pdf", make_pdf(1))], tok)
    assert "<b onclick" not in r.text and "&lt;b onclick" in r.text


def test_csrf_pflicht(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier, _ = setup
    r = up(client, dossier, [("a.pdf", make_pdf(1))], "falsch")
    assert r.status_code == 403
    assert db.scalars(select(Dokument)).all() == []


def test_ohne_login(client: TestClient, db: Session, storage: Storage) -> None:  # noqa: F811
    owner = make_user(db, "a@buero-a.ch")
    dossier = make_dossier(db, owner)
    assert client.get(f"/dossiers/{dossier.id}", follow_redirects=False).status_code == 303
    assert up(client, dossier, [("a.pdf", make_pdf(1))], "x").status_code == 401


def test_fremdes_dossier_404(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    other = make_user(db, "b@buero-b.ch")
    fremd = make_dossier(db, other)
    _, _, tok = setup
    assert client.get(f"/dossiers/{fremd.id}").status_code == 404
    assert up(client, fremd, [("a.pdf", make_pdf(1))], tok).status_code == 404
    assert db.scalars(select(Dokument)).all() == []
