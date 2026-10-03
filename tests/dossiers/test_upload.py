import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Dokument, Dossier, Kanton, User, Vorhabenstyp
from app.storage import Storage, object_key
from tests.auth.conftest import PASSWORD, make_user
from tests.dossiers.conftest import make_pdf


def make_dossier(db: Session, user: User) -> Dossier:
    dossier = Dossier(
        buero_id=user.buero_id,
        kanton=Kanton.LU,
        gemeinde="Luzern",
        vorhabenstyp=Vorhabenstyp.NEUBAU_EFH_MFH,
    )
    db.add(dossier)
    db.commit()
    return dossier


def login(client: TestClient, email: str) -> None:
    r = client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 204


def post(client: TestClient, dossier: Dossier, data: bytes, name: str = "plan.pdf"):  # type: ignore[no-untyped-def]
    return client.post(
        f"/dossiers/{dossier.id}/dokumente", files={"file": (name, data, "application/pdf")}
    )


@pytest.fixture
def setup(client: TestClient, db: Session, storage: Storage) -> tuple[User, Dossier]:
    user = make_user(db, "a@buero-a.ch")
    login(client, "a@buero-a.ch")
    return user, make_dossier(db, user)


def test_upload_ok(client: TestClient, db: Session, storage: Storage, setup) -> None:  # type: ignore[no-untyped-def]
    user, dossier = setup
    data = make_pdf(pages=3)
    r = post(client, dossier, data)
    assert r.status_code == 201
    body = r.json()
    sha = hashlib.sha256(data).hexdigest()
    assert body["sha256"] == sha
    assert body["seitenzahl"] == 3
    assert body["dateiname"] == "plan.pdf"
    dok = db.scalars(select(Dokument)).one()
    assert dok.speicherpfad == object_key(user.buero_id, dossier.id, sha)
    assert storage.get(user.buero_id, dossier.id, sha) == data


def test_dateiname_ohne_pfad(client: TestClient, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    r = post(client, dossier, make_pdf(), name="..\\..\\evil/plan.pdf")
    assert r.json()["dateiname"] == "plan.pdf"


def test_doppel_im_selben_dossier_409(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    data = make_pdf()
    assert post(client, dossier, data).status_code == 201
    r = post(client, dossier, data, name="anderer-name.pdf")
    assert r.status_code == 409
    assert r.json()["detail"] == "DUPLICATE"
    assert len(db.scalars(select(Dokument)).all()) == 1


def test_gleiches_pdf_in_anderem_dossier_erlaubt(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    user, dossier = setup
    data = make_pdf()
    assert post(client, dossier, data).status_code == 201
    assert post(client, make_dossier(db, user), data).status_code == 201


def test_endung_pdf_aber_kein_pdf_415(client: TestClient, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    r = post(client, dossier, b"MZ\x90\x00 kein pdf", name="plan.pdf")
    assert r.status_code == 415
    assert r.json()["detail"] == "NOT_A_PDF"


def test_pdf_ohne_endung_wird_akzeptiert(client: TestClient, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    assert post(client, dossier, make_pdf(), name="plan").status_code == 201


def test_kaputtes_pdf_422(client: TestClient, db: Session, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    r = post(client, dossier, b"%PDF-1.7\nkaputt")
    assert r.status_code == 422
    assert r.json()["detail"] == "PDF_INVALID"
    assert db.scalars(select(Dokument)).all() == []


def test_zu_gross_413(client: TestClient, db: Session, setup, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    data = make_pdf()
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(len(data) - 1))
    get_settings.cache_clear()
    r = post(client, dossier, data)
    assert r.status_code == 413
    assert r.json()["detail"] == "FILE_TOO_LARGE"
    assert db.scalars(select(Dokument)).all() == []
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(len(data)))
    get_settings.cache_clear()
    assert post(client, dossier, data).status_code == 201


def test_fremdbuero_404(client: TestClient, db: Session, storage: Storage, setup) -> None:  # type: ignore[no-untyped-def]
    _, dossier = setup
    make_user(db, "b@buero-b.ch")
    client.cookies.clear()
    login(client, "b@buero-b.ch")
    r = post(client, dossier, make_pdf())
    assert r.status_code == 404
    assert db.scalars(select(Dokument)).all() == []


def test_unbekanntes_dossier_404(client: TestClient, setup) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        f"/dossiers/{uuid.uuid4()}/dokumente",
        files={"file": ("a.pdf", make_pdf(), "application/pdf")},
    )
    assert r.status_code == 404


def test_ohne_login_401(client: TestClient, db: Session, storage: Storage) -> None:
    r = client.post(
        f"/dossiers/{uuid.uuid4()}/dokumente",
        files={"file": ("a.pdf", make_pdf(), "application/pdf")},
    )
    assert r.status_code == 401
