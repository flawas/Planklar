import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth.conftest import make_user
from tests.dossiers.test_upload import login

BODY = {
    "kanton": "LU",
    "gemeinde": "Luzern",
    "vorhabenstyp": "neubau_efh_mfh",
    "attribute": {"gebaeudehoehe_m": 9.5, "heizsystem": "waermepumpe", "ausserhalb_bauzone": False},
}


def _anmelden(client: TestClient, db: Session, email: str = "a@buero-a.ch") -> None:
    make_user(db, email)
    login(client, email)


def test_create_read_list(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    r = client.post("/dossiers", json=BODY)
    assert r.status_code == 201
    created = r.json()
    assert created["attribute"] == BODY["attribute"]
    assert created["status"] == "entwurf"
    assert client.get(f"/dossiers/{created['id']}").json() == created
    assert client.get("/dossiers").json() == [created]


def test_update_partial_and_attribute(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    did = client.post("/dossiers", json=BODY).json()["id"]
    r = client.patch(f"/dossiers/{did}", json={"gemeinde": "Kriens"})
    assert r.status_code == 200
    assert r.json()["gemeinde"] == "Kriens"
    assert r.json()["attribute"] == BODY["attribute"]
    r = client.patch(f"/dossiers/{did}", json={"attribute": {"gebaeudehoehe_m": 12}})
    assert r.json()["attribute"] == {"gebaeudehoehe_m": 12.0}


def test_unknown_attribute_rejected(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    bad = {**BODY, "attribute": {"farbe": "rot"}}
    assert client.post("/dossiers", json=bad).status_code == 422
    did = client.post("/dossiers", json=BODY).json()["id"]
    assert client.patch(f"/dossiers/{did}", json={"attribute": {"farbe": "rot"}}).status_code == 422


def test_attribute_per_vorhabenstyp(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    heiz = {**BODY, "vorhabenstyp": "heizungsersatz_waermepumpe"}
    # Gebäudehöhe gehört nicht zum Heizungsersatz
    assert client.post("/dossiers", json=heiz).status_code == 422
    did = client.post("/dossiers", json=BODY).json()["id"]
    # Typwechsel validiert die bestehenden Attribute neu
    r = client.patch(f"/dossiers/{did}", json={"vorhabenstyp": "heizungsersatz_waermepumpe"})
    assert r.status_code == 422
    r = client.patch(
        f"/dossiers/{did}",
        json={"vorhabenstyp": "heizungsersatz_waermepumpe", "attribute": {"heizsystem": "wp"}},
    )
    assert r.status_code == 200


def test_invalid_values_rejected(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    for patch in (
        {"kanton": "ZH"},
        {"gemeinde": "  "},
        {"vorhabenstyp": "pv"},
        {"attribute": {"gebaeudehoehe_m": -1}},
        {"attribute": {"waldbezug": "vielleicht"}},
        {"buero_id": str(uuid.uuid4())},
    ):
        assert client.post("/dossiers", json={**BODY, **patch}).status_code == 422, patch


def test_patch_null_rejected(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    did = client.post("/dossiers", json=BODY).json()["id"]
    assert client.patch(f"/dossiers/{did}", json={"gemeinde": None}).status_code == 422


def test_requires_login(client: TestClient) -> None:
    assert client.get("/dossiers").status_code == 401
    assert client.post("/dossiers", json=BODY).status_code == 401


def test_other_buero_gets_404(client: TestClient, db: Session) -> None:
    _anmelden(client, db, "a@buero-a.ch")
    did = client.post("/dossiers", json=BODY).json()["id"]
    client.post("/auth/logout")
    client.cookies.clear()
    make_user(db, "b@buero-b.ch")
    login(client, "b@buero-b.ch")
    assert client.get(f"/dossiers/{did}").status_code == 404
    assert client.patch(f"/dossiers/{did}", json={"gemeinde": "X"}).status_code == 404
    assert client.get("/dossiers").json() == []
    # Eigenes Büro wird nicht über den Body überschreibbar
    assert client.patch(f"/dossiers/{did}", json={"buero_id": str(uuid.uuid4())}).status_code == 422


def _unterlagen(client: TestClient, did: str) -> dict:  # type: ignore[type-arg]
    r = client.get(f"/dossiers/{did}/erwartete-unterlagen")
    assert r.status_code == 200
    return r.json()  # type: ignore[no-any-return]


def test_erwartete_unterlagen_mit_quelle_und_schwere(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    attribute = {k: False for k in ("gewaesserbezug", "kantonsstrassenbezug", "waldbezug")}
    attribute["ausserhalb_bauzone"] = False
    did = client.post("/dossiers", json={**BODY, "attribute": attribute}).json()["id"]
    data = _unterlagen(client, did)
    assert data["kanton"] == "LU"
    assert len(data["regelset_hash"]) == 64
    ids = {u["regel_id"] for u in data["unterlagen"]}
    assert "LU-PBV55-1-baugesuchsformular" in ids
    assert "LU-PBV55-2b-grundriss" in ids
    for u in data["unterlagen"]:
        assert u["url"].startswith("http")
        assert u["erlass"] and u["paragraph"] and u["stand"]
        assert u["schwere"] in {"fehlt_blockierend", "hinweis"}
        assert u["anwendbarkeit"] == "anwendbar"
        assert u["fehlende_variablen"] == []


def test_erwartete_unterlagen_vorhabenstyp_filtert(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    body = {**BODY, "vorhabenstyp": "heizungsersatz_waermepumpe", "attribute": {}}
    did = client.post("/dossiers", json=body).json()["id"]
    ids = {u["regel_id"] for u in _unterlagen(client, did)["unterlagen"]}
    assert "LU-PBV55-1-baugesuchsformular" in ids
    assert "LU-PBV55-2b-grundriss" not in ids


def test_erwartete_unterlagen_fehlende_angabe_bleibt_unbekannt(
    client: TestClient, db: Session
) -> None:
    _anmelden(client, db)
    did = client.post("/dossiers", json={**BODY, "attribute": {}}).json()["id"]
    unbekannt = [
        u for u in _unterlagen(client, did)["unterlagen"] if u["anwendbarkeit"] == "unbekannt"
    ]
    assert unbekannt
    assert all(u["fehlende_variablen"] for u in unbekannt)


def test_erwartete_unterlagen_fremdes_buero_404(client: TestClient, db: Session) -> None:
    _anmelden(client, db)
    did = client.post("/dossiers", json=BODY).json()["id"]
    client.post("/auth/logout")
    client.cookies.clear()
    _anmelden(client, db, "b@buero-b.ch")
    assert client.get(f"/dossiers/{did}/erwartete-unterlagen").status_code == 404
    assert client.get(f"/dossiers/{uuid.uuid4()}/erwartete-unterlagen").status_code == 404
